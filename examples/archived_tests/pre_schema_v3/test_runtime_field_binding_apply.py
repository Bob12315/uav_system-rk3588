"""Archived dual-state runtime binding apply tests."""

import copy
import math
from dataclasses import replace as dc_replace

import pytest

from field.profile import parse_field_profile
from field.models import (
    FieldReference,
    HeadingSource,
    OriginSource,
)
from field.reference_service import FieldReferenceService
from field.context import RuntimeContextBuilder
from field.calibration import (
    RuntimeFieldBindingCandidate,
    RuntimeFieldBindingSampler,
    validate_runtime_field_binding_candidate,
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


def _damage_geometry(candidate, case):
    geometry = candidate.geometry
    if case == "scan_nan_lat":
        points = list(geometry.drop_scan_waypoints)
        points[0] = dc_replace(points[0], lat=float("nan"))
        geometry = dc_replace(geometry, drop_scan_waypoints=tuple(points))
    elif case == "scan_bad_lon":
        points = list(geometry.drop_scan_waypoints)
        points[1] = dc_replace(points[1], lon=181.0)
        geometry = dc_replace(geometry, drop_scan_waypoints=tuple(points))
    elif case == "scan_bad_name":
        points = list(geometry.drop_scan_waypoints)
        points[2] = dc_replace(points[2], name="bad")
        geometry = dc_replace(geometry, drop_scan_waypoints=tuple(points))
    elif case == "drop_count":
        geometry = dc_replace(
            geometry, drop_area_corners=geometry.drop_area_corners[:3]
        )
    elif case == "drop_asymmetry":
        points = list(geometry.drop_area_corners)
        points[0] = dc_replace(points[0], field_x_m=points[0].field_x_m + 0.5)
        geometry = dc_replace(geometry, drop_area_corners=tuple(points))
    elif case == "recce_altitude":
        points = list(geometry.recce_area_corners)
        points[0] = dc_replace(points[0], altitude_m=1.0)
        geometry = dc_replace(geometry, recce_area_corners=tuple(points))
    elif case == "home_name":
        geometry = dc_replace(
            geometry, home=dc_replace(geometry.home, name="NOT_HOME")
        )
    elif case == "marker_field_y":
        geometry = dc_replace(
            geometry,
            forward_marker=dc_replace(
                geometry.forward_marker,
                field_y_m=geometry.forward_marker.field_y_m + 1.0,
            ),
        )
    else:
        raise AssertionError(case)
    return dc_replace(candidate, geometry=geometry)


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


@pytest.mark.parametrize(
    "case",
    [
        "scan_nan_lat",
        "scan_bad_lon",
        "scan_bad_name",
        "drop_count",
        "drop_asymmetry",
        "recce_altitude",
        "home_name",
        "marker_field_y",
    ],
)
def test_nested_geometry_damage_blocks_validator_service_and_builder(case):
    damaged = _damage_geometry(_make_candidate(), case)
    service = FieldReferenceService()
    builder = RuntimeContextBuilder()
    service_before = service.snapshot()
    builder_before = builder.snapshot_field_reference_state()

    errors = validate_runtime_field_binding_candidate(damaged)
    service_result = service.apply_runtime_binding(damaged, profile_name="Test")
    builder_result = builder.confirm_runtime_gps_reference(damaged)

    assert errors
    assert service_result["ok"] is False
    assert builder_result is False
    assert service.snapshot() == service_before
    assert builder.snapshot_field_reference_state() == builder_before


def test_coupled_heading_baseline_tamper_fails_independent_recomputation():
    candidate = _make_candidate()
    heading = candidate.field_heading_yaw_rad + 0.1
    baseline = candidate.baseline_m + 10.0
    geometry = dc_replace(
        candidate.geometry,
        field_heading_yaw_rad=heading,
        field_heading_deg=math.degrees(heading),
        baseline_m=baseline,
        forward_marker=dc_replace(
            candidate.geometry.forward_marker, field_y_m=baseline
        ),
    )
    damaged = dc_replace(
        candidate,
        field_heading_yaw_rad=heading,
        field_heading_deg=math.degrees(heading),
        baseline_m=baseline,
        geometry=geometry,
    )
    errors = validate_runtime_field_binding_candidate(damaged)
    assert errors
    assert any("recomputation" in error or "mismatch" in error for error in errors)


@pytest.mark.parametrize(
    "timestamp", [999.0, 1002.0, float("nan"), float("inf"), True, "1005"]
)
def test_service_and_builder_reject_identical_invalid_timestamp_semantics(timestamp):
    candidate = _make_candidate()
    service = FieldReferenceService()
    builder = RuntimeContextBuilder()
    service_before = service.snapshot()
    builder_before = builder.snapshot_field_reference_state()

    service_result = service.apply_runtime_binding(
        candidate, profile_name="Test", timestamp=timestamp
    )
    builder_result = builder.confirm_runtime_gps_reference(
        candidate, timestamp=timestamp
    )

    assert service_result["ok"] is False
    assert builder_result is False
    assert service.snapshot() == service_before
    assert builder.snapshot_field_reference_state() == builder_before


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



# =========================================================================
# H2. Service malformed geometry tests (5B.1.3)
# =========================================================================


class TestServiceMalformedGeometry:
    def _make_c(self):
        return _make_candidate()

    def _apply(self, c):
        svc = FieldReferenceService()
        before = svc.snapshot()
        r = svc.apply_runtime_binding(c, profile_name="Test")
        after = svc.snapshot()
        return r, before, after

    def test_geometry_origin_bad(self):
        c = self._make_c()
        c = dc_replace(c, geometry=dc_replace(c.geometry, origin_lat="bad"))
        r, before, after = self._apply(c)
        assert r["ok"] is False
        assert before == after

    def test_geometry_home_none(self):
        c = self._make_c()
        c = dc_replace(c, geometry=dc_replace(c.geometry, home=None))
        r, before, after = self._apply(c)
        assert r["ok"] is False
        assert before == after

    def test_geometry_marker_none(self):
        c = self._make_c()
        c = dc_replace(c, geometry=dc_replace(c.geometry, forward_marker=None))
        r, before, after = self._apply(c)
        assert r["ok"] is False
        assert before == after

    def test_malformed_warnings(self):
        c = self._make_c()
        c = dc_replace(c, warnings=("ok", 123))
        r, before, after = self._apply(c)
        assert r["ok"] is False
        assert before == after


# =========================================================================
# H3. Legacy transition tests (5B.1.3)
# =========================================================================


class TestLegacyTransition:
    def test_runtime_to_legacy_without_gps(self):
        b = RuntimeContextBuilder()
        c = _make_candidate()
        b.confirm_runtime_gps_reference(c)
        assert b.field_origin_gps_confirmed is True
        b.confirm_field_reference(
            0.5, 10.0, 20.0,
            origin_lat=None, origin_lon=None,
        )
        assert b.field_origin_confirmed is True
        assert b.field_origin_gps_confirmed is False
        assert b.field_transform_ready() is True
        assert b.field_gps_transform_ready() is False
        assert b.field_reference_mode == ""
        assert b.field_forward_marker_lat is None
        assert b.field_baseline_m is None
        assert b.field_gps_sample_count is None
        assert b.field_runtime_profile_id == ""

    def test_runtime_to_legacy_with_gps(self):
        b = RuntimeContextBuilder()
        c = _make_candidate()
        b.confirm_runtime_gps_reference(c)
        b.confirm_field_reference(
            0.5, 10.0, 20.0,
            origin_lat=34.103649, origin_lon=108.642674,
        )
        assert b.field_origin_confirmed is True
        assert b.field_origin_gps_confirmed is True
        assert b.field_transform_ready() is True
        assert b.field_gps_transform_ready() is True
        assert b.field_reference_mode == ""


# =========================================================================
# H4. Action context diagnostics (5B.1.3)
# =========================================================================


class TestContextDiagnostics:
    @pytest.mark.parametrize("snap", [{}, {"drone": {}}, {"drone": {"armed": False}}])
    def test_all_diagnostics_present(self, snap):
        b = RuntimeContextBuilder()
        c = _make_candidate()
        b.confirm_runtime_gps_reference(c)
        ctx = b.build_action_context(snap)
        mapping = {
            "field_gps_sample_count": c.sample_count,
            "field_gps_rejected_sample_count": c.rejected_sample_count,
            "field_gps_duplicate_sample_count": c.duplicate_sample_count,
            "field_gps_sample_duration_s": c.sample_duration_s,
            "field_gps_horizontal_spread_m": c.horizontal_spread_m,
            "field_gps_fix_type": c.gps_fix_type,
            "field_gps_satellites": c.gps_satellites,
            "field_gps_eph": c.gps_eph,
            "field_gps_epv": c.gps_epv,
        }
        for field, expected in mapping.items():
            assert field in ctx, f"missing {field}"
            assert ctx[field] == expected, f"{field}: {ctx[field]} != {expected}"


# =========================================================================
# H5. Restore malformed tests (5B.1.3)
# =========================================================================


class TestRestoreMalformed:
    def _make_snap(self):
        b = RuntimeContextBuilder()
        b.confirm_runtime_gps_reference(_make_candidate())
        return b.snapshot_field_reference_state()

    def _check_restore_fails_no_mutation(self, b, snap):
        before = b.snapshot_field_reference_state()
        assert b.restore_field_reference_state(snap) is False
        assert b.snapshot_field_reference_state() == before

    @pytest.mark.parametrize("key", [
        "field_gps_rejected_sample_count", "field_gps_duplicate_sample_count",
        "field_gps_sample_duration_s", "field_gps_horizontal_spread_m",
        "field_gps_fix_type", "field_gps_satellites", "field_gps_eph", "field_gps_epv",
    ])
    def test_missing_runtime_field(self, key):
        snap = self._make_snap()
        snap[key] = None
        self._check_restore_fails_no_mutation(RuntimeContextBuilder(), snap)

    @pytest.mark.parametrize("key, bad", [
        ("field_gps_rejected_sample_count", True), ("field_gps_duplicate_sample_count", 1.5),
        ("field_gps_sample_duration_s", float("nan")), ("field_gps_eph", -1.0),
    ])
    def test_bad_runtime_type(self, key, bad):
        snap = self._make_snap()
        snap[key] = bad
        self._check_restore_fails_no_mutation(RuntimeContextBuilder(), snap)

    @pytest.mark.parametrize("mods", [
        {"field_heading_confirmed": True, "field_heading_yaw_rad": None},
        {"field_heading_confirmed": True, "field_heading_source": ""},
        {"field_origin_confirmed": True, "field_origin_local_x": None},
        {"field_origin_gps_confirmed": True, "field_origin_lat": 90.0},
        {"field_reference_mode": "runtime_origin_forward_marker", "field_forward_marker_lon": None},
    ])
    def test_flag_consistency(self, mods):
        snap = self._make_snap()
        snap.update(mods)
        self._check_restore_fails_no_mutation(RuntimeContextBuilder(), snap)


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
