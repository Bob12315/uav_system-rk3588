"""Supported formal Action Mission template catalog."""
from __future__ import annotations

import json

from fastapi import HTTPException

from app.config import ROOT_DIR


ACTION_MISSION_TEMPLATE_DIR = ROOT_DIR / "config" / "action_missions"
ACTION_MISSION_TEMPLATE_NAMES = {
    "drop_two_targets": "投放任务 v2",
    "recon_gps": "GPS 侦察任务 v2",
    "rescue_2026_full_auto": "完整流程 v2",
}


def load_action_mission_template(name: str) -> dict:
    if name not in ACTION_MISSION_TEMPLATE_NAMES:
        raise HTTPException(status_code=404, detail="unknown action mission template")
    path = (ACTION_MISSION_TEMPLATE_DIR / f"{name}.json").resolve()
    template_dir = ACTION_MISSION_TEMPLATE_DIR.resolve()
    if path.parent != template_dir or path.suffix != ".json":
        raise HTTPException(status_code=404, detail="unknown action mission template")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="action mission template not found") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"invalid template JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
        raise HTTPException(status_code=500, detail="invalid action mission template structure")
    return data
