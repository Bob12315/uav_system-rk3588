from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.app_config import UiConfig
from telemetry_link.command_dispatcher import CommandResult
from web_ui.audit import AuditLog
from web_ui.config_store import ConfigStore
from web_ui.server import create_app


def test_config_store_saves_and_restores_approved_yaml(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "missions" / "demo").mkdir(parents=True)
    app_file = tmp_path / "config" / "app.yaml"
    app_file.write_text("runtime:\n  loop_hz: 20\n", encoding="utf-8")
    (tmp_path / "config" / "telemetry.yaml").write_text("value: 1\n", encoding="utf-8")
    (tmp_path / "config" / "yolo.yaml").write_text("value: 1\n", encoding="utf-8")
    (tmp_path / "missions" / "demo" / "config.yaml").write_text("name: demo\n", encoding="utf-8")
    store = ConfigStore(tmp_path)

    diff = store.save("config/app.yaml", "runtime:\n  loop_hz: 30\n")

    assert "loop_hz: 30" in diff
    assert app_file.with_suffix(".yaml.bak").read_text(encoding="utf-8") == "runtime:\n  loop_hz: 20\n"

    store.restore("config/app.yaml")

    assert app_file.read_text(encoding="utf-8") == "runtime:\n  loop_hz: 20\n"


def test_config_store_rejects_arbitrary_paths_and_invalid_yaml(tmp_path: Path) -> None:
    (tmp_path / "config").mkdir()
    (tmp_path / "missions").mkdir()
    (tmp_path / "config" / "app.yaml").write_text("runtime: {}\n", encoding="utf-8")
    (tmp_path / "config" / "telemetry.yaml").write_text("value: 1\n", encoding="utf-8")
    (tmp_path / "config" / "yolo.yaml").write_text("value: 1\n", encoding="utf-8")
    store = ConfigStore(tmp_path)

    with pytest.raises(ValueError):
        store.resolve("../secret.yaml")
    with pytest.raises(ValueError):
        store.save("config/app.yaml", "- invalid root\n")


def test_audit_log_is_persistent(tmp_path: Path) -> None:
    log = AuditLog(str(tmp_path / "audit.jsonl"))
    log.append("BUTTON", "control send off", True, "disabled")

    entries = AuditLog(str(tmp_path / "audit.jsonl")).read_latest()

    assert entries[0]["source"] == "BUTTON"
    assert entries[0]["action"] == "control send off"


class _FakeRunner:
    def web_status_snapshot(self):
        return {"mission": "visual_tracking", "events": []}

    def web_missions(self):
        return [{"name": "visual_tracking", "active": True}]

    def web_execute_command(self, command: str):
        return CommandResult(True, f"sent: {command}")

    def reconnect_telemetry_from_saved_config(self):
        return CommandResult(True, "reconnecting")

    def restart_external_service(self, service: str):
        return CommandResult(True, f"restart {service}")

    def apply_active_mission_config(self, _path: str):
        return CommandResult(True, "applied")


def test_web_api_executes_command_and_records_audit(tmp_path: Path) -> None:
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    app = create_app(
        _FakeRunner(),
        UiConfig(True, False, "127.0.0.1", 8080, str(tmp_path / "audit.jsonl")),
    )
    client = TestClient(app)

    response = client.post("/api/commands/execute", json={"command": "target next", "source": "BUTTON"})

    assert response.json()["ok"] is True
    audit = client.get("/api/audit").json()
    assert audit[0]["action"] == "target next"


def test_web_ui_exposes_manual_step_movement_controls() -> None:
    static_dir = Path(__file__).parents[1] / "web_ui" / "static"
    index = (static_dir / "index.html").read_text(encoding="utf-8")
    script = (static_dir / "app.js").read_text(encoding="utf-8")

    assert 'id="moveStep"' in index
    assert 'id="yawStep"' in index
    assert 'data-manual-move="forward"' in index
    assert 'data-manual-move="down"' in index
    assert 'data-manual-yaw="left"' in index
    assert "bodyOffsetToLocalOffset" in script
    assert '"/api/manual-step-move"' in script
    assert "JSON.stringify({direction, step_m: step})" in script
    assert 'body_offset' not in script
    assert "condition_yaw ${angle} 20 ${turn} relative" in script
    assert "signedAngle" not in script


