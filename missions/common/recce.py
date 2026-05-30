from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RecceConfig:
    cylinder_classes: set[str] = field(default_factory=lambda: {"recce_cylinder", "cylinder"})
    hazard_classes: set[str] = field(
        default_factory=lambda: {
            "explosive",
            "flammable",
            "corrosive",
            "toxic",
            "oxidizer",
            "biohazard",
            "hazard_sign",
        }
    )
    min_cylinder_confidence: float = 0.35
    min_hazard_confidence: float = 0.35
    vote_min_count: int = 3
    vote_min_confidence_sum: float = 1.2


@dataclass(slots=True)
class HazardVote:
    class_name: str
    count: int = 0
    confidence_sum: float = 0.0
    max_confidence: float = 0.0

    def add(self, confidence: float) -> None:
        self.count += 1
        self.confidence_sum += float(confidence)
        self.max_confidence = max(self.max_confidence, float(confidence))


@dataclass(slots=True)
class CylinderTrack:
    key: str
    track_id: int | None
    class_name: str
    first_seen: float
    last_seen: float
    seen_count: int = 0
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    hazard_votes: dict[str, HazardVote] = field(default_factory=dict)


@dataclass(slots=True)
class RecceResultItem:
    cylinder_key: str
    cylinder_track_id: int | None
    hazard_class: str | None
    vote_count: int
    confidence_sum: float
    max_confidence: float
    status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "cylinder_key": self.cylinder_key,
            "cylinder_track_id": self.cylinder_track_id,
            "hazard_class": self.hazard_class,
            "vote_count": self.vote_count,
            "confidence_sum": self.confidence_sum,
            "max_confidence": self.max_confidence,
            "status": self.status,
        }


class RecceAccumulator:
    def __init__(self, config: RecceConfig | None = None) -> None:
        self.config = config or RecceConfig()
        self.config.cylinder_classes = {item.strip().lower() for item in self.config.cylinder_classes}
        self.config.hazard_classes = {item.strip().lower() for item in self.config.hazard_classes}
        self.cylinders: dict[str, CylinderTrack] = {}
        self.observation_count = 0

    def reset(self) -> None:
        self.cylinders.clear()
        self.observation_count = 0

    def update(self, scene, timestamp: float) -> None:
        if scene is None or not getattr(scene, "valid", False):
            return
        self.observation_count += 1
        detections = list(getattr(scene, "detections", []))
        cylinder_detections = [
            detection
            for detection in detections
            if self._is_class(detection, self.config.cylinder_classes)
            and float(getattr(detection, "confidence", 0.0)) >= self.config.min_cylinder_confidence
        ]
        hazard_detections = [
            detection
            for detection in detections
            if self._is_class(detection, self.config.hazard_classes)
            and float(getattr(detection, "confidence", 0.0)) >= self.config.min_hazard_confidence
        ]

        cylinders = [self._update_cylinder(detection, timestamp) for detection in cylinder_detections]
        for hazard in hazard_detections:
            cylinder = associate_hazard_to_cylinder(hazard, cylinders)
            if cylinder is None:
                continue
            class_name = str(getattr(hazard, "class_name", ""))
            vote = cylinder.hazard_votes.setdefault(class_name, HazardVote(class_name=class_name))
            vote.add(float(getattr(hazard, "confidence", 0.0)))

    def results(self) -> list[RecceResultItem]:
        items: list[RecceResultItem] = []
        for cylinder in sorted(self.cylinders.values(), key=lambda item: item.key):
            if not cylinder.hazard_votes:
                items.append(
                    RecceResultItem(
                        cylinder_key=cylinder.key,
                        cylinder_track_id=cylinder.track_id,
                        hazard_class=None,
                        vote_count=0,
                        confidence_sum=0.0,
                        max_confidence=0.0,
                        status="blank",
                    )
                )
                continue
            vote = max(
                cylinder.hazard_votes.values(),
                key=lambda item: (item.confidence_sum, item.count, item.max_confidence),
            )
            confirmed = (
                vote.count >= self.config.vote_min_count
                and vote.confidence_sum >= self.config.vote_min_confidence_sum
            )
            items.append(
                RecceResultItem(
                    cylinder_key=cylinder.key,
                    cylinder_track_id=cylinder.track_id,
                    hazard_class=vote.class_name,
                    vote_count=vote.count,
                    confidence_sum=vote.confidence_sum,
                    max_confidence=vote.max_confidence,
                    status="confirmed" if confirmed else "uncertain",
                )
            )
        return items

    def _update_cylinder(self, detection, timestamp: float) -> CylinderTrack:
        key = _cylinder_key(detection)
        bbox = _bbox(detection)
        cylinder = self.cylinders.get(key)
        if cylinder is None:
            cylinder = CylinderTrack(
                key=key,
                track_id=getattr(detection, "track_id", None),
                class_name=str(getattr(detection, "class_name", "")),
                first_seen=float(timestamp),
                last_seen=float(timestamp),
                seen_count=0,
                bbox=bbox,
            )
            self.cylinders[key] = cylinder
        cylinder.last_seen = float(timestamp)
        cylinder.seen_count += 1
        cylinder.bbox = bbox
        return cylinder

    @staticmethod
    def _is_class(detection, classes: set[str]) -> bool:
        return str(getattr(detection, "class_name", "")).strip().lower() in classes


def point_inside_bbox(cx: float, cy: float, bbox: tuple[float, float, float, float]) -> bool:
    x1, y1, x2, y2 = bbox
    return float(x1) <= float(cx) <= float(x2) and float(y1) <= float(cy) <= float(y2)


def associate_hazard_to_cylinder(hazard, cylinders: list[CylinderTrack]) -> CylinderTrack | None:
    matches = [
        cylinder
        for cylinder in cylinders
        if point_inside_bbox(float(getattr(hazard, "cx", 0.0)), float(getattr(hazard, "cy", 0.0)), cylinder.bbox)
    ]
    if not matches:
        return None
    hx = float(getattr(hazard, "cx", 0.0))
    hy = float(getattr(hazard, "cy", 0.0))
    return min(matches, key=lambda cylinder: _center_distance_sq(hx, hy, cylinder.bbox))


def _cylinder_key(detection) -> str:
    track_id = getattr(detection, "track_id", None)
    if track_id is not None:
        return f"track:{int(track_id)}"
    rounded_cx = int(round(float(getattr(detection, "cx", 0.0)) / 20.0) * 20)
    rounded_cy = int(round(float(getattr(detection, "cy", 0.0)) / 20.0) * 20)
    class_name = str(getattr(detection, "class_name", ""))
    return f"pos:{class_name}:{rounded_cx}:{rounded_cy}"


def _bbox(detection) -> tuple[float, float, float, float]:
    return (
        float(getattr(detection, "x1", 0.0)),
        float(getattr(detection, "y1", 0.0)),
        float(getattr(detection, "x2", 0.0)),
        float(getattr(detection, "y2", 0.0)),
    )


def _center_distance_sq(cx: float, cy: float, bbox: tuple[float, float, float, float]) -> float:
    x1, y1, x2, y2 = bbox
    bx = (x1 + x2) / 2.0
    by = (y1 + y2) / 2.0
    dx = float(cx) - bx
    dy = float(cy) - by
    return dx * dx + dy * dy
