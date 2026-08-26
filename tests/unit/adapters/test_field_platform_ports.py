from __future__ import annotations

import json
from dataclasses import fields, replace

from contracts.platform.common import SchemaVersion
from contracts.platform.field import GpsObservation, ReferenceVersion
from contracts.platform.vehicle_commands import *
from field._reference_store import _ReferenceStore
from field.calibration import RuntimeFieldBindingCandidate
from field.geometry import build_runtime_field_geometry
from field.models import HeadingSource, OriginSource
from field.profile_service import FieldProfileService, ReadOnlyFieldProfileRepository
from field.calibration_transaction import FieldCalibrationTransactionAdapter
from telemetry_link.command_broker import CommandBroker


def _candidate():
    profile = FieldProfileService.load_profile("competition_runtime", "config/field_profiles")
    profile = replace(profile, forward_marker=replace(profile.forward_marker, lat=34.001, lon=108.0))
    geometry = build_runtime_field_geometry(profile, origin_lat=34.0, origin_lon=108.0)
    values = dict(profile_id=profile.profile_id, origin_source=OriginSource.RUNTIME_CURRENT_GPS.value,
        heading_source=HeadingSource.RUNTIME_FORWARD_MARKER.value, field_reference_mode="runtime_origin_forward_marker",
        origin_lat=34.0, origin_lon=108.0, forward_marker_lat=geometry.forward_marker_lat,
        forward_marker_lon=geometry.forward_marker_lon, field_heading_yaw_rad=geometry.field_heading_yaw_rad,
        field_heading_deg=geometry.field_heading_deg, baseline_m=geometry.baseline_m, sample_count=20,
        rejected_sample_count=0, duplicate_sample_count=0, sample_duration_s=2.0, started_at_s=1.0,
        horizontal_spread_m=0.1, gps_fix_type=6, gps_satellites=20, gps_eph=0.3, gps_epv=0.5,
        completed_at_s=3.0, warnings=(), geometry=geometry)
    return RuntimeFieldBindingCandidate(**{field.name: values[field.name] for field in fields(RuntimeFieldBindingCandidate)})


def test_profile_repository_priority_hash_and_path_guard(tmp_path) -> None:
    config_dir=tmp_path/"config"; runtime_dir=tmp_path/"runtime"; config_dir.mkdir(); runtime_dir.mkdir()
    source=json.loads(open("config/field_profiles/competition_runtime.json", encoding="utf-8").read())
    (config_dir/"competition_runtime.json").write_text(json.dumps(source), encoding="utf-8")
    source["name"]="runtime shadow"; (runtime_dir/"competition_runtime.json").write_text(json.dumps(source), encoding="utf-8")
    repo=ReadOnlyFieldProfileRepository((("config", config_dir), ("runtime", runtime_dir)))
    record=repo.get("competition_runtime")
    assert record.source == "config" and len(record.content_sha256) == 64 and len(repo.list()) == 1
    try: repo.get("../secret")
    except ValueError: pass
    else: raise AssertionError("path traversal accepted")


def test_reference_commit_is_atomic_versioned_and_replayed() -> None:
    store=_ReferenceStore(generation_id="boot-A"); candidate=_candidate(); base=store.current_version()
    first=store.commit_calibration(candidate, profile_name="test", session_id="s", operation_id="op",
        expected_version=base, timestamp=3.0)
    replay=store.commit_calibration(candidate, profile_name="test", session_id="s", operation_id="op",
        expected_version=base, timestamp=3.0)
    stale=store.commit_calibration(candidate, profile_name="test", session_id="s", operation_id="new",
        expected_version=base, timestamp=3.0)
    assert first.accepted and first.current_version.revision == 1
    assert replay.accepted and replay.replayed and replay.current_version == first.current_version
    assert not stale.accepted and stale.reason_code == "stale_reference_version"
    snap=store.snapshot(); assert snap.is_confirmed and snap.is_frozen and snap.calibration.session_id == "s"
    assert snap.calibration.field_reference_mode == candidate.field_reference_mode
    assert snap.calibration.gps_fix_type == candidate.gps_fix_type
    assert snap.calibration.gps_satellites == candidate.gps_satellites


def _envelope(version):
    return VehicleCommandEnvelope(SchemaVersion(1,0), "c", "r", "l", 1, 1, "sitl", "s", 0, 100,
        1, "k", AckPolicy.DISABLED, CompletionPolicy.STATE_OBSERVED, 0,
        GlobalPositionTarget(1,2,3), version)


def test_field_command_guard_checks_admission_and_prewrite() -> None:
    current=[ReferenceVersion("boot", 0)]; writes=[]
    broker=CommandBroker(writer=writes.append, source=lambda:"sitl", link_session=lambda:"s",
        authorization_generation=lambda:1, send_generation=lambda:1, monotonic_ns=lambda:1,
        field_version_matches=lambda version: version == current[0])
    assert broker.submit(_envelope(current[0])).submission_state == SubmissionState.ACCEPTED
    current[0]=ReferenceVersion("boot",1)
    assert broker.drain_one().reason_code == "stale_field_reference_version" and writes == []
    missing=CommandBroker(writer=writes.append, source=lambda:"sitl", link_session=lambda:"s",
        authorization_generation=lambda:1, send_generation=lambda:1, monotonic_ns=lambda:1)
    assert missing.submit(_envelope(current[0])).reason_code == "field_version_checker_unavailable"


def test_calibration_adapter_preserves_global_position_timestamp() -> None:
    class CaptureSession:
        _session_id = "session-1"
        _session_revision = 4
        state = "sampling"

        def observe(self, snapshot, **_kwargs):
            self.snapshot = snapshot
            return {"ok": True, "state": "sampling", "session_id": self._session_id,
                    "session_revision": self._session_revision}

    session = CaptureSession()
    adapter = FieldCalibrationTransactionAdapter(session, profiles=None)  # type: ignore[arg-type]
    result = adapter.observe(GpsObservation(
        observation_id="vehicle:123.5", observed_at_s=124.0, global_position_valid=True,
        lat=34.0, lon=108.0, gps_fix_type=6, satellites_visible=12, gps_eph=0.5, gps_epv=0.7,
        last_global_position_time=123.5,
    ))
    assert result.accepted
    assert session.snapshot["last_global_position_time"] == 123.5