def test_web_ui_distinguishes_selected_and_current_mission_steps() -> None:
    static_dir = Path(__file__).parents[1] / "web_ui" / "static"
    script = (static_dir / "app.js").read_text(encoding="utf-8")
    styles = (static_dir / "style.css").read_text(encoding="utf-8")

    assert 'next.mission_stage_selection || "AUTO"' in script
    assert 'mission?.selected_stage || "AUTO"' in script
    assert 'const active = viewingActiveMission ? next.stage || "" : "";' in script
    assert 'const command = `mission stage ${mode}`;' in script
    assert 'viewingActiveMission ? "" : "disabled"' in script
    assert "selected-mode" in script
    assert "current-mode" in script
    assert ".mission-steps button.selected-mode" in styles
    assert ".mission-steps button.current-mode" in styles


def test_web_ui_exposes_read_only_field_map() -> None:
    static_dir = Path(__file__).parents[1] / "web_ui" / "static"
    index = (static_dir / "index.html").read_text(encoding="utf-8")
    script = (static_dir / "app.js").read_text(encoding="utf-8")
    styles = (static_dir / "style.css").read_text(encoding="utf-8")

    assert 'id="fieldMap"' in index
    assert 'id="fieldMapLegend"' in index
    assert "function renderFieldMap(next)" in script
    assert "mission_detail" in script
    assert "mission_position" in script
    assert "drawCoordinateTicks" in script
    assert "drawTargetCoordinateList" in script
    assert "筒坐标" in script
    assert "Number(item.seen_count || 0) > 0" in script
    assert "ctx.rotate" not in script
    assert ".field-map-wrap" in styles


def test_action_lab_start_uses_confirmation_instead_of_send_checkbox() -> None:
    static_dir = Path(__file__).parents[1] / "web_ui" / "static"
    index = (static_dir / "index.html").read_text(encoding="utf-8")
    script = (static_dir / "app.js").read_text(encoding="utf-8")

    assert "actionSendToggle" not in index
    assert 'id="actionDryRunStart"' in index
    assert 'id="actionDispatchStart"' in index
    assert 'id="actionStop"' in index
    assert 'id="actionRunToggle"' in index
    assert 'id="actionSelected"' in index
    assert 'id="actionRunningAction"' in index
    assert 'id="actionSwitchHint"' in index
    assert "Send actions to vehicle/simulator" not in index
    assert "普通 Action；Dispatch 请求下发，实际发送仍受系统 SEND 和 dispatch 结果约束。" in script
    assert 'async function startActionLabAction(sendActions)' in script
    assert 'if (sendActions) {' in script
    assert 'window.confirm(' in script
    assert "if (!confirmed) return;" in script
    assert "send_actions: Boolean(sendActions)" in script
    assert 'console.log("Action Lab start request body", requestBody);' in script
    assert "?v=ui1-action-first" in index
    assert "$(\"actionSendToggle\").checked" not in script
    assert "let actionParamCache = {};" in script
    assert "function cacheSelectedActionParams()" in script
    assert "function toggleActionLabRun()" in script
    assert "selectedActionIsRunning()" in script
    confirm_index = script.index("window.confirm(")
    cancel_index = script.index("if (!confirmed) return;", confirm_index)
    body_index = script.index("const requestBody = {", cancel_index)
    send_actions_index = script.index("send_actions: Boolean(sendActions)", body_index)
    post_index = script.index('json("/api/actions/start"', send_actions_index)
    assert confirm_index < cancel_index < body_index < send_actions_index < post_index


