from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from contracts.platform.observability import (
    CycleRecordEnvelope, PruneReceipt, RecorderSegmentMetadata, RetentionPolicy,
)


class JsonlCycleStore:
    def __init__(self, output_dir: str | Path, *, runtime_root: str | Path,
                 rotate_bytes: int = 0, flush_every: int = 1) -> None:
        self.runtime_root = Path(runtime_root).resolve()
        self.output_dir = Path(output_dir).resolve()
        try: self.output_dir.relative_to(self.runtime_root)
        except ValueError as exc: raise ValueError("cycle store must be under injected runtime root") from exc
        self.rotate_bytes = max(0, int(rotate_bytes)); self.flush_every = max(1, int(flush_every))
        self._handle = None; self._path: Path | None = None; self._writes = 0
        self._metadata: RecorderSegmentMetadata | None = None
        self._meta_path: Path | None = None

    @property
    def current_segment(self) -> str | None:
        return None if self._path is None else str(self._path)

    def open_segment(self, metadata: RecorderSegmentMetadata) -> None:
        self.close_segment(); self.output_dir.mkdir(parents=True, exist_ok=True)
        self._metadata = metadata
        stamp = metadata.created_at_utc.strftime("%Y%m%d_%H%M%S_%f")
        self._path = self.output_dir / f"{stamp}_{metadata.recorder_session_id[:8]}_{uuid.uuid4().hex[:8]}.jsonl"
        self._handle = self._path.open("x", encoding="utf-8")
        self._meta_path = self._path.with_suffix(".meta.json")
        self._meta_path.write_text(json.dumps({
            "format": "uav_system.cycle.v1", "data_file": self._path.name,
            "recorder_session_id": metadata.recorder_session_id,
            "created_at_utc": metadata.created_at_utc.isoformat(), "reason": metadata.reason,
            "sample_hz": metadata.sample_hz,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        self._writes = 0

    def append(self, record: CycleRecordEnvelope) -> None:
        if self._handle is None: raise RuntimeError("cycle segment is not open")
        data = asdict(record); data["schema"] = asdict(record.schema); data["payload_schema"] = asdict(record.payload_schema)
        data["sampled_at_utc"] = record.sampled_at_utc.isoformat(); data["payload"] = record.payload.value()
        self._handle.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._writes += 1
        if self._writes % self.flush_every == 0: self._handle.flush()
        if self.rotate_bytes and self._path is not None:
            self._handle.flush()
        if self.rotate_bytes and self._path is not None and self._path.stat().st_size >= self.rotate_bytes:
            assert self._metadata is not None
            self.open_segment(RecorderSegmentMetadata(self._metadata.recorder_session_id,
                datetime.now(timezone.utc), self._metadata.reason, self._metadata.sample_hz))

    def close_segment(self, status: object | None = None) -> None:
        if self._handle is not None:
            self._handle.flush(); self._handle.close(); self._handle = None
        if status is not None and self._meta_path is not None and self._meta_path.exists():
            meta=json.loads(self._meta_path.read_text(encoding="utf-8"))
            meta["recorder_status"] = {
                "state": getattr(getattr(status,"state",None),"value",str(getattr(status,"state",""))),
                "persisted": int(getattr(status,"persisted",0)), "dropped": int(getattr(status,"dropped",0)),
                "dropped_sequence_ranges": list(getattr(status,"dropped_sequence_ranges",())),
                "write_failures": int(getattr(status,"write_failures",0)),
                "last_error": getattr(status,"last_error",None),
            }
            self._meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def prune(self, policy: RetentionPolicy) -> PruneReceipt:
        if policy.keep_files <= 0: return PruneReceipt((), ())
        files = sorted(self.output_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        removed=[]; failures=[]
        for path in files[policy.keep_files:]:
            try:
                path.unlink(); removed.append(str(path))
                meta = path.with_suffix(".meta.json")
                if meta.exists(): meta.unlink()
            except OSError as exc: failures.append(f"{path}:{exc}")
        return PruneReceipt(tuple(removed), tuple(failures))
