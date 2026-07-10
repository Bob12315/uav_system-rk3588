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


# =============================================================================
# Transaction failure tests (5B.2.2)
# =============================================================================


class TestTransactionFailure:
    def _setup(self):
        o = RuntimeBindingOrchestrator(FieldReferenceService(), RuntimeContextBuilder())
        o.start(_make_profile(), started_at_s=1000.0)
        for i in range(20):
            o.observe(_valid_snap(2000.0 + i * 0.1), observed_at_s=1000.0 + i * 0.26)
        return o

    def test_service_apply_failure_rolls_back(self):
        o = self._setup()
        # simulate: force service apply to fail by freezing first
        o._svc.reference.is_confirmed = True
        o._svc.reference.freeze()
        r = o.finalize(completed_at_s=1005.0)
        assert r["ok"] is False
        assert o.state == "apply_failed"
        assert o._candidate is not None

    def test_candidate_retained_after_failure(self):
        o = self._setup()
        o._svc.reference.is_confirmed = True
        o._svc.reference.freeze()
        o.finalize(completed_at_s=1005.0)
        # candidate still stored
        assert o._candidate is not None
        assert o._candidate.sample_count == 20

    def test_retry_with_same_candidate(self):
        o = self._setup()
        o._svc.reference.is_confirmed = True
        o._svc.reference.freeze()
        r1 = o.finalize(completed_at_s=1005.0)
        assert r1.get("ok") is False
        # Unfreeze and retry
        from app.field_reference import FieldReference
        o._svc._ref = FieldReference()
        r2 = o.finalize(completed_at_s=1005.0)
        assert r2["ok"] is True
        assert r2["state"] == "applied"

    def test_idempotent_finalize(self):
        o = self._setup()
        r1 = o.finalize(completed_at_s=1005.0)
        assert r1["ok"] is True
        r2 = o.finalize(completed_at_s=1006.0)
        assert r1 == r2

    def test_sync_failure_before_freeze(self):
        o = self._setup()
        # Freeze the service first — service apply will fail, rollback will trigger
        o._svc.reference.is_confirmed = True
        o._svc.reference.freeze()
        r = o.finalize(completed_at_s=1005.0)
        assert r["ok"] is False
        assert "frozen" in r.get("error", "").lower()


# =============================================================================
# Sync verification tests (5B.2.2)
# =============================================================================


class TestSyncMismatch:
    def _setup_and_apply(self):
        o = RuntimeBindingOrchestrator(FieldReferenceService(), RuntimeContextBuilder())
        o.start(_make_profile(), started_at_s=1000.0)
        for i in range(20):
            o.observe(_valid_snap(2000.0 + i * 0.1), observed_at_s=1000.0 + i * 0.26)
        r = o.finalize(completed_at_s=1005.0)
        return o, r

    def test_sync_checks_service_heading_source(self):
        o, r = self._setup_and_apply()
        assert r["ok"] is True
        assert o._svc.reference.heading_source == "runtime_forward_marker"

    def test_sync_checks_builder_gps_ready(self):
        o, r = self._setup_and_apply()
        assert o._builder.field_gps_transform_ready() is True
        assert o._builder.field_transform_ready() is False

    def test_sync_checks_builder_diagnostics(self):
        o, r = self._setup_and_apply()
        assert o._builder.field_gps_sample_count == 20
        assert o._builder.field_gps_rejected_sample_count == 0
        assert o._builder.field_gps_duplicate_sample_count == 0


# =============================================================================
# Orchestrator state tests (5B.2.2)
# =============================================================================


class TestOrchestratorStateMachine:
    def test_status_sampling_shows_counts(self):
        o = RuntimeBindingOrchestrator(FieldReferenceService(), RuntimeContextBuilder())
        o.start(_make_profile(), started_at_s=1000.0)
        for i in range(3):
            o.observe(_valid_snap(2000.0 + i * 0.1), observed_at_s=1000.0 + i * 0.3)
        st = o.status(now_s=1001.0)
        assert "sampling" in st
        assert st.get("candidate_ready") is False

    def test_status_applied_shows_candidate(self):
        o = RuntimeBindingOrchestrator(FieldReferenceService(), RuntimeContextBuilder())
        o.start(_make_profile(), started_at_s=1000.0)
        for i in range(20):
            o.observe(_valid_snap(2000.0 + i * 0.1), observed_at_s=1000.0 + i * 0.26)
        o.finalize(completed_at_s=1005.0)
        st = o.status()
        assert st["state"] == "applied"
        assert st["candidate_ready"] is True
        assert "candidate_summary" in st


# =============================================================================
# No-local and static checks (5B.2.2)
# =============================================================================


