from __future__ import annotations

import json

import pytest

from missions.common.actions.multi_photo_fusion import (
    MultiPhotoFusion,
    MultiPhotoFusionConfig,
)


def test_config_defaults_are_valid() -> None:
    config = MultiPhotoFusionConfig()

    assert config.cluster_radius_m == 0.8
    assert config.outlier_radius_m == 0.8
    assert config.min_cluster_size == 1
    assert config.min_total_weight == 1e-6
    assert config.default_confidence == 1.0
    assert config.center_weight_power == 1.0
    assert config.min_confidence == 0.35
    assert config.max_cluster_radius_m == 0.8
    assert config.max_objects is None
    assert config.debug is True


def test_config_rejects_invalid_values() -> None:
    with pytest.raises(ValueError):
        MultiPhotoFusionConfig(cluster_radius_m=0.0)
    with pytest.raises(ValueError):
        MultiPhotoFusionConfig(outlier_radius_m=0.0)
    with pytest.raises(ValueError):
        MultiPhotoFusionConfig(min_cluster_size=0)
    with pytest.raises(ValueError):
        MultiPhotoFusionConfig(min_total_weight=0.0)
    with pytest.raises(ValueError):
        MultiPhotoFusionConfig(default_confidence=0.0)
    with pytest.raises(ValueError):
        MultiPhotoFusionConfig(center_weight_power=-1.0)
    with pytest.raises(ValueError):
        MultiPhotoFusionConfig(min_confidence=-0.1)
    with pytest.raises(ValueError):
        MultiPhotoFusionConfig(max_cluster_radius_m=0.0)
    with pytest.raises(ValueError):
        MultiPhotoFusionConfig(max_objects=0)


def test_single_point_fuses_to_same_position() -> None:
    fusion = MultiPhotoFusion()

    fused = fusion.fuse([{"x": 1.0, "y": 2.0, "z": 0.0, "confidence": 0.9}])

    assert len(fused) == 1
    assert fused[0]["x"] == pytest.approx(1.0)
    assert fused[0]["y"] == pytest.approx(2.0)
    assert fused[0]["z"] == pytest.approx(0.0)
    assert fused[0]["count"] == 1
    assert fused[0]["raw_count"] == 1


def test_nearby_points_cluster_and_use_weighted_average() -> None:
    fusion = MultiPhotoFusion(MultiPhotoFusionConfig(cluster_radius_m=1.0))

    fused = fusion.fuse(
        [
            {"x": 0.0, "y": 0.0, "confidence": 1.0},
            {"x": 0.5, "y": 0.0, "confidence": 1.0},
        ]
    )

    assert len(fused) == 1
    assert fused[0]["x"] == pytest.approx(0.25)
    assert fused[0]["y"] == pytest.approx(0.0)
    assert fused[0]["count"] == 2


def test_far_points_form_separate_clusters() -> None:
    fusion = MultiPhotoFusion(MultiPhotoFusionConfig(cluster_radius_m=0.5))

    fused = fusion.fuse(
        [
            {"x": 0.0, "y": 0.0, "confidence": 1.0},
            {"x": 5.0, "y": 0.0, "confidence": 1.0},
        ]
    )

    assert len(fused) == 2
    assert [item["count"] for item in fused] == [1, 1]


def test_confidence_weight_affects_fused_position() -> None:
    fusion = MultiPhotoFusion(
        MultiPhotoFusionConfig(
            cluster_radius_m=20.0,
            outlier_radius_m=20.0,
            max_cluster_radius_m=20.0,
        )
    )

    fused = fusion.fuse(
        [
            {"x": 0.0, "y": 0.0, "confidence": 1.0},
            {"x": 10.0, "y": 0.0, "confidence": 3.0},
        ]
    )

    assert len(fused) == 1
    assert fused[0]["x"] == pytest.approx(7.5)


def test_center_weight_reduces_edge_detections() -> None:
    fusion = MultiPhotoFusion(MultiPhotoFusionConfig(cluster_radius_m=20.0))

    fused = fusion.fuse(
        [
            {"x": 0.0, "y": 0.0, "confidence": 1.0, "source": {"ex": 0.0, "ey": 0.0}},
            {"x": 10.0, "y": 0.0, "confidence": 1.0, "source": {"ex": 1.0, "ey": 0.0}},
        ]
    )

    assert len(fused) == 1
    assert fused[0]["x"] == pytest.approx(0.0)
    assert fused[0]["count"] == 1
    assert fused[0]["raw_count"] == 1


