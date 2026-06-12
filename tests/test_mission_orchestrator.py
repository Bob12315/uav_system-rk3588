from __future__ import annotations

import pytest

from app.mission_orchestrator import MissionActionStep, MissionOrchestrator


# ── FakeRuntime ──────────────────────────────────────────────────────


class FakeActionResult:
    def __init__(self, done=False, failed=False, reason="", detail=None):
        self.done = done
        self.failed = failed
        self.reason = reason
        self.detail = detail or {}

    def to_dict(self):
        return {
            "done": self.done,
            "failed": self.failed,
            "reason": self.reason,
            "detail": dict(self.detail),
        }


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
    assert orch.blackboard.data == {}


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


def test_blackboard_save_as_stores_done_detail() -> None:
    runtime = FakeRuntime([FakeActionResult(done=True, reason="done", detail={"value": 123})])
    orch = MissionOrchestrator(
        runtime,
        [
            MissionActionStep("fake1", {}, save_as="first"),
            MissionActionStep("fake2", {}),
        ],
    )

    orch.start()
    orch.tick({})

    assert orch.blackboard.data["first"]["value"] == 123
    assert orch.status().detail["blackboard_keys"] == ["first"]


def test_blackboard_resolves_next_step_params() -> None:
    runtime = FakeRuntime([FakeActionResult(done=True, reason="done", detail={"value": 123})])
    orch = MissionOrchestrator(
        runtime,
        [
            MissionActionStep("fake1", {}, save_as="first"),
            MissionActionStep("fake2", {"x": "$first.value"}),
        ],
    )

    orch.start()
    orch.tick({})

    assert runtime.runner.sent_actions == [
        ("fake1", {}),
        ("fake2", {"x": 123}),
    ]


def test_missing_blackboard_reference_fails_mission_without_starting_action() -> None:
    runtime = FakeRuntime([])
    orch = MissionOrchestrator(
        runtime,
        [MissionActionStep("fake2", {"x": "$missing.value"})],
    )

    orch.start()
    status = orch.status()

    assert status.failed is True
    assert status.running is False
    assert status.reason == "param_resolution_failed"
    assert runtime.runner.sent_actions == []


def test_start_clears_existing_blackboard_data() -> None:
    runtime = FakeRuntime([])
    orch = MissionOrchestrator(runtime, _single_step())
    orch.blackboard.set("old", {"value": 1})

    orch.start()

    assert orch.blackboard.data == {}


def test_blackboard_save_failure_fails_mission() -> None:
    runtime = FakeRuntime([FakeActionResult(done=True, reason="done", detail={"value": 123})])
    orch = MissionOrchestrator(
        runtime,
        [
            MissionActionStep("fake1", {}, save_as=" "),
            MissionActionStep("fake2", {}),
        ],
    )

    orch.start()
    status = orch.tick({})

    assert status.failed is True
    assert status.running is False
    assert status.reason == "blackboard_save_failed"


def test_duplicate_step_label_raises_value_error() -> None:
    runtime = FakeRuntime([])

    with pytest.raises(ValueError, match="duplicate mission step label"):
        MissionOrchestrator(
            runtime,
            [
                MissionActionStep("a", label="same"),
                MissionActionStep("b", label="same"),
            ],
        )


def test_retry_current_succeeds_on_second_attempt() -> None:
    runtime = FakeRuntime(
        [
            FakeActionResult(failed=True, reason="first_failed"),
            FakeActionResult(done=True, reason="done"),
        ]
    )
    orch = MissionOrchestrator(
        runtime,
        [
            MissionActionStep(
                "unstable",
                {},
                on_failed={"action": "retry_current", "max_attempts": 2},
            )
        ],
    )

    orch.start()
    retry_status = orch.tick({})
    done_status = orch.tick({})

    assert retry_status.running is True
    assert done_status.done is True
    assert done_status.reason == "mission_done"
    assert runtime.runner.sent_actions == [("unstable", {}), ("unstable", {})]


def test_retry_current_exhaustion_fails_mission() -> None:
    runtime = FakeRuntime(
        [
            FakeActionResult(failed=True, reason="failed_once"),
            FakeActionResult(failed=True, reason="failed_twice"),
        ]
    )
    orch = MissionOrchestrator(
        runtime,
        [
            MissionActionStep(
                "unstable",
                {},
                on_failed={"action": "retry_current", "max_attempts": 2},
            )
        ],
    )

    orch.start()
    orch.tick({})
    status = orch.tick({})

    assert status.failed is True
    assert status.reason == "retry_attempts_exhausted"


def test_jump_to_starts_labeled_recovery_step() -> None:
    runtime = FakeRuntime(
        [
            FakeActionResult(failed=True, reason="bad_failed"),
            FakeActionResult(done=True, reason="recovered"),
        ]
    )
    orch = MissionOrchestrator(
        runtime,
        [
            MissionActionStep("bad", on_failed={"action": "jump_to", "target": "recovery", "max_attempts": 1}),
            MissionActionStep("unused"),
            MissionActionStep("recovery", label="recovery"),
        ],
    )

    orch.start()
    jump_status = orch.tick({})
    done_status = orch.tick({})

    assert jump_status.current_index == 2
    assert done_status.done is True
    assert runtime.runner.sent_actions == [("bad", {}), ("recovery", {})]


def test_jump_to_missing_label_fails_mission() -> None:
    runtime = FakeRuntime([FakeActionResult(failed=True, reason="bad_failed")])
    orch = MissionOrchestrator(
        runtime,
        [
            MissionActionStep("bad", on_failed={"action": "jump_to", "target": "missing", "max_attempts": 1}),
        ],
    )

    orch.start()
    status = orch.tick({})

    assert status.failed is True
    assert status.reason == "jump_target_not_found"


def test_continue_after_failure_advances_to_next_step() -> None:
    runtime = FakeRuntime(
        [
            FakeActionResult(failed=True, reason="recon_failed"),
            FakeActionResult(done=True, reason="landed"),
        ]
    )
    orch = MissionOrchestrator(
        runtime,
        [
            MissionActionStep("recon_scan", on_failed={"action": "continue"}),
            MissionActionStep("land"),
        ],
    )

    orch.start()
    continue_status = orch.tick({})
    done_status = orch.tick({})

    assert continue_status.current_action == "land"
    assert done_status.done is True
    assert runtime.runner.sent_actions == [("recon_scan", {}), ("land", {})]


def test_default_failure_policy_still_fails_mission() -> None:
    runtime = FakeRuntime([FakeActionResult(failed=True, reason="failed")])
    orch = MissionOrchestrator(runtime, [MissionActionStep("bad")])

    orch.start()
    status = orch.tick({})

    assert status.failed is True
    assert status.reason == "failed"
