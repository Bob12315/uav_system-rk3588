from __future__ import annotations

from contracts.platform.observability import CycleRecordEnvelope, RecorderStart


class V1CycleWriterAdapter:
    """Stateless projection for historical blackbox-v1 readers."""

    @staticmethod
    def project(record: CycleRecordEnvelope) -> dict[str, object]:
        value = record.payload.value()
        if not isinstance(value, dict): raise ValueError("v1 cycle payload must be an object")
        projected = dict(value)
        projected.setdefault("seq", record.sequence)
        projected.setdefault("t", record.sampled_at_utc.timestamp())
        return projected

    def __init__(self, recorder: object | None = None, *, sample_hz: float = 0.0) -> None:
        self.recorder = recorder; self.sample_hz = sample_hz

    def update_recording_state(self, *, armed: bool, reason: str = "vehicle_armed"):
        if self.recorder is None: return None
        status = self.recorder.status()
        if armed and status.state.value != "RECORDING":
            return self.recorder.start_session(RecorderStart(reason, self.sample_hz))
        if not armed and status.state.value == "RECORDING":
            return self.recorder.stop_session("vehicle_disarmed")
        return status
