"""Supported schema-v3 Field Profile model and validation."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import WGS84_POLE_COS_EPS


@dataclass(slots=True)
class GpsQualityThresholds:
    min_fix_type: int = 3
    min_satellites: int = 10
    max_eph: float = 2.5
    max_epv: float = 5.0


@dataclass(slots=True)
class ForwardMarker:
    name: str
    lat: float
    lon: float
    coordinate_system: str = "WGS84"


@dataclass(slots=True)
class FieldScanWaypoint:
    x_m: float
    y_m: float
    altitude_m: float


@dataclass(slots=True)
class DropScanConfig:
    waypoints: list[FieldScanWaypoint] = field(default_factory=list)


@dataclass(slots=True)
class RuntimeOriginSampling:
    min_samples: int = 20
    sample_window_s: float = 5.0
    max_horizontal_spread_m: float = 1.0
    estimator: str = "median"


@dataclass(slots=True)
class FieldGeometry:
    lane_half_width_m: float
    drop_center_y_m: float
    recce_center_y_m: float
    drop_area_y_min: float
    drop_area_y_max: float
    recce_area_y_min: float
    recce_area_y_max: float


@dataclass(slots=True)
class BindingPolicy:
    min_baseline_m: float = 30.0
    warn_baseline_below_m: float = 50.0


@dataclass(slots=True)
class FieldProfile:
    schema_version: int
    profile_id: str
    name: str
    coordinate_convention: dict[str, str]
    forward_marker: ForwardMarker
    drop_scan: DropScanConfig
    recon_scan: DropScanConfig | None
    gps_quality: GpsQualityThresholds
    field_geometry: FieldGeometry
    binding_policy: BindingPolicy
    runtime_origin_sampling: RuntimeOriginSampling
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FieldProfileDiagnostics:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    @property
    def ok(self) -> bool: return not self.errors


class FieldProfileValidationError(ValueError):
    def __init__(self, diagnostics: FieldProfileDiagnostics) -> None:
        self.diagnostics = diagnostics
        super().__init__("FieldProfile validation failed: " + "; ".join(diagnostics.errors))


def _number(value: object, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if positive and result <= 0: raise ValueError(f"{name} must be > 0")
    return result


def _mapping(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name)
    if not isinstance(value, dict): raise ValueError(f"{name} must be an object")
    return value


def _scan(raw: dict[str, Any], name: str, geometry: FieldGeometry, *, area_min: float, area_max: float) -> DropScanConfig:
    items = _mapping(raw, name).get("waypoints")
    if not isinstance(items, list) or len(items) != 4: raise ValueError(f"{name}.waypoints must contain exactly 4 items")
    output: list[FieldScanWaypoint] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict): raise ValueError(f"{name}.waypoints[{index}] must be an object")
        if any(key in item for key in ("lat", "lon", "local_x", "local_y")):
            raise ValueError(f"{name}.waypoints[{index}] must use FIELD metres, not GPS/LOCAL_NED")
        point = FieldScanWaypoint(_number(item.get("x_m"), f"{name}[{index}].x_m"), _number(item.get("y_m"), f"{name}[{index}].y_m"), _number(item.get("altitude_m"), f"{name}[{index}].altitude_m", positive=True))
        if abs(point.x_m) > geometry.lane_half_width_m or not area_min <= point.y_m <= area_max:
            raise ValueError(f"{name}.waypoints[{index}] lies outside configured FIELD geometry")
        output.append(point)
    if len({(point.x_m, point.y_m, point.altitude_m) for point in output}) < 2: raise ValueError(f"{name}.waypoints must not be identical")
    return DropScanConfig(output)


def parse_field_profile(data: dict[str, Any]) -> FieldProfile:
    if not isinstance(data, dict): raise FieldProfileValidationError(FieldProfileDiagnostics(["profile must be an object"]))
    if data.get("schema_version") != 3:
        raise FieldProfileValidationError(FieldProfileDiagnostics(["only schema v3 Field Profiles are supported"]))
    forbidden = {"anchor", "centerline_points", "origin", "origin_lat", "origin_lon"} & data.keys()
    if forbidden: raise FieldProfileValidationError(FieldProfileDiagnostics([f"schema v3 must not contain {sorted(forbidden)[0]!r}"]))
    try:
        convention = _mapping(data, "coordinate_convention")
        if convention != {"field_x_positive": "right", "field_y_positive": "forward", "altitude_positive": "up"}:
            raise ValueError("coordinate_convention must define right/forward/up")
        marker = _mapping(data, "forward_marker")
        forward = ForwardMarker(str(marker.get("name", "")).strip(), _number(marker.get("lat"), "forward_marker.lat"), _number(marker.get("lon"), "forward_marker.lon"), str(marker.get("coordinate_system", "")))
        if not forward.name or forward.coordinate_system != "WGS84" or not -90 < forward.lat < 90 or not -180 <= forward.lon <= 180 or abs(math.cos(math.radians(forward.lat))) <= WGS84_POLE_COS_EPS:
            raise ValueError("forward_marker must be a non-polar WGS84 coordinate")
        g = _mapping(data, "field_geometry")
        geometry = FieldGeometry(*[_number(g.get(key), f"field_geometry.{key}", positive=True) for key in ("lane_half_width_m", "drop_center_y_m", "recce_center_y_m", "drop_area_y_min_m", "drop_area_y_max_m", "recce_area_y_min_m", "recce_area_y_max_m")])
        if not geometry.drop_area_y_min < geometry.drop_center_y_m < geometry.drop_area_y_max < geometry.recce_area_y_min < geometry.recce_center_y_m < geometry.recce_area_y_max:
            raise ValueError("field geometry areas must be ordered and contain their centres")
        gps = _mapping(data, "gps_quality")
        quality = GpsQualityThresholds(int(gps.get("min_fix_type", 0)), int(gps.get("min_satellites", 0)), _number(gps.get("max_eph"), "gps_quality.max_eph", positive=True), _number(gps.get("max_epv"), "gps_quality.max_epv", positive=True))
        if quality.min_fix_type < 3 or quality.min_satellites <= 0: raise ValueError("gps_quality requires fix type >= 3 and positive satellite count")
        sampling = _mapping(data, "runtime_origin_sampling")
        runtime = RuntimeOriginSampling(int(sampling.get("min_samples", 0)), _number(sampling.get("sample_window_s"), "runtime_origin_sampling.sample_window_s", positive=True), _number(sampling.get("max_horizontal_spread_m"), "runtime_origin_sampling.max_horizontal_spread_m", positive=True), str(sampling.get("estimator", "")))
        if runtime.min_samples <= 0 or runtime.estimator != "median": raise ValueError("runtime_origin_sampling requires positive samples and median estimator")
        policy = _mapping(data, "binding_policy")
        binding = BindingPolicy(_number(policy.get("min_baseline_m"), "binding_policy.min_baseline_m", positive=True), _number(policy.get("warn_baseline_below_m"), "binding_policy.warn_baseline_below_m", positive=True))
        profile = FieldProfile(3, str(data.get("profile_id", "")).strip(), str(data.get("name", "")).strip(), dict(convention), forward, _scan(data, "drop_scan", geometry, area_min=geometry.drop_area_y_min, area_max=geometry.drop_area_y_max), _scan(data, "recon_scan", geometry, area_min=geometry.recce_area_y_min, area_max=geometry.recce_area_y_max) if "recon_scan" in data else None, quality, geometry, binding, runtime, {key: value for key, value in data.items() if key not in {"schema_version", "profile_id", "name", "coordinate_convention", "forward_marker", "field_geometry", "drop_scan", "recon_scan", "gps_quality", "runtime_origin_sampling", "binding_policy", "created_at"}})
        if not profile.profile_id or not profile.name: raise ValueError("profile_id and name must be non-empty")
        return profile
    except ValueError as exc:
        raise FieldProfileValidationError(FieldProfileDiagnostics([str(exc)])) from exc


def validate_field_profile(profile: FieldProfile) -> FieldProfileDiagnostics:
    try:
        parse_field_profile(profile_to_dict(profile))
        return FieldProfileDiagnostics()
    except FieldProfileValidationError as exc:
        return exc.diagnostics


def profile_to_dict(profile: FieldProfile) -> dict[str, Any]:
    def scan(value: DropScanConfig | None) -> dict[str, Any] | None:
        return None if value is None else {"waypoints": [asdict(point) for point in value.waypoints]}
    data: dict[str, Any] = {"schema_version": 3, "profile_id": profile.profile_id, "name": profile.name, "coordinate_convention": profile.coordinate_convention, "forward_marker": asdict(profile.forward_marker), "field_geometry": {"lane_half_width_m": profile.field_geometry.lane_half_width_m, "drop_center_y_m": profile.field_geometry.drop_center_y_m, "recce_center_y_m": profile.field_geometry.recce_center_y_m, "drop_area_y_min_m": profile.field_geometry.drop_area_y_min, "drop_area_y_max_m": profile.field_geometry.drop_area_y_max, "recce_area_y_min_m": profile.field_geometry.recce_area_y_min, "recce_area_y_max_m": profile.field_geometry.recce_area_y_max}, "drop_scan": scan(profile.drop_scan), "gps_quality": asdict(profile.gps_quality), "runtime_origin_sampling": asdict(profile.runtime_origin_sampling), "binding_policy": asdict(profile.binding_policy)}
    if profile.recon_scan is not None: data["recon_scan"] = scan(profile.recon_scan)
    return data | profile.extra


def load_field_profile_json(path: str | Path) -> FieldProfile:
    return parse_field_profile(json.loads(Path(path).read_text(encoding="utf-8")))
