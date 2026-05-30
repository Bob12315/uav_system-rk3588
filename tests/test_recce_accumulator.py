from __future__ import annotations

import pytest

from fusion.models import SceneDetections, SceneObject
from missions.common.recce import (
    RecceAccumulator,
    RecceConfig,
    associate_hazard_to_cylinder,
    point_inside_bbox,
)


def _scene(*objects: SceneObject, timestamp: float = 1.0) -> SceneDetections:
    return SceneDetections(
        timestamp=timestamp,
        frame_id=1,
        image_width=640,
        image_height=480,
        detections=list(objects),
        valid=True,
    )


def _object(
    class_name: str,
    confidence: float = 0.8,
    track_id: int | None = 1,
    x1: float = 100.0,
    y1: float = 100.0,
    x2: float = 200.0,
    y2: float = 220.0,
    cx: float = 150.0,
    cy: float = 160.0,
) -> SceneObject:
    return SceneObject(
        track_id=track_id,
        class_name=class_name,
        confidence=confidence,
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
        cx=cx,
        cy=cy,
    )


def test_point_inside_bbox_and_association() -> None:
    accumulator = RecceAccumulator()
    accumulator.update(_scene(_object("cylinder")), timestamp=1.0)
    cylinder = accumulator.cylinders["track:1"]
    inside = _object("flammable", track_id=9, cx=150.0, cy=160.0)
    outside = _object("flammable", track_id=10, cx=300.0, cy=300.0)

    assert point_inside_bbox(150.0, 160.0, cylinder.bbox)
    assert not point_inside_bbox(300.0, 300.0, cylinder.bbox)
    assert associate_hazard_to_cylinder(inside, [cylinder]) == cylinder
    assert associate_hazard_to_cylinder(outside, [cylinder]) is None


def test_filters_non_matching_and_low_confidence_objects() -> None:
    accumulator = RecceAccumulator(
        RecceConfig(
            cylinder_classes={"cylinder"},
            hazard_classes={"flammable"},
            min_cylinder_confidence=0.5,
            min_hazard_confidence=0.5,
        )
    )

    accumulator.update(
        _scene(
            _object("person", confidence=0.9),
            _object("cylinder", confidence=0.2, track_id=2),
            _object("flammable", confidence=0.9, track_id=3),
        ),
        timestamp=1.0,
    )

    assert accumulator.results() == []


def test_accumulates_votes_and_confirms_best_hazard() -> None:
    accumulator = RecceAccumulator(
        RecceConfig(
            cylinder_classes={"cylinder"},
            hazard_classes={"flammable", "toxic"},
            vote_min_count=2,
            vote_min_confidence_sum=1.0,
        )
    )
    cylinder = _object("cylinder", track_id=12)
    flammable = _object("flammable", confidence=0.6, track_id=22, cx=150.0, cy=160.0)
    toxic = _object("toxic", confidence=0.4, track_id=23, cx=150.0, cy=160.0)

    accumulator.update(_scene(cylinder, flammable, toxic), timestamp=1.0)
    accumulator.update(_scene(cylinder, flammable), timestamp=2.0)

    result = accumulator.results()[0]
    assert result.cylinder_key == "track:12"
    assert result.cylinder_track_id == 12
    assert result.hazard_class == "flammable"
    assert result.vote_count == 2
    assert result.confidence_sum == pytest.approx(1.2)
    assert result.max_confidence == pytest.approx(0.6)
    assert result.status == "confirmed"


def test_uncertain_blank_and_position_key_results() -> None:
    accumulator = RecceAccumulator(
        RecceConfig(
            cylinder_classes={"cylinder"},
            hazard_classes={"flammable"},
            vote_min_count=3,
            vote_min_confidence_sum=2.0,
        )
    )
    untracked = _object("cylinder", track_id=None, cx=151.0, cy=161.0)
    hazard = _object("flammable", confidence=0.6, track_id=None, cx=150.0, cy=160.0)
    blank = _object("cylinder", track_id=99, x1=300.0, y1=100.0, x2=360.0, y2=200.0, cx=330.0, cy=150.0)

    accumulator.update(_scene(untracked, hazard, blank), timestamp=1.0)

    results = {item.cylinder_key: item for item in accumulator.results()}
    assert results["pos:cylinder:160:160"].status == "uncertain"
    assert results["pos:cylinder:160:160"].hazard_class == "flammable"
    assert results["track:99"].status == "blank"
    assert results["track:99"].hazard_class is None
