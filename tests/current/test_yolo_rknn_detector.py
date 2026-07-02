from __future__ import annotations

import numpy as np
import pytest

from yolo_app.rknn_detector import Detection, RknnDetector, letterbox, postprocess
from yolo_app.tracker_runner import _IoUTracker


def _empty_outputs():
    outputs = []
    for size in (80, 40, 20):
        outputs.extend(
            [
                np.zeros((1, 64, size, size), dtype=np.float32),
                np.zeros((1, 3, size, size), dtype=np.float32),
                np.zeros((1, 1, size, size), dtype=np.float32),
            ]
        )
    return outputs


def test_letterbox_produces_rgb_batched_uint8_input() -> None:
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    image[0, 0] = [10, 20, 30]

    data, scale, pad_x, pad_y = letterbox(image)

    assert data.shape == (1, 640, 640, 3)
    assert data.dtype == np.uint8
    assert data[0, pad_y, pad_x].tolist() == [30, 20, 10]
    assert (scale, pad_x, pad_y) == (1.0, 0, 80)


def test_postprocess_uses_score_sum_candidate_and_dfl_branch_output() -> None:
    outputs = _empty_outputs()
    outputs[2][0, 0, 10, 20] = 0.9
    outputs[1][0, 1, 10, 20] = 0.8

    detections = postprocess(outputs, 1.0, 0, 0, (640, 640, 3), 0.25, 0.45)

    assert len(detections) == 1
    detection = detections[0]
    assert detection.class_name == "bucket"
    assert np.isclose(detection.confidence, 0.8)
    assert (detection.x1, detection.y1, detection.x2, detection.y2) == (104.0, 24.0, 224.0, 144.0)


def test_postprocess_supports_flat_single_class_output() -> None:
    output = np.zeros((1, 5, 2), dtype=np.float32)
    output[0, :, 0] = [120.0, 140.0, 40.0, 60.0, 0.8]

    detections = postprocess(
        [output],
        1.0,
        0,
        0,
        (640, 640, 3),
        0.25,
        0.45,
        class_names=("bucket",),
    )

    assert len(detections) == 1
    detection = detections[0]
    assert detection.class_name == "bucket"
    assert np.isclose(detection.confidence, 0.8)
    assert (detection.x1, detection.y1, detection.x2, detection.y2) == (100.0, 110.0, 140.0, 170.0)


def test_rknn_iou_tracker_keeps_visible_detection_id() -> None:
    tracker = _IoUTracker(max_lost_frames=5)
    first = Detection(0, "Target", 0.9, 10, 10, 50, 50)
    shifted = Detection(0, "Target", 0.85, 12, 12, 52, 52)

    first_tracks = tracker.update([first])
    second_tracks = tracker.update([shifted])

    assert first_tracks[0].track_id == second_tracks[0].track_id


def test_detector_rejects_non_rknn_models_before_runtime_loading() -> None:
    with pytest.raises(ValueError, match=r"requires an \.rknn model"):
        RknnDetector("model.onnx", 0.25, 0.45, [])