def test_center_weight_power_zero_disables_center_weighting() -> None:
    fusion = MultiPhotoFusion(
        MultiPhotoFusionConfig(
            cluster_radius_m=20.0,
            outlier_radius_m=20.0,
            max_cluster_radius_m=20.0,
            center_weight_power=0.0,
        )
    )

    fused = fusion.fuse(
        [
            {"x": 0.0, "y": 0.0, "confidence": 1.0, "source": {"ex": 0.0, "ey": 0.0}},
            {"x": 10.0, "y": 0.0, "confidence": 1.0, "source": {"ex": 1.0, "ey": 0.0}},
        ]
    )

    assert len(fused) == 1
    assert fused[0]["x"] == pytest.approx(5.0)
    assert fused[0]["count"] == 2


def test_outlier_rejection_removes_points_far_from_weighted_center() -> None:
    fusion = MultiPhotoFusion(
        MultiPhotoFusionConfig(cluster_radius_m=20.0, outlier_radius_m=1.0)
    )

    fused = fusion.fuse(
        [
            {"x": 0.0, "y": 0.0, "confidence": 10.0},
            {"x": 0.2, "y": 0.0, "confidence": 10.0},
            {"x": 10.0, "y": 0.0, "confidence": 1.0},
        ]
    )

    assert len(fused) == 1
    assert fused[0]["raw_count"] == 3
    assert fused[0]["count"] == 2
    assert fused[0]["x"] == pytest.approx(0.1)


def test_min_cluster_size_drops_small_clusters() -> None:
    fusion = MultiPhotoFusion(MultiPhotoFusionConfig(min_cluster_size=2))

    fused = fusion.fuse([{"x": 1.0, "y": 2.0, "confidence": 1.0}])

    assert fused == []


def test_min_total_weight_drops_low_weight_clusters() -> None:
    fusion = MultiPhotoFusion(
        MultiPhotoFusionConfig(min_total_weight=2.0, default_confidence=1.0)
    )

    fused = fusion.fuse([{"x": 1.0, "y": 2.0}])

    assert fused == []


def test_class_names_filter_is_applied() -> None:
    fusion = MultiPhotoFusion(class_names={"cylinder"})

    fused = fusion.fuse(
        [
            {"x": 1.0, "y": 2.0, "class_name": "cylinder"},
            {"x": 10.0, "y": 20.0, "class_name": "hazard"},
        ]
    )

    assert len(fused) == 1
    assert fused[0]["x"] == pytest.approx(1.0)


def test_bad_inputs_are_skipped() -> None:
    fusion = MultiPhotoFusion()

    fused = fusion.fuse(
        [
            {"y": 1.0, "confidence": 1.0},
            {"x": "bad", "y": 1.0, "confidence": 1.0},
            {"x": 1.0, "y": 1.0, "confidence": 0.0},
            {"x": 2.0, "y": 3.0, "confidence": 1.0},
        ]
    )

    assert len(fused) == 1
    assert fused[0]["x"] == pytest.approx(2.0)
    assert fused[0]["y"] == pytest.approx(3.0)


def test_majority_class_and_track_ids_are_reported() -> None:
    fusion = MultiPhotoFusion(MultiPhotoFusionConfig(cluster_radius_m=5.0))

    fused = fusion.fuse(
        [
            {
                "x": 0.0,
                "y": 0.0,
                "confidence": 1.0,
                "class_name": "cylinder",
                "class_id": 2,
                "track_id": 4,
            },
            {
                "x": 0.1,
                "y": 0.0,
                "confidence": 1.0,
                "class_name": "hazard",
                "class_id": 3,
                "track_id": 2,
            },
            {
                "x": 0.2,
                "y": 0.0,
                "confidence": 1.0,
                "class_name": "cylinder",
                "class_id": 2,
                "track_id": 4,
            },
        ]
    )

    assert len(fused) == 2
    assert fused[0]["class_name"] == "cylinder"
    assert fused[0]["class_id"] == 2
    assert fused[0]["track_ids"] == [4]
    assert fused[1]["class_name"] == "hazard"
    assert fused[1]["class_id"] == 3
    assert fused[1]["track_ids"] == [2]


