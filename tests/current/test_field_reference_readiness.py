"""Tests for FieldReference GPS/LOCAL readiness split (step 4)."""

import math

import pytest

from app.coordinate_transform import (
    field_to_gps,
    field_to_local_ned,
    local_ned_to_field,
)
from app.field_reference import (
    FieldReference,
    FieldReferenceError,
    HeadingSource,
    OriginSource,
)
from app.field_reference_service import FieldReferenceService


# =========================================================================
# A. Enum values
# =========================================================================


class TestEnumValues:
    def test_runtime_origin_source_value(self):
        assert OriginSource.RUNTIME_CURRENT_GPS.value == "runtime_current_gps"

    def test_runtime_heading_source_value(self):
        assert HeadingSource.RUNTIME_FORWARD_MARKER.value == "runtime_forward_marker"

    def test_existing_enums_preserved(self):
        assert OriginSource.LOCAL_POSITION.value == "local_position"
        assert OriginSource.PROFILE_CENTERLINE.value == "profile_centerline"
        assert HeadingSource.PROFILE_GPS_CENTERLINE.value == "profile_gps_centerline"


# =========================================================================
# B. Unconfirmed
# =========================================================================


class TestUnconfirmed:
    def test_unconfirmed_reference_is_not_ready_for_any_transform(self):
        ref = FieldReference(is_confirmed=False)
        assert ref.is_ready() is False
        assert ref.is_ready_for_field_to_local() is False
        assert ref.is_ready_for_field_to_gps() is False

    def test_unconfirmed_even_with_data_still_false(self):
        ref = FieldReference(
            is_confirmed=False,
            origin_lat=34.0,
            origin_lon=108.0,
            origin_local_n_m=10.0,
            origin_local_e_m=20.0,
            field_heading_yaw_rad=0.5,
        )
        assert ref.is_ready_for_field_to_local() is False
        assert ref.is_ready_for_field_to_gps() is False


# =========================================================================
# C. LOCAL-only
# =========================================================================


class TestLocalOnly:
    def test_local_only_reference_is_ready_only_for_local_transform(self):
        ref = FieldReference(
            is_confirmed=True,
            origin_local_n_m=10.0,
            origin_local_e_m=20.0,
            field_heading_yaw_rad=0.5,
        )
        assert ref.is_ready_for_field_to_local() is True
        assert ref.is_ready_for_field_to_gps() is False
        assert ref.is_ready() is True


# =========================================================================
# D. GPS-only
# =========================================================================


class TestGpsOnly:
    def test_gps_only_reference_is_ready_only_for_gps_transform(self):
        ref = FieldReference(
            is_confirmed=True,
            origin_source=OriginSource.RUNTIME_CURRENT_GPS.value,
            heading_source=HeadingSource.RUNTIME_FORWARD_MARKER.value,
            origin_lat=34.103649,
            origin_lon=108.642674,
            forward_marker_lat=34.104189,
            forward_marker_lon=108.642674,
            field_heading_yaw_rad=0.0,
        )
        assert ref.is_ready_for_field_to_gps() is True
        assert ref.is_ready_for_field_to_local() is False
        assert ref.is_ready() is False


# =========================================================================
# E. Full (both LOCAL + GPS)
# =========================================================================


class TestFullReference:
    def test_full_reference_is_ready_for_both_transform_families(self):
        ref = FieldReference(
            is_confirmed=True,
            origin_lat=34.103649,
            origin_lon=108.642674,
            origin_local_n_m=10.0,
            origin_local_e_m=20.0,
            field_heading_yaw_rad=0.5,
        )
        assert ref.is_ready_for_field_to_local() is True
        assert ref.is_ready_for_field_to_gps() is True
        assert ref.is_ready() is True


# =========================================================================
# F. Frozen
# =========================================================================


class TestFrozen:
    def test_gps_readiness_does_not_require_frozen(self):
        ref = FieldReference(
            is_confirmed=True,
            origin_lat=34.103649,
            origin_lon=108.642674,
            field_heading_yaw_rad=0.0,
        )
        assert ref.is_ready_for_field_to_gps() is True

    def test_freeze_preserves_existing_readiness(self):
        ref = FieldReference(
            is_confirmed=True,
            origin_lat=34.103649,
            origin_lon=108.642674,
            field_heading_yaw_rad=0.0,
        )
        assert ref.is_ready_for_field_to_gps() is True
        ref.freeze()
        assert ref.is_ready_for_field_to_gps() is True


