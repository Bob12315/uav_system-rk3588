"""Tests for runtime binding orchestrator (step 5B.2)."""

import copy
import threading
from dataclasses import dataclass
from unittest.mock import Mock

import pytest

from app.field_profile import parse_field_profile, validate_field_profile
from app.field_reference import FieldReference
from app.field_reference_service import FieldReferenceService
from app.runtime_binding_orchestrator import RuntimeBindingOrchestrator, _synced
from app.runtime_context import RuntimeContextBuilder
from app.field_reference_controller import FieldReferenceController
from app.system_runner import SystemRunner


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


# =============================================================================
# Real Controller lifecycle (5B.2.3)
# =============================================================================


def _controller_with_profile(monkeypatch):
    svc = FieldReferenceService()
    builder = RuntimeContextBuilder()
    controller = FieldReferenceController(svc, builder, lambda: {})
    profile = _make_profile()
    monkeypatch.setattr(
        controller, "_load_profile", lambda profile_id: (profile, [])
    )
    return controller, svc, builder


class TestControllerRuntimeLifecycle:
    def test_start_observe_finalize_status_end_to_end(self, monkeypatch):
        controller, svc, builder = _controller_with_profile(monkeypatch)
        started = controller.start_runtime_profile_sampling(
            "test_orch", started_at_s=1000.0
        )
        assert started["state"] == "sampling"
        for i in range(20):
            observed = controller.observe_runtime_profile_sampling(
                _valid_snap(2000.0 + i * 0.1),
                observed_at_s=1000.0 + i * 0.25,
            )
            assert observed["observed"] is True
        finalized = controller.finalize_runtime_profile_binding(
            completed_at_s=1005.0
        )
        assert finalized["state"] == "applied"
        assert finalized["geometry"]["home"]["name"] == "HOME"
        status = controller.status()["field_reference"]
        assert svc.reference.is_frozen is True
        assert svc.reference.is_ready_for_field_to_gps() is True
        assert svc.reference.is_ready_for_field_to_local() is False
        assert builder.field_gps_transform_ready() is True
        assert builder.field_transform_ready() is False
        assert status["synced_to_runtime"] is True
        assert status["active_source"] == "runtime_origin_forward_marker"

    def test_cancel_calls_real_orchestrator(self, monkeypatch):
        controller, _, _ = _controller_with_profile(monkeypatch)
        controller.start_runtime_profile_sampling("test_orch", started_at_s=1.0)
        result = controller.cancel_runtime_profile_sampling()
        assert result == {"ok": True, "state": "idle"}
        assert controller._runtime_binding.state == "idle"

    def test_reset_cancels_and_clears_both_owners(self, monkeypatch):
        controller, svc, builder = _controller_with_profile(monkeypatch)
        controller.start_runtime_profile_sampling("test_orch", started_at_s=1.0)
        svc.reference.origin_lat = 34.0
        builder.field_origin_lat = 34.0
        result = controller.reset()
        assert result["ok"] is True
        assert controller._runtime_binding.state == "idle"
        assert svc.reference.origin_lat is None
        assert builder.field_origin_lat is None

    def test_missing_profile_rejected(self, monkeypatch):
        controller, _, _ = _controller_with_profile(monkeypatch)
        monkeypatch.setattr(
            controller,
            "_load_profile",
            lambda profile_id: (None, [f"profile not found: {profile_id}"]),
        )
        result = controller.start_runtime_profile_sampling(
            "missing", started_at_s=1.0
        )
        assert result["ok"] is False
        assert "not found" in result["error"]

    def test_schema_v2_explicitly_rejected(self, monkeypatch):
        controller, _, _ = _controller_with_profile(monkeypatch)
        profile = copy.deepcopy(_make_profile())
        profile.schema_version = 2
        monkeypatch.setattr(
            controller, "_load_profile", lambda profile_id: (profile, [])
        )
        result = controller.start_runtime_profile_sampling(
            "old", started_at_s=1.0
        )
        assert result["ok"] is False
        assert "schema v2" in result["error"]

    def test_frozen_reference_rejected(self, monkeypatch):
        controller, svc, _ = _controller_with_profile(monkeypatch)
        svc.reference.is_confirmed = True
        svc.reference.freeze()
        result = controller.start_runtime_profile_sampling(
            "test_orch", started_at_s=1.0
        )
        assert result["ok"] is False
        assert "frozen" in result["error"]


