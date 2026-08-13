from __future__ import annotations

from missions.common.actions.build_recon_report import BuildReconReportAction


def test_detected_blank_skipped_summary() -> None:
    action = BuildReconReportAction()
    action.start({
        "items": [
            {"target_id": "r0", "content": "baozha", "confidence": 0.82, "status": "detected"},
            {"target_id": "r1", "content": "blank", "confidence": 0.0, "status": "blank_or_uncertain"},
            {"target_id": "r2", "content": "blank", "confidence": 0.0, "status": "skipped_missing_target"},
            {"target_id": "r3", "content": "blank", "confidence": 0.0, "status": "blank_or_uncertain"},
            {"target_id": "r4", "content": "blank", "confidence": 0.0, "status": "skipped_missing_target"},
        ],
    })
    result = action.update()
    assert result.done is True
    assert result.failed is False
    assert result.actions == []
    d = result.detail
    assert d["detected_count"] == 1
    assert d["blank_count"] == 2
    assert d["skipped_count"] == 2
    assert d["barrel_count"] == 5
    barrels = d["recon_report"]["barrels"]
    assert len(barrels) == 5
    assert barrels[0]["status"] == "detected"
    assert barrels[0]["content"] == "baozha"


def test_empty_items_no_crash() -> None:
    action = BuildReconReportAction()
    action.start({"items": []})
    result = action.update()
    assert result.done is True
    assert result.actions == []
    assert result.detail["barrel_count"] == 0
    assert result.detail["detected_count"] == 0
    assert result.detail["blank_count"] == 0
    assert result.detail["skipped_count"] == 0


def test_non_dict_item_skipped() -> None:
    action = BuildReconReportAction()
    action.start({"items": ["not_a_dict", None, 42]})
    result = action.update()
    assert result.done is True
    assert result.detail["barrel_count"] == 3
    assert result.detail["skipped_count"] == 3


def test_no_flight_actions_produced() -> None:
    action = BuildReconReportAction()
    action.start({"items": [
        {"target_id": "r0", "content": "shenghua", "confidence": 0.90, "status": "detected"},
    ]})
    result = action.update()
    assert result.actions == []


def test_gps_hover_report_fields_are_normalized() -> None:
    action = BuildReconReportAction()
    action.start({"items": [{"target_id": "r1", "status": "confirmed", "hazard_label": "danger_3", "confidence_max": 0.91, "confidence_mean": 0.8}]})
    barrel = action.update().detail["recon_report"]["barrels"][0]
    assert barrel["status"] == "confirmed"
    assert barrel["content"] == "danger_3"
    assert barrel["confidence"] == 0.91
