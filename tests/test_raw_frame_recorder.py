from __future__ import annotations

import numpy as np

from yolo_app.raw_frame_recorder import RawFrameRecorder


def test_raw_frame_recorder_writes_mp4_frames(tmp_path) -> None:
    recorder = RawFrameRecorder(str(tmp_path), fps=5.0)
    frame = np.zeros((24, 32, 3), dtype=np.uint8)

    start_status = recorder.start(frame.shape)
    recorder.write(frame)
    stop_status = recorder.stop()

    assert start_status.recording is True
    assert start_status.path.endswith(".mp4")
    assert stop_status.recording is False
    assert stop_status.frames == 1
    assert (tmp_path / "camera").exists() is False
    assert (tmp_path / start_status.path.rsplit("/", 1)[-1]).exists()
