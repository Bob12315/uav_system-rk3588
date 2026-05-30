from __future__ import annotations

from dataclasses import dataclass

try:
    from .config import AppConfig
    from .models import Track
    from .rknn_detector import Detection, RknnDetector
except ImportError:
    from config import AppConfig
    from models import Track
    from rknn_detector import Detection, RknnDetector


class TrackerRunner:
    """Expose RK3588 RKNN detections as project-level tracks."""

    def __init__(self, cfg: AppConfig) -> None:
        self.detector = RknnDetector(
            model_path=cfg.model_path,
            conf_thres=cfg.conf_thres,
            iou_thres=cfg.iou_thres,
            classes=cfg.classes,
            class_names=tuple(cfg.class_names),
        )
        self.iou_tracker = _IoUTracker(max_lost_frames=cfg.max_lost_frames)

    def run(self, frame) -> list[Track]:
        return self.iou_tracker.update(self.detector.detect(frame))

    def release(self) -> None:
        self.detector.release()


@dataclass(slots=True)
class _TrackState:
    track: Track
    lost_frames: int = 0


class _IoUTracker:
    """Maintain short-lived IDs for RKNN detections consumed by target management."""

    def __init__(self, max_lost_frames: int, match_iou: float = 0.25) -> None:
        self.max_lost_frames = max(1, max_lost_frames)
        self.match_iou = match_iou
        self.next_id = 1
        self.states: dict[int, _TrackState] = {}

    def update(self, detections: list[Detection]) -> list[Track]:
        for state in self.states.values():
            state.lost_frames += 1

        candidates = []
        for detection_index, detection in enumerate(detections):
            for track_id, state in self.states.items():
                if state.track.class_id != detection.class_id:
                    continue
                overlap = _iou(detection, state.track)
                if overlap >= self.match_iou:
                    candidates.append((overlap, detection_index, track_id))

        assignments: dict[int, int] = {}
        used_track_ids: set[int] = set()
        for _, detection_index, track_id in sorted(candidates, reverse=True):
            if detection_index in assignments or track_id in used_track_ids:
                continue
            assignments[detection_index] = track_id
            used_track_ids.add(track_id)

        visible: list[Track] = []
        for index, detection in enumerate(detections):
            track_id = assignments.get(index)
            if track_id is None:
                track_id = self.next_id
                self.next_id += 1
            track = Track(
                track_id=track_id,
                class_id=detection.class_id,
                class_name=detection.class_name,
                confidence=detection.confidence,
                x1=detection.x1,
                y1=detection.y1,
                x2=detection.x2,
                y2=detection.y2,
            )
            self.states[track_id] = _TrackState(track=track)
            visible.append(track)

        self.states = {
            track_id: state
            for track_id, state in self.states.items()
            if state.lost_frames <= self.max_lost_frames
        }
        return visible


def _iou(first, second) -> float:
    left = max(first.x1, second.x1)
    top = max(first.y1, second.y1)
    right = min(first.x2, second.x2)
    bottom = min(first.y2, second.y2)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    first_area = max(0.0, first.x2 - first.x1) * max(0.0, first.y2 - first.y1)
    second_area = max(0.0, second.x2 - second.x1) * max(0.0, second.y2 - second.y1)
    union = first_area + second_area - intersection
    return intersection / union if union > 0 else 0.0