def test_action_lab_start_confirm_controls_api_request() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    root = Path(__file__).parents[1]
    code = r"""
const fs = require("fs");
const source = fs.readFileSync("web_ui/static/app.js", "utf8");
const start = source.indexOf("async function startActionLabAction(sendActions)");
const end = source.indexOf("\nasync function stopActionLabAction()", start);
if (start < 0 || end < 0) throw new Error("startActionLabAction source not found");
const fnSource = source.slice(start, end);
let selectedActionName = "align_descend";
let confirmValue = false;
let calls = [];
let logs = [];
function parseActionParams() { return {foo: 1}; }
async function json(url, options) {
  calls.push({url, options, body: JSON.parse(options.body)});
  return {ok: true, note: "ok", action_lab: {status: {last_result: {detail: {}}}}};
}
function $(id) { return {textContent: ""}; }
function renderActionLabStatus() {}
function renderFieldMap() {}
let state = {};
globalThis.window = {confirm: () => confirmValue};
globalThis.console = {log: (...args) => logs.push(args)};
eval(fnSource);
(async () => {
  await startActionLabAction(false);
  if (calls.length !== 1) throw new Error("dry-run start should call start API");
  if (calls[0].body.send_actions !== false) throw new Error("dry-run send_actions was not false");
  await startActionLabAction(true);
  if (calls.length !== 1) throw new Error("confirm=false dispatch should not call start API");
  confirmValue = true;
  await startActionLabAction(true);
  if (calls.length !== 2) throw new Error("confirm=true should call start API once more");
  if (calls[1].url !== "/api/actions/start") throw new Error("wrong start URL");
  if (calls[1].body.send_actions !== true) throw new Error("send_actions was not true");
  if (!logs.some(item => item[0] === "Action Lab start request body" && item[1].send_actions === true)) {
    throw new Error("missing start request console log");
  }
})().catch(error => {
  process.stderr.write(error.stack || String(error));
  process.exit(1);
});
"""
    result = subprocess.run(
        [node, "-e", code],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_action_mission_frontend_preserves_save_as_in_configure_request() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    root = Path(__file__).parents[1]
    code = r"""
const fs = require("fs");
const source = fs.readFileSync("web_ui/static/app.js", "utf8");
const start = source.indexOf("function parseActionMissionSteps()");
const end = source.indexOf("\nasync function startActionMission()", start);
if (start < 0 || end < 0) throw new Error("Action Mission parser source not found");
const fnSource = source.slice(start, end);
let calls = [];
const mission = {
  name: "test_mission",
  steps: [
    {
      name: "multi_view_localize",
      label: "drop_scan_label",
      save_as: "drop_scan",
      on_failed: {action: "retry_current", max_attempts: 2},
      params: {
        waypoint_mode: "absolute",
        waypoints: [{x: 0, y: 0, altitude_m: 3}],
      },
    },
    {
      name: "select_drop_targets",
      save_as: "drop_targets",
      params: {
        objects: "$drop_scan.localized_objects",
        target_count: 2,
      },
    },
  ],
};
const elements = {
  actionMissionSteps: {value: JSON.stringify(mission)},
  completionHint: {textContent: ""},
};
function $(id) { return elements[id]; }
async function json(url, options) {
  calls.push({url, body: JSON.parse(options.body)});
  return {ok: true, action_mission: {enabled: true}};
}
function renderActionMissionStatus() {}
eval(fnSource);
configureActionMission().then(() => {
  if (calls.length !== 1) throw new Error("configure should call API once");
  if (calls[0].url !== "/api/action-mission/configure") throw new Error("wrong configure URL");
  const steps = calls[0].body.steps;
  if (steps[0].save_as !== "drop_scan") throw new Error("drop_scan save_as was not preserved");
  if (steps[0].label !== "drop_scan_label") throw new Error("label was not preserved");
  if (steps[0].on_failed.action !== "retry_current") throw new Error("on_failed was not preserved");
  if (steps[1].save_as !== "drop_targets") throw new Error("drop_targets save_as was not preserved");
  if (steps[1].params.objects !== "$drop_scan.localized_objects") throw new Error("params object reference was not preserved");
}).catch(error => {
  process.stderr.write(error.stack || String(error));
  process.exit(1);
});
"""
    result = subprocess.run(
        [node, "-e", code],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_action_lab_frontend_caches_params_and_uses_run_toggle() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    root = Path(__file__).parents[1]
    code = r"""
const fs = require("fs");
const source = fs.readFileSync("web_ui/static/app.js", "utf8");
const start = source.indexOf("async function loadActionLab()");
const end = source.indexOf("\nasync function loadConfigFiles()", start);
if (start < 0 || end < 0) throw new Error("Action Lab source not found");
const fnSource = source.slice(start, end);
let selectedActionName = "";
let actionParamCache = {};
let latestActionLab = null;
let state = {controllers: {send_commands: false}};
let actionSpecs = [
  {name: "goto_waypoint", label: "Goto", default_params: {x: 1}},
  {name: "payload_release", label: "Payload", default_params: {channel: 8}},
];
let stopCalls = 0;
let startCalls = 0;
const elements = {
  actionParams: {value: "", oninput: null},
  actionState: {textContent: ""},
  actionDryRun: {textContent: ""},
  actionSelected: {textContent: ""},
  actionRunningAction: {textContent: ""},
  actionRunning: {textContent: ""},
  actionReason: {textContent: ""},
  actionDone: {textContent: ""},
  actionFailed: {textContent: ""},
  actionRunToggle: {textContent: "", classList: {toggle: () => {}}},
  actionSwitchHint: {textContent: ""},
  actionHighlights: {innerHTML: "", classList: {toggle: () => {}}},
  actionStatusJson: {textContent: ""},
  completionHint: {textContent: ""},
  actionParamHint: {textContent: ""},
  actionSafetyHint: {textContent: ""},
  actionGateRequested: {textContent: ""},
  actionGateEffective: {textContent: ""},
  actionGateSystemSend: {textContent: ""},
  actionGateDryRun: {textContent: ""},
  actionGateSentCount: {textContent: ""},
  actionGateSkippedCount: {textContent: ""},
  actionGateErrorCount: {textContent: ""},
  actionGateNote: {textContent: ""},
};
function $(id) { return elements[id]; }
function escapeHtml(value) { return String(value); }
function setOptionalText(id, value) { if (elements[id]) elements[id].textContent = value; }
function dispatchFromActionLab(payload) { return payload.dispatch || {}; }
function countDispatchItems(value) { return Array.isArray(value) ? value.length : 0; }
const ACTION_SAFETY_HINTS = {};
globalThis.document = {querySelectorAll: () => []};
eval(fnSource);
stopActionLabAction = () => { stopCalls += 1; return Promise.resolve(); };
startActionLabAction = () => { startCalls += 1; return Promise.resolve(); };
selectAction("goto_waypoint");
elements.actionParams.value = "{\"x\":42}";
selectAction("payload_release");
if (elements.actionParams.value !== JSON.stringify({channel: 8}, null, 2)) {
  throw new Error("payload should load default on first open");
}
elements.actionParams.value = "{\"channel\":9}";
selectAction("goto_waypoint");
if (elements.actionParams.value !== "{\"x\":42}") {
  throw new Error("goto params were not cached");
}
selectAction("payload_release");
if (elements.actionParams.value !== "{\"channel\":9}") {
  throw new Error("payload params were not cached");
}
renderActionLabStatus({status: {running: true, action_name: "payload_release", last_result: {}}, note: "action_dispatch_enabled", send_actions_effective: true});
if (elements.actionRunToggle.textContent !== "停止") throw new Error("running selected action should show stop");
toggleActionLabRun().then(() => {
  if (stopCalls !== 1 || startCalls !== 0) throw new Error("toggle should stop selected running action");
  selectAction("goto_waypoint");
  if (!elements.actionSwitchHint.textContent.includes("点击“开始”将停止 payload_release 并启动 goto_waypoint")) {
    throw new Error("missing running/selected switch hint");
  }
  if (elements.actionRunToggle.textContent !== "开始") throw new Error("different selected action should show start");
  return toggleActionLabRun();
}).then(() => {
  if (startCalls !== 1) throw new Error("toggle should start selected non-running action");
}).catch(error => {
  process.stderr.write(error.stack || String(error));
  process.exit(1);
});
"""
    result = subprocess.run(
        [node, "-e", code],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
