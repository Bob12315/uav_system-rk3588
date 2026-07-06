from __future__ import annotations

import math
from typing import Any

from .align_descend import AlignDescendAction
from .base import ActionModule
from .result import ActionResult

DEFAULT_SIGN_CLASS_NAMES = [
    "baozha", "shenghua", "yiran", "fangshe", "buran",
    "fushi", "youdu", "yushi", "ziran", "ciji",
    "danger_1", "danger_2", "danger_3",
]


class ReconDescendObserveAction(ActionModule):
    """Descend to a recon target while recording danger sign statistics.

    Delegates to AlignDescendAction for visual-assist descent.
    Records sign detections inside a configurable altitude window
    and outputs a single best-class result when altitude is reached.
    """

    def __init__(self) -> None:
        self.reset()

    # ── ActionModule interface ─────────────────────────────────────────

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}

        self.target = self._extract_target(data.get("target"))
        self.target_index = int(data.get("target_index", 0))
        self.record_start_altitude_m = self._finite_float(data.get("record_start_altitude_m", 2.0), "record_start_altitude_m")
        self.finish_altitude_m = self._finite_float(data.get("finish_altitude_m", 1.5), "finish_altitude_m")

        if self.record_start_altitude_m <= self.finish_altitude_m:
            raise ValueError("record_start_altitude_m must be > finish_altitude_m")
        if self.finish_altitude_m <= 0.0:
            raise ValueError("finish_altitude_m must be positive")

        self.sign_class_names = self._parse_class_names(data.get("sign_class_names", DEFAULT_SIGN_CLASS_NAMES))
        self.min_sign_confidence = self._finite_range(data.get("min_sign_confidence", 0.35), 0.0, 1.0, "min_sign_confidence")

        self.min_seen_frames = int(data.get("min_seen_frames", 3))
        self.min_confidence_max = self._finite_range(data.get("min_confidence_max", 0.55), 0.0, 1.0, "min_confidence_max")
        self.min_confidence_mean = self._finite_range(data.get("min_confidence_mean", 0.40), 0.0, 1.0, "min_confidence_mean")
        self.min_score = self._finite_ge(data.get("min_score", 1.2), 0.0, "min_score")
        self.min_margin_ratio = self._finite_ge(data.get("min_margin_ratio", 1.4), 1.0, "min_margin_ratio")

        if self.min_seen_frames < 0:
            raise ValueError("min_seen_frames must be non-negative")

        self.detection_source = str(data.get("detection_source", "scene")).strip().lower()
        if self.detection_source not in {"scene", "perception"}:
            raise ValueError("detection_source must be 'scene' or 'perception'")

        self.align_params = dict(data.get("align_descend") or {})
        self.align_params["finish_altitude_m"] = self.finish_altitude_m

        self._skipped = False
        self._done = False
        self._started = True
        self._stopped = False
        self._align_done = False
        self._align_failed = False
        self._align_reason = ""
        self._align_detail: dict[str, Any] = {}
        self._best_score = 0.0
        self._second_score = 0.0
        self._margin_ratio = 0.0
        self.record_frame_count = 0
        self.valid_sign_frame_count = 0
        self._class_stats: dict[str, dict[str, Any]] = {}
        self._priority = int(data.get("priority", 5))

        if self.target is None:
            self._skipped = True
            self._done = True
            return

        self._align_descend = AlignDescendAction()
        self._align_descend.start(self.align_params)

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self._started:
            return ActionResult(failed=True, reason="action_not_started")
        if self._stopped:
            return ActionResult(
                done=True, reason="stopped",
                actions=[self._zero_action()],
                detail=self._make_detail(),
            )
        if self._skipped:
            self._done = True
            return ActionResult(
                done=True,
                reason="skipped_missing_target",
                detail=self._make_detail(status="skipped_missing_target"),
            )
        if self._done:
            return ActionResult(done=True, reason=self._align_reason or "done", detail=self._make_detail())

        data = context or {}

        if not self._align_done:
            result = self._align_descend.update(data)
            self._align_detail = dict(result.detail)

            # wrap flight_command in Dispatcher envelope
            command = self._align_detail.get("command")
            if isinstance(command, dict) and command.get("active"):
                current_actions = [self._flight_action(command)]
            else:
                # Inactive command: control gate closed (control_allowed=false,
                # target lost, etc.) — emit zero velocity + clear to stop stale
                # continuous commands from previous ticks.
                current_actions = [self._zero_action(), self._clear_action()]

            align_height = self._align_detail.get("height_m")
            if align_height is not None:
                self._record_frame(align_height, data)

            if result.done:
                self._align_done = True
                self._align_reason = result.reason
                return self._finalize()
            if result.failed:
                self._align_done = True
                self._align_failed = True
                self._align_reason = result.reason
                return self._finalize()

            return ActionResult(
                actions=current_actions,
                reason=result.reason,
                detail=self._make_detail(),
            )

        # align already done
        return self._finalize()

    def stop(self) -> None:
        self._stopped = True
        if hasattr(self, "_align_descend"):
            self._align_descend.stop()

    def reset(self) -> None:
        self.target: dict[str, Any] | None = None
        self.target_index = 0
        self.record_start_altitude_m = 2.0
        self.finish_altitude_m = 1.5
        self.sign_class_names: set[str] = set()
        self.min_sign_confidence = 0.35
        self.min_seen_frames = 3
        self.min_confidence_max = 0.55
        self.min_confidence_mean = 0.40
        self.min_score = 1.2
        self.min_margin_ratio = 1.4
        self.detection_source = "scene"
        self.align_params: dict[str, Any] = {}
        self._skipped = False
        self._done = False
        self._started = False
        self._stopped = False
        self._align_done = False
        self._align_failed = False
        self._align_reason = ""
        self._align_detail: dict[str, Any] = {}
        self._best_score = 0.0
        self._second_score = 0.0
        self._margin_ratio = 0.0
        self.record_frame_count = 0
        self.valid_sign_frame_count = 0
        self._class_stats: dict[str, dict[str, Any]] = {}
        self._priority = 5
        self._align_descend: AlignDescendAction | None = None

    # ── helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _finite_float(value: Any, field_name: str) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field_name} must be a finite number")
        if not math.isfinite(result):
            raise ValueError(f"{field_name} must be finite")
        return result

    @staticmethod
    def _finite_range(value: Any, low: float, high: float, field_name: str) -> float:
        result = ReconDescendObserveAction._finite_float(value, field_name)
        if not (low <= result <= high):
            raise ValueError(f"{field_name} must be in [{low}, {high}]")
        return result

    @staticmethod
    def _finite_ge(value: Any, low: float, field_name: str) -> float:
        result = ReconDescendObserveAction._finite_float(value, field_name)
        if result < low:
            raise ValueError(f"{field_name} must be >= {low}")
        return result

    @staticmethod
    def _extract_target(target: Any) -> dict[str, Any] | None:
        if not isinstance(target, dict):
            return None
        try:
            x = float(target.get("local_x", float("nan")))
            y = float(target.get("local_y", float("nan")))
        except (TypeError, ValueError):
            return None
        if not (math.isfinite(x) and math.isfinite(y)):
            return None
        return dict(target)

    @staticmethod
    def _parse_class_names(raw: Any) -> set[str]:
        if not isinstance(raw, (list, tuple, set)):
            raise ValueError("sign_class_names must be a list, tuple, or set")
        names = {str(item) for item in raw}
        if not names:
            raise ValueError("sign_class_names must be non-empty")
        return names

    def _extract_detections(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract detection items from scene or perception source."""
        if self.detection_source == "scene":
            source = context.get("scene")
            if not isinstance(source, dict):
                return []
            detections = source.get("detections")
            if not isinstance(detections, list):
                return []
            return [d for d in detections if isinstance(d, dict)]
        source = context.get("perception")
        if isinstance(source, dict):
            return [source]
        return []

    def _record_frame(self, height_m: float, context: dict[str, Any]) -> None:
        """If height is inside the recording window, accumulate sign stats.

        Per-frame deduplication: each class is counted at most once per frame.
        When multiple detections of the same class exist, the highest
        confidence is used.
        """
        if not (self.finish_altitude_m <= height_m <= self.record_start_altitude_m):
            return

        self.record_frame_count += 1
        detections = self._extract_detections(context)

        # per-frame per-class best confidence
        frame_best: dict[str, float] = {}
        for item in detections:
            name = str(item.get("class_name") or item.get("label") or "")
            if name not in self.sign_class_names:
                continue
            try:
                confidence = float(item.get("confidence", 0.0))
            except (TypeError, ValueError):
                continue
            if confidence < self.min_sign_confidence:
                continue
            if not math.isfinite(confidence):
                continue
            current = frame_best.get(name, -1.0)
            if confidence > current:
                frame_best[name] = confidence

        if not frame_best:
            return

        self.valid_sign_frame_count += 1
        for name, best_conf in frame_best.items():
            if name not in self._class_stats:
                self._class_stats[name] = {
                    "seen_frames": 0,
                    "conf_sum": 0.0,
                    "conf_max": 0.0,
                }
            stats = self._class_stats[name]
            stats["seen_frames"] += 1
            stats["conf_sum"] += best_conf
            if best_conf > stats["conf_max"]:
                stats["conf_max"] = best_conf

    def _finalize(self) -> ActionResult:
        """Determine best sign class and produce final result with zero-velocity + clear."""
        self._done = True
        zero = self._zero_action()
        clear = self._clear_action()

        if self._skipped:
            return ActionResult(
                actions=[zero, clear],
                done=True,
                reason="skipped_missing_target",
                detail=self._make_detail(status="skipped_missing_target"),
            )

        best = self._best_class()
        if best is None:
            status = "align_failed" if self._align_failed else "blank_or_uncertain"
            depth = self._make_detail(
                status=status, content="blank", sign_class="", confidence=0.0,
                align_failed=self._align_failed,
            )
            return ActionResult(
                actions=[zero, clear],
                done=True,
                reason=self._align_reason or "done",
                detail=depth,
            )

        depth = self._make_detail(
            status="detected",
            content=best["class_name"],
            sign_class=best["class_name"],
            confidence=best["conf_max"],
            best_score=self._best_score,
            second_score=self._second_score,
            margin_ratio=self._margin_ratio,
        )
        return ActionResult(
            actions=[zero, clear],
            done=True,
            reason=self._align_reason or "done",
            detail=depth,
        )

    def _best_class(self) -> dict[str, Any] | None:
        """Return the best-scoring class dict with conf_mean and score.

        Stores best_score, second_score, margin_ratio on self for detail output.
        """
        best_item: dict[str, Any] | None = None
        best_score = 0.0
        second_score = 0.0

        for cls_name, stats in self._class_stats.items():
            seen = stats["seen_frames"]
            if seen < self.min_seen_frames:
                continue
            conf_max = stats["conf_max"]
            if conf_max < self.min_confidence_max:
                continue
            conf_mean = stats["conf_sum"] / seen
            if conf_mean < self.min_confidence_mean:
                continue
            score = seen * conf_mean
            stats["conf_mean"] = conf_mean
            stats["score"] = score
            if score < self.min_score:
                continue
            if score > best_score:
                second_score = best_score
                best_score = score
                best_item = {"class_name": cls_name, "conf_mean": conf_mean, "conf_max": conf_max,
                             "seen_frames": seen, "score": score}
            elif score > second_score:
                second_score = score

        self._best_score = best_score
        self._second_score = second_score

        if best_item is None:
            self._margin_ratio = 0.0
            return None

        # margin check
        if second_score > 0.0 and self.min_margin_ratio > 0.0:
            ratio = best_score / second_score
            self._margin_ratio = ratio
            if ratio < self.min_margin_ratio:
                return None

        self._margin_ratio = 0.0
        return best_item

    def _make_detail(
        self,
        *,
        status: str = "",
        content: str | None = None,
        sign_class: str | None = None,
        confidence: float | None = None,
        align_failed: bool | None = None,
        best_score: float | None = None,
        second_score: float | None = None,
        margin_ratio: float | None = None,
    ) -> dict[str, Any]:
        target = self.target or {}
        detail: dict[str, Any] = {
            "target_id": str(target.get("id") or target.get("target_id") or f"recon_{self.target_index}"),
            "target_index": self.target_index,
            "local_x": target.get("local_x"),
            "local_y": target.get("local_y"),
            "content": content if content is not None else "blank",
            "sign_class": sign_class if sign_class is not None else "",
            "confidence": confidence if confidence is not None else 0.0,
            "status": status or "blank_or_uncertain",
            "align_failed": align_failed if align_failed is not None else self._align_failed,
            "best_score": best_score if best_score is not None else self._best_score,
            "second_score": second_score if second_score is not None else self._second_score,
            "margin_ratio": margin_ratio if margin_ratio is not None else self._margin_ratio,
            "record_frame_count": self.record_frame_count,
            "valid_sign_frame_count": self.valid_sign_frame_count,
            "class_stats": self._serial_class_stats(),
            "height_m": self._align_detail.get("height_m") or self._align_detail.get("current_altitude_m"),
            "record_start_altitude_m": self.record_start_altitude_m,
            "finish_altitude_m": self.finish_altitude_m,
            "recording_active": False,
            "align_reason": self._align_reason,
            "align_detail": self._align_detail,
        }
        if status == "skipped_missing_target":
            detail["content"] = "blank"
            detail["confidence"] = 0.0
            detail["sign_class"] = ""
        return detail

    def _serial_class_stats(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for cls_name, stats in self._class_stats.items():
            seen = stats["seen_frames"]
            conf_mean = stats.get("conf_mean", stats["conf_sum"] / seen if seen > 0 else 0.0)
            score = stats.get("score", seen * conf_mean)
            out[cls_name] = {
                "seen_frames": seen,
                "conf_max": stats["conf_max"],
                "conf_mean": conf_mean,
                "score": score,
            }
        return out

    def _flight_action(self, command: dict[str, Any]) -> dict[str, Any]:
        """Wrap AlignDescend flight command in Dispatcher envelope."""
        return {
            "action_type": "flight_command",
            "params": command,
            "key": f"recon_descend_observe_{self.target_index}",
            "once": False,
            "priority": self._priority,
        }

    def _clear_action(self) -> dict[str, Any]:
        """Return a clear_continuous_commands action to stop stale BODY_NED commands."""
        uc = getattr(self._align_descend, 'update_count', 0) if self._align_descend is not None else 0
        return {
            "action_type": "clear_continuous_commands",
            "params": {"clear_pending_local_position": False},
            "key": f"recon_descend_observe_clear_t{self.target_index}_u{uc}",
            "once": True,
            "priority": 10,
        }

    def _zero_action(self) -> dict[str, Any]:
        """Return a zero-velocity BODY_NED action in Dispatcher envelope."""
        return {
            "action_type": "flight_command",
            "params": {
                "type": "flight_command",
                "frame": "BODY_NED",
                "vx_mps": 0.0,
                "vy_mps": 0.0,
                "vz_mps": 0.0,
                "vx_cmd": 0.0,
                "vy_cmd": 0.0,
                "vz_cmd": 0.0,
                "yaw_rate_cmd": 0.0,
                "gimbal_yaw_rate_cmd": 0.0,
                "gimbal_pitch_rate_cmd": 0.0,
                "gimbal_yaw_angle_cmd": None,
                "gimbal_pitch_angle_cmd": None,
                "enable_body": True,
                "enable_gimbal": False,
                "enable_gimbal_angle": False,
                "enable_approach": False,
                "active": True,
                "valid": True,
                "priority": self._priority,
            },
            "key": f"recon_descend_observe_zero_{self.target_index}",
            "once": False,
            "priority": self._priority,
        }
