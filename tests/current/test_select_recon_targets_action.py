from missions.common.actions.select_recon_targets import SelectReconTargetsAction


def _objects(count: int):
    return [{"id": f"b{i}", "class_name": "bucket", "local_x": i * 0.6,
             "local_y": 5.0, "seen_count": count - i, "raw_count": count - i,
             "weight": float(count - i)} for i in range(count)]


def _run(objects, context=None, **params):
    action = SelectReconTargetsAction()
    action.start({"objects": objects, "target_count": 5, "allow_fewer": True,
                  "deduplicate_radius_m": 0.45, **params})
    return action.update(context or {})


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
    result = _run([], allow_fewer=False)
    assert result.failed and result.reason == "no_recon_targets"


def test_deduplicates_and_rejects_missing_coordinates():
    objects = _objects(2)
    objects[1]["local_x"] = 0.1
    objects.append({"id": "bad", "class_name": "bucket", "seen_count": 2})
    result = _run(objects)
    assert result.detail["selected_count"] == 1
    reasons = {item["reason"] for item in result.detail["rejected_objects"]}
    assert {"duplicate_near_selected", "missing_xy"} <= reasons


def test_allow_fewer_zero_targets_success():
    result = _run([], allow_fewer=True)
    assert result.done is True
    assert result.failed is False
    assert result.detail["selected_count"] == 0
    assert result.detail["selected_targets"] == []
    slots = result.detail["target_slots"]
    assert len(slots) == 5
    for slot in slots:
        assert slot["valid"] is False
        assert slot["local_x"] is None
        assert slot["local_y"] is None
        assert slot["x"] is None
        assert slot["y"] is None
        assert slot["status"] == "missing"


def test_allow_fewer_false_zero_targets_still_fails():
    action = SelectReconTargetsAction()
    action.start({"objects": [], "target_count": 5, "allow_fewer": False, "deduplicate_radius_m": 0.45})
    result = action.update({})
    assert result.failed is True


# ── zone_center_mode tests ──────────────────────────────────────────────


def test_zone_center_mode_local_default():
    """zone_center_mode 默认 local，行为与旧版一致。"""
    result = _run(_objects(5), zone_center={"x": 0.0, "y": 0.0})
    assert result.done
    assert result.detail["selected_count"] == 5


def test_zone_center_mode_field_with_complete_context():
    """zone_center_mode=field 且有完整 field reference 时正确转换并排序。"""
    ctx = {
        "field_heading_confirmed": True,
        "field_origin_confirmed": True,
        "field_heading_yaw_rad": 0.0,
        "field_origin_local_x": 100.0,
        "field_origin_local_y": 200.0,
    }
    # zone_center field (0,10) with heading=0, origin=(100,200) → local (110, 200)
    # near: (110,200) distance=0, far: (100,210) distance≈14.14 → near wins
    near = {"id": "near", "class_name": "bucket", "local_x": 110.0, "local_y": 200.0,
            "seen_count": 1, "raw_count": 1, "weight": 1.0}
    far = {"id": "far", "class_name": "bucket", "local_x": 100.0, "local_y": 210.0,
           "seen_count": 1, "raw_count": 1, "weight": 1.0}
    action = SelectReconTargetsAction()
    action.start({"objects": [far, near], "target_count": 1, "allow_fewer": True,
                  "deduplicate_radius_m": 0.45, "zone_center": {"x": 0.0, "y": 10.0},
                  "zone_center_mode": "field"})
    result = action.update(ctx)
    assert result.done
    assert result.detail["selected_count"] == 1
    assert result.detail["selected_targets"][0]["id"] == "near"


def test_zone_center_mode_field_heading_pi_over_2():
    """zone_center_mode=field heading=π/2 时转换及排序正确。"""
    import math
    ctx = {
        "field_heading_confirmed": True,
        "field_origin_confirmed": True,
        "field_heading_yaw_rad": math.pi / 2,
        "field_origin_local_x": 0.0,
        "field_origin_local_y": 0.0,
    }
    # zone_center field (0,10), origin=(0,0), heading=π/2 → local (0, 10)
    # near: (0,10) distance=0, far: (10,0) distance≈14.14 → near wins
    near = {"id": "near", "class_name": "bucket", "local_x": 0.0, "local_y": 10.0,
            "seen_count": 1, "raw_count": 1, "weight": 1.0}
    far = {"id": "far", "class_name": "bucket", "local_x": 10.0, "local_y": 0.0,
           "seen_count": 1, "raw_count": 1, "weight": 1.0}
    action = SelectReconTargetsAction()
    action.start({"objects": [far, near], "target_count": 1, "allow_fewer": True,
                  "deduplicate_radius_m": 0.45, "zone_center": {"x": 0.0, "y": 10.0},
                  "zone_center_mode": "field"})
    result = action.update(ctx)
    assert result.done
    assert result.detail["selected_count"] == 1
    assert result.detail["selected_targets"][0]["id"] == "near"


def test_zone_center_mode_field_missing_confirmed():
    """zone_center_mode=field 但 field_heading_confirmed 缺失 → failed。"""
    ctx = {
        "field_heading_confirmed": False,
        "field_origin_confirmed": True,
    }
    action = SelectReconTargetsAction()
    action.start({"objects": _objects(5), "target_count": 5, "allow_fewer": True,
                  "deduplicate_radius_m": 0.45, "zone_center": {"x": 0.0, "y": 10.0},
                  "zone_center_mode": "field"})
    result = action.update(ctx)
    assert result.failed
    assert result.reason == "missing_field_reference_for_zone_center"


def test_zone_center_mode_field_missing_values():
    """zone_center_mode=field 但 field_heading_yaw_rad 缺失 → failed。"""
    ctx = {
        "field_heading_confirmed": True,
        "field_origin_confirmed": True,
        "field_origin_local_x": 100.0,
        "field_origin_local_y": 200.0,
    }
    action = SelectReconTargetsAction()
    action.start({"objects": _objects(5), "target_count": 5, "allow_fewer": True,
                  "deduplicate_radius_m": 0.45, "zone_center": {"x": 0.0, "y": 10.0},
                  "zone_center_mode": "field"})
    result = action.update(ctx)
    assert result.failed
    assert result.reason == "missing_field_reference_for_zone_center"
