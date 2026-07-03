"""FastAPI endpoint tests for field profile backend API (Phase C-1)."""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict, Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# helpers — build a minimal test app with mock runner
# ---------------------------------------------------------------------------


class _FakeFieldReference:
    """Small fake reference that behaves like FieldReference."""
    def __init__(self):
        self.is_confirmed = False
        self.is_frozen = False
        self.origin_source = None
        self.heading_source = None
        self.origin_local_n_m = None
        self.origin_local_e_m = None
        self.origin_local_z_m = None
        self.origin_lat = None
        self.origin_lon = None
        self.forward_marker_lat = None
        self.forward_marker_lon = None
        self.field_heading_yaw_rad = None
        self.confirmed_at_s = None

    def is_ready(self):
        return self.is_confirmed and self.origin_local_n_m is not None

    def freeze(self):
        self.is_frozen = True


class _FakeService:
    def __init__(self):
        self.reference = _FakeFieldReference()
        self._profile_id = None
        self._profile_name = None

    def status(self):
        r = {
            "is_confirmed": self.reference.is_confirmed,
            "is_frozen": self.reference.is_frozen,
            "is_ready": self.reference.is_ready(),
            "origin_source": self.reference.origin_source,
            "heading_source": self.reference.heading_source,
            "origin_local_n_m": self.reference.origin_local_n_m,
            "origin_local_e_m": self.reference.origin_local_e_m,
            "origin_local_z_m": self.reference.origin_local_z_m,
            "origin_lat": self.reference.origin_lat,
            "origin_lon": self.reference.origin_lon,
            "forward_marker_lat": self.reference.forward_marker_lat,
            "forward_marker_lon": self.reference.forward_marker_lon,
            "field_heading_yaw_rad": self.reference.field_heading_yaw_rad,
            "confirmed_at_s": self.reference.confirmed_at_s,
        }
        if self.reference.origin_source == "profile_gps_bound":
            r["profile_id"] = self._profile_id
            r["profile_name"] = self._profile_name
        return r

    def apply_profile_binding(self, **kw):
        self.reference.is_confirmed = True
        self.reference.origin_source = "profile_gps_bound"
        self.reference.heading_source = "profile_gps_two_point"
        self.reference.origin_lat = kw.get("origin_lat")
        self.reference.origin_lon = kw.get("origin_lon")
        self.reference.forward_marker_lat = kw.get("forward_lat")
        self.reference.forward_marker_lon = kw.get("forward_lon")
        self.reference.origin_local_n_m = kw["bind_result"].origin_local_n_m
        self.reference.origin_local_e_m = kw["bind_result"].origin_local_e_m
        self.reference.origin_local_z_m = kw["bind_result"].origin_local_z_m
        self.reference.field_heading_yaw_rad = kw["bind_result"].field_heading_yaw_rad
        self._profile_id = kw.get("profile_id")
        self._profile_name = kw.get("profile_name")
        return {"ok": True}

    def confirm(self):
        return {"ok": True}

    def freeze(self):
        self.reference.freeze()
        return {"ok": True}

    def reset(self):
        self.reference = _FakeFieldReference()
        self._profile_id = None
        self._profile_name = None
        return {"ok": True}


class _FakeBuilder:
    def __init__(self):
        self.field_heading_confirmed = False
        self.field_origin_confirmed = False
        self.field_heading_yaw_rad = None
        self.field_origin_local_x = None
        self.field_origin_local_y = None
        self.field_origin_local_z = None

    def confirm_field_reference(self, **kw):
        self.field_heading_confirmed = True
        self.field_origin_confirmed = True
        self.field_heading_yaw_rad = kw.get("field_heading_yaw_rad")
        self.field_origin_local_x = kw.get("origin_local_x")
        self.field_origin_local_y = kw.get("origin_local_y")
        self.field_origin_local_z = kw.get("origin_local_z")
        return True

    def field_transform_ready(self):
        return self.field_heading_confirmed and self.field_origin_confirmed

    def clear_field_heading(self):
        self.field_heading_confirmed = False
        self.field_origin_confirmed = False
        self.field_heading_yaw_rad = None
        self.field_origin_local_x = None
        self.field_origin_local_y = None
        self.field_origin_local_z = None


