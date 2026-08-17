from __future__ import annotations

import math
import threading
import uuid
from dataclasses import replace
from typing import Callable, Mapping

from contracts.platform.field import (
    CalibrationSummary, FieldReferenceSnapshot, ReferenceVersion, ReferenceWriteReceipt,
)
from .calibration import RuntimeFieldBindingCandidate, validate_runtime_field_binding_candidate
from .models import FieldReference, FieldReferenceError, OriginSource


class _ReferenceStore:
    """Atomic, versioned owner of the committed Field reference."""

    def __init__(self, reference: FieldReference | None = None, *, generation_id: str | None = None) -> None:
        self._lock = threading.RLock()
        self._generation_id = generation_id or uuid.uuid4().hex
        ref = reference or FieldReference()
        self._snapshot = self._from_legacy(ref, ReferenceVersion(self._generation_id, 0))
        self._operations: dict[str, ReferenceWriteReceipt] = {}
        self._listeners: list[Callable[[ReferenceVersion, str], None]] = []

    @property
    def reference(self) -> FieldReference:
        """Compatibility projection; never returns the live repository state."""
        return self.to_legacy_reference(self.snapshot())

    def snapshot(self) -> FieldReferenceSnapshot:
        with self._lock:
            return self._snapshot

    def current_version(self) -> ReferenceVersion:
        return self.snapshot().version

    def subscribe_version_change(self, listener: Callable[[ReferenceVersion, str], None]) -> None:
        with self._lock:
            self._listeners.append(listener)

    def version_matches(self, version: ReferenceVersion) -> bool:
        with self._lock:
            return self._snapshot.version == version

    def commit_calibration(
        self, candidate: RuntimeFieldBindingCandidate, *, profile_name: str,
        session_id: str, operation_id: str, expected_version: ReferenceVersion,
        timestamp: float,
    ) -> ReferenceWriteReceipt:
        with self._lock:
            replay = self._operations.get(operation_id)
            if replay is not None:
                return replace(replay, replayed=True)
            previous = self._snapshot
            rejected = self._validate_write(operation_id, previous.version, expected_version)
            if rejected is not None:
                return rejected
            errors = list(validate_runtime_field_binding_candidate(candidate))
            if errors:
                return self._reject(operation_id, previous.version, "invalid_candidate")
            if not profile_name.strip() or not math.isfinite(float(timestamp)) or timestamp < candidate.completed_at_s:
                return self._reject(operation_id, previous.version, "invalid_commit_metadata")
            version = ReferenceVersion(self._generation_id, previous.version.revision + 1)
            summary = CalibrationSummary(
                session_id=session_id, profile_id=candidate.profile_id,
                sample_count=candidate.sample_count,
                rejected_sample_count=candidate.rejected_sample_count,
                duplicate_sample_count=candidate.duplicate_sample_count,
                sample_duration_s=candidate.sample_duration_s,
                horizontal_spread_m=candidate.horizontal_spread_m,
                baseline_m=candidate.baseline_m,
                field_reference_mode=candidate.field_reference_mode,
                gps_fix_type=candidate.gps_fix_type,
                gps_satellites=candidate.gps_satellites,
                gps_eph=candidate.gps_eph,
                gps_epv=candidate.gps_epv,
                warnings=tuple(candidate.warnings),
            )
            self._snapshot = FieldReferenceSnapshot(
                version, True, True, candidate.origin_source, candidate.heading_source,
                candidate.origin_lat, candidate.origin_lon,
                candidate.forward_marker_lat, candidate.forward_marker_lon,
                FieldReference._normalize_yaw(candidate.field_heading_yaw_rad), float(timestamp),
                candidate.profile_id, profile_name.strip(), summary,
            )
            receipt = ReferenceWriteReceipt(True, operation_id, previous.version, version, "committed")
            self._operations[operation_id] = receipt
            listeners = tuple(self._listeners)
        self._notify(listeners, version, "calibration_commit")
        return receipt

    def reset(self, *, operation_id: str | None = None,
              expected_version: ReferenceVersion | None = None) -> dict[str, object]:
        operation_id = operation_id or uuid.uuid4().hex
        with self._lock:
            replay = self._operations.get(operation_id)
            if replay is not None:
                return self._receipt_dict(replace(replay, replayed=True))
            previous = self._snapshot
            expected = expected_version or previous.version
            rejected = self._validate_write(operation_id, previous.version, expected)
            if rejected is not None:
                return self._receipt_dict(rejected)
            version = ReferenceVersion(self._generation_id, previous.version.revision + 1)
            self._snapshot = FieldReferenceSnapshot(
                version, False, False, None, None, None, None, None, None, None, None,
                None, None, CalibrationSummary(),
            )
            receipt = ReferenceWriteReceipt(True, operation_id, previous.version, version, "reset")
            self._operations[operation_id] = receipt
            listeners = tuple(self._listeners)
        self._notify(listeners, version, "reset")
        return self._receipt_dict(receipt)

    def freeze(self, *, operation_id: str | None = None,
               expected_version: ReferenceVersion | None = None) -> dict[str, object]:
        operation_id = operation_id or uuid.uuid4().hex
        with self._lock:
            replay = self._operations.get(operation_id)
            if replay is not None: return self._receipt_dict(replace(replay, replayed=True))
            previous = self._snapshot
            if not previous.is_confirmed:
                return self._receipt_dict(self._reject(operation_id, previous.version, "not_confirmed"))
            expected = expected_version or previous.version
            rejected = self._validate_write(operation_id, previous.version, expected)
            if rejected is not None: return self._receipt_dict(rejected)
            if previous.is_frozen:
                receipt = ReferenceWriteReceipt(True, operation_id, previous.version, previous.version, "already_frozen")
            else:
                version = ReferenceVersion(self._generation_id, previous.version.revision + 1)
                self._snapshot = replace(previous, version=version, is_frozen=True)
                receipt = ReferenceWriteReceipt(True, operation_id, previous.version, version, "frozen")
            self._operations[operation_id] = receipt
            listeners = tuple(self._listeners)
        self._notify(listeners, receipt.current_version, "freeze")
        return self._receipt_dict(receipt)

    def status(self) -> dict[str, object]:
        snap = self.snapshot()
        ref = self.to_legacy_reference(snap)
        result = {
            "version": {"generation_id": snap.version.generation_id, "revision": snap.version.revision},
            "is_confirmed": snap.is_confirmed, "is_frozen": snap.is_frozen,
            "is_ready": ref.is_ready(), "is_ready_for_field_to_gps": ref.is_ready_for_field_to_gps(),
            "origin_source": snap.origin_source, "heading_source": snap.heading_source,
            "origin_lat": snap.origin_lat, "origin_lon": snap.origin_lon,
            "forward_marker_lat": snap.forward_marker_lat, "forward_marker_lon": snap.forward_marker_lon,
            "field_heading_yaw_rad": snap.field_heading_yaw_rad, "confirmed_at_s": snap.confirmed_at_s,
            "calibration": snap.calibration,
        }
        if snap.origin_source == OriginSource.RUNTIME_CURRENT_GPS.value:
            result.update(profile_id=snap.profile_id, profile_name=snap.profile_name)
        return result

    def _validate_write(self, operation_id: str, current: ReferenceVersion,
                        expected: ReferenceVersion) -> ReferenceWriteReceipt | None:
        if expected.generation_id != self._generation_id:
            return self._reject(operation_id, current, "generation_mismatch")
        if expected != current:
            return self._reject(operation_id, current, "stale_reference_version")
        return None

    def _reject(self, operation_id: str, current: ReferenceVersion, reason: str) -> ReferenceWriteReceipt:
        receipt = ReferenceWriteReceipt(False, operation_id, current, current, reason)
        self._operations.setdefault(operation_id, receipt)
        return receipt

    @staticmethod
    def _notify(listeners, version: ReferenceVersion, reason: str) -> None:
        for listener in listeners:
            try: listener(version, reason)
            except Exception: pass

    @staticmethod
    def _receipt_dict(receipt: ReferenceWriteReceipt) -> dict[str, object]:
        return {"ok": receipt.accepted, "reason_code": receipt.reason_code,
                "operation_id": receipt.operation_id, "replayed": receipt.replayed,
                "version": {"generation_id": receipt.current_version.generation_id,
                            "revision": receipt.current_version.revision}}

    @staticmethod
    def _from_legacy(ref: FieldReference, version: ReferenceVersion) -> FieldReferenceSnapshot:
        return FieldReferenceSnapshot(version, ref.is_confirmed, ref.is_frozen, ref.origin_source,
            ref.heading_source, ref.origin_lat, ref.origin_lon, ref.forward_marker_lat,
            ref.forward_marker_lon, ref.field_heading_yaw_rad, ref.confirmed_at_s,
            None, None, CalibrationSummary())

    @staticmethod
    def to_legacy_reference(snap: FieldReferenceSnapshot) -> FieldReference:
        return FieldReference(snap.is_confirmed, snap.is_frozen, snap.origin_source, snap.heading_source,
            snap.origin_lat, snap.origin_lon, snap.forward_marker_lat, snap.forward_marker_lon,
            snap.field_heading_yaw_rad, snap.confirmed_at_s)
