"""GPS-derived ENU fusion.

Wraps ``MultiPhotoFusion`` to fuse raw GPS estimates instead of
LOCAL_NED coordinates.  Converts each raw estimate to east/north
relative to the runtime origin A, fuses in ENU space, then converts
fused centres back to WGS84 lat/lon.

No LOCAL_NED, no FIELD local_x/local_y.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .gps_target_projection import GpsRawEstimate
from .multi_photo_fusion import MultiPhotoFusion, MultiPhotoFusionConfig


# ---------------------------------------------------------------------------
# GPS fusion config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GpsFusionConfig:
    """Configuration for GPS-derived ENU fusion."""

    cluster_radius_m: float = 1.0
    outlier_radius_m: float = 0.8
    min_cluster_size: int = 3
    center_weight_power: float = 1.0
    min_confidence: float = 0.25
    max_abs_ex: Optional[float] = 0.75
    max_abs_ey: Optional[float] = 0.75


# ---------------------------------------------------------------------------
# fusion result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GpsLocalizedObject:
    """A single fused localized object with GPS and ENU coordinates."""

    id: int
    lat: float
    lon: float
    east_m: float
    north_m: float
    sample_count: int
    raw_count: int
    class_name: str
    confidence: float
    cluster_spread_m: float
    source_waypoints: Tuple[str, ...]
    source_frames: Tuple[int, ...]


# ---------------------------------------------------------------------------
# fusion engine
# ---------------------------------------------------------------------------


class GpsDerivedEnuFusion:
    """Fuse raw GPS estimates using ENU clustering relative to runtime origin A.

    The fusion pipeline:

    1. Convert each raw GPS estimate to east/north relative to origin A.
    2. Feed (east_m, north_m) into ``MultiPhotoFusion``.
    3. Convert fused ENU centres back to WGS84 lat/lon.
    """

    _EARTH_RADIUS_M: float = 6371000.0

    def __init__(
        self,
        *,
        origin_lat: float,
        origin_lon: float,
        config: GpsFusionConfig | None = None,
        class_names: set[str] | None = None,
    ) -> None:
        self.origin_lat = float(origin_lat)
        self.origin_lon = float(origin_lon)
        self._config = config or GpsFusionConfig()

        mf_config = MultiPhotoFusionConfig(
            cluster_radius_m=self._config.cluster_radius_m,
            outlier_radius_m=self._config.outlier_radius_m,
            min_cluster_size=self._config.min_cluster_size,
            center_weight_power=self._config.center_weight_power,
            min_confidence=self._config.min_confidence,
            max_abs_ex=self._config.max_abs_ex,
            max_abs_ey=self._config.max_abs_ey,
        )
        self._fusion = MultiPhotoFusion(mf_config, class_names=class_names)

    def fuse(
        self,
        raw_estimates: List[GpsRawEstimate],
    ) -> List[GpsLocalizedObject]:
        """Fuse raw GPS estimates into localized objects.

        Args:
            raw_estimates: List of ``GpsRawEstimate`` from capture-time projection.

        Returns:
            List of ``GpsLocalizedObject`` sorted by ID, then confidence.
        """
        if not raw_estimates:
            return []

        # Convert to fusion-compatible dicts with local_x/local_y = east_m/north_m
        fusion_inputs: list[dict[str, Any]] = []
        for est in raw_estimates:
            east, north = self._gps_to_enu(est.lat, est.lon)
            fusion_inputs.append({
                "local_x": east,
                "local_y": north,
                "local_z": 0.0,
                "x": east,
                "y": north,
                "z": 0.0,
                "class_name": est.class_name,
                "confidence": est.confidence if est.confidence is not None else 1.0,
                "track_id": est.track_id,
                "frame_id": est.frame_id,
                "ex": est.ex,
                "ey": est.ey,
                "source_waypoint": est.source_waypoint,
                "_raw_est": est,
            })

        # Run fusion
        fused_raw = self._fusion.fuse(fusion_inputs)

        # Convert back to GPS
        result: list[GpsLocalizedObject] = []
        for i, obj in enumerate(fused_raw):
            east_m = float(obj.get("x", obj.get("local_x", 0.0)))
            north_m = float(obj.get("y", obj.get("local_y", 0.0)))
            lat, lon = self._enu_to_gps(east_m, north_m)

            # Collect source metadata
            source_estimates = obj.get("source_estimates", [])
            if not source_estimates:
                # fallback: use top-level fields
                source_waypoints: list[str] = []
                source_frames: list[int] = []
            else:
                source_waypoints = [
                    str(s.get("source_waypoint", ""))
                    for s in source_estimates
                    if isinstance(s, dict)
                ]
                source_frames = [
                    int(s.get("frame_id", 0))
                    for s in source_estimates
                    if isinstance(s, dict) and s.get("frame_id") is not None
                ]

            result.append(GpsLocalizedObject(
                id=i,
                lat=lat,
                lon=lon,
                east_m=east_m,
                north_m=north_m,
                sample_count=int(obj.get("count", 0)),
                raw_count=int(obj.get("raw_count", 0)),
                class_name=str(obj.get("class_name", "")),
                confidence=float(obj.get("avg_confidence", 0.0)),
                cluster_spread_m=float(obj.get("radius_m", 0.0)),
                source_waypoints=tuple(source_waypoints),
                source_frames=tuple(source_frames),
            ))

        return result

    # ------------------------------------------------------------------
    # GPS ↔ ENU helpers
    # ------------------------------------------------------------------

    def _gps_to_enu(self, lat: float, lon: float) -> Tuple[float, float]:
        """Convert GPS lat/lon to east/north metres relative to origin."""
        d_lat_rad = math.radians(lat - self.origin_lat)
        d_lon_rad = math.radians(lon - self.origin_lon)
        cos_lat = math.cos(math.radians(self.origin_lat))
        north_m = d_lat_rad * self._EARTH_RADIUS_M
        east_m = d_lon_rad * self._EARTH_RADIUS_M * cos_lat
        return east_m, north_m

    def _enu_to_gps(self, east_m: float, north_m: float) -> Tuple[float, float]:
        """Convert east/north metres relative to origin back to GPS."""
        d_lat_deg = math.degrees(north_m / self._EARTH_RADIUS_M)
        cos_lat = math.cos(math.radians(self.origin_lat))
        d_lon_deg = math.degrees(east_m / (self._EARTH_RADIUS_M * cos_lat))
        lat = self.origin_lat + d_lat_deg
        lon = self.origin_lon + d_lon_deg
        # Normalise
        if lat > 90.0 or lat < -90.0:
            raise ValueError(f"computed lat {lat} out of range")
        if lon > 180.0:
            lon -= 360.0
        elif lon < -180.0:
            lon += 360.0
        return lat, lon