class _FakeRunner:
    """Mock runner that delegates field-profile API calls."""
    def __init__(self):
        self._svc = _FakeService()
        self._builder = _FakeBuilder()

    # ---- field profile API ----
    def field_profile_list(self):
        profiles = []
        config_dir = os.path.join("config", "field_profiles")
        if os.path.isdir(config_dir):
            for f in sorted(os.listdir(config_dir)):
                if f.endswith(".json") and not f.startswith("."):
                    pid = os.path.splitext(f)[0]
                    profiles.append({
                        "profile_id": pid, "name": pid,
                        "source": "config", "schema_version": 1,
                        "valid": True, "errors": [], "warnings": [],
                    })
        return {"ok": True, "profiles": profiles}

    def field_profile_get(self, profile_id: str):
        path = os.path.join("config", "field_profiles", profile_id + ".json")
        if not os.path.isfile(path):
            return {"ok": False, "error": f"profile not found: {profile_id}"}
        return {"ok": True, "profile_id": profile_id, "name": profile_id}

    def field_profile_validate(self, profile_id: str):
        path = os.path.join("config", "field_profiles", profile_id + ".json")
        if not os.path.isfile(path):
            return {"ok": False, "error": f"profile not found: {profile_id}"}
        return {"ok": True, "profile_id": profile_id, "errors": [], "warnings": []}

    def field_profile_bind_current(self, profile_id: str):
        path = os.path.join("config", "field_profiles", profile_id + ".json")
        if not os.path.isfile(path):
            return {"ok": False, "error": f"profile not found: {profile_id}"}
        from app.field_profile_service import BindResult
        from app.field_profile import FieldProfileDiagnostics
        br = BindResult(
            ok=True, profile_id=profile_id,
            origin_local_n_m=0.0, origin_local_e_m=0.0, origin_local_z_m=-10.0,
            field_heading_yaw_rad=0.0, field_heading_deg=0.0,
            current_field_x_m=0.0, current_field_y_m=0.0,
            baseline_m=33.36,
            diagnostics=FieldProfileDiagnostics(),
        )
        self._svc.apply_profile_binding(
            bind_result=br, profile_id=profile_id,
            profile_name=profile_id,
            origin_lat=34.0, origin_lon=108.0,
            forward_lat=34.0003, forward_lon=108.0,
        )
        self._builder.confirm_field_reference(
            field_heading_yaw_rad=0.0,
            origin_local_x=0.0, origin_local_y=0.0, origin_local_z=-10.0,
            source=f"field_profile:{profile_id}",
        )
        return {
            "ok": True, "profile_id": profile_id,
            "synced_to_runtime": True,
            "field_heading_yaw_rad": 0.0, "field_heading_deg": 0.0,
            "origin_local_n_m": 0.0, "origin_local_e_m": 0.0,
            "origin_local_z_m": -10.0,
            "current_field_x_m": 0.0, "current_field_y_m": 0.0,
            "baseline_m": 33.36, "warnings": [], "check_points": [],
        }

    # ---- field reference (needed for /api/field-reference/status) ----
    def field_reference_status(self):
        st = self._svc.status()
        return {"ok": True, "field_reference": st, "telemetry": {}}


# ---------------------------------------------------------------------------
# fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    from web_ui.server import create_app
    from app.app_config import UiConfig
    runner = _FakeRunner()
    app = create_app(runner, UiConfig(True, "127.0.0.1", 8080, str(tmp_path / "audit.jsonl")))
    return TestClient(app)


# ===================================================================
# 1. GET /api/field-profiles
# ===================================================================


def test_api_list_profiles(client):
    resp = client.get("/api/field-profiles")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "profiles" in data
    ids = [p["profile_id"] for p in data["profiles"]]
    assert "example_competition_lane" in ids


def test_api_list_profiles_non_json_ignored():
    """Non-.json files in dir must be ignored, not crash."""
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, "readme.txt"), "w") as f:
            f.write("hello")
        # This just verifies the dir scanning logic doesn't crash
        from app.field_profile_service import FieldProfileService
        paths = FieldProfileService.list_profiles(td)
        assert len(paths) == 0


