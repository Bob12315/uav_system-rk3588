from __future__ import annotations

from missions.common.actions.resolve_gps_targets import ResolveGpsTargetsAction


def _context() -> dict:
    return {"field_origin_lat": 34.0, "field_origin_lon": 108.0, "field_heading_yaw_rad": 0.0}


def test_field_target_resolves_to_schema_v3_global_only() -> None:
    action = ResolveGpsTargetsAction()
    action.start({"targets": [{"source": "field", "x": 2.0, "y": 10.0, "altitude_m": 5.0}]})
    result = action.update(_context())
    target = result.detail["resolved_targets"][0]
    assert result.done is True
    assert target["lat"] > 34.0 and target["lon"] > 108.0
    assert target["field_x"] == 2.0 and target["field_y"] == 10.0
    assert not ({"local_x", "local_y", "z_down_m"} & set(target))


def test_home_target_is_global_origin() -> None:
    action = ResolveGpsTargetsAction()
    action.start({"targets": [{"source": "home", "altitude_m": 3.0}]})
    target = action.update(_context()).detail["resolved_targets"][0]
    assert (target["lat"], target["lon"], target["altitude_m"]) == (34.0, 108.0, 3.0)


def test_missing_schema_v3_reference_fails_closed() -> None:
    action = ResolveGpsTargetsAction()
    action.start({"targets": [{"source": "field", "x": 0.0, "y": 1.0, "altitude_m": 3.0}]})
    result = action.update({})
    assert result.failed is True and result.reason == "field_reference_not_ready"
