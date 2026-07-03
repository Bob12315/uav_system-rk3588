"""Tests for FieldReference centerline-only."""
import math, pytest
from app.field_reference import (FieldReference, FieldReferenceError, HeadingSource, OriginSource, _gps_distance_m, _gps_bearing_rad)
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
