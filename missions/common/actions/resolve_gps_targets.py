"""ResolveGpsTargetsAction — resolve diverse target sources to GPS + LOCAL_NED.

Supports three source types:
- ``"field"``:  FIELD x/y/altitude → ``field_to_gps()`` → ``gps_to_local_ned()``
- ``"home"``:   origin GPS from context → ``gps_to_local_ned()``
- ``"vision"``: drone GPS + yaw + altitude + image ex/ey → target GPS → ``gps_to_local_ned()``

Output is saved to blackboard under ``resolved_targets`` (or the key given in
``save_as``).  Each resolved target includes GPS, LOCAL_NED, and FIELD
coordinates plus source metadata.
"""

from __future__ import annotations

import math
from typing import Any

from app.coordinate_transform import (
    EARTH_RADIUS_M,
    field_to_gps,
    gps_to_local_ned,
)
from app.field_reference import FieldReference, FieldReferenceError

from .base import ActionModule
from .result import ActionResult


# default camera parameters (same as mission templates)
DEFAULT_FOV_X_DEG = 85.0
DEFAULT_FOV_Y_DEG = 69.0
DEFAULT_IMAGE_X_SIGN = 1.0
DEFAULT_IMAGE_Y_SIGN = -1.0
# default yaw stability threshold (rad/s)
DEFAULT_MAX_YAW_RATE_RAD_S = 0.35  # ≈ 20 deg/s


