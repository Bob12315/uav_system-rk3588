"""Tests for runtime field geometry (step 3)."""

import copy
import math
from pathlib import Path

import pytest

from app.coordinate_transform import (
    GpsPoint,
    field_to_gps,
    field_to_gps_from_origin,
)
from app.field_profile import (
    FieldProfile,
    FieldProfileValidationError,
    parse_field_profile,
)
from app.field_reference import (
    EARTH_RADIUS_M,
    FieldReference,
    FieldReferenceError,
    gps_enu_deltas,
)
from app.runtime_field_geometry import (
    RuntimeFieldGeometry,
    RuntimeFieldGeometryError,
    RuntimeFieldPoint,
    build_runtime_field_geometry,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def make_valid_v3_dict() -> dict:
    return {
        "schema_version": 3,
        "profile_id": "test_lane",
        "name": "Test Lane",
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
    return parse_field_profile(make_valid_v3_dict())


# =========================================================================
# A. field_to_gps_from_origin
# =========================================================================


class TestFieldToGpsFromOrigin:
    ORIGIN_LAT = 34.103649
    ORIGIN_LON = 108.642674

    def test_heading_north(self):
        g = field_to_gps_from_origin(
            0, 10, 5,
            origin_lat=self.ORIGIN_LAT,
            origin_lon=self.ORIGIN_LON,
            field_heading_yaw_rad=0.0,
        )
        assert g.lat > self.ORIGIN_LAT  # FIELD +Y north → lat increases
        assert g.lon == pytest.approx(self.ORIGIN_LON, abs=1e-9)
        assert g.alt_m == 5

    def test_heading_north_x_positive(self):
        g = field_to_gps_from_origin(
            10, 0, 5,
            origin_lat=self.ORIGIN_LAT,
            origin_lon=self.ORIGIN_LON,
            field_heading_yaw_rad=0.0,
        )
        # FIELD +X right when heading north → lon increases
        assert g.lon > self.ORIGIN_LON

    def test_heading_east(self):
        g = field_to_gps_from_origin(
            0, 10, 5,
            origin_lat=self.ORIGIN_LAT,
            origin_lon=self.ORIGIN_LON,
            field_heading_yaw_rad=math.pi / 2,
        )
        assert g.lon > self.ORIGIN_LON  # FIELD +Y east → lon increases
        assert g.lat == pytest.approx(self.ORIGIN_LAT, abs=1e-9)

    def test_heading_east_x_positive(self):
        g = field_to_gps_from_origin(
            10, 0, 5,
            origin_lat=self.ORIGIN_LAT,
            origin_lon=self.ORIGIN_LON,
            field_heading_yaw_rad=math.pi / 2,
        )
        # FIELD +X right when heading east → lat decreases (south)
        assert g.lat < self.ORIGIN_LAT

    def test_combined_rotation(self):
        g = field_to_gps_from_origin(
            3, 4, 5,
            origin_lat=self.ORIGIN_LAT,
            origin_lon=self.ORIGIN_LON,
            field_heading_yaw_rad=0.5,
        )
        c = math.cos(0.5)
        s = math.sin(0.5)
        dn = 4 * c - 3 * s
        de = 4 * s + 3 * c
        rlat = math.radians(self.ORIGIN_LAT)
        expected_lat = self.ORIGIN_LAT + math.degrees(dn / EARTH_RADIUS_M)
        expected_lon = self.ORIGIN_LON + math.degrees(de / (EARTH_RADIUS_M * math.cos(rlat)))
        assert g.lat == pytest.approx(expected_lat, abs=1e-9)
        assert g.lon == pytest.approx(expected_lon, abs=1e-9)

    def test_preserves_altitude(self):
        g = field_to_gps_from_origin(
            0, 0, 123.456,
            origin_lat=self.ORIGIN_LAT,
            origin_lon=self.ORIGIN_LON,
            field_heading_yaw_rad=0.0,
        )
        assert g.alt_m == 123.456

    def test_rejects_pole(self):
        with pytest.raises(FieldReferenceError, match="pole"):
            field_to_gps_from_origin(
                0, 0, 0,
                origin_lat=90.0,
                origin_lon=0.0,
                field_heading_yaw_rad=0.0,
            )

    @pytest.mark.parametrize("bad", [None, True, "x", float("nan"), float("inf")])
    def test_rejects_invalid_input(self, bad):
        with pytest.raises(FieldReferenceError):
            field_to_gps_from_origin(
                0, 0, 0,
                origin_lat=bad,
                origin_lon=self.ORIGIN_LON,
                field_heading_yaw_rad=0.0,
            )

    def test_origin_lat_out_of_range(self):
        with pytest.raises(FieldReferenceError, match="origin_lat"):
            field_to_gps_from_origin(
                0, 0, 0,
                origin_lat=91.0,
                origin_lon=0.0,
                field_heading_yaw_rad=0.0,
            )

    def test_origin_lon_out_of_range(self):
        with pytest.raises(FieldReferenceError, match="origin_lon"):
            field_to_gps_from_origin(
                0, 0, 0,
                origin_lat=0.0,
                origin_lon=181.0,
                field_heading_yaw_rad=0.0,
            )

    def test_existing_field_to_gps_matches_pure_function(self):
        ref = FieldReference()
        ref.set_origin_gps_with_local_snapshot(
            lat=self.ORIGIN_LAT,
            lon=self.ORIGIN_LON,
            local_n_m=0.0,
            local_e_m=0.0,
        )
        ref.set_manual_heading(0.5)
        ref.confirm()

        old = field_to_gps(10, 20, 5, reference=ref)
        new = field_to_gps_from_origin(
            10, 20, 5,
            origin_lat=self.ORIGIN_LAT,
            origin_lon=self.ORIGIN_LON,
            field_heading_yaw_rad=0.5,
        )
        assert old.lat == pytest.approx(new.lat, abs=1e-12)
        assert old.lon == pytest.approx(new.lon, abs=1e-12)
        assert old.alt_m == new.alt_m


# =========================================================================
# B. A→B heading
# =========================================================================


class TestABHeading:
    def test_marker_north(self):
        p = _profile()
        # B is at 34.104189, origin at 34.103649 → north
        g = build_runtime_field_geometry(p, origin_lat=34.103649, origin_lon=108.642674)
        assert g.field_heading_yaw_rad == pytest.approx(0.0, abs=0.01)
        assert g.field_heading_deg == pytest.approx(0.0, abs=0.5)

    def test_marker_east(self):
        import copy
        data = make_valid_v3_dict()
        # Place marker far enough east to get ~90° heading
        data['forward_marker']['lat'] = 34.103649
        data['forward_marker']['lon'] = 108.643200
        p = parse_field_profile(data)
        g = build_runtime_field_geometry(p, origin_lat=34.103649, origin_lon=108.642674)
        assert g.field_heading_yaw_rad == pytest.approx(math.pi / 2, abs=0.1)

    def test_marker_south(self):
        import copy
        data = make_valid_v3_dict()
        data['forward_marker']['lat'] = 34.103200
        data['forward_marker']['lon'] = 108.642674
        data['binding_policy']['min_baseline_m'] = 1.0
        p = parse_field_profile(data)
        g = build_runtime_field_geometry(p, origin_lat=34.103649, origin_lon=108.642674)
        assert g.field_heading_yaw_rad == pytest.approx(math.pi, abs=0.1)

    def test_marker_west(self):
        import copy
        data = make_valid_v3_dict()
        data['forward_marker']['lat'] = 34.103649
        data['forward_marker']['lon'] = 108.642100
        p = parse_field_profile(data)
        g = build_runtime_field_geometry(p, origin_lat=34.103649, origin_lon=108.642674)
        assert g.field_heading_yaw_rad == pytest.approx(-math.pi / 2, abs=0.1)


# =========================================================================
# C. Baseline policy
# =========================================================================


class TestBaselinePolicy:
    def _make_marker_at(self, origin_lat, origin_lon, distance_m, bearing_rad=0.0):
        rlat = math.radians(origin_lat)
        dn = distance_m * math.cos(bearing_rad)
        de = distance_m * math.sin(bearing_rad)
        mlat = origin_lat + math.degrees(dn / EARTH_RADIUS_M)
        mlon = origin_lon + math.degrees(de / (EARTH_RADIUS_M * math.cos(rlat)))
        data = make_valid_v3_dict()
        data["forward_marker"]["lat"] = mlat
        data["forward_marker"]["lon"] = mlon
        return parse_field_profile(data)

    def test_baseline_below_min_errors(self):
        p = self._make_marker_at(34.103649, 108.642674, 29.0)
        with pytest.raises(RuntimeFieldGeometryError, match="baseline"):
            build_runtime_field_geometry(p, origin_lat=34.103649, origin_lon=108.642674)

    def test_baseline_at_min_warns(self):
        p = self._make_marker_at(34.103649, 108.642674, 31.0)
        g = build_runtime_field_geometry(p, origin_lat=34.103649, origin_lon=108.642674)
        assert any("baseline" in w.lower() for w in g.warnings)

    def test_baseline_at_warn_threshold_no_warn(self):
        p = self._make_marker_at(34.103649, 108.642674, 51.0)
        g = build_runtime_field_geometry(p, origin_lat=34.103649, origin_lon=108.642674)
        assert not any("baseline" in w.lower() for w in g.warnings)

    def test_baseline_above_warn_no_warn(self):
        p = self._make_marker_at(34.103649, 108.642674, 60.0)
        g = build_runtime_field_geometry(p, origin_lat=34.103649, origin_lon=108.642674)
        assert not any("baseline" in w.lower() for w in g.warnings)


# =========================================================================
# D. Home and marker
# =========================================================================


class TestHomeAndMarker:
    def test_home(self):
        p = _profile()
        g = build_runtime_field_geometry(p, origin_lat=34.103649, origin_lon=108.642674)
        assert g.home.name == "HOME"
        assert g.home.field_x_m == 0.0
        assert g.home.field_y_m == 0.0
        assert g.home.altitude_m == 0.0
        assert g.home.lat == 34.103649
        assert g.home.lon == 108.642674

    def test_forward_marker(self):
        p = _profile()
        g = build_runtime_field_geometry(p, origin_lat=34.103649, origin_lon=108.642674)
        assert g.forward_marker.name == "far_centerline_marker"
        assert g.forward_marker.field_x_m == 0.0
        assert g.forward_marker.field_y_m == pytest.approx(g.baseline_m, abs=1e-6)
        assert g.forward_marker.lat == p.forward_marker.lat
        assert g.forward_marker.lon == p.forward_marker.lon


# =========================================================================
# E. Scan points
# =========================================================================


class TestScanPoints:
    def test_count_and_names(self):
        p = _profile()
        g = build_runtime_field_geometry(p, origin_lat=34.103649, origin_lon=108.642674)
        assert len(g.drop_scan_waypoints) == 4
        for i in range(4):
            assert g.drop_scan_waypoints[i].name == f"DROP_SCAN_{i + 1}"

    def test_order_and_field_coords(self):
        p = _profile()
        g = build_runtime_field_geometry(p, origin_lat=34.103649, origin_lon=108.642674)
        expected = [(-2.0, 31.25, 5.0), (2.0, 31.25, 5.0),
                    (2.0, 33.75, 5.0), (-2.0, 33.75, 5.0)]
        for i, (ex, ey, ez) in enumerate(expected):
            wp = g.drop_scan_waypoints[i]
            assert wp.field_x_m == ex
            assert wp.field_y_m == ey
            assert wp.altitude_m == ez

    def test_gps_vs_pure_transform(self):
        p = _profile()
        g = build_runtime_field_geometry(p, origin_lat=34.103649, origin_lon=108.642674)
        for wp in g.drop_scan_waypoints:
            gps = field_to_gps_from_origin(
                wp.field_x_m, wp.field_y_m, wp.altitude_m,
                origin_lat=g.origin_lat, origin_lon=g.origin_lon,
                field_heading_yaw_rad=g.field_heading_yaw_rad,
            )
            assert wp.lat == pytest.approx(gps.lat, abs=1e-12)
            assert wp.lon == pytest.approx(gps.lon, abs=1e-12)


# =========================================================================
# F. Drop area corners
# =========================================================================


class TestDropAreaCorners:
    def test_order_and_coords(self):
        p = _profile()
        g = build_runtime_field_geometry(p, origin_lat=34.103649, origin_lon=108.642674)
        assert len(g.drop_area_corners) == 4
        names = ["D1", "D2", "D3", "D4"]
        coords = [(-4.0, 30.0), (4.0, 30.0), (4.0, 35.0), (-4.0, 35.0)]
        for i, pt in enumerate(g.drop_area_corners):
            assert pt.name == names[i]
            assert pt.field_x_m == coords[i][0]
            assert pt.field_y_m == coords[i][1]
            assert pt.altitude_m == 0.0

    def test_north_heading_relative_positions(self):
        # heading very close to north; verify D1 west, D2 east
        p = _profile()
        g = build_runtime_field_geometry(p, origin_lat=34.103649, origin_lon=108.642674)
        assert g.field_heading_yaw_rad == pytest.approx(0.0, abs=0.01)
        assert g.drop_area_corners[0].lon < g.origin_lon  # D1 west
        assert g.drop_area_corners[1].lon > g.origin_lon  # D2 east
        assert g.drop_area_corners[2].lat > g.drop_area_corners[1].lat  # D3 more north


# =========================================================================
# G. Recce area corners
# =========================================================================


class TestRecceAreaCorners:
    def test_order_and_coords(self):
        p = _profile()
        g = build_runtime_field_geometry(p, origin_lat=34.103649, origin_lon=108.642674)
        assert len(g.recce_area_corners) == 4
        names = ["R1", "R2", "R3", "R4"]
        coords = [(-4.0, 55.0), (4.0, 55.0), (4.0, 60.0), (-4.0, 60.0)]
        for i, pt in enumerate(g.recce_area_corners):
            assert pt.name == names[i]
            assert pt.field_x_m == coords[i][0]
            assert pt.field_y_m == coords[i][1]

    def test_recce_further_than_drop(self):
        p = _profile()
        g = build_runtime_field_geometry(p, origin_lat=34.103649, origin_lon=108.642674)
        assert g.recce_area_corners[0].field_y_m > g.drop_area_corners[2].field_y_m


# =========================================================================
# H. Profile validation
# =========================================================================


class TestProfileValidation:
    def test_rejects_schema_v2(self):
        data = {
            "schema_version": 2,
            "profile_id": "v2",
            "name": "V2",
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
        }
        p = parse_field_profile(data)
        with pytest.raises(RuntimeFieldGeometryError, match="schema"):
            build_runtime_field_geometry(p, origin_lat=34.0, origin_lon=108.0)

    def test_rejects_missing_forward_marker(self):
        data = make_valid_v3_dict()
        del data["forward_marker"]
        with pytest.raises(FieldProfileValidationError):
            parse_field_profile(data)

    def test_rejects_invalid_origin(self):
        p = _profile()
        with pytest.raises(RuntimeFieldGeometryError, match="origin_lat"):
            build_runtime_field_geometry(p, origin_lat=float("nan"), origin_lon=0.0)


# =========================================================================
# I. Input immutability
# =========================================================================


class TestInputImmutability:
    def test_profile_unchanged(self):
        data = make_valid_v3_dict()
        p = parse_field_profile(data)
        before = copy.deepcopy(p)
        build_runtime_field_geometry(p, origin_lat=34.103649, origin_lon=108.642674)
        assert p == before


# =========================================================================
# J. No local dependencies
# =========================================================================


class TestNoLocalDependencies:
    def test_output_points_have_no_local(self):
        p = _profile()
        g = build_runtime_field_geometry(p, origin_lat=34.103649, origin_lon=108.642674)
        for point in [g.home, g.forward_marker] + list(g.drop_scan_waypoints) + list(g.drop_area_corners):
            assert not hasattr(point, "local_x")
            assert not hasattr(point, "local_y")
            assert not hasattr(point, "local_z")


def test_runtime_field_geometry_no_local_source():
    src = Path("app/runtime_field_geometry.py").read_text()
    forbidden = [
        "origin_local_n_m", "origin_local_e_m",
        "local_x", "local_y", "local_z",
        "field_to_local_ned", "gps_to_local_ned", "local_ned_to_field",
        "RuntimeContext", "FieldProfileService", "LinkManager",
        "Mission", "ActionDispatcher",
    ]
    for token in forbidden:
        assert token not in src, f"forbidden token '{token}' found in runtime_field_geometry.py"
