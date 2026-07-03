"""Tests for FieldReference ↔ RuntimeContext parity and sync checks."""
from __future__ import annotations

import pytest

from app.field_profile import (
    AnchorPoint,
    BindingPolicy,
    CenterlinePoint,
    FieldGeometry,
    FieldProfile,
    GpsQualityThresholds,
)
from app.field_profile_service import FieldProfileService
from app.field_reference_controller import FieldReferenceController
from app.field_reference_service import FieldReferenceService
from app.runtime_context import RuntimeContextBuilder


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_profile():
    """Build a minimal valid centerline profile with 4 north-aligned points."""
    cl = [
        CenterlinePoint("CL_1", 34.000075, 108.0),
        CenterlinePoint("CL_2", 34.000150, 108.0),
        CenterlinePoint("CL_3", 34.000225, 108.0),
        CenterlinePoint("CL_4", 34.000300, 108.0),
    ]
    return FieldProfile(
        schema_version=2,
        profile_id="test_parity",
        name="Test Parity Profile",
        coordinate_convention={
            "field_x_positive": "right",
            "field_y_positive": "forward",
            "altitude_positive": "up",
        },
        anchor=AnchorPoint("a", 34.0, 108.0),
        centerline_points=cl,
        gps_quality=GpsQualityThresholds(),
        field_geometry=FieldGeometry(),
        binding_policy=BindingPolicy(),
    )


def _bind_and_apply(svc, builder, profile, local_n=10.0, local_e=20.0, local_z=-1.0):
    """Run bind → apply → sync to RuntimeContext.  Returns the BindResult."""
    br = FieldProfileService.takeoff_anchor_centerline(
        profile=profile,
        current_lat=profile.anchor.lat,
        current_lon=profile.anchor.lon,
        current_local_n_m=local_n,
        current_local_e_m=local_e,
        current_local_z_m=local_z,
        gps_fix_type=3,
        satellites_visible=12,
        gps_eph=1.0,
        gps_epv=1.0,
        timestamp=1000.0,
    )
    assert br.ok, f"bind failed: {br.errors}"

    applied = svc.apply_profile_binding(
        bind_result=br,
        profile_id=profile.profile_id,
        profile_name=profile.name,
        anchor_lat=profile.anchor.lat,
        anchor_lon=profile.anchor.lon,
        timestamp=1000.0,
    )
    assert applied["ok"], f"apply failed: {applied.get('error')}"

    ok = builder.confirm_field_reference(
        field_heading_yaw_rad=svc.reference.field_heading_yaw_rad,
        origin_local_x=svc.reference.origin_local_n_m,
        origin_local_y=svc.reference.origin_local_e_m,
        origin_local_z=svc.reference.origin_local_z_m,
        source=f"field_profile:{profile.profile_id}",
        timestamp=1000.0,
    )
    assert ok, "sync to RuntimeContext failed"
    return br


# ---------------------------------------------------------------------------
# synced_to_runtime
# ---------------------------------------------------------------------------


def test_synced_after_bind_and_sync():
    """After bind+apply+sync, is_field_reference_synced returns True."""
    svc = FieldReferenceService()
    builder = RuntimeContextBuilder()
    profile = _make_profile()
    _bind_and_apply(svc, builder, profile)

    assert FieldReferenceController._is_field_reference_synced(
        svc.status(), builder
    ) is True


def test_not_synced_when_heading_mismatch():
    """Heading mismatch → synced False."""
    svc = FieldReferenceService()
    builder = RuntimeContextBuilder()
    profile = _make_profile()
    _bind_and_apply(svc, builder, profile)

    # Mutate RuntimeContext heading
    builder.field_heading_yaw_rad += 0.1

    assert FieldReferenceController._is_field_reference_synced(
        svc.status(), builder
    ) is False


def test_not_synced_when_origin_n_mismatch():
    """origin_local_n mismatch → synced False."""
    svc = FieldReferenceService()
    builder = RuntimeContextBuilder()
    profile = _make_profile()
    _bind_and_apply(svc, builder, profile)

    builder.field_origin_local_x += 0.01

    assert FieldReferenceController._is_field_reference_synced(
        svc.status(), builder
    ) is False