# =========================================================================
# G. Reset
# =========================================================================


class TestReset:
    def test_reset_clears_all_readiness(self):
        ref = FieldReference(
            is_confirmed=True,
            origin_lat=34.103649,
            origin_lon=108.642674,
            origin_local_n_m=10.0,
            origin_local_e_m=20.0,
            field_heading_yaw_rad=0.5,
        )
        assert ref.is_ready_for_field_to_local() is True
        assert ref.is_ready_for_field_to_gps() is True

        ref.reset()

        assert ref.is_ready() is False
        assert ref.is_ready_for_field_to_local() is False
        assert ref.is_ready_for_field_to_gps() is False
        assert ref.origin_lat is None
        assert ref.origin_lon is None
        assert ref.origin_local_n_m is None
        assert ref.origin_local_e_m is None
        assert ref.field_heading_yaw_rad is None
        assert ref.is_confirmed is False
        assert ref.is_frozen is False


# =========================================================================
# H. LOCAL invalid values
# =========================================================================


@pytest.mark.parametrize("bad_field, bad_value", [
    ("origin_local_n_m", float("nan")),
    ("origin_local_e_m", float("inf")),
    ("field_heading_yaw_rad", float("nan")),
])
class TestLocalInvalidValues:
    def test_local_invalid_makes_not_ready(self, bad_field, bad_value):
        values = {
            "is_confirmed": True,
            "origin_local_n_m": 10.0,
            "origin_local_e_m": 20.0,
            "field_heading_yaw_rad": 0.5,
        }
        values[bad_field] = bad_value
        ref = FieldReference(**values)
        assert ref.is_ready_for_field_to_local() is False
        assert ref.is_ready() is False


# =========================================================================
# I. GPS invalid values
# =========================================================================


@pytest.mark.parametrize("bad_field, bad_value", [
    ("origin_lat", None),
    ("origin_lat", True),
    ("origin_lat", "bad"),
    ("origin_lat", float("nan")),
    ("origin_lat", 91),
    ("origin_lat", 90.0),
    ("origin_lon", None),
    ("origin_lon", True),
    ("origin_lon", float("inf")),
    ("origin_lon", 181),
    ("field_heading_yaw_rad", None),
    ("field_heading_yaw_rad", True),
    ("field_heading_yaw_rad", float("nan")),
])
class TestGpsInvalidValues:
    def test_gps_invalid_makes_not_ready(self, bad_field, bad_value):
        values = {
            "is_confirmed": True,
            "origin_lat": 34.0,
            "origin_lon": 108.0,
            "field_heading_yaw_rad": 0.5,
        }
        values[bad_field] = bad_value
        ref = FieldReference(**values)
        assert ref.is_ready_for_field_to_gps() is False


# =========================================================================
# J. Forward marker not required
# =========================================================================


class TestForwardMarkerNotRequired:
    def test_gps_readiness_does_not_require_forward_marker_after_heading_exists(self):
        ref = FieldReference(
            is_confirmed=True,
            origin_lat=34.103649,
            origin_lon=108.642674,
            field_heading_yaw_rad=0.0,
            forward_marker_lat=None,
            forward_marker_lon=None,
        )
        assert ref.is_ready_for_field_to_gps() is True


# =========================================================================
# K. Source labels not required
# =========================================================================


class TestSourceNotRequired:
    def test_gps_readiness_does_not_require_source_labels(self):
        ref = FieldReference(
            is_confirmed=True,
            origin_lat=34.103649,
            origin_lon=108.642674,
            field_heading_yaw_rad=0.0,
            origin_source=None,
            heading_source=None,
        )
        assert ref.is_ready_for_field_to_gps() is True


# =========================================================================
# L. GPS-only can FIELD→GPS
# =========================================================================


class TestFieldToGpsGpsOnly:
    def test_field_to_gps_accepts_confirmed_gps_only_reference(self):
        ref = FieldReference(
            is_confirmed=True,
            origin_lat=34.103649,
            origin_lon=108.642674,
            field_heading_yaw_rad=0.0,
        )
        point = field_to_gps(2.0, 30.0, 5.0, reference=ref)
        assert math.isfinite(point.lat)
        assert math.isfinite(point.lon)
        assert point.alt_m == 5


