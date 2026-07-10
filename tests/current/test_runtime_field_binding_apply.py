"""Tests for runtime field binding apply (step 5B.1)."""

import copy
import math
from dataclasses import replace as dc_replace

import pytest

from app.field_profile import parse_field_profile
from app.field_reference import (
    FieldReference,
    HeadingSource,
    OriginSource,
)
from app.field_reference_service import FieldReferenceService
from app.runtime_context import RuntimeContextBuilder
from app.runtime_field_binding import (
    RuntimeFieldBindingCandidate,
    RuntimeFieldBindingSampler,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_valid_v3_dict() -> dict:
    return {
        "schema_version": 3, "profile_id": "test_apply", "name": "Test Apply",
        "coordinate_convention": {"field_x_positive": "right", "field_y_positive": "forward", "altitude_positive": "up"},
        "forward_marker": {"name": "far", "lat": 34.104189, "lon": 108.642674, "coordinate_system": "WGS84"},
        "field_geometry": {"lane_half_width_m": 4.0, "drop_area_y_min_m": 30.0, "drop_area_y_max_m": 35.0, "drop_center_y_m": 32.5, "recce_area_y_min_m": 55.0, "recce_area_y_max_m": 60.0, "recce_center_y_m": 57.5},
        "drop_scan": {"waypoints": [{"x_m": -2.0, "y_m": 31.25, "altitude_m": 5.0}, {"x_m": 2.0, "y_m": 31.25, "altitude_m": 5.0}, {"x_m": 2.0, "y_m": 33.75, "altitude_m": 5.0}, {"x_m": -2.0, "y_m": 33.75, "altitude_m": 5.0}]},
        "gps_quality": {"min_fix_type": 3, "min_satellites": 10, "max_eph": 2.5, "max_epv": 5.0},
        "runtime_origin_sampling": {"min_samples": 20, "sample_window_s": 5.0, "max_horizontal_spread_m": 1.0, "estimator": "median"},
        "binding_policy": {"min_baseline_m": 30.0, "warn_baseline_below_m": 50.0},
    }


def _make_candidate() -> RuntimeFieldBindingCandidate:
    profile = parse_field_profile(_make_valid_v3_dict())
    s = RuntimeFieldBindingSampler(profile)
    s.start(started_at_s=1000.0)
    for i in range(20):
        s.observe_snapshot({
            "global_position_valid": True, "last_global_position_time": 2000.0 + i * 0.1,
            "lat": 34.103649, "lon": 108.642674,
            "gps_fix_type": 3, "satellites_visible": 12, "gps_eph": 1.0, "gps_epv": 1.5,
        }, observed_at_s=1000.0 + i * 0.26)
    return s.finalize(completed_at_s=1005.0)


# =========================================================================
# A. Service apply_runtime_binding success
# =========================================================================


class TestServiceApplySuccess:
    def test_creates_gps_only_reference(self):
        svc = FieldReferenceService()
        r = svc.apply_runtime_binding(_make_candidate(), profile_name="Test")
        assert r["ok"] is True
        ref = svc.reference
        assert ref.is_confirmed is True
        assert ref.is_frozen is False
        assert ref.origin_source == OriginSource.RUNTIME_CURRENT_GPS.value
        assert ref.heading_source == HeadingSource.RUNTIME_FORWARD_MARKER.value
        assert ref.origin_lat == 34.103649
        assert ref.origin_lon == 108.642674
        assert ref.forward_marker_lat == 34.104189
        assert ref.forward_marker_lon == 108.642674
        assert ref.origin_local_n_m is None
        assert ref.origin_local_e_m is None
        assert ref.origin_local_z_m is None
        assert ref.is_ready() is False
        assert ref.is_ready_for_field_to_local() is False
        assert ref.is_ready_for_field_to_gps() is True

    def test_clears_old_local_origin(self):
        svc = FieldReferenceService()
        ref = svc.reference
        ref.origin_local_n_m = 10.0
        ref.origin_local_e_m = 20.0
        svc.apply_runtime_binding(_make_candidate(), profile_name="Test")
        assert ref.origin_local_n_m is None
        assert ref.origin_local_e_m is None

    def test_status_includes_profile_metadata(self):
        svc = FieldReferenceService()
        svc.apply_runtime_binding(_make_candidate(), profile_name="Test Profile")
        st = svc.status()
        assert st["profile_id"] == "test_apply"
        assert st["profile_name"] == "Test Profile"

    def test_timestamp_default(self):
        svc = FieldReferenceService()
        svc.apply_runtime_binding(_make_candidate(), profile_name="T")
        assert svc.reference.confirmed_at_s == 1005.0

    def test_timestamp_explicit(self):
        svc = FieldReferenceService()
        svc.apply_runtime_binding(_make_candidate(), profile_name="T", timestamp=2000.0)
        assert svc.reference.confirmed_at_s == 2000.0


# =========================================================================
# B. Service apply - rejections
# =========================================================================


class TestServiceApplyRejection:
    def test_frozen_rejected(self):
        svc = FieldReferenceService()
        svc.reference.is_confirmed = True
        svc.reference.freeze()
        r = svc.apply_runtime_binding(_make_candidate(), profile_name="T")
        assert r["ok"] is False
        assert "frozen" in r["error"]

    def test_non_candidate_rejected(self):
        svc = FieldReferenceService()
        for bad in (None, {}, "bad", 123):
            r = svc.apply_runtime_binding(bad, profile_name="T")
            assert r["ok"] is False

    def test_bad_timestamp_rejected(self):
        svc = FieldReferenceService()
        r = svc.apply_runtime_binding(_make_candidate(), profile_name="T", timestamp=float("nan"))
        assert r["ok"] is False

    def test_empty_profile_name_rejected(self):
        svc = FieldReferenceService()
        r = svc.apply_runtime_binding(_make_candidate(), profile_name="")
        assert r["ok"] is False


# =========================================================================
# C. Service - malicious candidate
# =========================================================================


class TestServiceMaliciousCandidate:
    def test_wrong_origin_source(self):
        c = dc_replace(_make_candidate(), origin_source="bad")
        r = FieldReferenceService().apply_runtime_binding(c, profile_name="T")
        assert r["ok"] is False

    def test_wrong_heading_source(self):
        c = dc_replace(_make_candidate(), heading_source="bad")
        r = FieldReferenceService().apply_runtime_binding(c, profile_name="T")
        assert r["ok"] is False

    def test_wrong_mode(self):
        c = dc_replace(_make_candidate(), field_reference_mode="bad")
        r = FieldReferenceService().apply_runtime_binding(c, profile_name="T")
        assert r["ok"] is False

    def test_nan_origin(self):
        c = dc_replace(_make_candidate(), origin_lat=float("nan"))
        r = FieldReferenceService().apply_runtime_binding(c, profile_name="T")
        assert r["ok"] is False

    def test_heading_deg_inconsistent(self):
        c = dc_replace(_make_candidate(), field_heading_deg=999.0)
        r = FieldReferenceService().apply_runtime_binding(c, profile_name="T")
        assert r["ok"] is False

    def test_geometry_profile_mismatch(self):
        c = _make_candidate()
        c = dc_replace(c, geometry=dc_replace(c.geometry, profile_id="wrong"))
        r = FieldReferenceService().apply_runtime_binding(c, profile_name="T")
        assert r["ok"] is False

    def test_geometry_origin_mismatch(self):
        c = _make_candidate()
        c = dc_replace(c, geometry=dc_replace(c.geometry, origin_lat=99.0))
        r = FieldReferenceService().apply_runtime_binding(c, profile_name="T")
        assert r["ok"] is False

    def test_warnings_mismatch(self):
        c = _make_candidate()
        c = dc_replace(c, warnings=("fake",))
        r = FieldReferenceService().apply_runtime_binding(c, profile_name="T")
        assert r["ok"] is False

    def test_no_state_change_on_rejection(self):
        svc = FieldReferenceService()
        ref = svc.reference
        ref.origin_lat = 99.0  # pre-existing value
        c = dc_replace(_make_candidate(), origin_lat=float("nan"))
        svc.apply_runtime_binding(c, profile_name="T")
        assert ref.origin_lat == 99.0  # unchanged


# =========================================================================
# D. Builder confirm_runtime_gps_reference
# =========================================================================


class TestBuilderConfirm:
    def test_creates_gps_only_builder(self):
        b = RuntimeContextBuilder()
        assert b.confirm_runtime_gps_reference(_make_candidate()) is True
        assert b.field_heading_confirmed is True
        assert b.field_origin_gps_confirmed is True
        assert b.field_origin_confirmed is False
        assert b.field_gps_transform_ready() is True
        assert b.field_transform_ready() is False
        assert b.field_origin_local_x is None
        assert b.field_origin_lat == 34.103649
        assert b.field_forward_marker_lat == 34.104189
        assert b.field_baseline_m == pytest.approx(60.0, abs=0.1)
        assert b.field_gps_sample_count == 20

    def test_timestamp_default(self):
        b = RuntimeContextBuilder()
        b.confirm_runtime_gps_reference(_make_candidate())
        assert b.field_origin_time == 1005.0

    def test_timestamp_explicit(self):
        b = RuntimeContextBuilder()
        b.confirm_runtime_gps_reference(_make_candidate(), timestamp=2000.0)
        assert b.field_origin_time == 2000.0

    def test_invalid_no_mutation(self):
        b = RuntimeContextBuilder()
        b.field_origin_lat = 99.0
        b.confirm_runtime_gps_reference("bad")  # non-candidate
        assert b.field_origin_lat == 99.0

    def test_spread_over_threshold(self):
        c = dc_replace(_make_candidate(), horizontal_spread_m=float("nan"))
        b = RuntimeContextBuilder()
        assert b.confirm_runtime_gps_reference(c) is False


# =========================================================================
# E. Builder action context
# =========================================================================


class TestBuilderActionContext:
    def test_gps_context_flags(self):
        b = RuntimeContextBuilder()
        b.confirm_runtime_gps_reference(_make_candidate())
        ctx = b.build_action_context({"drone": {}})
        assert ctx["field_origin_confirmed"] is False
        assert ctx["field_origin_gps_confirmed"] is True
        assert ctx["field_gps_transform_confirmed"] is True
        assert "field_origin_lat" in ctx
        assert "field_origin_local_x" not in ctx

    def test_field_gps_transform_dict(self):
        b = RuntimeContextBuilder()
        b.confirm_runtime_gps_reference(_make_candidate())
        ctx = b.build_action_context({"drone": {}})
        ft = ctx["field_gps_transform"]
        assert ft["confirmed"] is True
        assert "origin_lat" in ft
        assert "origin_local_x" not in ft


# =========================================================================
# F. Builder clear
# =========================================================================


class TestBuilderClear:
    def test_clear_resets_all(self):
        b = RuntimeContextBuilder()
        b.confirm_runtime_gps_reference(_make_candidate())
        b.clear_field_heading()
        assert b.field_gps_transform_ready() is False
        assert b.field_transform_ready() is False
        assert b.field_origin_gps_confirmed is False
        assert b.field_heading_confirmed is False


# =========================================================================
# G. Builder snapshot/restore
# =========================================================================


class TestBuilderSnapshotRestore:
    def test_roundtrip(self):
        b = RuntimeContextBuilder()
        b.confirm_runtime_gps_reference(_make_candidate())
        snap = b.snapshot_field_reference_state()
        b.clear_field_heading()
        assert b.restore_field_reference_state(snap) is True
        assert b.field_gps_transform_ready() is True

    def test_invalid_snapshot(self):
        b = RuntimeContextBuilder()
        b.confirm_runtime_gps_reference(_make_candidate())
        assert b.restore_field_reference_state("bad") is False
        assert b.restore_field_reference_state({"a": 1}) is False

    def test_snapshot_independent(self):
        b = RuntimeContextBuilder()
        b.confirm_runtime_gps_reference(_make_candidate())
        snap = b.snapshot_field_reference_state()
        b.clear_field_heading()
        assert b.field_gps_transform_ready() is False
        assert snap["field_origin_lat"] == 34.103649


# =========================================================================
# H. Service/reference parity
# =========================================================================


class TestParity:
    def test_service_and_builder_apply_same(self):
        c = _make_candidate()
        svc = FieldReferenceService()
        svc.apply_runtime_binding(c, profile_name="T")
        b = RuntimeContextBuilder()
        b.confirm_runtime_gps_reference(c)
        assert svc.reference.origin_lat == b.field_origin_lat
        assert svc.reference.origin_lon == b.field_origin_lon
        assert svc.reference.is_ready_for_field_to_gps() is True
        assert b.field_gps_transform_ready() is True
