"""Schema v3 field profile parsing and validation tests."""

import copy
import json
import math
from pathlib import Path

import pytest

from app.field_reference import WGS84_POLE_COS_EPS

from app.field_profile import (
    AnchorPoint,
    CenterlinePoint,
    BindingPolicy,
    DropScanConfig,
    FieldGeometry,
    FieldProfile,
    FieldProfileDiagnostics,
    FieldProfileValidationError,
    FieldScanWaypoint,
    ForwardMarker,
    GpsQualityThresholds,
    RuntimeOriginSampling,
    load_field_profile_json,
    parse_field_profile,
    validate_field_profile,
)


# ---------------------------------------------------------------------------
# helper — valid v3 profile dict
# ---------------------------------------------------------------------------


def make_valid_v3_profile_dict() -> dict:
    """Return a deep-copyable minimal-valid Schema v3 profile dict."""
    return {
        "schema_version": 3,
        "profile_id": "test_v3_lane",
        "name": "Test V3 Lane",
        "coordinate_convention": {
            "field_x_positive": "right",
            "field_y_positive": "forward",
            "altitude_positive": "up",
        },
        "forward_marker": {
            "name": "far_centerline_marker",
            "lat": 34.1030000,
            "lon": 108.6435000,
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


@pytest.mark.parametrize(
    "latitude",
    [
        90.0,
        -90.0,
        math.degrees(math.acos(WGS84_POLE_COS_EPS / 2.0)),
    ],
)
def test_schema_v3_rejects_forward_marker_at_pole(latitude):
    data = make_valid_v3_profile_dict()
    data["forward_marker"]["lat"] = latitude
    profile = parse_field_profile(data)
    diagnostics = validate_field_profile(profile)
    assert diagnostics.ok is False
    assert any(
        "forward_marker" in error and "pole" in error
        for error in diagnostics.errors
    )


# =========================================================================
# A. Valid parsing
# =========================================================================


class TestValidSchemaV3:
    def test_parse_valid_schema_v3(self):
        data = make_valid_v3_profile_dict()
        p = parse_field_profile(data)

        assert p.schema_version == 3
        assert p.profile_id == "test_v3_lane"
        assert p.name == "Test V3 Lane"
        assert p.anchor is None
        assert p.centerline_points == []

        # forward_marker
        assert p.forward_marker is not None
        assert p.forward_marker.name == "far_centerline_marker"
        assert p.forward_marker.lat == 34.103
        assert p.forward_marker.lon == 108.6435
        assert p.forward_marker.coordinate_system == "WGS84"

        # drop_scan
        assert p.drop_scan is not None
        assert len(p.drop_scan.waypoints) == 4
        expected = [(-2.0, 31.25, 5.0), (2.0, 31.25, 5.0),
                    (2.0, 33.75, 5.0), (-2.0, 33.75, 5.0)]
        for i, (ex, ey, ez) in enumerate(expected):
            wp = p.drop_scan.waypoints[i]
            assert wp.x_m == ex
            assert wp.y_m == ey
            assert wp.altitude_m == ez

        # sampling
        assert p.runtime_origin_sampling is not None
        assert p.runtime_origin_sampling.min_samples == 20
        assert p.runtime_origin_sampling.estimator == "median"

        # binding policy
        assert p.binding_policy.min_baseline_m == 30.0
        assert p.binding_policy.warn_baseline_below_m == 50.0

    def test_validate_valid_schema_v3(self):
        data = make_valid_v3_profile_dict()
        p = parse_field_profile(data)
        diag = validate_field_profile(p)
        assert diag.ok is True

    def test_load_valid_schema_v3_from_file(self, tmp_path):
        data = make_valid_v3_profile_dict()
        path = tmp_path / "v3.json"
        path.write_text(json.dumps(data))
        p = load_field_profile_json(str(path))
        assert p.schema_version == 3

    def test_schema_v2_still_parses_and_validates(self):
        data = {
            "schema_version": 2,
            "profile_id": "test_v2",
            "name": "Test V2",
            "coordinate_convention": {
                "field_x_positive": "right",
                "field_y_positive": "forward",
                "altitude_positive": "up",
            },
            "anchor": {"name": "a", "lat": 34.1, "lon": 108.6,
                        "field_x_m": 0.0, "field_y_m": 0.0},
            "centerline_points": [
                {"name": "c1", "lat": 34.1001, "lon": 108.6001},
                {"name": "c2", "lat": 34.1002, "lon": 108.6002},
                {"name": "c3", "lat": 34.1003, "lon": 108.6003},
                {"name": "c4", "lat": 34.1004, "lon": 108.6004},
            ],
        }
        p = parse_field_profile(data)
        assert p.schema_version == 2
        assert p.anchor is not None
        assert len(p.centerline_points) == 4
        diag = validate_field_profile(p)
        assert diag.ok is True


# =========================================================================
# B. Forbidden pre-surveyed origin fields
# =========================================================================


@pytest.mark.parametrize("forbidden_key", [
    "anchor",
    "centerline_points",
    "origin",
    "origin_lat",
    "origin_lon",
])
class TestForbiddenOriginFields:
    def test_schema_v3_rejects(self, forbidden_key):
        data = make_valid_v3_profile_dict()
        data[forbidden_key] = {"lat": 34.0, "lon": 108.0}
        with pytest.raises(FieldProfileValidationError) as exc:
            parse_field_profile(data)
        errs = exc.value.diagnostics.errors
        assert any(forbidden_key in e for e in errs), (
            f"expected error mentioning '{forbidden_key}', got {errs}"
        )


# =========================================================================
# C. Forward marker
# =========================================================================


class TestForwardMarker:
    def test_missing(self):
        data = make_valid_v3_profile_dict()
        del data["forward_marker"]
        with pytest.raises(FieldProfileValidationError) as exc:
            parse_field_profile(data)
        assert any("forward_marker" in e.lower() for e in exc.value.diagnostics.errors)

    def test_not_object(self):
        data = make_valid_v3_profile_dict()
        data["forward_marker"] = "not_an_object"
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_lat_out_of_range(self):
        data = make_valid_v3_profile_dict()
        data["forward_marker"]["lat"] = 91.0
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_lon_out_of_range(self):
        data = make_valid_v3_profile_dict()
        data["forward_marker"]["lon"] = 181.0
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_lat_nan(self):
        data = make_valid_v3_profile_dict()
        data["forward_marker"]["lat"] = float("nan")
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_lon_inf(self):
        data = make_valid_v3_profile_dict()
        data["forward_marker"]["lon"] = float("inf")
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_coordinate_system_missing(self):
        data = make_valid_v3_profile_dict()
        del data["forward_marker"]["coordinate_system"]
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_coordinate_system_gcj02(self):
        data = make_valid_v3_profile_dict()
        data["forward_marker"]["coordinate_system"] = "GCJ-02"
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_coordinate_system_lowercase(self):
        data = make_valid_v3_profile_dict()
        data["forward_marker"]["coordinate_system"] = "wgs84"
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_name_empty(self):
        data = make_valid_v3_profile_dict()
        data["forward_marker"]["name"] = ""
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_name_missing(self):
        data = make_valid_v3_profile_dict()
        del data["forward_marker"]["name"]
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)


# =========================================================================
# D. Geometry
# =========================================================================


class TestGeometry:
    def test_lane_half_width_zero(self):
        data = make_valid_v3_profile_dict()
        data["field_geometry"]["lane_half_width_m"] = 0.0
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_drop_min_ge_max(self):
        data = make_valid_v3_profile_dict()
        # swap so dmin=35, dmax=30: parse-time waypoint range check catches
        # since waypoints y=31.25,33.75 are outside [35,30]
        data["field_geometry"]["drop_area_y_min_m"] = 35.0
        data["field_geometry"]["drop_area_y_max_m"] = 30.0
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_drop_center_out_of_range(self):
        data = make_valid_v3_profile_dict()
        data["field_geometry"]["drop_center_y_m"] = 40.0
        p = parse_field_profile(data)
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_recce_min_ge_max(self):
        data = make_valid_v3_profile_dict()
        data["field_geometry"]["recce_area_y_min_m"] = 60.0
        data["field_geometry"]["recce_area_y_max_m"] = 50.0
        p = parse_field_profile(data)
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_recce_center_out_of_range(self):
        data = make_valid_v3_profile_dict()
        data["field_geometry"]["recce_center_y_m"] = 50.0
        p = parse_field_profile(data)
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_drop_max_ge_recce_min(self):
        data = make_valid_v3_profile_dict()
        data["field_geometry"]["drop_area_y_max_m"] = 56.0
        data["field_geometry"]["recce_area_y_min_m"] = 55.0
        p = parse_field_profile(data)
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_nan_field(self):
        data = make_valid_v3_profile_dict()
        data["field_geometry"]["lane_half_width_m"] = float("nan")
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_negative_y(self):
        data = make_valid_v3_profile_dict()
        data["field_geometry"]["drop_area_y_min_m"] = -1.0
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)