# =============================================================================
# Transaction exceptions, returned failures, retry and rollback
# =============================================================================


def _ready_orchestrator():
    orchestrator = RuntimeBindingOrchestrator(
        FieldReferenceService(), RuntimeContextBuilder()
    )
    orchestrator.start(_make_profile(), started_at_s=1000.0)
    for i in range(20):
        orchestrator.observe(
            _valid_snap(2000.0 + i * 0.1),
            observed_at_s=1000.0 + i * 0.25,
        )
    return orchestrator


def _applied_orchestrator():
    orchestrator = _ready_orchestrator()
    result = orchestrator.finalize(completed_at_s=1005.0)
    assert result["state"] == "applied"
    return orchestrator, result


@pytest.mark.parametrize("failure_stage", ["service", "builder", "freeze"])
def test_returned_transaction_failure_restores_both_owners(
    monkeypatch, failure_stage
):
    orchestrator = _ready_orchestrator()
    service_before = orchestrator._svc.snapshot()
    builder_before = orchestrator._builder.snapshot_field_reference_state()
    if failure_stage == "service":
        monkeypatch.setattr(
            orchestrator._svc,
            "apply_runtime_binding",
            lambda *args, **kwargs: {"ok": False, "error": "injected"},
        )
    elif failure_stage == "builder":
        monkeypatch.setattr(
            orchestrator._builder,
            "confirm_runtime_gps_reference",
            lambda *args, **kwargs: False,
        )
    else:
        monkeypatch.setattr(
            orchestrator._svc,
            "freeze",
            lambda: {"ok": False, "error": "injected freeze"},
        )
    result = orchestrator.finalize(completed_at_s=1005.0)
    assert result["state"] == "apply_failed"
    assert result["rollback_ok"] is True
    assert orchestrator._candidate is not None
    assert orchestrator._svc.snapshot() == service_before
    assert orchestrator._builder.snapshot_field_reference_state() == builder_before


@pytest.mark.parametrize(
    "failure_stage", ["service_apply", "builder_apply", "status", "freeze"]
)
def test_transaction_exceptions_do_not_escape(monkeypatch, failure_stage):
    orchestrator = _ready_orchestrator()
    if failure_stage == "service_apply":
        monkeypatch.setattr(
            orchestrator._svc,
            "apply_runtime_binding",
            Mock(side_effect=RuntimeError("service boom")),
        )
    elif failure_stage == "builder_apply":
        monkeypatch.setattr(
            orchestrator._builder,
            "confirm_runtime_gps_reference",
            Mock(side_effect=RuntimeError("builder boom")),
        )
    elif failure_stage == "status":
        monkeypatch.setattr(
            orchestrator._svc,
            "status",
            Mock(side_effect=RuntimeError("status boom")),
        )
    else:
        monkeypatch.setattr(
            orchestrator._svc,
            "freeze",
            Mock(side_effect=RuntimeError("freeze boom")),
        )
    result = orchestrator.finalize(completed_at_s=1005.0)
    assert result["ok"] is False
    assert result["state"] == "apply_failed"
    assert result["rollback_ok"] is True