class ResolveGpsTargetsAction(ActionModule):
    """Resolve target specs to GPS + LOCAL_NED and store on blackboard."""

    def __init__(self) -> None:
        self.reset()

    # ── ActionModule interface ──────────────────────────────────────────

    def start(self, params: dict[str, Any] | None = None) -> None:
        data = params or {}

        raw_targets = data.get("targets", [])
        if not isinstance(raw_targets, list):
            raise ValueError("targets must be a list")

        self.save_as = str(data.get("save_as", "resolved_targets")).strip() or "resolved_targets"
        self.key = str(data.get("key", "resolve_gps_targets"))

        # camera params (for vision source)
        camera = dict(data.get("camera") or {})
        self.fov_x_deg = float(camera.get("fov_x_deg", DEFAULT_FOV_X_DEG))
        self.fov_y_deg = float(camera.get("fov_y_deg", DEFAULT_FOV_Y_DEG))
        self.image_x_sign = float(camera.get("image_x_sign", DEFAULT_IMAGE_X_SIGN))
        self.image_y_sign = float(camera.get("image_y_sign", DEFAULT_IMAGE_Y_SIGN))

        # yaw stability
        self.max_yaw_rate_rad_s = float(
            data.get("max_yaw_rate_rad_s", DEFAULT_MAX_YAW_RATE_RAD_S)
        )
        self.yaw_stability_required = bool(data.get("yaw_stability_required", True))

        self.default_source = str(data.get("default_source", "")).strip().lower() or None

        self.target_specs: list[dict[str, Any]] = []
        for spec in raw_targets:
            if not isinstance(spec, dict):
                continue
            self.target_specs.append(dict(spec))

        self.started = True
        self.stopped = False
        self._done = False
        self._last_detail: dict[str, Any] = {}

    def update(self, context: dict[str, Any] | None = None) -> ActionResult:
        if not self.started:
            return ActionResult(failed=True, reason="action_not_started")
        if self.stopped:
            return ActionResult(done=True, reason="stopped", detail=self._last_detail)
        if self._done:
            return ActionResult(
                done=True,
                reason="targets_resolved",
                detail=self._last_detail,
            )

        data = context or {}
        ref = self._build_field_reference(data)

        resolved: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        for i, spec in enumerate(self.target_specs):
            source = str(spec.get("source", self.default_source or "")).strip().lower()
            try:
                if source == "field":
                    result = self._resolve_field(spec, ref)
                elif source == "home":
                    result = self._resolve_home(spec, ref, data)
                elif source == "vision":
                    result = self._resolve_vision(spec, ref, data)
                else:
                    errors.append({
                        "index": i,
                        "source": source or "unknown",
                        "reason": f"unsupported_source: {source!r}",
                    })
                    continue

                if result is not None:
                    resolved.append(result)
                else:
                    errors.append({
                        "index": i,
                        "source": source,
                        "reason": "resolution_returned_null",
                    })
            except FieldReferenceError as exc:
                errors.append({
                    "index": i,
                    "source": source,
                    "reason": f"field_reference_error: {exc}",
                })
            except ValueError as exc:
                errors.append({
                    "index": i,
                    "source": source,
                    "reason": f"value_error: {exc}",
                })
            except Exception as exc:
                errors.append({
                    "index": i,
                    "source": source,
                    "reason": f"unexpected_error: {exc}",
                })

        self._done = True
        self._last_detail = {
            "resolved_targets": resolved,
            "gps_localized_targets": resolved,  # alias
            "resolved_count": len(resolved),
            "error_count": len(errors),
            "errors": errors,
            "key": self.key,
        }
        return ActionResult(
            done=True,
            reason="targets_resolved",
            detail=self._last_detail,
        )

    def stop(self) -> None:
        self.stopped = True

    def reset(self) -> None:
        self.started = False
        self.stopped = False
        self.target_specs = []
        self.save_as = "resolved_targets"
        self.key = "resolve_gps_targets"
        self.fov_x_deg = DEFAULT_FOV_X_DEG
        self.fov_y_deg = DEFAULT_FOV_Y_DEG
        self.image_x_sign = DEFAULT_IMAGE_X_SIGN
        self.image_y_sign = DEFAULT_IMAGE_Y_SIGN
        self.max_yaw_rate_rad_s = DEFAULT_MAX_YAW_RATE_RAD_S
        self.yaw_stability_required = True
        self._done = False
        self._last_detail = {}

    # ── per-source resolvers ────────────────────────────────────────────

    def _resolve_field(
        self,
        spec: dict[str, Any],
        ref: FieldReference,
    ) -> dict[str, Any] | None:
        """Resolve a FIELD waypoint: field→GPS→LOCAL_NED."""
        field_x_m = self._required_float(spec, "field_x_m", "x")
        field_y_m = self._required_float(spec, "field_y_m", "y")
        altitude_m = self._required_float(spec, "altitude_m")

        gps = field_to_gps(field_x_m, field_y_m, altitude_m, reference=ref)
        local = gps_to_local_ned(gps.lat, gps.lon, altitude_m, reference=ref)

        return self._build_output(
            source="field",
            lat=gps.lat,
            lon=gps.lon,
            altitude_m=altitude_m,
            local_x=local.north_m,
            local_y=local.east_m,
            z_down_m=local.z_down_m,
            field_x=field_x_m,
            field_y=field_y_m,
            class_name=spec.get("class_name", ""),
            confidence=spec.get("confidence"),
        )

    def _resolve_home(
        self,
        spec: dict[str, Any],
        ref: FieldReference,
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Resolve the home/origin position: origin GPS→LOCAL_NED."""
        origin_lat = ref.origin_lat
        origin_lon = ref.origin_lon
        if origin_lat is None or origin_lon is None:
            # try context as fallback
            origin_lat = self._float_context(context, "field_origin_lat")
            origin_lon = self._float_context(context, "field_origin_lon")
        if origin_lat is None or origin_lon is None:
            raise FieldReferenceError("home resolution requires origin GPS (origin_lat/origin_lon)")

        altitude_m = self._optional_float(spec, "altitude_m", 5.0)

        local = gps_to_local_ned(origin_lat, origin_lon, altitude_m, reference=ref)

        return self._build_output(
            source="home",
            lat=origin_lat,
            lon=origin_lon,
            altitude_m=altitude_m,
            local_x=local.north_m,
            local_y=local.east_m,
            z_down_m=local.z_down_m,
            field_x=0.0,
            field_y=0.0,
            class_name="home",
            confidence=None,
        )

    def _resolve_vision(
        self,
        spec: dict[str, Any],
        ref: FieldReference,
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Resolve a vision target: drone GPS + yaw + altitude + ex/ey → target GPS → LOCAL_NED.

        Reads drone GPS / yaw / altitude from context (drone dict or top-level keys).
        Checks yaw stability before computing.
        """
        # ── drone state ──
        drone = context.get("drone")
        if not isinstance(drone, dict):
            drone = {}

        drone_lat = self._float_context(drone, "lat")
        drone_lon = self._float_context(drone, "lon")
        if drone_lat is None or drone_lon is None:
            drone_lat = self._float_context(context, "lat")
            drone_lon = self._float_context(context, "lon")
        if drone_lat is None or drone_lon is None:
            raise ValueError("vision resolution requires drone GPS (lat/lon) in context")

        if not bool(drone.get("global_position_valid", True)):
            raise ValueError("drone global_position_valid is false")

        # altitude
        altitude_m: float | None = None
        for name in ("relative_altitude", "relative_altitude_m", "altitude", "altitude_m"):
            alt = drone.get(name)
            if alt is None:
                alt = context.get(name)
            if alt is not None:
                try:
                    altitude_m = float(alt)
                    break
                except (TypeError, ValueError):
                    continue
        if altitude_m is None:
            raise ValueError("vision resolution requires altitude in drone context")
        if altitude_m <= 0.0:
            raise ValueError("altitude must be positive for vision resolution")

        # yaw
        yaw = self._float_context(drone, "yaw")
        if yaw is None:
            yaw = self._float_context(context, "yaw")
        if yaw is None or not math.isfinite(yaw):
            raise ValueError("vision resolution requires yaw in drone context")

        # ── yaw stability check ──
        if self.yaw_stability_required:
            yaw_rate = self._float_context(drone, "yaw_rate")
            if yaw_rate is None:
                yaw_rate = self._float_context(context, "yaw_rate")
            if yaw_rate is None:
                raise ValueError(
                    "yaw_rate_unavailable: yaw_stability_required=true but yaw_rate is missing from context"
                )
            if not math.isfinite(yaw_rate):
                raise ValueError(
                    "yaw_rate_unavailable: yaw_stability_required=true but yaw_rate is non-finite"
                )
            if abs(yaw_rate) > self.max_yaw_rate_rad_s:
                raise ValueError(
                    f"yaw_rate unstable: |{yaw_rate:.3f}| > {self.max_yaw_rate_rad_s:.3f} rad/s"
                )
            yaw_rate_unavailable = False
        else:
            yaw_rate_unavailable = False

        # ── image errors ──
        # try top-level ex/ey first, then nested source.ex/source.ey
        # (from localize_detection raw_estimates format)
        ex = self._optional_float(spec, "ex")
        ey = self._optional_float(spec, "ey")
        if ex is None or ey is None:
            source_nested = spec.get("source")
            if isinstance(source_nested, dict):
                if ex is None:
                    ex = self._optional_float(source_nested, "ex")
                if ey is None:
                    ey = self._optional_float(source_nested, "ey")
        if ex is None or ey is None:
            raise ValueError("vision resolution requires ex/ey (top-level or in source.ex/source.ey)")

        # ── body-frame offsets (same math as TargetLocalization) ──
        half_fov_x = math.radians(self.fov_x_deg) / 2.0
        half_fov_y = math.radians(self.fov_y_deg) / 2.0
        angle_x = ex * half_fov_x
        angle_y = ey * half_fov_y

        body_right_m = self.image_x_sign * altitude_m * math.tan(angle_x)
        body_forward_m = self.image_y_sign * altitude_m * math.tan(angle_y)

        # ENU offsets
        d_north = body_forward_m * math.cos(yaw) - body_right_m * math.sin(yaw)
        d_east = body_forward_m * math.sin(yaw) + body_right_m * math.cos(yaw)

        # target GPS
        drone_lat_rad = math.radians(drone_lat)
        cos_lat = math.cos(drone_lat_rad)
        if abs(cos_lat) < 1e-9:
            raise ValueError("drone latitude too close to pole")

        target_lat = drone_lat + math.degrees(d_north / EARTH_RADIUS_M)
        target_lon = drone_lon + math.degrees(d_east / (EARTH_RADIUS_M * cos_lat))

        # GPS → LOCAL_NED
        local = gps_to_local_ned(target_lat, target_lon, altitude_m, reference=ref)

        result = self._build_output(
            source="vision",
            lat=target_lat,
            lon=target_lon,
            altitude_m=altitude_m,
            local_x=local.north_m,
            local_y=local.east_m,
            z_down_m=local.z_down_m,
            field_x=None,  # computed below
            field_y=None,
            class_name=spec.get("class_name", ""),
            confidence=self._optional_float(spec, "confidence"),
        )
        # add vision-specific metadata
        result["yaw_rad"] = yaw
        result["ex"] = ex
        result["ey"] = ey
        result["body_forward_m"] = body_forward_m
        result["body_right_m"] = body_right_m
        result["drone_lat"] = drone_lat
        result["drone_lon"] = drone_lon
        if yaw_rate_unavailable:
            result["yaw_rate_warning"] = "yaw_rate_unavailable_in_context"
        return result

    # ── helpers ─────────────────────────────────────────────────────────

    def _build_field_reference(self, context: dict[str, Any]) -> FieldReference:
        """Build a FieldReference from context for coordinate transforms."""
        ref = FieldReference()
        # GPS origin
        ref.origin_lat = self._float_context(context, "field_origin_lat")
        ref.origin_lon = self._float_context(context, "field_origin_lon")
        # LOCAL origin
        ref.origin_local_n_m = self._float_context(context, "field_origin_local_x")
        ref.origin_local_e_m = self._float_context(context, "field_origin_local_y")
        # heading
        ref.field_heading_yaw_rad = self._float_context(context, "field_heading_yaw_rad")
        ref.is_confirmed = True

        # validate minimum requirements
        if (
            ref.origin_lat is None
            or ref.origin_lon is None
            or ref.origin_local_n_m is None
            or ref.origin_local_e_m is None
        ):
            raise FieldReferenceError(
                "context missing field origin GPS or LOCAL_NED for GPS resolution"
            )
        return ref

    def _build_output(
        self,
        *,
        source: str,
        lat: float,
        lon: float,
        altitude_m: float,
        local_x: float,
        local_y: float,
        z_down_m: float,
        field_x: float | None = None,
        field_y: float | None = None,
        class_name: str = "",
        confidence: float | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "valid": True,
            "source": source,
            "lat": lat,
            "lon": lon,
            "altitude_m": altitude_m,
            "local_x": local_x,
            "local_y": local_y,
            "z_down_m": z_down_m,
            "class_name": class_name,
        }
        if field_x is not None:
            result["field_x"] = field_x
        if field_y is not None:
            result["field_y"] = field_y
        if confidence is not None:
            result["confidence"] = confidence
        return result

    @staticmethod
    def _required_float(spec: dict[str, Any], *names: str) -> float:
        """Get the first present key from *names* as a finite float."""
        for name in names:
            value = spec.get(name)
            if value is not None:
                try:
                    result = float(value)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(result):
                    return result
        raise ValueError(f"required float field(s) {list(names)} missing or invalid")

    @staticmethod
    def _optional_float(spec: dict[str, Any], name: str, default: float | None = None) -> float | None:
        value = spec.get(name)
        if value is None:
            return default
        try:
            result = float(value)
        except (TypeError, ValueError):
            return default
        return result if math.isfinite(result) else default

    @staticmethod
    def _float_context(context: dict[str, Any], name: str) -> float | None:
        value = context.get(name)
        if value is None:
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) else None
