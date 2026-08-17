from __future__ import annotations

from yolo_app.raw_frame_recorder import RawFrameRecorder


class _Writer:
    def __init__(self): self.released=False; self.frames=0
    def isOpened(self): return True
    def write(self, frame): self.frames += 1
    def release(self): self.released=True


def test_recorder_is_actual_owner_of_state_session_and_hard_timeout(tmp_path) -> None:
    now=[10.0]; writers=[]
    def factory(*args, **kwargs):
        writer=_Writer(); writers.append(writer); return writer
    recorder=RawFrameRecorder(str(tmp_path), 30, max_duration_s=2, monotonic=lambda:now[0],
        video_writer_factory=factory, fourcc_factory=lambda *args: 0)
    started=recorder.start((480,640,3))
    assert started.state == "RECORDING" and started.recorder_session_id and started.expires_at_monotonic == 12
    same=recorder.start((480,640,3)); assert same.recorder_session_id == started.recorder_session_id
    now[0]=12.1
    assert recorder.stop_if_expired() is True
    stopped=recorder.status()
    assert stopped.state == "STOPPED" and not stopped.recording and writers[0].released


def test_recorder_reports_write_and_close_failures_as_actual_failed_state(tmp_path) -> None:
    class BrokenWrite(_Writer):
        def write(self, frame): raise OSError("disk full")
    writer = BrokenWrite()
    recorder = RawFrameRecorder(str(tmp_path), 30, video_writer_factory=lambda *args: writer,
                                fourcc_factory=lambda *args: 0)
    recorder.start((10, 10, 3)); recorder.write(object())
    assert recorder.status().state == "FAILED"
    assert recorder.status().error == "recording write failed: disk full"
    assert writer.released

    class BrokenClose(_Writer):
        def release(self): raise OSError("flush failed")
    writer2 = BrokenClose()
    recorder2 = RawFrameRecorder(str(tmp_path), 30, video_writer_factory=lambda *args: writer2,
                                 fourcc_factory=lambda *args: 0)
    recorder2.start((10, 10, 3))
    stopped = recorder2.stop()
    assert stopped.state == "FAILED" and stopped.error == "recording close failed: flush failed"