def test_rollback_reports_both_restore_failures(monkeypatch):
    orchestrator = _ready_orchestrator()
    monkeypatch.setattr(
        orchestrator._svc,
        "apply_runtime_binding",
        lambda *args, **kwargs: {"ok": False, "error": "injected"},
    )
    monkeypatch.setattr(
        orchestrator._svc,
        "restore",
        Mock(side_effect=RuntimeError("restore boom")),
    )
    monkeypatch.setattr(
        orchestrator._builder,
        "restore_field_reference_state",
        lambda snapshot: False,
    )
    result = orchestrator.finalize(completed_at_s=1005.0)
    assert result["rollback_ok"] is False


def test_apply_failure_retries_same_candidate_without_refinalize(monkeypatch):
    orchestrator = _ready_orchestrator()
    real_apply = orchestrator._svc.apply_runtime_binding
    calls = {"apply": 0, "finalize": 0}
    real_finalize = orchestrator._sampler.finalize

    def counted_finalize(*args, **kwargs):
        calls["finalize"] += 1
        return real_finalize(*args, **kwargs)

    def fail_once(*args, **kwargs):
        calls["apply"] += 1
        if calls["apply"] == 1:
            return {"ok": False, "error": "first apply fails"}
        return real_apply(*args, **kwargs)

    monkeypatch.setattr(orchestrator._sampler, "finalize", counted_finalize)
    monkeypatch.setattr(orchestrator._svc, "apply_runtime_binding", fail_once)
    first = orchestrator.finalize(completed_at_s=1005.0)
    retained = orchestrator._candidate
    second = orchestrator.finalize(completed_at_s=1006.0)
    assert first["state"] == "apply_failed"
    assert second["state"] == "applied"
    assert orchestrator._candidate is retained
    assert calls == {"apply": 2, "finalize": 1}


def test_applied_finalize_has_no_transaction_side_effects(monkeypatch):
    orchestrator = _ready_orchestrator()
    first = orchestrator.finalize(completed_at_s=1005.0)
    monkeypatch.setattr(
        orchestrator._svc,
        "apply_runtime_binding",
        Mock(side_effect=AssertionError("must not apply twice")),
    )
    monkeypatch.setattr(
        orchestrator._builder,
        "confirm_runtime_gps_reference",
        Mock(side_effect=AssertionError("must not sync twice")),
    )
    monkeypatch.setattr(
        orchestrator._svc,
        "freeze",
        Mock(side_effect=AssertionError("must not freeze twice")),
    )
    assert orchestrator.finalize(completed_at_s=1006.0) == first


def test_applied_cancel_preserves_complete_successful_state():
    orchestrator, successful = _applied_orchestrator()
    candidate = orchestrator._candidate
    service_snapshot = orchestrator._svc.snapshot()
    builder_snapshot = orchestrator._builder.snapshot_field_reference_state()

    cancelled = orchestrator.cancel()

    assert cancelled == {
        "ok": False,
        "state": "applied",
        "error": (
            "runtime binding is already applied; use field reference reset"
        ),
    }
    assert orchestrator._candidate is candidate
    assert orchestrator._svc.snapshot() == service_snapshot
    assert orchestrator._builder.snapshot_field_reference_state() == builder_snapshot
    assert orchestrator.synced_to_runtime(require_frozen=True) is True
    assert orchestrator.finalize(completed_at_s=1006.0) == successful


def test_applied_start_does_not_overwrite_successful_result():
    orchestrator, successful = _applied_orchestrator()
    candidate = orchestrator._candidate
    last_error = orchestrator._last_error

    restarted = orchestrator.start(_make_profile(), started_at_s=2000.0)

    assert restarted["ok"] is False
    assert restarted["state"] == "applied"
    assert orchestrator._candidate is candidate
    assert orchestrator._last_error is last_error
    assert orchestrator.finalize(completed_at_s=2001.0) == successful


def test_applied_invalid_repeated_finalize_returns_first_success():
    orchestrator, successful = _applied_orchestrator()
    stored = orchestrator._last_result
    assert orchestrator.finalize(completed_at_s=float("nan")) == successful
    assert orchestrator._last_result is stored


