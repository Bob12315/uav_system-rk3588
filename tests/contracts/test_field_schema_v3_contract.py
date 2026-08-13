from __future__ import annotations

import math
from dataclasses import fields, replace

import pytest

from field.calibration import RuntimeFieldBindingCandidate
from field.context import RuntimeContextBuilder
from field.coordinates import field_to_gps, gps_to_field_from_origin
from field.geometry import build_runtime_field_geometry
from field.models import FieldReference, HeadingSource, OriginSource
from field.profile_service import FieldProfileService
from field.service import FieldService


def _candidate() -> RuntimeFieldBindingCandidate:
    origin_lat, origin_lon = 34.0, 108.0
    profile = FieldProfileService.load_profile("competition_runtime_v3", profile_dir="config/field_profiles")
    profile = replace(profile, forward_marker=replace(profile.forward_marker, lat=34.001, lon=108.0))
    geometry = build_runtime_field_geometry(profile, origin_lat=origin_lat, origin_lon=origin_lon)
    yaw = geometry.field_heading_yaw_rad
    values = {
        "profile_id": profile.profile_id, "origin_source": OriginSource.RUNTIME_CURRENT_GPS.value,
        "heading_source": HeadingSource.RUNTIME_FORWARD_MARKER.value,
        "field_reference_mode": "runtime_origin_forward_marker",
        "origin_lat": origin_lat, "origin_lon": origin_lon,
        "forward_marker_lat": geometry.forward_marker_lat, "forward_marker_lon": geometry.forward_marker_lon,
        "field_heading_yaw_rad": yaw, "field_heading_deg": math.degrees(yaw),
        "baseline_m": geometry.baseline_m, "sample_count": 20, "rejected_sample_count": 0,
        "duplicate_sample_count": 0, "sample_duration_s": 2.0,
        "started_at_s": 1.0, "horizontal_spread_m": 0.1, "gps_fix_type": 6, "gps_satellites": 20,
        "gps_eph": 0.3, "gps_epv": 0.5, "completed_at_s": 3.0,
        "warnings": (), "geometry": geometry,
    }
    return RuntimeFieldBindingCandidate(**{f.name: values[f.name] for f in fields(RuntimeFieldBindingCandidate)})


def test_field_reference_contains_no_local_origin_and_round_trips_global() -> None:
    assert not any(name.startswith("origin_local_") for name in FieldReference.__dataclass_fields__)
    ref = FieldReference(is_confirmed=True, origin_lat=34.0, origin_lon=108.0, field_heading_yaw_rad=0.25)
    gps = field_to_gps(3.0, 8.0, 4.0, ref)
    field = gps_to_field_from_origin(gps.lat, gps.lon, gps.alt_m, origin_lat=34.0, origin_lon=108.0, field_heading_yaw_rad=0.25)
    assert field.field_x_m == pytest.approx(3.0, abs=1e-6)
    assert field.field_y_m == pytest.approx(8.0, abs=1e-6)


def test_field_service_and_context_share_exact_reference() -> None:
    builder = RuntimeContextBuilder()
    service = FieldService(builder, lambda: {})
    assert builder.field_reference is service.reference
    service.reference.origin_lat = 34.0
    assert builder.field_origin_lat == 34.0


def test_apply_metadata_failure_rolls_back_single_reference(monkeypatch) -> None:
    builder = RuntimeContextBuilder()
    service = FieldService(builder, lambda: {})
    session = service._runtime_binding
    candidate = _candidate()
    session._candidate = candidate
    session._profile_name = "test"
    monkeypatch.setattr(builder, "set_calibration_metadata", lambda value: False)
    result = session._apply(candidate, completed_at_s=3.0)
    assert result["ok"] is False and result["rollback_ok"] is True
    assert service.reference.is_confirmed is False
    assert service.reference.is_frozen is False


def test_successful_apply_is_confirmed_frozen_and_builder_reads_same_values() -> None:
    builder = RuntimeContextBuilder()
    service = FieldService(builder, lambda: {})
    session = service._runtime_binding
    candidate = _candidate()
    session._candidate = candidate
    session._profile_name = "test"
    result = session._apply(candidate, completed_at_s=3.0)
    assert result["ok"] is True
    assert service.reference.is_ready_for_field_to_gps() is True
    assert service.reference.is_frozen is True
    assert builder.field_origin_lat == candidate.origin_lat
    context = builder.build_action_context({})
    assert context["field_gps_transform_confirmed"] is True
    assert "field_origin_local_x" not in context