# =========================================================================
# M. GPS-only rejected by LOCAL transforms
# =========================================================================


class TestGpsOnlyRejected:
    def test_field_to_local_rejects_gps_only_reference(self):
        ref = FieldReference(
            is_confirmed=True,
            origin_lat=34.103649,
            origin_lon=108.642674,
            field_heading_yaw_rad=0.0,
        )
        with pytest.raises(FieldReferenceError):
            field_to_local_ned(1, 2, 3, reference=ref)

    def test_local_ned_to_field_rejects_gps_only_reference(self):
        ref = FieldReference(
            is_confirmed=True,
            origin_lat=34.103649,
            origin_lon=108.642674,
            field_heading_yaw_rad=0.0,
        )
        with pytest.raises(FieldReferenceError):
            local_ned_to_field(1, 2, 3, reference=ref)


# =========================================================================
# N. LOCAL-only rejected by FIELD→GPS
# =========================================================================


class TestLocalOnlyRejected:
    def test_field_to_gps_rejects_local_only_reference(self):
        ref = FieldReference(
            is_confirmed=True,
            origin_local_n_m=10.0,
            origin_local_e_m=20.0,
            field_heading_yaw_rad=0.5,
        )
        with pytest.raises(FieldReferenceError):
            field_to_gps(1, 2, 3, reference=ref)


# =========================================================================
# O. Backward-compatible LOCAL roundtrip
# =========================================================================


class TestBackwardCompat:
    def test_local_transform_still_uses_backward_compatible_is_ready_semantics(self):
        ref = FieldReference(
            is_confirmed=True,
            origin_local_n_m=10.0,
            origin_local_e_m=20.0,
            field_heading_yaw_rad=0.0,
        )
        assert ref.is_ready() is True
        # roundtrip
        local = field_to_local_ned(3, 4, 5, reference=ref)
        field = local_ned_to_field(
            local.north_m, local.east_m, -local.z_down_m, reference=ref
        )
        assert field.field_x_m == pytest.approx(3, abs=1e-9)
        assert field.field_y_m == pytest.approx(4, abs=1e-9)


# =========================================================================
# P. Service status
# =========================================================================


class TestServiceStatus:
    def test_service_status_reports_separate_readiness_for_gps_only_reference(self):
        ref = FieldReference(
            is_confirmed=True,
            origin_source=OriginSource.RUNTIME_CURRENT_GPS.value,
            heading_source=HeadingSource.RUNTIME_FORWARD_MARKER.value,
            origin_lat=34.103649,
            origin_lon=108.642674,
            field_heading_yaw_rad=0.0,
        )
        svc = FieldReferenceService(reference=ref)
        s = svc.status()
        assert s["is_ready"] is False
        assert s["is_ready_for_field_to_local"] is False
        assert s["is_ready_for_field_to_gps"] is True

    def test_service_status_reports_both_readiness_for_full_reference(self):
        ref = FieldReference(
            is_confirmed=True,
            origin_lat=34.103649,
            origin_lon=108.642674,
            origin_local_n_m=10.0,
            origin_local_e_m=20.0,
            field_heading_yaw_rad=0.5,
        )
        svc = FieldReferenceService(reference=ref)
        s = svc.status()
        assert s["is_ready"] is True
        assert s["is_ready_for_field_to_local"] is True
        assert s["is_ready_for_field_to_gps"] is True

    def test_old_status_fields_still_present(self):
        ref = FieldReference(
            is_confirmed=True,
            origin_lat=34.103649,
            origin_lon=108.642674,
            field_heading_yaw_rad=0.0,
        )
        svc = FieldReferenceService(reference=ref)
        s = svc.status()
        for key in (
            "is_confirmed", "is_frozen", "is_ready",
            "origin_source", "heading_source",
            "origin_local_n_m", "origin_local_e_m",
            "origin_lat", "origin_lon", "field_heading_yaw_rad",
        ):
            assert key in s, f"missing status key: {key}"


# =========================================================================
# Q. No runtime binding service yet
# =========================================================================


def test_step4_does_not_add_runtime_binding_service():
    src = __import__("app.field_reference_service", fromlist=["FieldReferenceService"])
    for name in ("apply_runtime_binding", "bind_runtime_origin",
                 "sample_gps", "confirm_runtime_field"):
        assert not hasattr(src, name), f"forbidden method {name} in field_reference_service"
