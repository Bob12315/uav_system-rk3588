"""Tests for ResolveGpsTargetsAction — GPS + LOCAL_NED resolution."""
from __future__ import annotations

import math

import pytest

from missions.common.actions.resolve_gps_targets import ResolveGpsTargetsAction


def _make_context(*, field_origin_lat=30.0, field_origin_lon=120.0,
                  field_origin_local_x=100.0, field_origin_local_y=200.0,
                  field_heading_yaw_rad=0.0):
    """Build a minimal context with field reference fields."""
    return {
        "field_origin_lat": field_origin_lat,
        "field_origin_lon": field_origin_lon,
        "field_origin_local_x": field_origin_local_x,
        "field_origin_local_y": field_origin_local_y,
        "field_heading_yaw_rad": field_heading_yaw_rad,
    }


# ---------------------------------------------------------------------------
# field source
# ---------------------------------------------------------------------------


def test_resolve_field_produces_gps_and_local():
    """A field target resolves to GPS + LOCAL_NED."""
    ctx = _make_context(field_heading_yaw_rad=0.0)
    action = ResolveGpsTargetsAction()
    action.start({
        "targets": [
            {"source": "field", "field_x_m": 0.0, "field_y_m": 10.0, "altitude_m": 5.0},
        ],
    })
    result = action.update(ctx)

    assert result.done
    resolved = result.detail["resolved_targets"]
    assert len(resolved) == 1
    t = resolved[0]
    assert t["valid"] is True
    assert t["source"] == "field"
    assert "lat" in t
    assert "lon" in t
    assert t["altitude_m"] == 5.0
    assert t["local_x"] == pytest.approx(110.0)  # 100 + 10*cos(0)
    assert t["local_y"] == pytest.approx(200.0)  # 200 + 10*sin(0)
    assert t["z_down_m"] == -5.0
    assert t["field_x"] == 0.0
    assert t["field_y"] == 10.0


def test_resolve_field_yaw_90_degrees():
    """Field +Y at heading π/2 → LOCAL east."""
    ctx = _make_context(field_heading_yaw_rad=math.pi / 2)
    action = ResolveGpsTargetsAction()
    action.start({
        "targets": [
            {"source": "field", "field_x_m": 0.0, "field_y_m": 10.0, "altitude_m": 3.0},
        ],
    })
    result = action.update(ctx)
    resolved = result.detail["resolved_targets"]
    assert len(resolved) == 1
    t = resolved[0]
    assert t["local_x"] == pytest.approx(100.0)
    assert t["local_y"] == pytest.approx(210.0)  # 200 + 10


# ---------------------------------------------------------------------------
# home source
# ---------------------------------------------------------------------------


def test_resolve_home():
    """Home resolves to origin GPS + LOCAL_NED at origin + altitude."""
    ctx = _make_context()
    action = ResolveGpsTargetsAction()
    action.start({
        "targets": [
            {"source": "home", "altitude_m": 5.0},
        ],
    })
    result = action.update(ctx)

    assert result.done
    resolved = result.detail["resolved_targets"]
    assert len(resolved) == 1
    t = resolved[0]
    assert t["valid"] is True
    assert t["source"] == "home"
    assert t["lat"] == pytest.approx(30.0)
    assert t["lon"] == pytest.approx(120.0)
    assert t["altitude_m"] == 5.0
    assert t["local_x"] == pytest.approx(100.0)
    assert t["local_y"] == pytest.approx(200.0)
    assert t["z_down_m"] == -5.0


# ---------------------------------------------------------------------------
# vision source
# ---------------------------------------------------------------------------


def test_resolve_vision_center_detection():
    """Vision target at image center → near drone GPS position."""
    ctx = _make_context()
    ctx["drone"] = {
        "lat": 30.0,
        "lon": 120.0,
        "relative_altitude": 5.0,
        "yaw": 0.0,
        "yaw_rate": 0.01,
        "global_position_valid": True,
    }
    action = ResolveGpsTargetsAction()
    action.start({
        "targets": [
            {"source": "vision", "ex": 0.0, "ey": 0.0, "class_name": "bucket_1"},
        ],
    })
    result = action.update(ctx)

    assert result.done
    resolved = result.detail["resolved_targets"]
    assert len(resolved) == 1
    t = resolved[0]
    assert t["valid"] is True
    assert t["source"] == "vision"
    # Center of image (ex=0, ey=0) → target at drone position
    # tan(0) = 0, so body offsets are zero
    assert t["lat"] == pytest.approx(30.0, abs=0.0001)
    assert t["lon"] == pytest.approx(120.0, abs=0.0001)
    assert t["local_x"] == pytest.approx(100.0, abs=0.02)
    assert t["local_y"] == pytest.approx(200.0, abs=0.02)
    assert t["body_right_m"] == pytest.approx(0.0, abs=0.01)
    assert t["body_forward_m"] == pytest.approx(0.0, abs=0.01)


