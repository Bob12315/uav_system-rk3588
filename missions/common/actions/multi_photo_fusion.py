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
    min_confidence: float = 0.35
    max_cluster_radius_m: float = 0.8
    max_objects: int | None = None
    debug: bool = True

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
        if self.min_confidence < 0.0:
            raise ValueError("min_confidence must be non-negative")
        if self.max_cluster_radius_m <= 0.0:
            raise ValueError("max_cluster_radius_m must be positive")
        if self.max_objects is not None and self.max_objects < 1:
            raise ValueError("max_objects must be positive when set")


class MultiPhotoFusion:
    def __init__(
        self,
        config: MultiPhotoFusionConfig | None = None,
        *,
        class_names: set[str] | None = None,
    ) -> None:
        self.config = config or MultiPhotoFusionConfig()
        self.class_names = set(class_names) if class_names is not None else None
        self.last_debug: dict[str, Any] = self._empty_debug(0)

    def fuse(self, estimates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        points = [point for estimate in estimates if (point := self._point(estimate)) is not None]
        candidate_clusters = self._connected_clusters(points)

        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for raw_points in candidate_clusters:
            raw_center = self._weighted_center(raw_points)
            kept_points = [
                point
                for point in raw_points
                if self._distance_xy(point, raw_center) <= self.config.outlier_radius_m
            ]
            if len(kept_points) < self.config.min_cluster_size:
                rejected.append(
                    self._rejected_cluster(
                        "too_few_points",
                        raw_points,
                        kept_points,
                        raw_center,
                    )
                )
                continue
            center = self._weighted_center(kept_points)
            if center["weight"] < self.config.min_total_weight:
                rejected.append(
                    self._rejected_cluster(
                        "too_few_points",
                        raw_points,
                        kept_points,
                        center,
                    )
                )
                continue
            radius_m = self._cluster_radius(kept_points, center)
            if radius_m > self.config.max_cluster_radius_m:
                rejected.append(
                    self._rejected_cluster(
                        "radius_too_large",
                        raw_points,
                        kept_points,
                        center,
                        radius_m=radius_m,
                    )
                )
                continue
            accepted.append(self._fused_object(center, kept_points, raw_points, radius_m))

        indexed = list(enumerate(accepted))
        indexed.sort(key=lambda item: (-item[1]["score"], item[0]))
        if self.config.max_objects is not None:
            indexed = indexed[: self.config.max_objects]
        result = []
        for new_id, (_, item) in enumerate(indexed):
            item["id"] = new_id
            result.append(item)
        self.last_debug = self._debug_payload(
            input_count=len(estimates),
            valid_point_count=len(points),
            candidate_cluster_count=len(candidate_clusters),
            accepted_objects=result,
            rejected_clusters=rejected,
        )
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
            if confidence < self.config.min_confidence:
                return None
            center_weight = self._center_weight(estimate)
        except (KeyError, ValueError):
            return None
        weight = confidence * center_weight
        if weight <= 0.0:
            return None
        source = estimate.get("source") if isinstance(estimate.get("source"), dict) else {}
        return {
            "x": x,
            "y": y,
            "z": z,
            "local_x": x,
            "local_y": y,
            "local_z": z,
            "weight": weight,
            "confidence": confidence,
            "track_id": estimate.get("track_id"),
            "class_name": estimate.get("class_name"),
            "class_id": estimate.get("class_id"),
            "source": {
                "ex": self._optional_float(source.get("ex")),
                "ey": self._optional_float(source.get("ey")),
            },
            "estimate": estimate,
            "cluster_key": self._cluster_key(estimate),
        }

    def _connected_clusters(self, points: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        clusters: list[list[dict[str, Any]]] = []
        visited: set[int] = set()
        for start_index, start_point in enumerate(points):
            if start_index in visited:
                continue
            visited.add(start_index)
            cluster = [start_point]
            queue = [start_index]
            while queue:
                current_index = queue.pop(0)
                current = points[current_index]
                for next_index, candidate in enumerate(points):
                    if next_index in visited:
                        continue
                    if candidate["cluster_key"] != current["cluster_key"]:
                        continue
                    if self._distance_xy(current, candidate) > self.config.cluster_radius_m:
                        continue
                    visited.add(next_index)
                    queue.append(next_index)
                    cluster.append(candidate)
            clusters.append(cluster)
        return clusters

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
        radius_m: float,
    ) -> dict[str, Any]:
        avg_confidence = sum(point["confidence"] for point in kept_points) / len(kept_points)
        std_x_m = self._weighted_std(kept_points, center, "x")
        std_y_m = self._weighted_std(kept_points, center, "y")
        score = len(kept_points) * avg_confidence / (radius_m + 0.2)
        stable = (
            len(kept_points) >= self.config.min_cluster_size
            and radius_m <= self.config.max_cluster_radius_m
        )
        members = [
            {
                "x": point["x"],
                "y": point["y"],
                "z": point["z"],
                "local_x": point["local_x"],
                "local_y": point["local_y"],
                "local_z": point["local_z"],
                "weight": point["weight"],
                "confidence": point["confidence"],
                "track_id": self._json_safe_value(point["track_id"]),
                "class_name": self._json_safe_value(point["class_name"]),
                "class_id": self._json_safe_value(point["class_id"]),
                "source": point["source"],
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
            "radius_m": radius_m,
            "std_x_m": std_x_m,
            "std_y_m": std_y_m,
            "avg_confidence": avg_confidence,
            "score": score,
            "stable": stable,
            "detail": {
                "cluster_radius_m": self.config.cluster_radius_m,
                "outlier_radius_m": self.config.outlier_radius_m,
                "min_cluster_size": self.config.min_cluster_size,
                "max_cluster_radius_m": self.config.max_cluster_radius_m,
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

    def _cluster_key(self, estimate: dict[str, Any]) -> tuple[Any, Any]:
        return (
            self._json_safe_value(estimate.get("class_name")),
            self._json_safe_value(estimate.get("class_id")),
        )

    def _cluster_radius(self, points: list[dict[str, Any]], center: dict[str, Any]) -> float:
        if not points:
            return 0.0
        return max(self._distance_xy(point, center) for point in points)

    def _weighted_std(
        self,
        points: list[dict[str, Any]],
        center: dict[str, float],
        axis: str,
    ) -> float:
        total_weight = sum(point["weight"] for point in points)
        if total_weight <= 0.0:
            return 0.0
        variance = sum(
            ((point[axis] - center[axis]) ** 2) * point["weight"]
            for point in points
        ) / total_weight
        return math.sqrt(max(0.0, variance))

    def _rejected_cluster(
        self,
        reason: str,
        raw_points: list[dict[str, Any]],
        kept_points: list[dict[str, Any]],
        center: dict[str, float],
        *,
        radius_m: float | None = None,
    ) -> dict[str, Any]:
        if radius_m is None:
            radius_m = self._cluster_radius(kept_points, center) if kept_points else 0.0
        return {
            "reason": reason,
            "raw_count": len(raw_points),
            "kept_count": len(kept_points),
            "center": {"x": center["x"], "y": center["y"]},
            "radius_m": radius_m,
        }

    def _config_debug(self) -> dict[str, Any]:
        return {
            "cluster_radius_m": self.config.cluster_radius_m,
            "outlier_radius_m": self.config.outlier_radius_m,
            "min_cluster_size": self.config.min_cluster_size,
            "min_total_weight": self.config.min_total_weight,
            "default_confidence": self.config.default_confidence,
            "center_weight_power": self.config.center_weight_power,
            "min_confidence": self.config.min_confidence,
            "max_cluster_radius_m": self.config.max_cluster_radius_m,
            "max_objects": self.config.max_objects,
            "debug": self.config.debug,
        }

    def _debug_payload(
        self,
        *,
        input_count: int,
        valid_point_count: int,
        candidate_cluster_count: int,
        accepted_objects: list[dict[str, Any]],
        rejected_clusters: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "input_count": input_count,
            "valid_point_count": valid_point_count,
            "candidate_cluster_count": candidate_cluster_count,
            "accepted_cluster_count": len(accepted_objects),
            "rejected_cluster_count": len(rejected_clusters),
            "accepted_objects": [
                {
                    "id": obj.get("id"),
                    "x": obj.get("x"),
                    "y": obj.get("y"),
                    "count": obj.get("count"),
                    "raw_count": obj.get("raw_count"),
                    "radius_m": obj.get("radius_m"),
                    "score": obj.get("score"),
                    "stable": obj.get("stable"),
                    "class_name": obj.get("class_name"),
                    "class_id": obj.get("class_id"),
                    "track_ids": obj.get("track_ids", []),
                }
                for obj in accepted_objects
            ],
            "rejected_clusters": rejected_clusters,
            "config": self._config_debug(),
        }

    def _empty_debug(self, input_count: int) -> dict[str, Any]:
        return self._debug_payload(
            input_count=input_count,
            valid_point_count=0,
            candidate_cluster_count=0,
            accepted_objects=[],
            rejected_clusters=[],
        )

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

    def _optional_float(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(result):
            return None
        return result

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