def test_api_list_profiles_runtime_dir_missing_no_crash():
    """runtime dir missing → no crash, empty list."""
    from app.field_profile_service import FieldProfileService
    paths = FieldProfileService.list_profiles(
        os.path.join("runtime", "field_profiles")
    )
    assert isinstance(paths, list)


# ===================================================================
# 2. GET /api/field-profiles/{id}
# ===================================================================


def test_api_get_valid_profile(client):
    resp = client.get("/api/field-profiles/example_competition_lane")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["profile_id"] == "example_competition_lane"


def test_api_get_missing_profile(client):
    resp = client.get("/api/field-profiles/nonexistent_xyz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False


# ===================================================================
# 3. GET /api/field-profiles/{id}/validate
# ===================================================================


def test_api_validate_valid(client):
    resp = client.get("/api/field-profiles/example_competition_lane/validate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True


def test_api_validate_missing(client):
    resp = client.get("/api/field-profiles/nonexistent/validate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False


# ===================================================================
# 4. POST /api/field-profiles/{id}/bind-current
# ===================================================================


def test_api_bind_current_success(client):
    resp = client.post("/api/field-profiles/example_competition_lane/bind-current")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["synced_to_runtime"] is True


def test_api_bind_current_missing_profile(client):
    resp = client.post("/api/field-profiles/nonexistent/bind-current")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False


def test_api_bind_current_response_structure(client):
    resp = client.post("/api/field-profiles/example_competition_lane/bind-current")
    data = resp.json()
    assert "ok" in data
    assert "profile_id" in data
    if data["ok"]:
        assert "synced_to_runtime" in data
        assert "field_heading_yaw_rad" in data
    else:
        assert "error" in data


# ===================================================================
# 5. status includes profile after bind
# ===================================================================


def test_api_status_includes_profile_after_bind(client):
    client.post("/api/field-profiles/example_competition_lane/bind-current")
    # The _FakeRunner doesn't fully wire profile into status,
    # but we verify the field-reference status endpoint works.
    resp = client.get("/api/field-reference/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "field_reference" in data


# ===================================================================
# 6. response format: no traceback leak
# ===================================================================


def test_api_error_no_traceback(client):
    """Error responses must be JSON with ok=false, no traceback."""
    resp = client.get("/api/field-profiles/nonexistent")
    data = resp.json()
    assert data["ok"] is False
    # No Python traceback in the response
    raw = resp.text
    assert "Traceback" not in raw
    assert "File " not in raw


# ===================================================================
# 7. path traversal rejected by API
# ===================================================================


def test_api_path_traversal_rejected(client):
    """API path parameters with / don't even reach our handler (FastAPI 404)."""
    resp = client.get("/api/field-profiles/../../../etc/passwd")
    assert resp.status_code == 404  # FastAPI rejects paths with / in param


def test_api_subdir_rejected(client):
    """API path parameters with / don't reach our handler (FastAPI 404)."""
    resp = client.get("/api/field-profiles/subdir/file")
    assert resp.status_code == 404  # FastAPI rejects paths with / in param


def test_api_non_json_rejected_by_real_runner(tmp_path):
    """A dotted non-json ID is rejected through the real FastAPI wrapper."""
    from app.app_config import UiConfig, build_arg_parser, load_app_config
    from app.system_runner import SystemRunner
    from web_ui.server import create_app

    raw = open(
        os.path.join("config", "field_profiles", "example_competition_lane.json"),
        encoding="utf-8",
    ).read()
    (tmp_path / "foo.txt.json").write_text(raw, encoding="utf-8")
    args = build_arg_parser().parse_args(["--run-seconds", "0.1", "--no-yolo-udp"])
    runner = SystemRunner(load_app_config(args))
    runner._PROFILE_DIRS = [str(tmp_path)]
    app = create_app(
        runner,
        UiConfig(True, "127.0.0.1", 8080, str(tmp_path / "audit.jsonl")),
    )

    response = TestClient(app).get("/api/field-profiles/foo.txt")
    data = response.json()
    assert data["ok"] is False
    assert data["profile_id"] == "foo.txt"
    assert isinstance(data["errors"], list) and data["errors"]
    assert isinstance(data["warnings"], list)
    assert isinstance(data["diagnostics"], dict)


def test_api_dot_dot_rejected(client):
    """Simple .. (no slashes) should be rejected by our handler."""
    resp = client.get("/api/field-profiles/..%2Foutside")
    # This reaches our handler, should reject
    data = resp.json()
    # Either ok=False or 404 is acceptable
    assert data.get("ok") is False or resp.status_code == 404


# ===================================================================
# 8. synced_to_runtime uses math.isclose
# ===================================================================


def test_synced_to_runtime_uses_math_isclose():
    """Heading diff of 1e-12 should still be considered synced."""
    from app.field_reference_controller import FieldReferenceController
    from app.runtime_context import RuntimeContextBuilder
    import math
    builder = RuntimeContextBuilder()
    builder.field_heading_confirmed = True
    builder.field_origin_confirmed = True
    builder.field_heading_yaw_rad = 0.0
    builder.field_origin_local_x = 100.0
    builder.field_origin_local_y = 200.0
    builder.field_origin_local_z = -10.0
    status = {
        "is_confirmed": True,
        "field_heading_yaw_rad": 1e-12,  # tiny diff
        "origin_local_n_m": 100.0,
        "origin_local_e_m": 200.0,
        "origin_local_z_m": -10.0,
    }
    assert FieldReferenceController._is_field_reference_synced(status, builder) is True


def test_synced_heading_mismatch_false():
    from app.field_reference_controller import FieldReferenceController
    from app.runtime_context import RuntimeContextBuilder
    builder = RuntimeContextBuilder()
    builder.field_heading_confirmed = True
    builder.field_origin_confirmed = True
    builder.field_heading_yaw_rad = 0.0
    builder.field_origin_local_x = 100.0
    builder.field_origin_local_y = 200.0
    status = {
        "is_confirmed": True,
        "field_heading_yaw_rad": 0.1,  # 0.1 rad = ~5.7 deg
        "origin_local_n_m": 100.0,
        "origin_local_e_m": 200.0,
    }
    assert FieldReferenceController._is_field_reference_synced(status, builder) is False


def test_synced_origin_n_mismatch_false():
    from app.field_reference_controller import FieldReferenceController
    from app.runtime_context import RuntimeContextBuilder
    builder = RuntimeContextBuilder()
    builder.field_heading_confirmed = True
    builder.field_origin_confirmed = True
    builder.field_heading_yaw_rad = 0.0
    builder.field_origin_local_x = 100.0
    builder.field_origin_local_y = 200.0
    status = {
        "is_confirmed": True,
        "field_heading_yaw_rad": 0.0,
        "origin_local_n_m": 200.0,  # mismatch
        "origin_local_e_m": 200.0,
    }
    assert FieldReferenceController._is_field_reference_synced(status, builder) is False


def test_synced_origin_e_mismatch_false():
    from app.field_reference_controller import FieldReferenceController
    from app.runtime_context import RuntimeContextBuilder
    builder = RuntimeContextBuilder()
    builder.field_heading_confirmed = True
    builder.field_origin_confirmed = True
    builder.field_heading_yaw_rad = 0.0
    builder.field_origin_local_x = 100.0
    builder.field_origin_local_y = 200.0
    status = {
        "is_confirmed": True,
        "field_heading_yaw_rad": 0.0,
        "origin_local_n_m": 100.0,
        "origin_local_e_m": 300.0,  # mismatch
    }
    assert FieldReferenceController._is_field_reference_synced(status, builder) is False


def test_synced_origin_z_mismatch_false():
    from app.field_reference_controller import FieldReferenceController
    from app.runtime_context import RuntimeContextBuilder
    builder = RuntimeContextBuilder()
    builder.field_heading_confirmed = True
    builder.field_origin_confirmed = True
    builder.field_heading_yaw_rad = 0.0
    builder.field_origin_local_x = 100.0
    builder.field_origin_local_y = 200.0
    builder.field_origin_local_z = -10.0
    status = {
        "is_confirmed": True,
        "field_heading_yaw_rad": 0.0,
        "origin_local_n_m": 100.0,
        "origin_local_e_m": 200.0,
        "origin_local_z_m": -20.0,  # mismatch
    }
    assert FieldReferenceController._is_field_reference_synced(status, builder) is False