def test_not_synced_when_origin_e_mismatch():
    """origin_local_e mismatch → synced False."""
    svc = FieldReferenceService()
    builder = RuntimeContextBuilder()
    profile = _make_profile()
    _bind_and_apply(svc, builder, profile)

    builder.field_origin_local_y += 0.01

    assert FieldReferenceController._is_field_reference_synced(
        svc.status(), builder
    ) is False


def test_not_synced_when_origin_z_mismatch():
    """origin_local_z mismatch → synced False."""
    svc = FieldReferenceService()
    builder = RuntimeContextBuilder()
    profile = _make_profile()
    _bind_and_apply(svc, builder, profile)

    builder.field_origin_local_z = (builder.field_origin_local_z or 0.0) + 0.01

    assert FieldReferenceController._is_field_reference_synced(
        svc.status(), builder
    ) is False


def test_not_synced_when_unconfirmed():
    """Unconfirmed reference → synced False regardless of builder state."""
    svc = FieldReferenceService()
    builder = RuntimeContextBuilder()
    # Don't bind — leave reference unconfirmed
    assert FieldReferenceController._is_field_reference_synced(
        svc.status(), builder
    ) is False


def test_not_synced_when_builder_unconfirmed():
    """Builder not confirmed → synced False even if reference is confirmed."""
    svc = FieldReferenceService()
    builder = RuntimeContextBuilder()
    profile = _make_profile()
    br = FieldProfileService.takeoff_anchor_centerline(
        profile=profile,
        current_lat=profile.anchor.lat,
        current_lon=profile.anchor.lon,
        current_local_n_m=10.0,
        current_local_e_m=20.0,
        current_local_z_m=-1.0,
        gps_fix_type=3,
        satellites_visible=12,
        gps_eph=1.0,
        gps_epv=1.0,
        timestamp=1000.0,
    )
    svc.apply_profile_binding(
        bind_result=br,
        profile_id=profile.profile_id,
        profile_name=profile.name,
        anchor_lat=profile.anchor.lat,
        anchor_lon=profile.anchor.lon,
        timestamp=1000.0,
    )
    # Do NOT call builder.confirm_field_reference()

    assert FieldReferenceController._is_field_reference_synced(
        svc.status(), builder
    ) is False


# ---------------------------------------------------------------------------
# active_source
# ---------------------------------------------------------------------------


def test_active_source_is_centerline_when_confirmed():
    """Controller status shows active_source='field_profile_centerline' when confirmed."""
    svc = FieldReferenceService()
    builder = RuntimeContextBuilder()
    profile = _make_profile()
    _bind_and_apply(svc, builder, profile)

    controller = FieldReferenceController(
        field_reference_service=svc,
        runtime_context_builder=builder,
        get_drone_snapshot=lambda: {},
    )
    status = controller.status()
    assert status["field_reference"]["active_source"] == "field_profile_centerline"


def test_active_source_is_none_when_reset():
    """Controller status shows active_source='none' after reset."""
    svc = FieldReferenceService()
    builder = RuntimeContextBuilder()
    profile = _make_profile()
    _bind_and_apply(svc, builder, profile)

    svc.reset()
    builder.clear_field_heading()

    controller = FieldReferenceController(
        field_reference_service=svc,
        runtime_context_builder=builder,
        get_drone_snapshot=lambda: {},
    )
    status = controller.status()
    assert status["field_reference"]["active_source"] == "none"


def test_active_source_never_legacy():
    """active_source must never be 'legacy_field_heading'."""
    svc = FieldReferenceService()
    builder = RuntimeContextBuilder()

    controller = FieldReferenceController(
        field_reference_service=svc,
        runtime_context_builder=builder,
        get_drone_snapshot=lambda: {},
    )
    status = controller.status()
    # Even if builder has some legacy state, active_source must not be the legacy value
    assert status["field_reference"]["active_source"] != "legacy_field_heading"

    # Set builder state without going through FieldReferenceService
    builder.field_heading_confirmed = True
    builder.field_origin_confirmed = True
    builder.field_heading_yaw_rad = 0.5
    builder.field_origin_local_x = 1.0
    builder.field_origin_local_y = 2.0

    status2 = controller.status()
    # Still must not be legacy — the controller checks is_confirmed on the reference
    assert status2["field_reference"]["active_source"] != "legacy_field_heading"
