from missions.common.actions.select_recon_targets import SelectReconTargetsAction


def _objects(count: int):
    return [{"id": f"b{i}", "class_name": "bucket", "local_x": i * 0.6,
             "local_y": 5.0, "seen_count": count - i, "raw_count": count - i,
             "weight": float(count - i)} for i in range(count)]


def _run(objects, **params):
    action = SelectReconTargetsAction()
    action.start({"objects": objects, "target_count": 5, "allow_fewer": True,
                  "deduplicate_radius_m": 0.45, **params})
    return action.update({})


def test_selects_five_recon_targets():
    result = _run(_objects(5))
    assert result.done
    assert result.detail["selected_count"] == 5


def test_allow_fewer_selects_three():
    result = _run(_objects(3))
    assert result.done
    assert result.detail["selected_count"] == 3


def test_disallow_fewer_fails():
    result = _run(_objects(3), allow_fewer=False)
    assert result.failed and result.reason == "not_enough_recon_targets"


def test_zero_targets_fails():
    result = _run([])
    assert result.failed and result.reason == "no_recon_targets"


def test_deduplicates_and_rejects_missing_coordinates():
    objects = _objects(2)
    objects[1]["local_x"] = 0.1
    objects.append({"id": "bad", "class_name": "bucket", "seen_count": 2})
    result = _run(objects)
    assert result.detail["selected_count"] == 1
    reasons = {item["reason"] for item in result.detail["rejected_objects"]}
    assert {"duplicate_near_selected", "missing_xy"} <= reasons
