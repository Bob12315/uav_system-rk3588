"""Tests for FieldProfile v2 centerline schema."""
import math, os, pytest
from app.field_profile import (AnchorPoint, BindingPolicy, CenterlinePoint, FieldProfile, FieldProfileDiagnostics, FieldProfileValidationError, fit_centerline, load_field_profile_json, parse_field_profile, validate_field_profile)

def test_parse_valid():
    data = {"schema_version":2,"profile_id":"test","name":"Test","coordinate_convention":{"field_x_positive":"right","field_y_positive":"forward","altitude_positive":"up"},"anchor":{"name":"a","lat":34.0,"lon":108.0,"field_x_m":0.0,"field_y_m":0.0},"centerline_points":[{"name":"CL_1","lat":34.000075,"lon":108.0},{"name":"CL_2","lat":34.000150,"lon":108.0},{"name":"CL_3","lat":34.000225,"lon":108.0},{"name":"CL_4","lat":34.000300,"lon":108.0}]}
    p = parse_field_profile(data)
    assert p.schema_version == 2

def test_min_4_points():
    data = {"schema_version":2,"profile_id":"test","name":"Test","coordinate_convention":{"field_x_positive":"right","field_y_positive":"forward","altitude_positive":"up"},"anchor":{"name":"a","lat":34.0,"lon":108.0,"field_x_m":0.0,"field_y_m":0.0},"centerline_points":[{"name":"CL_1","lat":34.0001,"lon":108.0},{"name":"CL_2","lat":34.0002,"lon":108.0}]}
    p = parse_field_profile(data)
    assert not validate_field_profile(p).ok

def test_centerline_fit_north():
    a = AnchorPoint("a",34.0,108.0)
    cl = [CenterlinePoint("c1",34.0001,108.0),CenterlinePoint("c2",34.0002,108.0),CenterlinePoint("c3",34.0003,108.0),CenterlinePoint("c4",34.0004,108.0)]
    r = fit_centerline(a, cl, BindingPolicy())
    assert r.diagnostics.ok
    assert abs(r.field_heading_yaw_rad) < 0.02

def test_outlier_rejected():
    a = AnchorPoint("a",34.0,108.0)
    cl = [CenterlinePoint("c1",34.0001,108.0),CenterlinePoint("c2",34.0002,108.0001),CenterlinePoint("c3",34.0003,108.0),CenterlinePoint("c4",34.0004,108.0)]
    r = fit_centerline(a, cl, BindingPolicy(max_centerline_residual_m=2.5))
    assert not r.diagnostics.ok
