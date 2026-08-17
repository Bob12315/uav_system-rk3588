from __future__ import annotations

from application.result_service import ResultService


def test_result_service_owns_defensive_result_snapshots() -> None:
    service = ResultService()
    value = {"objects": [{"id": 1}]}
    service.set("localization", value)
    value["objects"][0]["id"] = 2
    read = service.get("localization")
    read["objects"][0]["id"] = 3
    assert service.get("localization")["objects"][0]["id"] == 1


def test_clear_run_results_keeps_selected_drop_targets() -> None:
    service = ResultService()
    service.set("drop_targets", {"selected": [1]})
    service.set("drop_workflow", {"state": "running"})
    service.clear_run_results()
    assert service.get("drop_targets") == {"selected": [1]}
    assert service.get("drop_workflow") == {}