def test_no_local_in_orchestrator():
    src = __import__("pathlib").Path("app/runtime_binding_orchestrator.py").read_text()
    for token in ("origin_local_n_m", "origin_local_e_m", "local_x", "local_y", "local_z",
                  "field_to_local_ned", "gps_to_local_ned"):
        assert token not in src, f"forbidden: {token}"


class TestControllerIntegration:
    def test_controller_has_runtime_binding(self):
        from app.field_reference_controller import FieldReferenceController
        svc = FieldReferenceService()
        from app.runtime_context import RuntimeContextBuilder
        bld = RuntimeContextBuilder()
        ctrl = FieldReferenceController(svc, bld, None)
        assert hasattr(ctrl, '_runtime_binding')


# =============================================================================
# Quick regression tests (5B.2.2)
# =============================================================================


class TestQuickController:
    def test_service_apply_bad_timestamp(self):
        o = RuntimeBindingOrchestrator(FieldReferenceService(), RuntimeContextBuilder())
        o.start(_make_profile(), started_at_s=1000.0)
        for i in range(20):
            o.observe(_valid_snap(2000.0 + i * 0.1), observed_at_s=1000.0 + i * 0.26)
        # Not a valid timestamp
        r = o.finalize(completed_at_s=999.0)
        assert r["ok"] is False

    def test_cancel_clears_state(self):
        o = RuntimeBindingOrchestrator(FieldReferenceService(), RuntimeContextBuilder())
        o.start(_make_profile(), started_at_s=1000.0)
        o.observe(_valid_snap(2000.0), observed_at_s=1000.1)
        r = o.cancel()
        assert r["ok"] is True
        assert o.state == "idle"

    def test_observe_non_sampling(self):
        o = RuntimeBindingOrchestrator(FieldReferenceService(), RuntimeContextBuilder())
        r = o.observe(_valid_snap(2000.0), observed_at_s=1000.0)
        assert r.get("observed") is False


class TestServiceFields:
    def test_applied_sets_gps_ready(self):
        o = RuntimeBindingOrchestrator(FieldReferenceService(), RuntimeContextBuilder())
        o.start(_make_profile(), started_at_s=1000.0)
        for i in range(20):
            o.observe(_valid_snap(2000.0 + i * 0.1), observed_at_s=1000.0 + i * 0.26)
        r = o.finalize(completed_at_s=1005.0)
        assert o._svc.reference.is_ready_for_field_to_gps() is True
        assert o._svc.reference.is_ready() is False

    def test_frozen_after_apply(self):
        o = RuntimeBindingOrchestrator(FieldReferenceService(), RuntimeContextBuilder())
        o.start(_make_profile(), started_at_s=1000.0)
        for i in range(20):
            o.observe(_valid_snap(2000.0 + i * 0.1), observed_at_s=1000.0 + i * 0.26)
        o.finalize(completed_at_s=1005.0)
        assert o._svc.reference.is_frozen is True

    def test_return_contains_origin(self):
        o = RuntimeBindingOrchestrator(FieldReferenceService(), RuntimeContextBuilder())
        o.start(_make_profile(), started_at_s=1000.0)
        for i in range(20):
            o.observe(_valid_snap(2000.0 + i * 0.1), observed_at_s=1000.0 + i * 0.26)
        r = o.finalize(completed_at_s=1005.0)
        assert r.get("origin_lat") is not None
        assert r.get("origin_lon") is not None
        assert r.get("baseline_m") is not None

    def test_rollback_preserves_previous_state(self):
        o = RuntimeBindingOrchestrator(FieldReferenceService(), RuntimeContextBuilder())
        o.start(_make_profile(), started_at_s=1000.0)
        for i in range(20):
            o.observe(_valid_snap(2000.0 + i * 0.1), observed_at_s=1000.0 + i * 0.26)
        ref = o._svc.reference
        ref.is_confirmed = True
        ref.freeze()
        o.finalize(completed_at_s=1005.0)
        # Service should be restored (unfrozen/unconfirmed from rollback)
        # The frozen ref should have been restored by snapshot
        assert ref.is_frozen is True  # frozen ref was snapshot before apply

    def test_status_shows_profile_name(self):
        o = RuntimeBindingOrchestrator(FieldReferenceService(), RuntimeContextBuilder())
        o.start(_make_profile(), started_at_s=1000.0)
        st = o.status(now_s=1000.0)
        assert "profile_name" in st

    def test_start_frozen_reference(self):
        o = RuntimeBindingOrchestrator(FieldReferenceService(), RuntimeContextBuilder())
        o._svc.reference.is_confirmed = True
        o._svc.reference.freeze()
        r = o.start(_make_profile(), started_at_s=1000.0)
        assert r["ok"] is False
        assert "frozen" in r.get("error", "").lower()