def test_majority_ties_use_first_seen_value() -> None:
    fusion = MultiPhotoFusion(MultiPhotoFusionConfig(cluster_radius_m=5.0))

    fused = fusion.fuse(
        [
            {"x": 0.0, "y": 0.0, "class_name": "first", "class_id": 1},
            {"x": 0.1, "y": 0.0, "class_name": "second", "class_id": 2},
        ]
    )

    assert fused[0]["class_name"] == "first"
    assert fused[0]["class_id"] == 1


def test_mixed_track_id_types_do_not_crash() -> None:
    fusion = MultiPhotoFusion(MultiPhotoFusionConfig(cluster_radius_m=5.0))

    fused = fusion.fuse(
        [
            {"x": 0.0, "y": 0.0, "track_id": 1},
            {"x": 0.1, "y": 0.0, "track_id": "2"},
        ]
    )

    assert len(fused) == 1
    assert set(fused[0]["track_ids"]) == {1, "2"}
    json.dumps(fused)


def test_unhashable_class_values_do_not_crash() -> None:
    fusion = MultiPhotoFusion(MultiPhotoFusionConfig(cluster_radius_m=5.0))

    fused = fusion.fuse(
        [
            {"x": 0.0, "y": 0.0, "class_name": ["bad"], "class_id": {"id": 1}},
            {"x": 0.1, "y": 0.0, "class_name": ["bad"], "class_id": {"id": 1}},
        ]
    )

    assert len(fused) == 1
    assert fused[0]["class_name"] == "['bad']"
    assert fused[0]["class_id"] == "{'id': 1}"
    json.dumps(fused)


def test_member_track_id_values_are_json_safe() -> None:
    fusion = MultiPhotoFusion()

    fused = fusion.fuse([{"x": 0.0, "y": 0.0, "track_id": ("cam", 1)}])

    assert len(fused) == 1
    assert fused[0]["members"][0]["track_id"] == "('cam', 1)"
    json.dumps(fused)


def test_output_is_plain_json_serializable_dict() -> None:
    fusion = MultiPhotoFusion()

    fused = fusion.fuse(
        [
            {
                "x": 1.0,
                "y": 2.0,
                "z": 0.0,
                "confidence": 0.9,
                "track_id": 1,
                "class_name": "cylinder",
            }
        ]
    )

    assert isinstance(fused[0], dict)
    assert fused[0]["local_x"] == pytest.approx(1.0)
    assert fused[0]["local_y"] == pytest.approx(2.0)
    assert fused[0]["local_z"] == pytest.approx(0.0)
    assert fused[0]["members"][0]["track_id"] == 1
    json.dumps(fused)


def test_three_real_targets_with_noisy_observations_fuse_to_three_objects() -> None:
    fusion = MultiPhotoFusion(
        MultiPhotoFusionConfig(
            cluster_radius_m=0.8,
            outlier_radius_m=0.8,
            min_cluster_size=2,
            max_cluster_radius_m=0.8,
        ),
        class_names={"bucket"},
    )

    estimates = [
        {"x": 0.0, "y": 0.0, "confidence": 0.92, "class_name": "bucket", "track_id": 1},
        {"x": 0.12, "y": -0.05, "confidence": 0.88, "class_name": "bucket", "track_id": 7},
        {"x": -0.08, "y": 0.06, "confidence": 0.91, "class_name": "bucket", "track_id": 2},
        {"x": 4.0, "y": 1.0, "confidence": 0.90, "class_name": "bucket", "track_id": 3},
        {"x": 4.08, "y": 0.92, "confidence": 0.87, "class_name": "bucket", "track_id": 8},
        {"x": 3.93, "y": 1.05, "confidence": 0.89, "class_name": "bucket", "track_id": 3},
        {"x": -2.0, "y": 3.0, "confidence": 0.93, "class_name": "bucket", "track_id": 4},
        {"x": -1.9, "y": 3.08, "confidence": 0.90, "class_name": "bucket", "track_id": 9},
        {"x": -2.06, "y": 2.95, "confidence": 0.86, "class_name": "bucket", "track_id": 4},
    ]

    fused = fusion.fuse(estimates)

    assert len(fused) == 3
    centers = sorted((item["x"], item["y"]) for item in fused)
    assert centers[0][0] == pytest.approx(-1.99, abs=0.1)
    assert centers[0][1] == pytest.approx(3.01, abs=0.1)
    assert centers[1][0] == pytest.approx(0.01, abs=0.1)
    assert centers[1][1] == pytest.approx(0.00, abs=0.1)
    assert centers[2][0] == pytest.approx(4.00, abs=0.1)
    assert centers[2][1] == pytest.approx(0.99, abs=0.1)
    assert fusion.last_debug["candidate_cluster_count"] == 3
    assert fusion.last_debug["accepted_cluster_count"] == 3