# =========================================================================
# E. Drop scan
# =========================================================================


class TestDropScan:
    def test_missing(self):
        data = make_valid_v3_profile_dict()
        del data["drop_scan"]
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_waypoints_missing(self):
        data = make_valid_v3_profile_dict()
        del data["drop_scan"]["waypoints"]
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_waypoints_not_list(self):
        data = make_valid_v3_profile_dict()
        data["drop_scan"]["waypoints"] = "not_list"
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_not_4_points(self):
        data = make_valid_v3_profile_dict()
        data["drop_scan"]["waypoints"] = [{"x_m": 0, "y_m": 0, "altitude_m": 5}]
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_waypoint_not_object(self):
        data = make_valid_v3_profile_dict()
        data["drop_scan"]["waypoints"][1] = "bad"
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_missing_x(self):
        data = make_valid_v3_profile_dict()
        del data["drop_scan"]["waypoints"][0]["x_m"]
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_missing_y(self):
        data = make_valid_v3_profile_dict()
        del data["drop_scan"]["waypoints"][0]["y_m"]
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_missing_altitude(self):
        data = make_valid_v3_profile_dict()
        del data["drop_scan"]["waypoints"][0]["altitude_m"]
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_x_outside_lane(self):
        data = make_valid_v3_profile_dict()
        data["drop_scan"]["waypoints"][0]["x_m"] = 5.0
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_y_outside_drop_area(self):
        data = make_valid_v3_profile_dict()
        data["drop_scan"]["waypoints"][0]["y_m"] = 0.0
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_altitude_zero(self):
        data = make_valid_v3_profile_dict()
        data["drop_scan"]["waypoints"][0]["altitude_m"] = 0.0
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_all_identical(self):
        data = make_valid_v3_profile_dict()
        for i in range(4):
            data["drop_scan"]["waypoints"][i] = {"x_m": 0.0, "y_m": 32.0, "altitude_m": 5.0}
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_contains_lat(self):
        data = make_valid_v3_profile_dict()
        data["drop_scan"]["waypoints"][0]["lat"] = 34.0
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_contains_lon(self):
        data = make_valid_v3_profile_dict()
        data["drop_scan"]["waypoints"][0]["lon"] = 108.0
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_contains_local_x(self):
        data = make_valid_v3_profile_dict()
        data["drop_scan"]["waypoints"][0]["local_x"] = 1.0
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_contains_local_y(self):
        data = make_valid_v3_profile_dict()
        data["drop_scan"]["waypoints"][0]["local_y"] = 1.0
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_exact_waypoint_order_preserved(self):
        data = make_valid_v3_profile_dict()
        p = parse_field_profile(data)
        expected = [(-2.0, 31.25, 5.0), (2.0, 31.25, 5.0),
                    (2.0, 33.75, 5.0), (-2.0, 33.75, 5.0)]
        for i, (ex, ey, ez) in enumerate(expected):
            assert p.drop_scan.waypoints[i].x_m == ex
            assert p.drop_scan.waypoints[i].y_m == ey
            assert p.drop_scan.waypoints[i].altitude_m == ez