def test_applied_observe_is_noop_even_with_invalid_time():
    orchestrator, successful = _applied_orchestrator()
    candidate = orchestrator._candidate
    stored = orchestrator._last_result
    observed = orchestrator.observe({}, observed_at_s=float("nan"))
    assert observed == {"ok": True, "observed": False, "state": "applied"}
    assert orchestrator._candidate is candidate
    assert orchestrator._last_result is stored
    assert orchestrator.finalize(completed_at_s=1006.0) == successful


def test_cancel_then_late_observe_cannot_restore_sampling_state():
    orchestrator = _ready_orchestrator()
    assert orchestrator.cancel() == {"ok": True, "state": "idle"}
    observed = orchestrator.observe({}, observed_at_s=float("nan"))
    assert observed == {"ok": True, "observed": False, "state": "idle"}
    assert orchestrator.state == "idle"
    assert orchestrator._sampler is None


def test_controller_reset_clears_applied_runtime_binding(monkeypatch):
    controller, service, builder = _controller_with_profile(monkeypatch)
    controller.start_runtime_profile_sampling("test_orch", started_at_s=1000.0)
    for i in range(20):
        controller.observe_runtime_profile_sampling(
            _valid_snap(2000.0 + i * 0.1),
            observed_at_s=1000.0 + i * 0.25,
        )
    applied = controller.finalize_runtime_profile_binding(completed_at_s=1005.0)
    assert applied["state"] == "applied"

    reset = controller.reset()
    status = controller.status()["field_reference"]

    assert reset["ok"] is True
    assert controller._runtime_binding.state == "idle"
    assert controller._runtime_binding._candidate is None
    assert service.reference.is_confirmed is False
    assert service.reference.is_frozen is False
    assert builder.field_gps_transform_ready() is False
    assert builder.field_transform_ready() is False
    assert status["active_source"] == "none"


# =============================================================================
# Full synchronization tamper checks
# =============================================================================


@pytest.mark.parametrize(
    ("owner", "field", "bad_value"),
    [
        ("service", "heading_source", "bad"),
        ("service", "forward_marker_lat", 0.0),
        ("service", "field_heading_yaw_rad", 0.5),
        ("service", "profile_id", "bad"),
        ("service", "is_ready_for_field_to_local", True),
        ("builder", "field_forward_marker_lat", 0.0),
        ("builder", "field_baseline_m", 1.0),
        ("builder", "field_runtime_profile_id", "bad"),
        ("builder", "field_gps_rejected_sample_count", 1),
        ("builder", "field_gps_duplicate_sample_count", 1),
        ("builder", "field_gps_sample_duration_s", 4.0),
        ("builder", "field_gps_horizontal_spread_m", 1.0),
        ("builder", "field_gps_fix_type", 4),
        ("builder", "field_gps_satellites", 11),
        ("builder", "field_gps_eph", 2.0),
        ("builder", "field_gps_epv", 2.0),
    ],
)
def test_synced_rejects_each_tampered_runtime_field(owner, field, bad_value):
    orchestrator = _ready_orchestrator()
    result = orchestrator.finalize(completed_at_s=1005.0)
    assert result["ok"] is True
    candidate = orchestrator._candidate
    status = orchestrator._svc.status()
    if owner == "service":
        status[field] = bad_value
    else:
        setattr(orchestrator._builder, field, bad_value)
    assert _synced(
        candidate, status, orchestrator._builder, require_frozen=True
    ) is False


# =============================================================================
# SystemRunner sampling bridge
# =============================================================================


@dataclass
class _DroneDataclass:
    lat: float
    lon: float


def _runner_sampling_spy():
    runner = SystemRunner.__new__(SystemRunner)
    runner.logger = Mock()
    runner.action_runtime_lock = threading.RLock()
    runner.field_reference_controller = Mock()
    return runner


class _LockSpy:
    def __init__(self):
        self.held = False
        self.enter_count = 0

    def __enter__(self):
        assert self.held is False
        self.held = True
        self.enter_count += 1
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.held = False
        return False


