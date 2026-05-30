from __future__ import annotations

import csv
import json

from missions.common.recce import RecceResultItem
from missions.common.recce_output import write_recce_results


def test_write_recce_results_json_and_csv(tmp_path) -> None:
    item = RecceResultItem(
        cylinder_key="track:12",
        cylinder_track_id=12,
        hazard_class="flammable",
        vote_count=5,
        confidence_sum=3.8,
        max_confidence=0.92,
        status="confirmed",
    )

    paths = write_recce_results(
        output_dir=tmp_path / "missing" / "recce",
        mission="rescue_competition",
        timestamp=1_700_000_000.0,
        items=[item],
    )

    assert len(paths) == 2
    json_path = next(path for path in paths if path.suffix == ".json")
    csv_path = next(path for path in paths if path.suffix == ".csv")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["mission"] == "rescue_competition"
    assert payload["items"][0]["hazard_class"] == "flammable"
    assert payload["items"][0]["status"] == "confirmed"

    with csv_path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["cylinder_key"] == "track:12"
    assert rows[0]["cylinder_track_id"] == "12"
    assert rows[0]["hazard_class"] == "flammable"


def test_write_recce_results_can_disable_formats(tmp_path) -> None:
    paths = write_recce_results(
        output_dir=tmp_path,
        mission="rescue_competition",
        timestamp=1.0,
        items=[],
        write_json=False,
        write_csv=True,
    )

    assert len(paths) == 1
    assert paths[0].suffix == ".csv"