# =========================================================================
# F. GPS quality
# =========================================================================


class TestGpsQuality:
    def test_missing(self):
        data = make_valid_v3_profile_dict()
        del data["gps_quality"]
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_min_fix_type_missing(self):
        data = make_valid_v3_profile_dict()
        del data["gps_quality"]["min_fix_type"]
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_min_fix_type_too_low(self):
        data = make_valid_v3_profile_dict()
        data["gps_quality"]["min_fix_type"] = 2
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_min_fix_type_float(self):
        data = make_valid_v3_profile_dict()
        data["gps_quality"]["min_fix_type"] = 3.5
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_min_satellites_zero(self):
        data = make_valid_v3_profile_dict()
        data["gps_quality"]["min_satellites"] = 0
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_min_satellites_bool(self):
        data = make_valid_v3_profile_dict()
        data["gps_quality"]["min_satellites"] = True
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_max_eph_zero(self):
        data = make_valid_v3_profile_dict()
        data["gps_quality"]["max_eph"] = 0.0
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_max_epv_zero(self):
        data = make_valid_v3_profile_dict()
        data["gps_quality"]["max_epv"] = 0.0
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_rejects_max_hdop(self):
        data = make_valid_v3_profile_dict()
        data["gps_quality"]["max_hdop"] = 1.5
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_rejects_hdop(self):
        data = make_valid_v3_profile_dict()
        data["gps_quality"]["hdop"] = 1.0
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)


# =========================================================================
# G. Sampling
# =========================================================================


