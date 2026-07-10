"""Tests for FieldReference centerline-only."""
import math, pytest
from app.field_reference import (FieldReference, FieldReferenceError, HeadingSource, OriginSource, WGS84_POLE_COS_EPS, _gps_distance_m, _gps_bearing_rad, circular_median_longitude_deg, gps_enu_deltas, normalize_longitude_deg, shortest_longitude_delta_deg, validate_wgs84_lat_lon)
from app.field_reference_service import FieldReferenceService
from app.field_profile_service import BindResult, FieldProfileService
from app.field_profile import (AnchorPoint, BindingPolicy, CenterlinePoint, FieldGeometry, FieldProfile, GpsQualityThresholds)

def _mkp():
    cl = [CenterlinePoint("CL_1",34.000075,108.0),CenterlinePoint("CL_2",34.000150,108.0),CenterlinePoint("CL_3",34.000225,108.0),CenterlinePoint("CL_4",34.000300,108.0)]
    return FieldProfile(schema_version=2,profile_id="test",name="Test",coordinate_convention={"field_x_positive":"right","field_y_positive":"forward","altitude_positive":"up"},anchor=AnchorPoint("a",34.0,108.0),centerline_points=cl)

def _bind_res():
    return FieldProfileService.takeoff_anchor_centerline(profile=_mkp(),current_lat=34.0,current_lon=108.0,current_local_n_m=10.0,current_local_e_m=20.0,current_local_z_m=-1.0,gps_fix_type=3,satellites_visible=12,gps_eph=1.0,gps_epv=1.0,timestamp=1000.0)

def test_unconfirmed_not_ready():
    ref = FieldReference()
    assert not ref.is_ready()

def test_apply_frozen():
    svc = FieldReferenceService()
    br = _bind_res()
    svc.apply_profile_binding(br,"test","Test",34.0,108.0)
    svc.freeze()
    assert not svc.apply_profile_binding(br,"test2","Test2",34.0,108.0)["ok"]

def test_status_centerline_source():
    svc = FieldReferenceService()
    br = _bind_res()
    svc.apply_profile_binding(br,"test","Test",34.0,108.0)
    s = svc.status()
    assert s["origin_source"] == OriginSource.PROFILE_CENTERLINE.value

def test_gps_distance():
    assert _gps_distance_m(34.0,108.0,34.0001,108.0) == pytest.approx(11.12, abs=0.1)

def test_gps_bearing_north():
    assert abs(_gps_bearing_rad(34.0,108.0,34.0001,108.0)) < 0.01


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (180.0001, -179.9999),
        (-180.0001, 179.9999),
        (540.0, -180.0),
        (-540.0, -180.0),
    ],
)
def test_normalize_longitude_canonical(value, expected):
    assert normalize_longitude_deg(value) == pytest.approx(expected, abs=1e-10)


@pytest.mark.parametrize("value", [True, None, math.nan, math.inf])
def test_normalize_longitude_rejects_invalid_input(value):
    with pytest.raises(FieldReferenceError):
        normalize_longitude_deg(value)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([10.0], 10.0),
        ([10.0, 11.0, 12.0], 11.0),
        ([179.9998, -179.9998], -180.0),
        ([-179.9998, 179.9998], -180.0),
        ([179.9998] * 10 + [-179.9998] * 10, -180.0),
        ([-179.9998] * 10 + [179.9998] * 10, -180.0),
        ([180.0, -180.0], -180.0),
    ],
)
def test_circular_longitude_median(values, expected):
    actual = circular_median_longitude_deg(values)
    assert abs(shortest_longitude_delta_deg(expected, actual)) < 1e-10


@pytest.mark.parametrize(
    "values",
    [[], [True], ["1"], [None], [math.nan], [math.inf], [181.0], object()],
)
def test_circular_longitude_median_rejects_invalid_input(values):
    with pytest.raises(FieldReferenceError):
        circular_median_longitude_deg(values)


@pytest.mark.parametrize(
    ("lon_a", "lon_b", "sign"),
    [(179.9999, -179.9999, 1), (-179.9999, 179.9999, -1)],
)
def test_dateline_enu_and_bearing_use_shortest_delta(lon_a, lon_b, sign):
    delta = shortest_longitude_delta_deg(lon_a, lon_b)
    north, east = gps_enu_deltas(0.0, lon_a, 0.0, lon_b)
    bearing = _gps_bearing_rad(0.0, lon_a, 0.0, lon_b)
    assert delta * sign > 0.0
    assert north == pytest.approx(0.0, abs=1e-9)
    assert 20.0 < abs(east) < 25.0
    assert east * sign > 0.0
    assert bearing == pytest.approx(sign * math.pi / 2.0, abs=1e-9)


@pytest.mark.parametrize(
    ("lat", "lon"),
    [(True, 0.0), (0.0, False), ("0", 0.0), (0.0, None), (math.nan, 0.0), (0.0, math.inf)],
)
def test_wgs84_validation_rejects_non_numeric_or_nonfinite(lat, lon):
    with pytest.raises(FieldReferenceError):
        validate_wgs84_lat_lon(lat, lon, reject_pole=True)


@pytest.mark.parametrize("lat", [90.0, -90.0])
def test_wgs84_validation_rejects_poles(lat):
    with pytest.raises(FieldReferenceError, match="pole"):
        validate_wgs84_lat_lon(lat, 0.0, reject_pole=True)


def test_wgs84_validation_rejects_inside_shared_pole_epsilon():
    latitude = math.degrees(math.acos(WGS84_POLE_COS_EPS / 2.0))
    with pytest.raises(FieldReferenceError, match="pole"):
        validate_wgs84_lat_lon(latitude, 0.0, reject_pole=True)
