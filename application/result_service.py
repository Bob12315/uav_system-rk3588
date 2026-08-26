from __future__ import annotations

import copy
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from contracts.action import OperationResult


@dataclass(frozen=True, slots=True)
class ResultSnapshot:
    localization: dict[str, Any] = field(default_factory=dict)
    drop_localization: dict[str, Any] = field(default_factory=dict)
    recon_localization: dict[str, Any] = field(default_factory=dict)
    drop_targets: dict[str, Any] = field(default_factory=dict)
    drop_workflow: dict[str, Any] = field(default_factory=dict)


class ResultService:
    """Thread-safe owner of mission result state; it has no command dependencies."""

    _NAMES = set(ResultSnapshot.__dataclass_fields__)

    def __init__(self, *, with_field_coordinates=None, get_action_runtime=None,
                 get_mission_orchestrator=None, record_event=None) -> None:
        object.__setattr__(self, "_lock", threading.RLock())
        object.__setattr__(self, "_values", {name: {} for name in self._NAMES})
        object.__setattr__(self, "_with_field_coordinates_callback", with_field_coordinates or (lambda items: list(items)))
        object.__setattr__(self, "_get_action_runtime", get_action_runtime or (lambda: None))
        object.__setattr__(self, "_get_mission_orchestrator", get_mission_orchestrator or (lambda: None))
        object.__setattr__(self, "_record_event_callback", record_event or (lambda _level, _message: None))

    _COMPAT_NAMES = {
        "latest_localization_result": "localization",
        "latest_drop_localization_result": "drop_localization",
        "latest_recon_localization_result": "recon_localization",
        "latest_drop_targets_result": "drop_targets",
        "latest_drop_workflow_result": "drop_workflow",
    }

    def __getattr__(self, name: str):
        result_name = self._COMPAT_NAMES.get(name)
        if result_name is not None:
            return self.edit_view(result_name)
        raise AttributeError(name)

    def __setattr__(self, name: str, value) -> None:
        result_name = self._COMPAT_NAMES.get(name)
        if result_name is not None and "_values" in self.__dict__:
            self.set(result_name, value)
            return
        object.__setattr__(self, name, value)

    @property
    def action_runtime(self):
        return self._get_action_runtime()

    @property
    def action_mission_orchestrator(self):
        return self._get_mission_orchestrator()

    def _with_field_coordinates(self, items):
        return self._with_field_coordinates_callback(items)

    def _record_event(self, level: str, message: str) -> None:
        self._record_event_callback(level, message)

    def get(self, name: str) -> dict[str, Any]:
        if name not in self._NAMES:
            raise KeyError(name)
        with self._lock:
            return copy.deepcopy(self._values[name])

    def set(self, name: str, value: dict[str, Any]) -> None:
        if name not in self._NAMES:
            raise KeyError(name)
        with self._lock:
            self._values[name] = copy.deepcopy(dict(value))

    def edit_view(self, name: str) -> dict[str, Any]:
        """Internal application write view; adapters must use get()/snapshot()."""
        if name not in self._NAMES:
            raise KeyError(name)
        with self._lock:
            return self._values[name]

    def clear_run_results(self) -> None:
        with self._lock:
            for name in self._NAMES - {"drop_targets"}:
                self._values[name] = {}

    def snapshot(self) -> ResultSnapshot:
        with self._lock:
            return ResultSnapshot(**copy.deepcopy(self._values))

    def _save_localization_from_detail(self, detail: dict[str, object], source: str = "gps_fuse_views") -> bool:
        """Extract localized_objects from *detail* and persist to latest_localization_result.
        Returns True on success, False if no valid localized_objects found."""
        if not isinstance(detail, dict):
            return False
        localized = detail.get("localized_objects")
        if not isinstance(localized, list) or not localized:
            return False
        self.latest_localization_result = {
            "source": source,
            "updated_at": time.time(),
            "run_id": str(detail.get("run_id", "")),
            "objects": self._with_field_coordinates(localized),
            "object_count": int(detail.get("object_count", len(localized))),
            "raw_estimates_count": int(detail.get("raw_estimates_count", 0)),
            "captures_count": int(detail.get("captures_count", 0)),
        }
        return True

    def _maybe_save_localization_result(self) -> None:
        """Persist an atomic GPS fusion completed through Action Lab."""
        name = getattr(self.action_runtime, "action_name", None) if self.action_runtime else None
        if name != "gps_fuse_views":
            return
        last = getattr(self.action_runtime, "last_result", None)
        if last is None:
            return
        done = last.get("done") if isinstance(last, dict) else getattr(last, "done", False)
        if not done:
            return
        detail = last.get("detail") if isinstance(last, dict) else getattr(last, "detail", None)
        if isinstance(detail, dict):
            pass
        elif hasattr(detail, "__dict__"):
            detail = detail.__dict__
        else:
            detail = {}
        self._save_localization_from_detail(detail, source=name)

    def _maybe_save_localization_from_mission(self) -> None:
        """Persist drop/recon fusion independently from their explicit mission keys."""
        orch = getattr(self, "action_mission_orchestrator", None)
        if orch is None:
            return
        bb = getattr(orch, "blackboard", None)
        if bb is None:
            return
        data = getattr(bb, "data", {})
        for key, attribute in (("drop_scan", "latest_drop_localization_result"),):
            value = data.get(key) if isinstance(data, dict) else None
            if isinstance(value, dict) and isinstance(value.get("localized_objects"), list):
                result = self._localization_result(value, "gps_fuse_views")
                setattr(self, attribute, result)

    def _localization_result(self, detail: dict[str, object], source: str) -> dict[str, object]:
        localized = detail.get("localized_objects")
        objects = localized if isinstance(localized, list) else []
        return {"source": source, "updated_at": time.time(), "run_id": str(detail.get("run_id", "")), "objects": self._with_field_coordinates(objects), "object_count": int(detail.get("object_count", len(objects)))}

    def _ensure_drop_workflow(self) -> dict[str, object]:
        if not isinstance(self.latest_drop_workflow_result, dict):
            self.latest_drop_workflow_result = {}
        wf = self.latest_drop_workflow_result
        wf.setdefault("source", "drop_workflow")
        wf.setdefault("updated_at", time.time())
        wf.setdefault("selected_targets", [])
        wf.setdefault("target_lock", {})
        wf.setdefault("align_descend", {})
        wf.setdefault("payload_release", {})
        wf.setdefault("release_events", [])
        wf.setdefault("released_target_ids", [])
        return wf

    def _workflow_targets(self) -> list[dict[str, object]]:
        workflow = self._ensure_drop_workflow()
        targets = workflow.get("selected_targets")
        if not isinstance(targets, list):
            return []
        return [item for item in targets if isinstance(item, dict)]

    def _rank_by_target_id(self, target_id: object) -> int | None:
        if target_id is None:
            return None
        wanted = str(target_id)
        for index, target in enumerate(self._workflow_targets(), start=1):
            ids = {
                str(value)
                for value in (
                    target.get("id"),
                    target.get("target_id"),
                    target.get("object_id"),
                )
                if value is not None
            }
            if wanted in ids:
                return index
        return None

    def _point_xy(self, item: object) -> tuple[float, float] | None:
        if not isinstance(item, dict):
            return None
        x = item.get("local_x", item.get("x", item.get("field_x")))
        y = item.get("local_y", item.get("y", item.get("field_y")))
        try:
            xf = float(x)
            yf = float(y)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(xf) or not math.isfinite(yf):
            return None
        return xf, yf

    def _rank_by_target_xy(self, target: object, tolerance_m: float = 0.35) -> int | None:
        xy = self._point_xy(target)
        if xy is None:
            return None
        tx, ty = xy
        best_rank = None
        best_dist = None
        for index, item in enumerate(self._workflow_targets(), start=1):
            item_xy = self._point_xy(item)
            if item_xy is None:
                continue
            ix, iy = item_xy
            dist = math.hypot(tx - ix, ty - iy)
            if dist <= tolerance_m and (best_dist is None or dist < best_dist):
                best_rank = index
                best_dist = dist
        return best_rank

    def _drop_rank_from_result(
        self, action_name: str | None, detail: dict[str, object],
        step_index: int | None = None, step_label: str | None = None,
    ) -> int | None:
        if not isinstance(detail, dict):
            return None
        # 1. ID matching (most reliable)
        for value in (detail.get("target_id"), detail.get("id"), detail.get("object_id")):
            rank = self._rank_by_target_id(value)
            if rank is not None:
                return rank
        target = detail.get("target")
        if isinstance(target, dict):
            for value in (target.get("target_id"), target.get("id"), target.get("object_id")):
                rank = self._rank_by_target_id(value)
                if rank is not None:
                    return rank
        best_estimate = detail.get("best_estimate")
        if isinstance(best_estimate, dict):
            for value in (best_estimate.get("target_id"), best_estimate.get("id"), best_estimate.get("object_id")):
                rank = self._rank_by_target_id(value)
                if rank is not None:
                    return rank
        # 2. key / payload_id / step_label inference
        key = str(detail.get("key") or "")
        payload_id = str(detail.get("payload_id") or "")
        text = " ".join([str(action_name or ""), key, payload_id, str(step_label or "")])
        if "target_lock_0" in text or "payload_1" in text or "payload_release_1" in text:
            return 1
        if "target_lock_1" in text or "payload_2" in text or "payload_release_2" in text:
            return 2
        # 3. xy coordinate matching
        rank = self._rank_by_target_xy(detail.get("target"))
        if rank is not None:
            return rank
        rank = self._rank_by_target_xy(detail.get("best_estimate"))
        if rank is not None:
            return rank
        # 4. safe fallback: current_rank
        workflow = self._ensure_drop_workflow()
        cur = workflow.get("current_rank")
        try:
            cur_rank = int(cur) if cur is not None else None
        except (TypeError, ValueError):
            cur_rank = None
        targets = self._workflow_targets()
        if cur_rank is not None and 1 <= cur_rank <= len(targets):
            return cur_rank
        return None

    def _save_drop_workflow_from_action_result(
        self,
        action_name: str | None,
        result: dict[str, object] | None,
        *,
        step_index: int | None = None,
        step_label: str | None = None,
    ) -> None:
        if not result or not action_name:
            return
        detail = result.get("detail") or {}
        if not isinstance(detail, dict):
            return

        if action_name == "select_drop_targets":
            selected = detail.get("selected_targets")
            if isinstance(selected, list):
                wf = self._ensure_drop_workflow()
                wf["updated_at"] = time.time()
                targets = []
                for i, t in enumerate(self._with_field_coordinates(selected), start=1):
                    targets.append({
                        **t,
                        "rank": int(t.get("rank") or i),
                        "status": "selected",
                        "locked": False,
                        "released": False,
                        "payload_id": None,
                        "release_sent": False,
                        "hold_sent": False,
                    })
                wf["selected_targets"] = targets
                wf["selected_count"] = int(detail.get("selected_count", len(selected)))
                wf["candidate_count"] = int(detail.get("candidate_count", 0))
                wf["current_rank"] = 1 if targets else None
            return

        wf = self._ensure_drop_workflow()
        wf["updated_at"] = time.time()
        rank = self._drop_rank_from_result(action_name, detail, step_index, step_label)
        targets = wf.setdefault("selected_targets", [])
        target = None
        if rank is not None and 1 <= rank <= len(targets):
            target = targets[rank - 1]
        elif targets:
            # fallback: use current_rank or first un-released
            cur = wf.get("current_rank")
            if isinstance(cur, int) and 1 <= cur <= len(targets) and not targets[cur - 1].get("released"):
                rank = cur
                target = targets[cur - 1]
            else:
                for i, t in enumerate(targets):
                    if not t.get("released"):
                        rank = i + 1
                        target = t
                        break

        if action_name == "target_lock":
            target_raw = detail.get("target")
            best_raw = detail.get("best_estimate")
            wf["target_lock"] = {
                "source": "target_lock",
                "step_index": step_index,
                "step_label": step_label,
                "done": bool(result.get("done")),
                "failed": bool(result.get("failed")),
                "reason": str(result.get("reason", "")),
                "target": self._with_field_coordinates([target_raw])[0]
                    if isinstance(target_raw, dict) else {},
                "best_estimate": self._with_field_coordinates([best_raw])[0]
                    if isinstance(best_raw, dict) else {},
                "locked_track_id": detail.get("locked_track_id"),
                "best_distance_m": detail.get("best_distance_m"),
            }
            if target is not None and not bool(target.get("released")):
                target["status"] = "locked" if bool(result.get("done")) else "locking"
                target["locked"] = bool(result.get("done"))
                target["locked_track_id"] = detail.get("locked_track_id")
                target["best_distance_m"] = detail.get("best_distance_m")
                target["lock_reason"] = str(result.get("reason", ""))
            wf["current_rank"] = rank

        elif action_name == "align_descend":
            wf["align_descend"] = {
                "source": "align_descend",
                "step_index": step_index,
                "step_label": step_label,
                "done": bool(result.get("done")),
                "failed": bool(result.get("failed")),
                "reason": str(result.get("reason", "")),
                "aligned": detail.get("within_release_deadband"),
                "height_m": detail.get("altitude_m"),
                "target_altitude_m": detail.get("target_altitude_m"),
                "ex": detail.get("ex"),
                "ey": detail.get("ey"),
                "target_track_id": detail.get("target_track_id"),
                "yaw_deg": detail.get("yaw_deg"),
                "vx_forward_mps": detail.get("vx_forward_mps"),
                "vy_right_mps": detail.get("vy_right_mps"),
                "vz_down_mps": detail.get("vz_down_mps"),
                "within_descent_deadband": detail.get("within_descent_deadband"),
                "within_release_deadband": detail.get("within_release_deadband"),
            }
            if target is not None and not bool(target.get("released")):
                target["status"] = "aligned" if detail.get("within_release_deadband") else "aligning"

        elif action_name == "payload_release":
            release = {
                "source": "payload_release",
                "step_index": step_index,
                "step_label": step_label,
                "done": bool(result.get("done")),
                "failed": bool(result.get("failed")),
                "reason": str(result.get("reason", "")),
                "state": detail.get("state"),
                "payload_id": detail.get("payload_id"),
                "target_id": detail.get("target_id"),
                "servo_channels": detail.get("servo_channels") or detail.get("channels") or [],
                "release_sent": bool(detail.get("release_sent")),
                "hold_sent": bool(detail.get("hold_sent")),
                "release_pwm": detail.get("release_pwm"),
                "hold_pwm": detail.get("hold_pwm"),
                "wait_updates": detail.get("wait_updates"),
                "release_wait_updates": detail.get("release_wait_updates"),
            }
            wf["payload_release"] = release
            released_flag = release["done"] or release["release_sent"]
            if target is not None and released_flag:
                target["status"] = "released"
                target["released"] = True
                target["payload_id"] = release.get("payload_id")
                target["release_sent"] = bool(release.get("release_sent"))
                target["hold_sent"] = bool(release.get("hold_sent"))
                target["servo_channels"] = release.get("servo_channels")
            # advance current_rank
            if rank is not None and rank + 1 <= len(targets):
                wf["current_rank"] = rank + 1
            else:
                wf["current_rank"] = None
            # release events
            events = wf.setdefault("release_events", [])
            payload_id = str(release.get("payload_id") or "")
            target_id = str(release.get("target_id") or "")
            event_key = "{}:{}:{}".format(payload_id, target_id, rank or "")
            if released_flag:
                if not any(e.get("event_key") == event_key for e in events if isinstance(e, dict)):
                    events.append({**release, "event_key": event_key, "updated_at": time.time()})

    def clear_localization_result(self) -> OperationResult:
        self.latest_localization_result = {}
        self.latest_drop_localization_result = {}
        self.latest_recon_localization_result = {}
        result = OperationResult(True, "localized object coordinates cleared")
        self._record_event("OK", result.message)
        return result

    def _maybe_save_drop_targets_result(self) -> None:
        """If select_drop_targets just completed, persist selected targets for Web UI map."""
        name = getattr(self.action_runtime, "action_name", None)
        if name != "select_drop_targets":
            return
        last = getattr(self.action_runtime, "last_result", None)
        if last is None:
            return
        detail = last.get("detail") if isinstance(last, dict) else getattr(last, "detail", None)
        if isinstance(detail, dict):
            detail = detail
        elif hasattr(detail, "__dict__"):
            detail = detail.__dict__  # type: ignore[union-attr]
        else:
            detail = {}
        done = last.get("done") if isinstance(last, dict) else getattr(last, "done", False)
        if not done:
            return
        selected = detail.get("selected_targets")
        if not isinstance(selected, list):
            return
        self.latest_drop_targets_result = {
            "source": "select_drop_targets",
            "updated_at": time.time(),
            "selected_targets": self._with_field_coordinates(selected),
            "selected_count": detail.get("selected_count", len(selected)),
            "candidate_count": detail.get("candidate_count", 0),
        }
