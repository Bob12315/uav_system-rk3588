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

from guidance.target_projection import GpsRawEstimate
from guidance.target_fusion import MultiPhotoFusion, MultiPhotoFusionConfig


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
    min_source_waypoints: int = 1

    def __post_init__(self) -> None:
        if self.min_source_waypoints < 1:
            raise ValueError("min_source_waypoints must be at least 1")


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
    weight: float = 0.0
    score: float = 0.0


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
                "timestamp": est.timestamp,
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

            # Collect source metadata from MultiPhotoFusion members
            members = obj.get("members", [])
            wp_set: set[str] = set()
            fr_set: set[int] = set()
            for m in (members or []):
                if isinstance(m, dict):
                    sw = m.get("source_waypoint")
                    if sw is not None and str(sw):
                        wp_set.add(str(sw))
                    fid = m.get("frame_id")
                    if fid is not None:
                        try:
                            fr_set.add(int(fid))
                        except (TypeError, ValueError):
                            pass
            source_waypoints = sorted(wp_set)
            source_frames = sorted(fr_set)
            if len(source_waypoints) < self._config.min_source_waypoints:
                continue

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
                weight=float(obj.get("weight", 0.0)),
                score=float(obj.get("score", 0.0)),
            ))

        # Stable sort: class_name, then lat, then lon
        result.sort(key=lambda o: (o.class_name, o.lat, o.lon))
        for i, obj in enumerate(result):
            object.__setattr__(obj, 'id', i)
        return result

    # ------------------------------------------------------------------
    # GPS ↔ ENU helpers
    # ------------------------------------------------------------------

    def _gps_to_enu(self, lat: float, lon: float) -> Tuple[float, float]:
        """Convert GPS lat/lon to east/north metres relative to origin.
        Uses gps_enu_deltas for cross-dateline correctness."""
        from field.models import gps_enu_deltas  # noqa: PLC0415
        d_north, d_east = gps_enu_deltas(
            self.origin_lat, self.origin_lon, lat, lon
        )
        return d_east, d_north

    def _enu_to_gps(self, east_m: float, north_m: float) -> Tuple[float, float]:
        """Convert east/north metres relative to origin back to GPS.
        Uses field_to_gps_from_origin with heading=0 (east=x, north=y)."""
        from field.coordinates import field_to_gps_from_origin  # noqa: PLC0415
        gps = field_to_gps_from_origin(
            field_x_m=east_m,
            field_y_m=north_m,
            altitude_m=0.0,
            origin_lat=self.origin_lat,
            origin_lon=self.origin_lon,
            field_heading_yaw_rad=0.0,
        )
        return gps.lat, gps.lon