def test_resolve_vision_right_of_center():
    """Vision target right of image → positive local east offset at yaw=0."""
    ctx = _make_context()
    ctx["drone"] = {
        "lat": 30.0,
        "lon": 120.0,
        "relative_altitude": 5.0,
        "yaw": 0.0,
        "yaw_rate": 0.01,
        "global_position_valid": True,
    }
    action = ResolveGpsTargetsAction()
    action.start({
        "targets": [
            {"source": "vision", "ex": 0.5, "ey": 0.0},
        ],
    })
    result = action.update(ctx)

    assert result.done
    resolved = result.detail["resolved_targets"]
    assert len(resolved) == 1
    t = resolved[0]
    assert t["valid"] is True
    # ex=0.5 positive → body_right_m positive → local_y positive (east) at yaw=0
    assert t["body_right_m"] > 0.0
    assert t["local_y"] > 200.0
    # local_x should be near origin (no forward offset)
    assert t["local_x"] == pytest.approx(100.0, abs=0.02)


def test_resolve_vision_yaw_unstable():
    """Vision target with yaw_rate exceeding threshold → valid=false."""
    ctx = _make_context()
    ctx["drone"] = {
        "lat": 30.0,
        "lon": 120.0,
        "relative_altitude": 5.0,
        "yaw": 0.0,
        "yaw_rate": 0.5,  # ~28.6 deg/s, exceeds default 0.35 rad/s
        "global_position_valid": True,
    }
    action = ResolveGpsTargetsAction()
    action.start({
        "targets": [
            {"source": "vision", "ex": 0.0, "ey": 0.0},
        ],
    })
    result = action.update(ctx)

    assert result.done
    # Vision target should fail due to yaw instability
    assert result.detail["resolved_count"] == 0
    assert result.detail["error_count"] == 1
    assert "yaw_rate unstable" in result.detail["errors"][0]["reason"]


def test_resolve_vision_yaw_stability_bypass():
    """Vision target with yaw_stability_required=false accepts unstable yaw."""
    ctx = _make_context()
    ctx["drone"] = {
        "lat": 30.0,
        "lon": 120.0,
        "relative_altitude": 5.0,
        "yaw": 0.0,
        "yaw_rate": 0.5,
        "global_position_valid": True,
    }
    action = ResolveGpsTargetsAction()
    action.start({
        "targets": [
            {"source": "vision", "ex": 0.0, "ey": 0.0},
        ],
        "yaw_stability_required": False,
    })
    result = action.update(ctx)

    assert result.done
    assert result.detail["resolved_count"] == 1


def test_resolve_vision_yaw_rate_missing_fails():
    """Vision target with yaw_stability_required=true and no yaw_rate → valid=false."""
    ctx = _make_context()
    ctx["drone"] = {
        "lat": 30.0,
        "lon": 120.0,
        "relative_altitude": 5.0,
        "yaw": 0.0,
        # yaw_rate deliberately missing
        "global_position_valid": True,
    }
    action = ResolveGpsTargetsAction()
    action.start({
        "targets": [
            {"source": "vision", "ex": 0.0, "ey": 0.0},
        ],
    })
    result = action.update(ctx)

    assert result.done
    assert result.detail["resolved_count"] == 0
    assert result.detail["error_count"] == 1
    assert "yaw_rate_unavailable" in result.detail["errors"][0]["reason"]


# ---------------------------------------------------------------------------
# error handling
# ---------------------------------------------------------------------------


def test_resolve_unknown_source():
    """Unknown source type → error in output, no crash."""
    ctx = _make_context()
    action = ResolveGpsTargetsAction()
    action.start({
        "targets": [
            {"source": "mars"},
        ],
    })
    result = action.update(ctx)
    assert result.done
    assert result.detail["resolved_count"] == 0
    assert result.detail["error_count"] == 1
    assert "unsupported_source" in result.detail["errors"][0]["reason"]


def test_resolve_multiple_targets():
    """Multiple targets resolve together (field + home + vision)."""
    ctx = _make_context(field_heading_yaw_rad=0.0)
    ctx["drone"] = {
        "lat": 30.0,
        "lon": 120.0,
        "relative_altitude": 5.0,
        "yaw": 0.0,
        "yaw_rate": 0.01,
        "global_position_valid": True,
    }
    action = ResolveGpsTargetsAction()
    action.start({
        "targets": [
            {"source": "field", "field_x_m": 0.0, "field_y_m": 5.0, "altitude_m": 3.0},
            {"source": "home", "altitude_m": 5.0},
            {"source": "vision", "ex": 0.0, "ey": 0.0, "class_name": "bucket"},
        ],
    })
    result = action.update(ctx)

    assert result.done
    assert result.detail["resolved_count"] == 3
    assert result.detail["error_count"] == 0
    sources = [t["source"] for t in result.detail["resolved_targets"]]
    assert sources == ["field", "home", "vision"]
