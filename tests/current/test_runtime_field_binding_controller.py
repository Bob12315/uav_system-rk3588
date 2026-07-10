"""Tests for runtime binding orchestrator (step 5B.2)."""

import copy

import pytest

from app.field_profile import parse_field_profile, validate_field_profile
from app.field_reference import FieldReference
from app.field_reference_service import FieldReferenceService
from app.runtime_binding_orchestrator import RuntimeBindingOrchestrator
from app.runtime_context import RuntimeContextBuilder


def _make_profile():
    return parse_field_profile({
        "schema_version": 3, "profile_id": "test_orch", "name": "Test Orch",
        "coordinate_convention": {"field_x_positive": "right", "field_y_positive": "forward", "altitude_positive": "up"},
        "forward_marker": {"name": "far", "lat": 34.104189, "lon": 108.642674, "coordinate_system": "WGS84"},
        "field_geometry": {"lane_half_width_m": 4.0, "drop_area_y_min_m": 30.0, "drop_area_y_max_m": 35.0, "drop_center_y_m": 32.5, "recce_area_y_min_m": 55.0, "recce_area_y_max_m": 60.0, "recce_center_y_m": 57.5},
        "drop_scan": {"waypoints": [{"x_m": -2.0, "y_m": 31.25, "altitude_m": 5.0}, {"x_m": 2.0, "y_m": 31.25, "altitude_m": 5.0}, {"x_m": 2.0, "y_m": 33.75, "altitude_m": 5.0}, {"x_m": -2.0, "y_m": 33.75, "altitude_m": 5.0}]},
        "gps_quality": {"min_fix_type": 3, "min_satellites": 10, "max_eph": 2.5, "max_epv": 5.0},
        "runtime_origin_sampling": {"min_samples": 20, "sample_window_s": 5.0, "max_horizontal_spread_m": 1.0, "estimator": "median"},
        "binding_policy": {"min_baseline_m": 30.0, "warn_baseline_below_m": 50.0},
    })


def _valid_snap(source_time: float) -> dict:
    return {
        "global_position_valid": True, "last_global_position_time": source_time,
        "lat": 34.103649, "lon": 108.642674,
        "gps_fix_type": 3, "satellites_visible": 12, "gps_eph": 1.0, "gps_epv": 1.5,
    }


class TestOrchestratorLifecycle:
    def test_start_sampling(self):
        o = RuntimeBindingOrchestrator(FieldReferenceService(), RuntimeContextBuilder())
        r = o.start(_make_profile(), started_at_s=1000.0)
        assert r["ok"] is True
        assert r["state"] == "sampling"

    def test_observe_and_finalize(self):
        o = RuntimeBindingOrchestrator(FieldReferenceService(), RuntimeContextBuilder())
        o.start(_make_profile(), started_at_s=1000.0)
        for i in range(20):
            o.observe(_valid_snap(2000.0 + i * 0.1), observed_at_s=1000.0 + i * 0.26)
        r = o.finalize(completed_at_s=1005.0)
        assert r["ok"] is True
        assert r["state"] == "applied"
        assert r["is_frozen"] is True
        assert r["is_ready_for_field_to_gps"] is True

    def test_finalize_idempotent(self):
        o = RuntimeBindingOrchestrator(FieldReferenceService(), RuntimeContextBuilder())
        o.start(_make_profile(), started_at_s=1000.0)
        for i in range(20):
            o.observe(_valid_snap(2000.0 + i * 0.1), observed_at_s=1000.0 + i * 0.26)
        r1 = o.finalize(completed_at_s=1005.0)
        r2 = o.finalize(completed_at_s=1006.0)
        assert r1 == r2

    def test_insufficient_samples_fails(self):
        o = RuntimeBindingOrchestrator(FieldReferenceService(), RuntimeContextBuilder())
        o.start(_make_profile(), started_at_s=1000.0)
        for i in range(10):
            o.observe(_valid_snap(2000.0 + i * 0.1), observed_at_s=1000.0 + i * 0.5)
        r = o.finalize(completed_at_s=1005.0)
        assert r["ok"] is False

    def test_cancel(self):
        o = RuntimeBindingOrchestrator(FieldReferenceService(), RuntimeContextBuilder())
        o.start(_make_profile(), started_at_s=1000.0)
        o.observe(_valid_snap(2000.0), observed_at_s=1000.1)
        r = o.cancel()
        assert r["ok"] is True
        assert o.state == "idle"


def test_no_local_in_orchestrator():
    src = __import__("pathlib").Path("app/runtime_binding_orchestrator.py").read_text()
    for token in ("origin_local_n_m", "origin_local_e_m", "local_x", "local_y", "local_z",
                  "field_to_local_ned", "gps_to_local_ned", ):
        assert token not in src, f"forbidden: {token}"
