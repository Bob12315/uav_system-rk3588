"""Tests for runtime field binding sampler (step 5A)."""

import copy
import math
import statistics
from dataclasses import FrozenInstanceError
from dataclasses import replace as dc_replace
from pathlib import Path

import pytest

from app.field_profile import FieldProfile, parse_field_profile
from app.field_reference import shortest_longitude_delta_deg
from app.runtime_field_binding import (
    RuntimeFieldBindingCandidate,
    RuntimeFieldBindingError,
    validate_runtime_field_binding_candidate,
    RuntimeFieldBindingSampler,
    RuntimeFieldSamplingStatus,
    RuntimeGpsSample,
)
from app.runtime_field_geometry import RuntimeFieldGeometry


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_valid_v3_dict() -> dict:
    return {
        "schema_version": 3,
        "profile_id": "test_sampling",
        "name": "Test Sampling",
        "coordinate_convention": {
            "field_x_positive": "right",
            "field_y_positive": "forward",
            "altitude_positive": "up",
        },
        "forward_marker": {
            "name": "far_centerline_marker",
            "lat": 34.104189,
            "lon": 108.642674,
            "coordinate_system": "WGS84",
        },
        "field_geometry": {
            "lane_half_width_m": 4.0,
            "drop_area_y_min_m": 30.0,
            "drop_area_y_max_m": 35.0,
            "drop_center_y_m": 32.5,
            "recce_area_y_min_m": 55.0,
            "recce_area_y_max_m": 60.0,
            "recce_center_y_m": 57.5,
        },
        "drop_scan": {
            "waypoints": [
                {"x_m": -2.0, "y_m": 31.25, "altitude_m": 5.0},
                {"x_m": 2.0, "y_m": 31.25, "altitude_m": 5.0},
                {"x_m": 2.0, "y_m": 33.75, "altitude_m": 5.0},
                {"x_m": -2.0, "y_m": 33.75, "altitude_m": 5.0},
            ]
        },
        "gps_quality": {
            "min_fix_type": 3,
            "min_satellites": 10,
            "max_eph": 2.5,
            "max_epv": 5.0,
        },
        "runtime_origin_sampling": {
            "min_samples": 20,
            "sample_window_s": 5.0,
            "max_horizontal_spread_m": 1.0,
            "estimator": "median",
        },
        "binding_policy": {
            "min_baseline_m": 30.0,
            "warn_baseline_below_m": 50.0,
        },
    }


def _profile() -> FieldProfile:
    return parse_field_profile(_make_valid_v3_dict())


def _valid_snapshot(source_time: float, lat=34.103649, lon=108.642674) -> dict:
    return {
        "global_position_valid": True,
        "last_global_position_time": source_time,
        "lat": lat,
        "lon": lon,
        "gps_fix_type": 3,
        "satellites_visible": 12,
        "gps_eph": 1.0,
        "gps_epv": 1.5,
    }


def _finalize_valid(extra_spread=0.0):
    profile = _profile()
    if extra_spread > 0:
        profile.runtime_origin_sampling.max_horizontal_spread_m = max(1.0, extra_spread * 1.5)
    s = RuntimeFieldBindingSampler(profile)
    s.start(started_at_s=1000.0)
    for i in range(20):
        s.observe_snapshot(
            _valid_snapshot(2000.0 + i * 0.1),
            observed_at_s=1000.0 + i * 0.26,
        )
    return s.finalize(completed_at_s=1005.0)


# =========================================================================
# A. Construction
# =========================================================================