class TestSampling:
    def test_missing(self):
        data = make_valid_v3_profile_dict()
        del data["runtime_origin_sampling"]
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_min_samples_too_low(self):
        data = make_valid_v3_profile_dict()
        data["runtime_origin_sampling"]["min_samples"] = 2
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_min_samples_float(self):
        data = make_valid_v3_profile_dict()
        data["runtime_origin_sampling"]["min_samples"] = 20.5
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_window_zero_is_allowed_for_count_based_sampling(self):
        data = make_valid_v3_profile_dict()
        data["runtime_origin_sampling"]["sample_window_s"] = 0.0
        assert parse_field_profile(data).runtime_origin_sampling.sample_window_s == 0.0

    def test_spread_zero(self):
        data = make_valid_v3_profile_dict()
        data["runtime_origin_sampling"]["max_horizontal_spread_m"] = 0.0
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_estimator_missing(self):
        data = make_valid_v3_profile_dict()
        del data["runtime_origin_sampling"]["estimator"]
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_estimator_not_median(self):
        data = make_valid_v3_profile_dict()
        data["runtime_origin_sampling"]["estimator"] = "mean"
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)


# =========================================================================
# H. Binding policy
# =========================================================================


class TestBindingPolicy:
    def test_missing(self):
        data = make_valid_v3_profile_dict()
        del data["binding_policy"]
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_min_baseline_zero(self):
        data = make_valid_v3_profile_dict()
        data["binding_policy"]["min_baseline_m"] = 0.0
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_warn_not_gt_min(self):
        data = make_valid_v3_profile_dict()
        data["binding_policy"]["warn_baseline_below_m"] = 30.0
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_nan(self):
        data = make_valid_v3_profile_dict()
        data["binding_policy"]["min_baseline_m"] = float("nan")
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_inf(self):
        data = make_valid_v3_profile_dict()
        data["binding_policy"]["min_baseline_m"] = float("inf")
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)


# =========================================================================
# I. Unknown fields
# =========================================================================


class TestUnknownFields:
    def test_unknown_top_level_goes_to_extra(self):
        data = make_valid_v3_profile_dict()
        data["my_custom_field"] = 42
        p = parse_field_profile(data)
        assert "my_custom_field" in p.extra
        assert p.extra["my_custom_field"] == 42

    def test_unknown_generates_warning(self):
        data = make_valid_v3_profile_dict()
        data["my_custom_field"] = 42
        p = parse_field_profile(data)
        diag = validate_field_profile(p)
        assert any("my_custom_field" in w for w in diag.warnings)
        assert diag.ok is True  # unknown fields don't cause errors


# =========================================================================
# J. No old centerline math called
# =========================================================================


class TestNoCenterlineRequired:
    def test_schema_v3_validation_does_not_require_anchor_or_centerline(self):
        data = make_valid_v3_profile_dict()
        p = parse_field_profile(data)
        assert p.anchor is None
        assert p.centerline_points == []
        diag = validate_field_profile(p)
        assert diag.ok is True


# =========================================================================
# K. Schema v2 regression tests (v2.1 fixes)
# =========================================================================


class TestV2Regression:
    def test_schema_v2_direction_deviation_remains_warning_not_error(self):
        data = {
            "schema_version": 2,
            "profile_id": "test",
            "name": "Test",
            "coordinate_convention": {
                "field_x_positive": "right",
                "field_y_positive": "forward",
                "altitude_positive": "up",
            },
            "anchor": {"name": "a", "lat": 34.0, "lon": 108.0,
                       "field_x_m": 0.0, "field_y_m": 0.0},
            "centerline_points": [
                {"name": "c1", "lat": 34.002, "lon": 108.001},
                {"name": "c2", "lat": 34.003, "lon": 108.002},
                {"name": "c3", "lat": 34.004, "lon": 108.003},
                {"name": "c4", "lat": 34.0005, "lon": 108.004},
            ],
        }
        profile = parse_field_profile(data)
        diag = validate_field_profile(profile)
        assert diag.ok is True
        assert any(
            "direction deviates from main axis" in w
            for w in diag.warnings
        )
        assert not any(
            "direction deviates from main axis" in e
            for e in diag.errors
        )

    def test_schema_v2_nonpositive_recce_center_is_rejected(self):
        data = {
            "schema_version": 2,
            "profile_id": "test",
            "name": "Test",
            "coordinate_convention": {
                "field_x_positive": "right",
                "field_y_positive": "forward",
                "altitude_positive": "up",
            },
            "anchor": {"name": "a", "lat": 34.0, "lon": 108.0,
                       "field_x_m": 0.0, "field_y_m": 0.0},
            "centerline_points": [
                {"name": "c1", "lat": 34.001, "lon": 108.001},
                {"name": "c2", "lat": 34.002, "lon": 108.002},
                {"name": "c3", "lat": 34.003, "lon": 108.003},
                {"name": "c4", "lat": 34.004, "lon": 108.004},
            ],
            "field_geometry": {"recce_center_y_m": 0.0},
        }
        profile = parse_field_profile(data)
        diag = validate_field_profile(profile)
        assert not diag.ok
        assert any("recce_center_y_m must be > 0" in e for e in diag.errors)


