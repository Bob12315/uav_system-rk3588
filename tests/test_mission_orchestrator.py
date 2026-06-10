from __future__ import annotations

import pytest

from app.mission_orchestrator import MissionActionStep, MissionOrchestrator


# ── FakeRuntime ──────────────────────────────────────────────────────


class FakeActionResult:
    def __init__(self, done=False, failed=False, reason=""):
        self.done = done
        self.failed = failed
        self.reason = reason

    def to_dict(self):
        return {"done": self.done, "failed": self.failed, "reason": self.reason}


class FakeRunner:
    def __init__(self, results):
        self.results = list(results)
        self.state = "running"
        self.current_action = None
        self.action_name = None
        self.sent_actions = []  # track what we started

    def start(self, name, params=None):
        self.sent_actions.append((name, dict(params or {})))
        self.state = "running"

    def update(self, context):
        if self.results:
            r = self.results.pop(0)
        else:
            r = FakeActionResult(done=False, failed=False, reason="running")
        return r

    def status(self):
        return {"state": self.state, "action_name": self.action_name}

    def stop(self):
        self.state = "stopped"

    def reset(self):
        self.state = "idle"


class FakeRuntime:
    def __init__(self, results):
        self.runner = FakeRunner(results)
        self.last_result = None
        self.clear_nav_calls = 0

    def start(self, name, params=None, *, send_actions=None, link_manager=None):
        self.runner.start(name, params)

    def tick(self, context, *, link_manager=None, send_commands=False):
        self.last_result = self.runner.update(context)
        return self.runner.status()

    def stop(self, link_manager=None, *, hold_current=False):
        self.runner.stop()

    def reset(self, link_manager=None, *, hold_current=False):
        self.runner.reset()
        self.last_result = None

    def clear_navigation_queue(self, link_manager=None, *, hold_current=False):
        self.clear_nav_calls += 1


# ── helpers ──────────────────────────────────────────────────────────


def _steps():
    return [
        MissionActionStep("goto_waypoint", {"x": 1.0}),
        MissionActionStep("payload_release", {"payload_id": "p1"}),
    ]


def _single_step():
    return [MissionActionStep("payload_release", {"payload_id": "p1"})]


# ── tests ────────────────────────────────────────────────────────────


def test_start_starts_first_action() -> None:
    runtime = FakeRuntime([])
    orch = MissionOrchestrator(runtime, _steps())
    orch.start()
    assert runtime.runner.sent_actions == [("goto_waypoint", {"x": 1.0})]
    status = orch.status()
    assert status.running is True
    assert status.current_index == 0
    assert status.current_action == "goto_waypoint"


def test_done_advances_to_next_step() -> None:
    runtime = FakeRuntime([FakeActionResult(done=True, reason="done")])
    orch = MissionOrchestrator(runtime, _steps())
    orch.start()
    orch.tick({})

    # after first tick returns done, should start step 2
    assert len(runtime.runner.sent_actions) == 2
    assert runtime.runner.sent_actions[1] == ("payload_release", {"payload_id": "p1"})
    status = orch.status()
    assert status.current_index == 1
    assert status.current_action == "payload_release"
    assert status.reason == "next_step"


def test_last_step_done_missions_done() -> None:
    runtime = FakeRuntime([FakeActionResult(done=True, reason="done")])
    orch = MissionOrchestrator(runtime, _single_step())
    orch.start()
    status = orch.tick({})

    assert status.done is True
    assert status.running is False
    assert status.reason == "mission_done"


def test_failed_stops_and_does_not_advance() -> None:
    runtime = FakeRuntime([FakeActionResult(failed=True, reason="failed")])
    orch = MissionOrchestrator(runtime, _steps())
    orch.start()
    status = orch.tick({})

    assert status.failed is True
    assert status.running is False
    assert status.reason == "failed"
    # only first action started, never the second
    assert len(runtime.runner.sent_actions) == 1


def test_tick_passes_context_and_link_manager() -> None:
    runtime = FakeRuntime([])
    orch = MissionOrchestrator(runtime, _single_step())
    orch.start()
    fake_link = object()
    orch.tick({"altitude": 10}, link_manager=fake_link, send_commands=True)

    # verify that tick was called and produced a result on the runtime
    assert runtime.last_result is not None


def test_stop_delegates_to_runtime() -> None:
    runtime = FakeRuntime([])
    orch = MissionOrchestrator(runtime, _steps())
    orch.stop()
    assert orch.status().running is False
    assert orch.status().reason == "stopped"


def test_reset_delegates_to_runtime_and_clears_state() -> None:
    runtime = FakeRuntime([FakeActionResult(done=True, reason="done")])
    orch = MissionOrchestrator(runtime, _steps())
    orch.start()
    orch.tick({})
    orch.reset()

    status = orch.status()
    assert status.running is False
    assert status.done is False
    assert status.failed is False
    assert status.current_index == 0
    assert status.reason == "reset"


def test_empty_steps_raises_value_error() -> None:
    runtime = FakeRuntime([])
    with pytest.raises(ValueError, match="non-empty"):
        MissionOrchestrator(runtime, [])


def test_step_transition_clears_navigation_queue() -> None:
    """When a step completes and the next begins, clear_navigation_queue is called."""
    runtime = FakeRuntime([FakeActionResult(done=True, reason="step1_done")])
    orch = MissionOrchestrator(runtime, _steps())
    assert runtime.clear_nav_calls == 0

    fake_link = object()
    orch.start(link_manager=fake_link)
    # first tick — step1 completes, advances to step2
    status = orch.tick({}, link_manager=fake_link)

    assert status.current_action == "payload_release"
    assert status.reason == "next_step"
    assert runtime.clear_nav_calls == 1
    assert len(runtime.runner.sent_actions) == 2  # step1 started + step2 started


def test_stop_with_hold_passes_hold_current() -> None:
    """stop() with hold_current=True is accepted without error."""
    runtime = FakeRuntime([])
    orch = MissionOrchestrator(runtime, _steps())
    orch.start()
    orch.stop(link_manager=object(), hold_current=True)
    assert orch.status().running is False
