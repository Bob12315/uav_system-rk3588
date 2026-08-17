# Archived composite-Action behavior lock; replaced by Mission subflow contracts.
"""GPS recon observes from a continuously refreshed GLOBAL hover setpoint."""
from __future__ import annotations

from missions.common.actions import gps_recon_sequence as mod
from missions.common.actions.gps_recon_sequence import GpsReconSequenceAction
from missions.common.actions.result import ActionResult


class ScriptedGoto:
    starts: list[dict] = []
    def start(self, params): self.params = params; type(self).starts.append(params)
    def update(self, context):
        # Arrival goto completes once; hover has an intentionally unreachable hold count.
        if self.params["key"].startswith("gps_recon_goto"):
            return ActionResult(done=True)
        return ActionResult(effects=ActionResult.typed([{"action_type": "global_goto", "params": {"lat": self.params["lat"], "lon": self.params["lon"], "alt": self.params["altitude_m"]}}]))


def _params(targets):
    return {"targets": targets, "approach_altitude_m": 2.5, "observe_duration_s": 2.0, "goto_max_updates": 20,
            "goto": {"tolerance_xy_m": .25, "tolerance_z_m": .15, "min_hold_updates": 3, "require_velocity_valid": True,
                     "max_horizontal_speed_mps": .15, "max_vertical_speed_mps": .1},
            "observation": {"record_start_altitude_m": 3., "finish_altitude_m": 2., "min_seen_frames": 1}}


def test_recon_goto_then_two_second_global_hover(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(mod, "GotoWaypointAction", ScriptedGoto)
    monkeypatch.setattr(mod.time, "monotonic", lambda: now[0])
    action = GpsReconSequenceAction()
    action.start(_params([{"lat": 34.1, "lon": 108.1, "target_id": "r1"}]))
    action.update({})  # goto -> operation
    started = action.update({"drone": {"relative_altitude": 2.5}})
    assert started.reason == "gps_recon_observing"
    assert started.actions[0]["action_type"] == "global_goto"
    assert started.detail["hover_target_altitude_m"] == 2.5
    now[0] = 101.99
    assert not action.update({"drone": {"relative_altitude": 2.5}}).done
    now[0] = 102.0
    done = action.update({"drone": {"relative_altitude": 2.5}})
    assert done.done and len(action.observations) == 1
    assert any(item["action_type"] == "clear_continuous_commands" for item in done.actions)
    assert action.phase_history == ["goto", "operation"]


def test_recon_visits_only_valid_targets_and_empty_targets_succeed(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(mod, "GotoWaypointAction", ScriptedGoto)
    monkeypatch.setattr(mod.time, "monotonic", lambda: now[0])
    empty = GpsReconSequenceAction(); empty.start(_params([]))
    assert empty.update({}).done and empty.observations == []
    action = GpsReconSequenceAction()
    targets = [{"lat": 34 + i / 100, "lon": 108 + i / 100, "target_id": str(i)} for i in range(5)]
    action.start(_params(targets))
    for _ in range(5):
        action.update({})
        action.update({"drone": {"relative_altitude": 2.5}})
        now[0] += 2.0
        result = action.update({"drone": {"relative_altitude": 2.5}})
    assert result.done and len(action.observations) == 5
    assert action.phase_history == ["goto", "operation"] * 5