# =========================================================================
# L. V3 parser — strict name type
# =========================================================================


@pytest.mark.parametrize("bad_name", [None, 123, True, [], {}, "", "   "])
class TestV3StrictForwardMarkerName:
    def test_schema_v3_rejects_non_string_or_blank_name(self, bad_name):
        data = make_valid_v3_profile_dict()
        data["forward_marker"]["name"] = bad_name
        with pytest.raises(FieldProfileValidationError) as exc:
            parse_field_profile(data)
        assert any(
            "forward_marker.name" in e
            for e in exc.value.diagnostics.errors
        )


# =========================================================================
# M. Direct-object validator tests
# =========================================================================


class TestValidateDirectV3:
    def _valid(self) -> FieldProfile:
        return parse_field_profile(make_valid_v3_profile_dict())

    def test_rejects_anchor(self):
        p = self._valid()
        p.anchor = AnchorPoint(name="bad", lat=0, lon=0)
        diag = validate_field_profile(p)
        assert not diag.ok
        assert any("anchor" in e for e in diag.errors)

    def test_rejects_centerline_points(self):
        p = self._valid()
        p.centerline_points = [CenterlinePoint(name="bad", lat=0, lon=0)]
        diag = validate_field_profile(p)
        assert not diag.ok
        assert any("centerline_points" in e for e in diag.errors)

    def test_fm_lat_nan(self):
        p = self._valid()
        p.forward_marker.lat = float("nan")
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_fm_lon_inf(self):
        p = self._valid()
        p.forward_marker.lon = float("inf")
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_geom_lane_nan(self):
        p = self._valid()
        p.field_geometry.lane_half_width_m = float("nan")
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_wp_x_nan(self):
        p = self._valid()
        p.drop_scan.waypoints[0].x_m = float("nan")
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_wp_alt_nan(self):
        p = self._valid()
        p.drop_scan.waypoints[0].altitude_m = float("nan")
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_gps_eph_inf(self):
        p = self._valid()
        p.gps_quality.max_eph = float("inf")
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_gps_epv_nan(self):
        p = self._valid()
        p.gps_quality.max_epv = float("nan")
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_samp_window_inf(self):
        p = self._valid()
        p.runtime_origin_sampling.sample_window_s = float("inf")
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_samp_spread_nan(self):
        p = self._valid()
        p.runtime_origin_sampling.max_horizontal_spread_m = float("nan")
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_bp_min_inf(self):
        p = self._valid()
        p.binding_policy.min_baseline_m = float("inf")
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_bp_warn_nan(self):
        p = self._valid()
        p.binding_policy.warn_baseline_below_m = float("nan")
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_gps_fix_float(self):
        p = self._valid()
        p.gps_quality.min_fix_type = 3.5
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_gps_fix_bool(self):
        p = self._valid()
        p.gps_quality.min_fix_type = True
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_gps_sat_float(self):
        p = self._valid()
        p.gps_quality.min_satellites = 10.5
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_gps_sat_bool(self):
        p = self._valid()
        p.gps_quality.min_satellites = True
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_samp_min_float(self):
        p = self._valid()
        p.runtime_origin_sampling.min_samples = 3.5
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_samp_min_bool(self):
        p = self._valid()
        p.runtime_origin_sampling.min_samples = True
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_geom_lane_str(self):
        p = self._valid()
        p.field_geometry.lane_half_width_m = "bad"
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_wp_x_none(self):
        p = self._valid()
        p.drop_scan.waypoints[0].x_m = None
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_gps_eph_str(self):
        p = self._valid()
        p.gps_quality.max_eph = "bad"
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_samp_win_list(self):
        p = self._valid()
        p.runtime_origin_sampling.sample_window_s = []
        diag = validate_field_profile(p)
        assert not diag.ok

    def test_bp_min_dict(self):
        p = self._valid()
        p.binding_policy.min_baseline_m = {}
        diag = validate_field_profile(p)
        assert not diag.ok
