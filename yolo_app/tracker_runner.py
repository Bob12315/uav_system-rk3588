from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np

try:
    from .config import AppConfig
    from .models import Track
    from .rknn_detector import Detection, RknnDetector
except ImportError:
    from config import AppConfig
    from models import Track
    from rknn_detector import Detection, RknnDetector


@dataclass(frozen=True, slots=True)
class InferenceTicket:
    future: Future


class TrackerRunner:
    """Expose RK3588 RKNN detections as project-level tracks."""

    def __init__(
        self,
        cfg: AppConfig,
        detector_factory: Callable[..., RknnDetector] = RknnDetector,
    ) -> None:
        worker_count = int(cfg.inference_workers)
        self.detectors: list[RknnDetector] = []
        try:
            for worker_index in range(worker_count):
                self.detectors.append(detector_factory(
                    model_path=cfg.model_path,
                    conf_thres=cfg.conf_thres,
                    iou_thres=cfg.iou_thres,
                    classes=cfg.classes,
                    class_names=tuple(cfg.class_names),
                    npu_core=worker_index if worker_count > 1 else None,
                ))
        except Exception:
            for detector in self.detectors:
                detector.release()
            raise
        self.executors = [
            ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"RknnCore{index}")
            for index in range(worker_count)
        ]
        self._next_worker = 0
        self._last_metrics_ms = {"preprocess": 0.0, "npu": 0.0, "postprocess": 0.0}
        self.iou_tracker = _IoUTracker(max_lost_frames=cfg.max_lost_frames)

    def run(self, frame, valid_mask=None) -> list[Track]:
        return self.complete(self.submit(frame, valid_mask=valid_mask))

    def submit(self, frame, valid_mask=None) -> InferenceTicket:
        worker_index = self._next_worker
        self._next_worker = (self._next_worker + 1) % len(self.detectors)
        future = self.executors[worker_index].submit(
            self._detect,
            self.detectors[worker_index],
            frame,
            valid_mask,
        )
        return InferenceTicket(future)

    @staticmethod
    def _detect(detector: RknnDetector, frame, valid_mask=None):
        detector_frame = frame
        if valid_mask is not None:
            _validate_mask(valid_mask, frame.shape[:2])
            detector_frame = cv2.bitwise_and(frame, frame, mask=valid_mask)
        detections = detector.detect(detector_frame)
        if valid_mask is not None:
            detections = _filter_detections_by_valid_mask(detections, valid_mask)
        return detections, dict(detector.last_metrics_ms)

    def complete(self, ticket: InferenceTicket) -> list[Track]:
        detections, metrics = ticket.future.result()
        self._last_metrics_ms = metrics
        return self.iou_tracker.update(detections)

    @staticmethod
    def cancel(ticket: InferenceTicket) -> None:
        ticket.future.cancel()

    def reset(self) -> None:
        self.iou_tracker.reset()

    @property
    def last_metrics_ms(self) -> dict[str, float]:
        return self._last_metrics_ms

    def release(self) -> None:
        for executor in self.executors:
            executor.shutdown(wait=True, cancel_futures=True)
        for detector in self.detectors:
            detector.release()


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

    def reset(self) -> None:
        self.states.clear()

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


def _validate_mask(valid_mask: np.ndarray, frame_shape: tuple[int, int]) -> None:
    if valid_mask.ndim != 2 or valid_mask.shape != frame_shape:
        raise ValueError("valid_mask must match the frame height and width")
    if valid_mask.dtype != np.uint8:
        raise ValueError("valid_mask must be uint8")


def _filter_detections_by_valid_mask(
    detections: list[Detection], valid_mask: np.ndarray
) -> list[Detection]:
    """Reject every box containing pixels not backed by the real camera image."""
    height, width = valid_mask.shape
    valid = valid_mask == 255
    filtered: list[Detection] = []
    for detection in detections:
        left = max(0, min(width - 1, int(np.floor(detection.x1))))
        top = max(0, min(height - 1, int(np.floor(detection.y1))))
        right = max(left + 1, min(width, int(np.ceil(detection.x2)) + 1))
        bottom = max(top + 1, min(height, int(np.ceil(detection.y2)) + 1))
        if bool(np.all(valid[top:bottom, left:right])):
            filtered.append(detection)
    return filtered


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