class TestConstruction:
    def test_valid_v3_profile(self):
        s = RuntimeFieldBindingSampler(_profile())
        assert s.status().state == "idle"

    def test_rejects_schema_v2(self):
        data = {
            "schema_version": 2, "profile_id": "v2", "name": "V2",
            "coordinate_convention": {"field_x_positive": "right", "field_y_positive": "forward", "altitude_positive": "up"},
            "anchor": {"name": "a", "lat": 34.0, "lon": 108.0, "field_x_m": 0.0, "field_y_m": 0.0},
            "centerline_points": [
                {"name": "c1", "lat": 34.001, "lon": 108.001},
                {"name": "c2", "lat": 34.002, "lon": 108.002},
                {"name": "c3", "lat": 34.003, "lon": 108.003},
                {"name": "c4", "lat": 34.004, "lon": 108.004},
            ],
        }
        with pytest.raises(RuntimeFieldBindingError, match="schema"):
            RuntimeFieldBindingSampler(parse_field_profile(data))

    def test_rejects_non_fieldprofile(self):
        with pytest.raises(RuntimeFieldBindingError, match="FieldProfile"):
            RuntimeFieldBindingSampler("not a profile")

    def test_does_not_modify_profile(self):
        data = _make_valid_v3_dict()
        p = parse_field_profile(data)
        before = copy.deepcopy(p)
        RuntimeFieldBindingSampler(p)
        assert p == before


# =========================================================================
# B. State machine
# =========================================================================


