from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(slots=True)
class EstimatedObject:
    class_name: str
    confidence: float
    target_size: float
    x: float
    y: float
    track_id: int | None = None
    source: str = ""
    timestamp: float = 0.0

    @property
    def weight(self) -> float:
        return max(1e-6, float(self.confidence) * max(float(self.target_size), 1e-3))


@dataclass(slots=True)
class SurveyTarget:
    target_id: int
    x: float
    y: float
    seen_count: int = 0
    max_confidence: float = 0.0
    mean_target_size: float = 0.0
    source_names: set[str] = field(default_factory=set)
    observations: list[EstimatedObject] = field(default_factory=list)
    visited: bool = False

    def to_detail(self) -> dict[str, object]:
        return {
            "target_id": self.target_id,
            "x": self.x,
            "y": self.y,
            "seen_count": self.seen_count,
            "max_confidence": self.max_confidence,
            "mean_target_size": self.mean_target_size,
            "sources": sorted(self.source_names),
            "visited": self.visited,
        }


def cluster_estimates(
    estimates: list[EstimatedObject],
    *,
    radius_m: float,
) -> list[SurveyTarget]:
    clusters: list[SurveyTarget] = []
    radius = max(0.01, float(radius_m))
    for estimate in estimates:
        cluster = _nearest_cluster(estimate, clusters, radius)
        if cluster is None:
            cluster = SurveyTarget(
                target_id=len(clusters) + 1,
                x=float(estimate.x),
                y=float(estimate.y),
            )
            clusters.append(cluster)
        _add_estimate(cluster, estimate)
    return sorted(clusters, key=target_score, reverse=True)


def target_score(target: SurveyTarget) -> float:
    return (
        float(target.seen_count) * 2.0
        + float(target.max_confidence)
        + float(target.mean_target_size)
    )


def select_targets(
    targets: list[SurveyTarget],
    *,
    count: int,
    min_separation_m: float,
) -> list[SurveyTarget]:
    selected: list[SurveyTarget] = []
    for target in sorted(targets, key=target_score, reverse=True):
        if all(distance_xy(target, item) >= min_separation_m for item in selected):
            selected.append(target)
        if len(selected) >= count:
            break
    return selected


def distance_xy(a: SurveyTarget, b: SurveyTarget) -> float:
    return math.hypot(float(a.x) - float(b.x), float(a.y) - float(b.y))


def _nearest_cluster(
    estimate: EstimatedObject,
    clusters: list[SurveyTarget],
    radius: float,
) -> SurveyTarget | None:
    if not clusters:
        return None
    nearest = min(
        clusters,
        key=lambda item: math.hypot(float(item.x) - estimate.x, float(item.y) - estimate.y),
    )
    if math.hypot(float(nearest.x) - estimate.x, float(nearest.y) - estimate.y) <= radius:
        return nearest
    return None


def _add_estimate(target: SurveyTarget, estimate: EstimatedObject) -> None:
    target.observations.append(estimate)
    total_weight = sum(item.weight for item in target.observations)
    target.x = sum(item.x * item.weight for item in target.observations) / total_weight
    target.y = sum(item.y * item.weight for item in target.observations) / total_weight
    target.seen_count = len(target.observations)
    target.max_confidence = max(item.confidence for item in target.observations)
    target.mean_target_size = (
        sum(item.target_size * item.weight for item in target.observations) / total_weight
    )
    if estimate.source:
        target.source_names.add(estimate.source)
