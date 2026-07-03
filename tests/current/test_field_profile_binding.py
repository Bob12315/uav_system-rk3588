"""Tests for centerline profile binding."""
import math, pytest
from app.field_profile import (AnchorPoint, BindingPolicy, CenterlinePoint, FieldGeometry, FieldProfile, GpsQualityThresholds)
from app.field_profile_service import FieldProfileService

def _mkp():
    cl = [CenterlinePoint("CL_1",34.000075,108.0),CenterlinePoint("CL_2",34.000150,108.0),CenterlinePoint("CL_3",34.000225,108.0),CenterlinePoint("CL_4",34.000300,108.0)]
    return FieldProfile(schema_version=2,profile_id="test",name="Test",coordinate_convention={"field_x_positive":"right","field_y_positive":"forward","altitude_positive":"up"},anchor=AnchorPoint("a",34.0,108.0),centerline_points=cl,gps_quality=GpsQualityThresholds(),field_geometry=FieldGeometry(),binding_policy=BindingPolicy())

def _bind(p, ln=10.0, le=20.0, lz=-1.0, lat=34.0, lon=108.0, fix=3, sats=12, eph=1.0, epv=1.0, yaw=0.0):
    return FieldProfileService.takeoff_anchor_centerline(profile=p,current_lat=lat,current_lon=lon,current_local_n_m=ln,current_local_e_m=le,current_local_z_m=lz,current_yaw_rad=yaw,gps_fix_type=fix,satellites_visible=sats,gps_eph=eph,gps_epv=epv,timestamp=1000.0)

def test_origin_local_equals_input():
    r = _bind(_mkp(), ln=10.0, le=20.0, lz=-1.0)
    assert r.ok
    assert r.origin_local_n_m == pytest.approx(10.0)
    assert r.origin_local_e_m == pytest.approx(20.0)

def test_origin_independent_of_gps():
    r = _bind(_mkp(), ln=10.0, le=20.0, lat=34.000018, lon=108.0)
    assert r.ok
    assert r.origin_local_n_m == pytest.approx(10.0)
    assert r.current_start_error_m == pytest.approx(2.0, abs=0.3)

def test_start_error_rejected():
    p = _mkp()
    p.binding_policy = BindingPolicy(max_start_error_m=3.0)
    r = _bind(p, lat=34.000045, lon=108.0)
    assert not r.ok

def test_yaw_does_not_affect_heading():
    p = _mkp()
    r1 = _bind(p, yaw=0.0)
    r2 = _bind(p, yaw=math.pi)
    assert r1.field_heading_yaw_rad == pytest.approx(r2.field_heading_yaw_rad)
    assert abs(r1.yaw_error_deg - r2.yaw_error_deg) > 1.0