class TestStateMachine:
    def test_initial_idle(self):
        s = RuntimeFieldBindingSampler(_profile())
        st = s.status()
        assert st.state == "idle"
        assert st.elapsed_s == 0
        assert st.window_complete is False

    def test_start_transitions_to_sampling(self):
        s = RuntimeFieldBindingSampler(_profile())
        st = s.start(started_at_s=1000.0)
        assert st.state == "sampling"

    def test_start_clears_old(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        s.observe_snapshot(_valid_snapshot(2001.0), observed_at_s=1000.1)
        s.reset()
        s.start(started_at_s=2000.0)
        st = s.status(now_s=2000.0)
        assert st.accepted_samples == 0

    def test_start_during_sampling_raises(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        with pytest.raises(RuntimeFieldBindingError, match="sampling"):
            s.start(started_at_s=2000.0)

    def test_reset_from_any(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        s.reset()
        assert s.status().state == "idle"

    def test_start_after_ready(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        for i in range(20):
            s.observe_snapshot(_valid_snapshot(2000.0 + i * 0.1), observed_at_s=1000.0 + i * 0.26)
        s.finalize(completed_at_s=1005.0)
        st = s.start(started_at_s=2000.0)
        assert st.state == "sampling"

    def test_start_after_failed(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        try:
            s.finalize(completed_at_s=1005.0)
        except RuntimeFieldBindingError:
            pass
        st = s.start(started_at_s=2000.0)
        assert st.state == "sampling"


# =========================================================================
# C. Status timing
# =========================================================================


class TestStatusTiming:
    def test_sampling_needs_now(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        with pytest.raises(RuntimeFieldBindingError, match="now_s"):
            s.status()

    def test_now_before_start(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        with pytest.raises(RuntimeFieldBindingError):
            s.status(now_s=999.0)

    def test_elapsed(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        st = s.status(now_s=1003.0)
        assert st.elapsed_s == pytest.approx(3.0)

    def test_elapsed_time_does_not_complete_sampling(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        assert s.status(now_s=1005.0).can_finalize is False

    def test_minimum_samples_complete_before_legacy_window(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        for i in range(20):
            s.observe_snapshot(
                _valid_snapshot(2000.0 + i * 0.1),
                observed_at_s=1000.0 + i * 0.1,
            )
        assert s.status(now_s=1001.9).can_finalize is True
        candidate = s.finalize(completed_at_s=1001.9)
        assert candidate.sample_count == 20


# =========================================================================
# D. Valid acceptance
# =========================================================================


class TestAcceptance:
    def test_accept_valid(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        st = s.observe_snapshot(_valid_snapshot(2001.0), observed_at_s=1000.1)
        assert st.accepted_samples == 1

    def test_source_time_used(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        s.observe_snapshot(_valid_snapshot(2001.5), observed_at_s=1000.1)
        assert s.status(now_s=1000.2).last_source_time_s == 2001.5

    def test_snapshot_not_modified(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        snap = _valid_snapshot(2001.0)
        before = copy.deepcopy(snap)
        s.observe_snapshot(snap, observed_at_s=1000.1)
        assert snap == before


# =========================================================================
# E. Duplicate
# =========================================================================


class TestDuplicate:
    def test_same_source_duplicate(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        s.observe_snapshot(_valid_snapshot(2001.0), observed_at_s=1000.1)
        st = s.observe_snapshot(_valid_snapshot(2001.0), observed_at_s=1000.2)
        assert st.duplicate_samples == 1
        assert st.accepted_samples == 1

    def test_older_new_rejected(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        s.observe_snapshot(_valid_snapshot(2005.0), observed_at_s=1000.1)
        st = s.observe_snapshot(_valid_snapshot(2003.0), observed_at_s=1000.2)
        assert st.rejected_samples == 1
        assert "monotonic" in (st.last_rejection_reason or "").lower()


# =========================================================================
# F. Quality boundaries
# =========================================================================


class TestQualityBoundaries:
    def test_fix_at_min_ok(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        snap = _valid_snapshot(2001.0); snap["gps_fix_type"] = 3
        assert s.observe_snapshot(snap, observed_at_s=1000.1).accepted_samples == 1

    def test_sats_at_min_ok(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        snap = _valid_snapshot(2001.0); snap["satellites_visible"] = 10
        assert s.observe_snapshot(snap, observed_at_s=1000.1).accepted_samples == 1

    def test_eph_at_max_ok(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        snap = _valid_snapshot(2001.0); snap["gps_eph"] = 2.5
        assert s.observe_snapshot(snap, observed_at_s=1000.1).accepted_samples == 1

    def test_epv_at_max_ok(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        snap = _valid_snapshot(2001.0); snap["gps_epv"] = 5.0
        assert s.observe_snapshot(snap, observed_at_s=1000.1).accepted_samples == 1


# =========================================================================
# G. Rejection parameterized
# =========================================================================


@pytest.mark.parametrize("field, bad_value", [
    ("global_position_valid", False), ("global_position_valid", 1),
    ("last_global_position_time", None), ("last_global_position_time", 0), ("last_global_position_time", float("nan")),
    ("lat", None), ("lat", True), ("lat", 91), ("lat", 90.0),
    ("lon", None), ("lon", 181),
    ("gps_fix_type", True), ("gps_fix_type", 2.5), ("gps_fix_type", 2),
    ("satellites_visible", True), ("satellites_visible", 9.5), ("satellites_visible", 9),
    ("gps_eph", None), ("gps_eph", -1), ("gps_eph", float("nan")), ("gps_eph", 3.0),
    ("gps_epv", None), ("gps_epv", -1), ("gps_epv", float("inf")), ("gps_epv", 6.0),
])
class TestRejection:
    def test_rejected_no_exception(self, field, bad_value):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        snap = _valid_snapshot(2001.0)
        snap[field] = bad_value
        st = s.observe_snapshot(snap, observed_at_s=1000.1)
        assert st.rejected_samples == 1
        assert st.accepted_samples == 0


# =========================================================================
# H. Window
# =========================================================================


class TestWindow:
    def test_at_boundary_accepts(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        for i in range(19):
            s.observe_snapshot(_valid_snapshot(2000.0 + i * 0.1), observed_at_s=1000.0 + i * 0.25)
        st = s.observe_snapshot(_valid_snapshot(2050.0), observed_at_s=1005.0)
        assert st.accepted_samples == 20

    def test_after_window_not_counted(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        for i in range(20):
            s.observe_snapshot(_valid_snapshot(2000.0 + i * 0.1), observed_at_s=1000.0 + i * 0.24)
        after = s.observe_snapshot(_valid_snapshot(2100.0), observed_at_s=1006.0)
        assert after.accepted_samples == 20  # the after-window doesn't change count


# =========================================================================
# I. Sample count
# =========================================================================


class TestSampleCount:
    def test_insufficient_fails(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        for i in range(19):
            s.observe_snapshot(_valid_snapshot(2000.0 + i * 0.1), observed_at_s=1000.0 + i * 0.27)
        with pytest.raises(RuntimeFieldBindingError, match="samples"):
            s.finalize(completed_at_s=1005.0)

    def test_exact_20_ok(self):
        c = _finalize_valid()
        assert c.sample_count == 20

    def test_extra_retained(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        for i in range(25):
            s.observe_snapshot(_valid_snapshot(2000.0 + i * 0.1), observed_at_s=1000.0 + i * 0.20)
        assert s.finalize(completed_at_s=1005.0).sample_count == 25


# =========================================================================
# J. Median
# =========================================================================


class TestMedian:
    def test_median_origin(self):
        profile = _profile()
        profile.runtime_origin_sampling.max_horizontal_spread_m = 10.0
        s = RuntimeFieldBindingSampler(profile)
        s.start(started_at_s=1000.0)
        step = 5.0 / 19.0
        lats = [34.103649 + (i - 10) * 0.000001 for i in range(20)]
        lons = [108.642674 + (i - 10) * 0.000001 for i in range(20)]
        for i in range(20):
            s.observe_snapshot(
                _valid_snapshot(2000.0 + i * 0.1, lat=lats[i], lon=lons[i]),
                observed_at_s=1000.0 + i * step,
            )
        c = s.finalize(completed_at_s=1005.0)
        assert c.origin_lat == pytest.approx(statistics.median(lats), abs=1e-12)
        assert c.origin_lon == pytest.approx(statistics.median(lons), abs=1e-12)

    def test_median_even_count(self):
        profile = _profile()
        profile.runtime_origin_sampling.max_horizontal_spread_m = 10.0
        s = RuntimeFieldBindingSampler(profile)
        s.start(started_at_s=1000.0)
        step = 5.0 / 19.0
        base = 34.103649
        for i in range(10):
            s.observe_snapshot(_valid_snapshot(2000.0 + i * 0.1, lat=base), observed_at_s=1000.0 + i * step)
        for i in range(10):
            s.observe_snapshot(_valid_snapshot(2010.0 + i * 0.1, lat=base + 0.000002), observed_at_s=1000.0 + (i + 10) * step)
        c = s.finalize(completed_at_s=1005.0)
        assert c.origin_lat == pytest.approx(base + 0.000001, abs=1e-11)


def _finalize_longitude_samples(longitudes, *, max_spread_m=1.0):
    profile = _profile()
    profile.forward_marker.lon = -179.9994
    profile.runtime_origin_sampling.max_horizontal_spread_m = max_spread_m
    sampler = RuntimeFieldBindingSampler(profile)
    sampler.start(started_at_s=1000.0)
    step = 5.0 / (len(longitudes) - 1)
    for index, longitude in enumerate(longitudes):
        sampler.observe_snapshot(
            _valid_snapshot(
                2000.0 + index * 0.1,
                lat=34.103649,
                lon=longitude,
            ),
            observed_at_s=1000.0 + index * step,
        )
    return sampler.finalize(completed_at_s=1005.0)


class TestCircularLongitudeMedian:
    def test_even_symmetric_dateline_samples(self):
        candidate = _finalize_longitude_samples(
            [179.999998] * 10 + [-179.999998] * 10
        )
        assert abs(
            shortest_longitude_delta_deg(candidate.origin_lon, 180.0)
        ) < 1e-9
        assert candidate.origin_lon != 0.0
        assert 0.0 < candidate.horizontal_spread_m < 1.0

    def test_reversed_dateline_sample_order_is_circular_equivalent(self):
        positive_first = _finalize_longitude_samples(
            [179.999998] * 10 + [-179.999998] * 10
        )
        negative_first = _finalize_longitude_samples(
            [-179.999998] * 10 + [179.999998] * 10
        )
        assert abs(
            shortest_longitude_delta_deg(
                positive_first.origin_lon, negative_first.origin_lon
            )
        ) < 1e-10

    def test_odd_dateline_samples_remain_near_dateline(self):
        candidate = _finalize_longitude_samples(
            [179.999998] * 11 + [-179.999998] * 10
        )
        assert abs(
            shortest_longitude_delta_deg(candidate.origin_lon, 180.0)
        ) < 3e-6

    def test_ordinary_longitudes_match_linear_median(self):
        longitudes = [108.642670 + index * 0.0000001 for index in range(20)]
        candidate = _finalize_longitude_samples(longitudes)
        assert candidate.origin_lon == pytest.approx(
            statistics.median(longitudes), abs=1e-12
        )

    def test_real_local_spread_still_fails(self):
        longitudes = [108.64267] * 10 + [108.64271] * 10
        with pytest.raises(RuntimeFieldBindingError, match="spread"):
            _finalize_longitude_samples(longitudes)

    def test_dateline_candidate_geometry_and_validator(self):
        candidate = _finalize_longitude_samples(
            [179.999998] * 10 + [-179.999998] * 10
        )
        assert -180.0 <= candidate.geometry.origin_lon < 180.0
        assert candidate.geometry.home.lon == candidate.origin_lon
        assert validate_runtime_field_binding_candidate(candidate) == ()


# =========================================================================
# K. Spread
# =========================================================================


class TestSpread:
    def test_all_identical_zero(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        for i in range(20):
            s.observe_snapshot(_valid_snapshot(2000.0 + i * 0.1), observed_at_s=1000.0 + i * 0.26)
        assert s.finalize(completed_at_s=1005.0).horizontal_spread_m == 0.0

    def test_max_radius_definition(self):
        profile = _profile()
        profile.runtime_origin_sampling.max_horizontal_spread_m = 10.0
        s = RuntimeFieldBindingSampler(profile)
        s.start(started_at_s=1000.0)
        step = 5.0 / 19.0
        for i in range(19):
            s.observe_snapshot(_valid_snapshot(2000.0 + i * 0.1), observed_at_s=1000.0 + i * step)
        s.observe_snapshot(_valid_snapshot(2100.0, lat=34.103650, lon=108.642675), observed_at_s=1004.9)
        from app.field_reference import gps_enu_deltas
        dn, de = gps_enu_deltas(34.103649, 108.642674, 34.103650, 108.642675)
        expected = math.hypot(dn, de)
        c = s.finalize(completed_at_s=1005.0)
        assert c.horizontal_spread_m == pytest.approx(expected, abs=0.01)

    def test_at_threshold_ok(self):
        profile = _profile()
        s = RuntimeFieldBindingSampler(profile)
        s.start(started_at_s=1000.0)
        step = 5.0 / 19.0
        for i in range(19):
            s.observe_snapshot(_valid_snapshot(2000.0 + i * 0.1), observed_at_s=1000.0 + i * step)
        s.observe_snapshot(_valid_snapshot(2100.0, lat=34.103650, lon=108.642675), observed_at_s=1004.9)
        from app.field_reference import gps_enu_deltas
        dn, de = gps_enu_deltas(34.103649, 108.642674, 34.103650, 108.642675)
        profile.runtime_origin_sampling.max_horizontal_spread_m = math.hypot(dn, de)
        c = s.finalize(completed_at_s=1005.0)
        assert c.horizontal_spread_m > 0


# =========================================================================
# L. Candidate
# =========================================================================


class TestCandidate:
    def test_source_labels(self):
        c = _finalize_valid()
        assert c.origin_source == "runtime_current_gps"
        assert c.heading_source == "runtime_forward_marker"
        assert c.field_reference_mode == "runtime_origin_forward_marker"

    def test_diagnostics(self):
        c = _finalize_valid()
        assert c.sample_count == 20
        assert c.sample_duration_s == 5.0

    def test_quality_conservative(self):
        c = _finalize_valid()
        assert c.gps_fix_type == 3
        assert c.gps_satellites == 12
        assert c.gps_eph == 1.0
        assert c.gps_epv == 1.5

    def test_geometry_included(self):
        c = _finalize_valid()
        assert isinstance(c.geometry, RuntimeFieldGeometry)


# =========================================================================
# M. Candidate lifecycle
# =========================================================================


class TestCandidateLifecycle:
    def test_frozen(self):
        c = _finalize_valid()
        with pytest.raises(FrozenInstanceError):
            c.origin_lat = 0.0

    def test_idempotent(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        for i in range(20):
            s.observe_snapshot(_valid_snapshot(2000.0 + i * 0.1), observed_at_s=1000.0 + i * 0.26)
        c1 = s.finalize(completed_at_s=1005.0)
        c2 = s.finalize(completed_at_s=1006.0)
        assert c1 is c2

    def test_observe_after_ready(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        for i in range(20):
            s.observe_snapshot(_valid_snapshot(2000.0 + i * 0.1), observed_at_s=1000.0 + i * 0.26)
        s.finalize(completed_at_s=1005.0)
        with pytest.raises(RuntimeFieldBindingError):
            s.observe_snapshot(_valid_snapshot(2100.0), observed_at_s=1006.0)


# =========================================================================
# N. Failed
# =========================================================================


class TestFailed:
    def test_insufficient_state_failed(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        try:
            s.finalize(completed_at_s=1005.0)
        except RuntimeFieldBindingError:
            pass
        assert s.status().state == "failed"

    def test_failed_finalize_again(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        try:
            s.finalize(completed_at_s=1005.0)
        except RuntimeFieldBindingError:
            pass
        with pytest.raises(RuntimeFieldBindingError):
            s.finalize(completed_at_s=1006.0)

    def test_failed_can_start(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        try:
            s.finalize(completed_at_s=1005.0)
        except RuntimeFieldBindingError:
            pass
        s.start(started_at_s=2000.0)


# =========================================================================
# =========================================================================
# O. Max seen source time (5A.1 fix)
# =========================================================================


class TestMaxSeenSourceTime:
    def test_newer_rejected_advances_max_seen(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        # Accept source_time=8
        s.observe_snapshot(_valid_snapshot(8.0), observed_at_s=1000.1)
        # Reject source_time=10 (bad eph) — must advance max_seen
        snap10 = _valid_snapshot(10.0)
        snap10["gps_eph"] = 99.0
        st = s.observe_snapshot(snap10, observed_at_s=1000.2)
        assert st.last_source_time_s == 10.0
        # source_time=9 with valid content — must be rejected as non-monotonic
        st2 = s.observe_snapshot(_valid_snapshot(9.0), observed_at_s=1000.3)
        assert st2.rejected_samples == 2
        assert "monotonic" in (st2.last_rejection_reason or "").lower()
        assert st2.accepted_samples == 1

    def test_repeated_bad_becomes_duplicate(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        snap = _valid_snapshot(10.0)
        snap["gps_eph"] = 99.0
        st1 = s.observe_snapshot(snap, observed_at_s=1000.1)
        assert st1.rejected_samples == 1
        assert st1.duplicate_samples == 0
        st2 = s.observe_snapshot(snap, observed_at_s=1000.2)
        assert st2.rejected_samples == 1
        assert st2.duplicate_samples == 1

    def test_duplicate_does_not_change_rejection_reason(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        s.observe_snapshot(_valid_snapshot(8.0), observed_at_s=1000.1)
        snap = _valid_snapshot(10.0)
        snap["global_position_valid"] = False
        s.observe_snapshot(snap, observed_at_s=1000.2)
        reason = s.status(now_s=1000.3).last_rejection_reason
        s.observe_snapshot(snap, observed_at_s=1000.3)  # duplicate
        assert s.status(now_s=1000.4).last_rejection_reason == reason

    def test_one_bad_gps_does_not_poison_a_later_valid_candidate(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        bad = _valid_snapshot(1999.0)
        bad["global_position_valid"] = False
        rejected = s.observe_snapshot(bad, observed_at_s=1000.0)
        assert rejected.state == "sampling"
        assert rejected.rejected_samples == 1
        for i in range(20):
            s.observe_snapshot(
                _valid_snapshot(2000.0 + i * 0.1),
                observed_at_s=1000.1 + i * 0.24,
            )
        candidate = s.finalize(completed_at_s=1005.0)
        assert candidate.sample_count == 20
        assert candidate.rejected_sample_count == 1


# =========================================================================
# P. Non-Mapping snapshot
# =========================================================================


@pytest.mark.parametrize("bad_snapshot", [None, [], "bad", 123, True])
class TestNonMapping:
    def test_rejected_without_exception(self, bad_snapshot):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        st = s.observe_snapshot(bad_snapshot, observed_at_s=1000.1)
        assert st.rejected_samples == 1
        assert st.accepted_samples == 0
        assert st.duplicate_samples == 0
        assert st.last_source_time_s is None
        assert "mapping" in (st.last_rejection_reason or "").lower()


# =========================================================================
# Q. Ready/failed status
# =========================================================================


class TestReadyFailedStatus:
    def _make_ready(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        for i in range(20):
            s.observe_snapshot(_valid_snapshot(2000.0 + i * 0.1), observed_at_s=1000.0 + i * 0.26)
        s.finalize(completed_at_s=1005.0)
        return s

    def _make_failed_insufficient(self):
        s = RuntimeFieldBindingSampler(_profile())
        s.start(started_at_s=1000.0)
        for i in range(19):
            s.observe_snapshot(_valid_snapshot(2000.0 + i * 0.1), observed_at_s=1000.0 + i * 0.27)
        try:
            s.finalize(completed_at_s=1005.0)
        except RuntimeFieldBindingError:
            pass
        return s

    def test_ready_window_complete(self):
        s = self._make_ready()
        st = s.status()
        assert st.state == "ready"
        assert st.window_complete is True
        assert st.can_finalize is False
        assert st.elapsed_s == 5.0

    def test_ready_elapsed_not_backwards(self):
        s = self._make_ready()
        assert s.status(now_s=1002.0).elapsed_s == 5.0
        assert s.status(now_s=1008.0).elapsed_s == 8.0

    @pytest.mark.parametrize("bad_now", [True, "bad", [], float("nan"), float("inf")])
    def test_ready_rejects_bad_now(self, bad_now):
        s = self._make_ready()
        with pytest.raises(RuntimeFieldBindingError):
            s.status(now_s=bad_now)

    def test_ready_rejects_now_before_start(self):
        s = self._make_ready()
        with pytest.raises(RuntimeFieldBindingError):
            s.status(now_s=999.0)

    def test_failed_insufficient_samples_cannot_finalize(self):
        s = self._make_failed_insufficient()
        st = s.status()
        assert st.state == "failed"
        assert st.window_complete is False
        assert st.can_finalize is False

    def test_failed_rejects_bad_now(self):
        s = self._make_failed_insufficient()
        with pytest.raises(RuntimeFieldBindingError):
            s.status(now_s=float("nan"))


# =========================================================================
# R. Spread failure + geometry failure
# =========================================================================


class TestSpreadAndGeometryFailure:
    def test_spread_above_threshold_fails(self):
        profile = _profile()
        profile.runtime_origin_sampling.max_horizontal_spread_m = 0.5
        s = RuntimeFieldBindingSampler(profile)
        s.start(started_at_s=1000.0)
        step = 5.0 / 19.0
        for i in range(19):
            s.observe_snapshot(_valid_snapshot(2000.0 + i * 0.1), observed_at_s=1000.0 + i * step)
        s.observe_snapshot(_valid_snapshot(2100.0, lat=34.103655, lon=108.642680), observed_at_s=1004.9)
        with pytest.raises(RuntimeFieldBindingError, match="spread"):
            s.finalize(completed_at_s=1005.0)
        assert s.status().state == "failed"
        assert s.status().window_complete is True

    def test_geometry_failure_sets_failed(self):
        profile = _profile()
        # Move B too close so baseline < 30m
        profile.binding_policy.min_baseline_m = 30.0
        import math as _m
        from app.field_reference import EARTH_RADIUS_M as _ER
        profile.forward_marker.lat = 34.103649 + _m.degrees(20.0 / _ER)
        s = RuntimeFieldBindingSampler(profile)
        s.start(started_at_s=1000.0)
        for i in range(20):
            s.observe_snapshot(_valid_snapshot(2000.0 + i * 0.1), observed_at_s=1000.0 + i * 0.26)
        with pytest.raises(RuntimeFieldBindingError, match="baseline"):
            s.finalize(completed_at_s=1005.0)
        assert s.status().state == "failed"
        assert s.status().window_complete is True


# =========================================================================
# S. Profile immutability
# =========================================================================


class TestProfileImmutability:
    def test_sampling_and_finalize_do_not_modify_profile(self):
        profile = _profile()
        before = copy.deepcopy(profile)
        s = RuntimeFieldBindingSampler(profile)
        s.start(started_at_s=1000.0)
        for i in range(20):
            s.observe_snapshot(_valid_snapshot(2000.0 + i * 0.1), observed_at_s=1000.0 + i * 0.26)
        s.finalize(completed_at_s=1005.0)
        assert profile == before


# =========================================================================
# O-z. Static checks (moved to end)
# =========================================================================



# =========================================================================
# P. Shared validator tests (5B.1.3)
# =========================================================================


def _make_candidate_for_validator():
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


class TestSharedValidator:
    def test_accepts_valid_candidate(self):
        assert validate_runtime_field_binding_candidate(_make_candidate_for_validator()) == ()

    @pytest.mark.parametrize("field, bad_value", [
        ("origin_lat", "bad"), ("field_heading_yaw_rad", None), ("home", None),
        ("forward_marker", "bad"), ("warnings", ("ok", 123)),
        ("drop_scan_waypoints", []), ("drop_area_corners", (None,)),
        ("recce_area_corners", ("bad",)),
    ])
    def test_rejects_malformed_geometry(self, field, bad_value):
        c = _make_candidate_for_validator()
        bad_geom = dc_replace(c.geometry, **{field: bad_value})
        c = dc_replace(c, geometry=bad_geom)
        errs = validate_runtime_field_binding_candidate(c)
        assert len(errs) > 0
        assert not any(isinstance(e, (TypeError, AttributeError, ValueError, KeyError)) for e in [None])

    def test_rejects_malformed_warnings(self):
        c = _make_candidate_for_validator()
        c = dc_replace(c, warnings=("ok", 123))
        errs = validate_runtime_field_binding_candidate(c)
        assert len(errs) > 0

    def test_rejects_unnormalized_heading(self):
        c = _make_candidate_for_validator()
        c = dc_replace(c, field_heading_yaw_rad=2 * math.pi, field_heading_deg=360.0)
        bad_geom = dc_replace(c.geometry, field_heading_yaw_rad=2 * math.pi, field_heading_deg=360.0)
        c = dc_replace(c, geometry=bad_geom)
        errs = validate_runtime_field_binding_candidate(c)
        assert len(errs) > 0
        assert any("normaliz" in e.lower() for e in errs)

    def test_rejects_bad_home_field(self):
        c = _make_candidate_for_validator()
        bad_home = dc_replace(c.geometry.home, field_x_m="bad")
        bad_geom = dc_replace(c.geometry, home=bad_home)
        c = dc_replace(c, geometry=bad_geom)
        errs = validate_runtime_field_binding_candidate(c)
        assert len(errs) > 0

    def test_rejects_bad_marker_field(self):
        c = _make_candidate_for_validator()
        bad_fwd = dc_replace(c.geometry.forward_marker, field_y_m=None)
        bad_geom = dc_replace(c.geometry, forward_marker=bad_fwd)
        c = dc_replace(c, geometry=bad_geom)
        errs = validate_runtime_field_binding_candidate(c)
        assert len(errs) > 0


# =========================================================================
# O-z. Static checks
# =========================================================================


def test_no_local():
    src = Path("app/runtime_field_binding.py").read_text()
    for token in (
        "local_x",
        "local_y",
        "local_z",
        "origin_local_n_m",
        "origin_local_e_m",
        "field_to_local_ned",
        "gps_to_local_ned",
        "local_ned_to_field",
    ):
        assert token not in src, f"forbidden: {token}"


def test_no_clock():
    src = Path("app/runtime_field_binding.py").read_text()
    for token in ["import time", "from time ", "time.time", "time.monotonic", "sleep(",
                  "threading", "asyncio", "RuntimeContextBuilder", "FieldReferenceService",
                  "FieldReferenceController", "SystemRunner", "LinkManager", "MAVLink"]:
        assert token not in src, f"forbidden: {token}"