def test_single_false_positive_is_rejected_by_min_cluster_size() -> None:
    fusion = MultiPhotoFusion(MultiPhotoFusionConfig(min_cluster_size=2))

    fused = fusion.fuse([{"x": 10.0, "y": 20.0, "confidence": 0.95}])

    assert fused == []
    assert fusion.last_debug["rejected_cluster_count"] == 1
    assert fusion.last_debug["rejected_clusters"][0]["reason"] == "too_few_points"


def test_low_confidence_points_are_filtered_before_clustering() -> None:
    fusion = MultiPhotoFusion(MultiPhotoFusionConfig(min_confidence=0.35, min_cluster_size=1))

    fused = fusion.fuse(
        [
            {"x": 0.0, "y": 0.0, "confidence": 0.2},
            {"x": 1.0, "y": 1.0, "confidence": 0.8},
        ]
    )

    assert len(fused) == 1
    assert fused[0]["x"] == pytest.approx(1.0)
    assert fusion.last_debug["input_count"] == 2
    assert fusion.last_debug["valid_point_count"] == 1


def test_large_radius_cluster_is_rejected() -> None:
    fusion = MultiPhotoFusion(
        MultiPhotoFusionConfig(
            cluster_radius_m=1.0,
            outlier_radius_m=5.0,
            min_cluster_size=2,
            max_cluster_radius_m=0.2,
            center_weight_power=0.0,
        )
    )

    fused = fusion.fuse(
        [
            {"x": 0.0, "y": 0.0, "confidence": 0.9},
            {"x": 0.6, "y": 0.0, "confidence": 0.9},
            {"x": 1.2, "y": 0.0, "confidence": 0.9},
        ]
    )

    assert fused == []
    assert fusion.last_debug["rejected_clusters"][0]["reason"] == "radius_too_large"
    assert fusion.last_debug["rejected_clusters"][0]["radius_m"] > 0.2


def test_max_objects_limits_highest_scoring_objects() -> None:
    fusion = MultiPhotoFusion(
        MultiPhotoFusionConfig(
            cluster_radius_m=0.8,
            outlier_radius_m=0.8,
            min_cluster_size=2,
            max_objects=3,
        )
    )
    estimates = []
    for index in range(5):
        estimates.extend(
            [
                {"x": index * 3.0, "y": 0.0, "confidence": 0.9 - index * 0.05},
                {"x": index * 3.0 + 0.05, "y": 0.0, "confidence": 0.9 - index * 0.05},
            ]
        )

    fused = fusion.fuse(estimates)

    assert len(fused) == 3
    assert [item["id"] for item in fused] == [0, 1, 2]
    assert [round(item["x"], 1) for item in fused] == [0.0, 3.0, 6.0]
    assert fusion.last_debug["accepted_cluster_count"] == 3


def test_output_contains_stability_score_and_debug_fields() -> None:
    fusion = MultiPhotoFusion(
        MultiPhotoFusionConfig(
            cluster_radius_m=1.0,
            outlier_radius_m=1.0,
            min_cluster_size=2,
        )
    )

    fused = fusion.fuse(
        [
            {"x": 0.0, "y": 0.0, "confidence": 0.8, "source": {"ex": 0.1, "ey": 0.2}},
            {"x": 0.1, "y": 0.0, "confidence": 0.9, "source": {"ex": 0.0, "ey": 0.1}},
            {"x": 3.0, "y": 3.0, "confidence": 0.9},
        ]
    )

    assert len(fused) == 1
    obj = fused[0]
    assert "radius_m" in obj
    assert "std_x_m" in obj
    assert "std_y_m" in obj
    assert "avg_confidence" in obj
    assert "score" in obj
    assert "stable" in obj
    assert obj["stable"] is True
    assert obj["avg_confidence"] == pytest.approx(0.85)
    assert obj["score"] > 0.0
    assert obj["members"][0]["source"]["ex"] == pytest.approx(0.1)
    assert fusion.last_debug["accepted_objects"][0]["stable"] is True
    assert fusion.last_debug["rejected_clusters"][0]["reason"] == "too_few_points"
    json.dumps(fusion.last_debug)
