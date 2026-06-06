from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class MultiPhotoFusionConfig:
    cluster_radius_m: float = 0.8
    outlier_radius_m: float = 0.8
    min_cluster_size: int = 1
    min_total_weight: float = 1e-6
    default_confidence: float = 1.0
    center_weight_power: float = 1.0

    def __post_init__(self) -> None:
        if self.cluster_radius_m <= 0.0:
            raise ValueError("cluster_radius_m must be positive")
        if self.outlier_radius_m <= 0.0:
            raise ValueError("outlier_radius_m must be positive")
        if self.min_cluster_size < 1:
            raise ValueError("min_cluster_size must be at least 1")
        if self.min_total_weight <= 0.0:
            raise ValueError("min_total_weight must be positive")
        if self.default_confidence <= 0.0:
            raise ValueError("default_confidence must be positive")
        if self.center_weight_power < 0.0:
            raise ValueError("center_weight_power must be non-negative")


class MultiPhotoFusion:
    def __init__(
        self,
        config: MultiPhotoFusionConfig | None = None,
        *,
        class_names: set[str] | None = None,
    ) -> None:
        self.config = config or MultiPhotoFusionConfig()
        self.class_names = set(class_names) if class_names is not None else None

    def fuse(self, estimates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        points = [point for estimate in estimates if (point := self._point(estimate)) is not None]
        clusters: list[dict[str, Any]] = []
        for point in points:
            cluster = self._matching_cluster(clusters, point)
            if cluster is None:
                cluster = {"points": [], "center": {"x": point["x"], "y": point["y"]}}
                clusters.append(cluster)
            cluster["points"].append(point)
            cluster["center"] = self._weighted_center(cluster["points"])

        fused = []
        for cluster in clusters:
            raw_points = cluster["points"]
            raw_center = self._weighted_center(raw_points)
            kept_points = [
                point
                for point in raw_points
                if self._distance_xy(point, raw_center) <= self.config.outlier_radius_m
            ]
            if len(kept_points) < self.config.min_cluster_size:
                continue
            center = self._weighted_center(kept_points)
            if center["weight"] < self.config.min_total_weight:
                continue
            fused.append(self._fused_object(center, kept_points, raw_points))

        indexed = list(enumerate(fused))
        indexed.sort(key=lambda item: (-item[1]["weight"], item[0]))
        result = []
        for new_id, (_, item) in enumerate(indexed):
            item["id"] = new_id
            result.append(item)
        return result

    def _point(self, estimate: dict[str, Any]) -> dict[str, Any] | None:
        if (
            self.class_names is not None
            and self._json_safe_value(estimate.get("class_name")) not in self.class_names
        ):
            return None
        try:
            x = self._float_value(estimate["x"], "x")
            y = self._float_value(estimate["y"], "y")
            z = self._float_value(estimate.get("z", 0.0), "z")
            confidence = self._confidence(estimate)
            center_weight = self._center_weight(estimate)
        except (KeyError, ValueError):
            return None
        weight = confidence * center_weight
        if weight <= 0.0:
            return None
        return {
            "x": x,
            "y": y,
            "z": z,
            "weight": weight,
            "confidence": confidence if estimate.get("confidence") is not None else None,
            "track_id": estimate.get("track_id"),
            "class_name": estimate.get("class_name"),
            "class_id": estimate.get("class_id"),
            "estimate": estimate,
        }

    def _matching_cluster(
        self,
        clusters: list[dict[str, Any]],
        point: dict[str, Any],
    ) -> dict[str, Any] | None:
        for cluster in clusters:
            if self._distance_xy(point, cluster["center"]) <= self.config.cluster_radius_m:
                return cluster
        return None

    def _weighted_center(self, points: list[dict[str, Any]]) -> dict[str, float]:
        total_weight = sum(point["weight"] for point in points)
        if total_weight <= 0.0:
            raise ValueError("total point weight must be positive")
        return {
            "x": sum(point["x"] * point["weight"] for point in points) / total_weight,
            "y": sum(point["y"] * point["weight"] for point in points) / total_weight,
            "z": sum(point["z"] * point["weight"] for point in points) / total_weight,
            "weight": total_weight,
        }

    def _fused_object(
        self,
        center: dict[str, float],
        kept_points: list[dict[str, Any]],
        raw_points: list[dict[str, Any]],
    ) -> dict[str, Any]:
        members = [
            {
                "x": point["x"],
                "y": point["y"],
                "z": point["z"],
                "weight": point["weight"],
                "confidence": point["confidence"],
                "track_id": self._json_safe_value(point["track_id"]),
                "class_name": self._json_safe_value(point["class_name"]),
            }
            for point in kept_points
        ]
        return {
            "id": 0,
            "x": center["x"],
            "y": center["y"],
            "z": center["z"],
            "local_x": center["x"],
            "local_y": center["y"],
            "local_z": center["z"],
            "weight": center["weight"],
            "count": len(kept_points),
            "raw_count": len(raw_points),
            "class_name": self._majority(point["class_name"] for point in kept_points),
            "class_id": self._majority(point["class_id"] for point in kept_points),
            "track_ids": self._stable_unique_sorted_values(
                point["track_id"] for point in kept_points
            ),
            "members": members,
            "detail": {
                "cluster_radius_m": self.config.cluster_radius_m,
                "outlier_radius_m": self.config.outlier_radius_m,
                "min_cluster_size": self.config.min_cluster_size,
            },
        }

    def _confidence(self, estimate: dict[str, Any]) -> float:
        if estimate.get("confidence") is None:
            return self.config.default_confidence
        confidence = self._float_value(estimate["confidence"], "confidence")
        if confidence <= 0.0:
            raise ValueError("confidence must be positive")
        return confidence

    def _center_weight(self, estimate: dict[str, Any]) -> float:
        if self.config.center_weight_power == 0.0:
            return 1.0
        source = estimate.get("source")
        if not isinstance(source, dict) or "ex" not in source or "ey" not in source:
            return 1.0
        ex = self._float_value(source["ex"], "source.ex")
        ey = self._float_value(source["ey"], "source.ey")
        r = math.sqrt(ex * ex + ey * ey)
        base = max(0.0, 1.0 - min(r, 1.0))
        return base ** self.config.center_weight_power

    def _stable_unique_sorted_values(self, values: Iterable[Any]) -> list[Any]:
        unique: dict[tuple[str, str], Any] = {}
        for value in values:
            if value is None:
                continue
            safe_value = self._json_safe_value(value)
            key = (type(safe_value).__name__, str(safe_value))
            if key not in unique:
                unique[key] = safe_value
        return sorted(unique.values(), key=lambda value: (type(value).__name__, str(value)))

    def _json_safe_value(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, bool)):
            return value
        if isinstance(value, float):
            if math.isfinite(value):
                return value
            return str(value)
        return str(value)

    def _majority(self, values: Any) -> Any:
        counts: dict[Any, int] = {}
        best_value = None
        best_count = 0
        for value in values:
            safe_value = self._json_safe_value(value)
            if safe_value is None:
                continue
            counts[safe_value] = counts.get(safe_value, 0) + 1
            if counts[safe_value] > best_count:
                best_value = safe_value
                best_count = counts[safe_value]
        return best_value

    def _distance_xy(self, point: dict[str, Any], center: dict[str, Any]) -> float:
        dx = point["x"] - center["x"]
        dy = point["y"] - center["y"]
        return math.sqrt(dx * dx + dy * dy)

    def _float_value(self, value: Any, name: str) -> float:
        try:
            result = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a float") from exc
        if not math.isfinite(result):
            raise ValueError(f"{name} must be finite")
        return result