def test_system_runner_preserves_mapping_snapshot():
    runner = _runner_sampling_spy()
    snapshot = {"lat": 34.0, "nested": {"valid": True}}
    runner._observe_runtime_field_sampling(snapshot, now_s=10.0)
    passed = runner.field_reference_controller.observe_runtime_profile_sampling.call_args.args[0]
    assert passed == snapshot
    assert passed is not snapshot


def test_system_runner_converts_dataclass_snapshot():
    runner = _runner_sampling_spy()
    runner._observe_runtime_field_sampling(
        _DroneDataclass(lat=34.0, lon=108.0), now_s=10.0
    )
    runner.field_reference_controller.observe_runtime_profile_sampling.assert_called_once_with(
        {"lat": 34.0, "lon": 108.0}, observed_at_s=10.0
    )


def test_system_runner_isolates_controller_observe_exception():
    runner = _runner_sampling_spy()
    runner.field_reference_controller.observe_runtime_profile_sampling.side_effect = RuntimeError("boom")
    runner._observe_runtime_field_sampling({}, now_s=10.0)
    runner.logger.warning.assert_called_once()


def test_system_runner_observe_holds_action_runtime_lock():
    runner = _runner_sampling_spy()
    lock = _LockSpy()
    runner.action_runtime_lock = lock

    def assert_locked(*args, **kwargs):
        assert lock.held is True
        return {"ok": True}

    runner.field_reference_controller.observe_runtime_profile_sampling.side_effect = (
        assert_locked
    )
    runner._observe_runtime_field_sampling({}, now_s=10.0)
    assert lock.enter_count == 1
    assert lock.held is False


@pytest.mark.parametrize(
    ("runner_method", "controller_method"),
    [
        ("field_reference_status", "status"),
        ("field_reference_reset", "reset"),
        ("field_reference_freeze", "freeze"),
    ],
)
def test_system_runner_field_reference_handlers_hold_action_runtime_lock(
    runner_method, controller_method
):
    runner = _runner_sampling_spy()
    lock = _LockSpy()
    runner.action_runtime_lock = lock

    def assert_locked():
        assert lock.held is True
        return {"ok": True}

    getattr(runner.field_reference_controller, controller_method).side_effect = (
        assert_locked
    )
    assert getattr(runner, runner_method)() == {"ok": True}
    assert lock.enter_count == 1
    assert lock.held is False


def test_system_runner_loop_source_observes_immediately_after_drone_read():
    import inspect

    source = inspect.getsource(SystemRunner._action_lab_only_loop)
    read_at = source.index("drone = self.services.get_drone_state()")
    observe_at = source.index("self._observe_runtime_field_sampling", read_at)
    gimbal_at = source.index("gimbal = self.services.get_gimbal_state()", read_at)
    assert read_at < observe_at < gimbal_at


@pytest.mark.parametrize(
    ("wrapper", "controller_method"),
    [
        ("field_profile_runtime_sampling_start", "start_runtime_profile_sampling"),
        ("field_profile_runtime_sampling_finalize", "finalize_runtime_profile_binding"),
        ("field_profile_runtime_sampling_cancel", "cancel_runtime_profile_sampling"),
    ],
)
def test_system_runner_runtime_wrappers_use_controller_and_lock(
    monkeypatch, wrapper, controller_method
):
    runner = SystemRunner.__new__(SystemRunner)
    runner.action_runtime_lock = threading.RLock()
    runner.field_reference_controller = Mock()
    getattr(runner.field_reference_controller, controller_method).return_value = {"ok": True}
    monkeypatch.setattr("app.system_runner.time.time", lambda: 123.0)
    args = ("test_orch",) if wrapper.endswith("start") else ()
    assert getattr(runner, wrapper)(*args) == {"ok": True}
    getattr(runner.field_reference_controller, controller_method).assert_called_once()
