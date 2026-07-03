const AppState = window.UavAppState;

let state = {};
let completions = AppState.completions;
let history = AppState.history;

let historyIndex = -1;
// currentConfigPath/currentOriginal moved to config_panel.js (WU-7B v2)
let missionCatalog = [];
let currentActionMission = null;
let currentActionMissionSteps = [];
let lastActionMissionStatus = null;
let lastActionMissionResult = null;
let actionMissionAutoTickTimer = null;
// latestCameraRecording moved to video_panel.js (WU-6 v2)
const fallbackStageModes = ["AUTO", "IDLE", "APPROACH_TRACK", "OVERHEAD_HOLD", "CORRIDOR_FOLLOW"];
const ACTION_SAFETY_HINTS = {
  goto_waypoint: "默认输入 FIELD 坐标（x=右，y=前），转换为 LOCAL_NED 后下发；需要 SEND=ON 才实发。",
  survey_area: "默认航点为 FIELD 坐标，转换为 LOCAL_NED 后连续下发；需要 SEND=ON 才实发。",
  target_lock: "YOLO 锁定命令，不需要 SEND=ON，但需要 Dispatch。",
  align_descend: "BODY_NED 速度控制，需要 SEND=ON 才实发。",
  payload_release: "舵机 PWM 输出，需要 SEND=ON 才实发；确认 SERVO 输出通道和 PWM。",
  single_view_localize: "单帧定位调试 Action：只读取当前 YOLO 检测和飞行状态，计算目标 local 坐标，不发送飞控命令。",
  multi_view_localize: "四点移动采样并融合定位所有筒；会发送 local_position，需要 SEND=ON 才实发。",
};
const ACTION_ZH_LABELS = {
  takeoff: "起飞",
  land: "降落",
  goto_waypoint: "飞到航点",
  survey_area: "区域扫描",
  single_view_localize: "单视角定位",
  multi_view_localize: "多视角定位",
  target_lock: "目标锁定",
  align_descend: "对准下降",
  payload_release: "载荷投放",
  select_drop_targets: "选择投放目标",
  recon_scan: "侦察扫描",
  select_recon_targets: "选择侦察目标",
  recon_inspect_target: "单筒侦察识别",
};
const DEFAULT_ACTION_MISSION_STEPS = [
  {
    name: "goto_waypoint",
    params: {
      x: 0.0,
      y: 0.0,
      altitude_m: 1.5,
      waypoint_mode: "field",
      yaw_mode: "field_heading",
    },
  },
  {
    name: "payload_release",
    params: {
      servo_outputs: [
        {
          servo_output: 8,
          release_pwm: 1200,
          hold_pwm: 1700,
        },
      ],
      payload_id: "p1",
      target_id: "t1",
      release_wait_updates: 1,
    },
  },
];
const actionMissionPresets = {
  dry_goto: [
    {
      name: "goto_waypoint",
      params: {
        x: 0.0,
        y: 0.0,
        altitude_m: 1.5,
        waypoint_mode: "field",
        yaw_mode: "field_heading",
      },
    },
  ],
  payload_release_test: [
    {
      name: "payload_release",
      params: {
        servo_outputs: [
          {
            servo_output: 8,
            release_pwm: 1200,
            hold_pwm: 1700,
          },
        ],
        payload_id: "p1",
        target_id: "t1",
        release_wait_updates: 1,
      },
    },
  ],
  goto_payload_release: [
    {
      name: "goto_waypoint",
      params: {
        x: 0.0,
        y: 0.0,
        altitude_m: 1.5,
        waypoint_mode: "field",
        yaw_mode: "field_heading",
      },
    },
    {
      name: "payload_release",
      params: {
        servo_outputs: [
          {
            servo_output: 8,
            release_pwm: 1200,
            hold_pwm: 1700,
          },
        ],
        payload_id: "p1",
        target_id: "t1",
        release_wait_updates: 1,
      },
    },
  ],
  survey_area_dry: [
    {
      name: "survey_area",
      params: {
        waypoints: [
          {x: 0.0, y: 0.0, altitude_m: 1.5},
          {x: 1.0, y: 0.0, altitude_m: 1.5},
        ],
        waypoint_mode: "field",
        yaw_mode: "field_heading",
        capture_updates_per_waypoint: 1,
        max_updates_per_waypoint: 20,
        detection_source: "scene",
        class_names: ["bucket", "cylinder"],
      },
    },
  ],
  target_lock_test: [
    {
      name: "target_lock",
      params: {
        target: {x: 0.0, y: 0.0},
        max_match_distance_m: 1.0,
        detection_source: "scene",
        class_names: ["bucket", "cylinder"],
        max_updates: 30,
        key: "target_lock_test",
      },
    },
  ],
};

const json = window.UavApi.request;

const {
  stamp,
  escapeHtml,
  num,
  degNum,
  xyzText,
  boolText,
} = window.UavFormat;

const {
  $,
  setOptionalText,
  cards,
  infoRows,
  renderSummaryRows,
} = window.UavDom;

// Field Map thin aliases (WU-5) — functions now in field_map.js
const pointX = function () { return window.UavFieldMap.pointX.apply(window.UavFieldMap, arguments); };
const pointY = function () { return window.UavFieldMap.pointY.apply(window.UavFieldMap, arguments); };
const renderFieldMap = function (next) { return window.UavFieldMap.renderFieldMap(next); };
const setupFieldMapInteractions = function () { window.UavFieldMap.setupFieldMapInteractions(); };

async function execute(command, source = "BUTTON") {
  if (!command) return;
  const result = await json("/api/commands/execute", {
    method: "POST", body: JSON.stringify({command, source})
  });
  $("completionHint").textContent = result.message;
  await loadAudit();
  return result;
}
async function clearLocalization() {
  const result = await json("/api/localization/clear", {method: "POST", body: "{}"});
  $("completionHint").textContent = result.message || "localized object coordinates cleared";
  state.localization = {};
  renderFieldMap(state);
  await loadAudit();
  return result;
}
// Field Map configure (WU-5 v3) — must be before init() and ActionLab
if (window.UavFieldMap && window.UavFieldMap.configure) {
  window.UavFieldMap.configure({
    dom: window.UavDom,
    format: window.UavFormat,
    getState: function () { return state; },
    getLatestActionLab: function () { return window.UavActionLab.getLatestActionLab(); },
    onClearLocalization: clearLocalization,
    setCompletionHint: function (text) { $("completionHint").textContent = text; },
  });
}
function setBadge(element, text, cls) {
  element.textContent = text;
  element.className = `badge ${cls || ""}`;
}
function actionDisplayName(name, fallback = "") {
  const base = String(fallback || name || "--");
  const zh = ACTION_ZH_LABELS[name] || "";
  if (!zh || base.includes(zh)) return base;
  return `${base} ${zh}`;
}
function actionNameWithZh(name) {
  if (!name) return "--";
  return actionDisplayName(name, name);
}
function positiveStep(inputId, label) {
  const value = Number($(inputId).value);
  if (!Number.isFinite(value) || value <= 0) {
    $("completionHint").textContent = `${label}必须大于 0`;
    return null;
  }
  return value;
}
function commandNumber(value) {
  const normalized = Math.abs(value) < 1e-9 ? 0 : value;
  return Number(normalized.toFixed(6)).toString();
}
function bodyOffsetToLocalOffset(offset, yaw) {
  const [forward, right, down] = offset;
  const cosYaw = Math.cos(yaw);
  const sinYaw = Math.sin(yaw);
  return [
    forward * cosYaw - right * sinYaw,
    forward * sinYaw + right * cosYaw,
    down,
  ];
}
function executeManualMove(direction) {
  const step = positiveStep("moveStep", "移动步长");
  if (step === null) return;
  const confirmed = window.confirm(
    `确认手动${direction}移动 ${step} m？\n` +
    "该操作会停止当前 Action/Action Mission，并发送 LOCAL_NED 绝对位置目标，yaw 保持当前值。"
  );
  if (!confirmed) return;
  json("/api/manual-step-move", {
    method: "POST",
    body: JSON.stringify({direction, step_m: step}),
  }).then(result => {
    $("completionHint").textContent = result.message || (result.ok ? "manual step queued" : "manual step failed");
  }).catch(() => {
    $("completionHint").textContent = "manual step move failed";
  });
}
function executeManualYaw(direction) {
  const angle = positiveStep("yawStep", "偏航角度");
  if (angle === null) return;
  const turn = direction === "left" ? "ccw" : "cw";
  execute(`condition_yaw ${angle} 20 ${turn} relative`, "MANUAL_MOVE");
}
function setButtonActive(selector, predicate) {
  document.querySelectorAll(selector).forEach(button => {
    button.classList.toggle("active-choice", Boolean(predicate(button)));
  });
}
function updateControlHighlights(next, drone, controls) {
  const sendEnabled = Boolean(controls.send_commands);
  $("sendToggle").classList.toggle("active-choice", sendEnabled);
  $("sendToggleState").textContent = sendEnabled ? "ON" : "OFF";
  setButtonActive("[data-mode]", button => (drone.mode || "").toUpperCase() === button.dataset.mode);
  setButtonActive("[data-arm-state]", button =>
    (button.dataset.armState === "armed" && drone.armed)
    || (button.dataset.armState === "disarmed" && !drone.armed));
  setButtonActive("[data-source]", button => button.dataset.source === next.active_source);
  ["gimbal", "body", "approach"].forEach(name => {
    const enabled = Boolean(controls[name]);
    const row = document.querySelector(`[data-controller-row="${name}"]`);
    if (!row) return;
    row.classList.toggle("enabled", enabled);
    row.querySelectorAll("button").forEach(button => {
      const command = button.dataset.command || "";
      button.classList.toggle("active-choice", command.endsWith(enabled ? " on" : " off"));
    });
  });
  const allEnabled = Boolean(controls.gimbal && controls.body && controls.approach);
  const allDisabled = Boolean(!controls.gimbal && !controls.body && !controls.approach);
  const allRow = document.querySelector('[data-controller-row="all"]');
  if (allRow) {
    allRow.classList.toggle("enabled", allEnabled);
    allRow.querySelectorAll("button").forEach(button => {
      const command = button.dataset.command || "";
      button.classList.toggle(
        "active-choice",
        (allEnabled && command.endsWith(" on")) || (allDisabled && command.endsWith(" off"))
      );
    });
  }
}
// Field Heading / Field Reference moved to field_reference.js
//   confirmFieldHeading calls "/api/field-heading/confirm"
//   renderFieldHeading uses delta_current_to_field_deg
//   Field Reference uses /api/field-reference/*
const {
  gpsText,
  fetchFieldReferenceStatus,
  renderFieldReference,
  frPost,
  frSetManualHeading,
} = window.UavFieldRef;

const {
  fetchProfileList,
  fetchFieldReferenceStatus: fpFetchFieldReferenceStatus,
} = window.UavFieldProfiles || {};

function renderFieldHeading(next) { window.UavFieldRef.renderFieldHeading(next); }
async function confirmFieldHeading() { return window.UavFieldRef.confirmFieldHeading(); }

function renderMissionSteps(next) {
  if (!$("missionSelect") || !$("stageOverride") || !$("missionSteps")) return;
  const selectedMission = $("missionSelect")?.value || next.mission || "";
  const mission = missionCatalog.find(item => item.name === selectedMission);
  const viewingActiveMission = selectedMission === next.mission;
  const active = viewingActiveMission ? next.stage || "" : "";
  const selected = viewingActiveMission
    ? next.mission_stage_selection || "AUTO"
    : mission?.selected_stage || "AUTO";
  const modes = mission && Array.isArray(mission.stage_modes) && mission.stage_modes.length
    ? ["AUTO", ...mission.stage_modes]
    : Array.isArray(next.stage_modes) && next.stage_modes.length
      ? next.stage_modes
      : fallbackStageModes;
  $("stageOverride").textContent = selected;
  $("missionSteps").innerHTML = modes.map(mode => {
    const command = `mission stage ${mode}`;
    const selectedMode = mode === selected;
    const currentMode = mode !== "AUTO" && mode === active;
    return `<button class="${selectedMode ? "selected-mode" : ""} ${currentMode ? "current-mode" : ""}" data-stage-mode="${mode}" data-command="${command}" ${viewingActiveMission ? "" : "disabled"}>${mode}</button>`;
  }).join("");
  $("missionSteps").querySelectorAll("[data-stage-mode]").forEach(button => button.onclick = () =>
    execute(button.dataset.command, "STAGE"));
}
function dispatchFromActionLab(actionLab) {
  const payload = actionLab || window.UavActionLab.getLatestActionLab() || {};
  const status = payload?.status || payload || {};
  const last = status?.last_result || {};
  const detail = last.detail || {};
  return payload.dispatch || detail.dispatch || detail.last_dispatch || payload.last_dispatch || last.dispatch || {};
}
function countDispatchItems(value) {
  if (Array.isArray(value)) return value.length;
  if (value && typeof value === "object") return Object.keys(value).length;
  return value ? 1 : 0;
}
function actionMissionDetail(actionMission) {
  return (actionMission && typeof actionMission.detail === "object" && actionMission.detail) ? actionMission.detail : {};
}
function actionMissionBlackboard(actionMission) {
  const detail = actionMissionDetail(actionMission);
  return (detail.blackboard && typeof detail.blackboard === "object") ? detail.blackboard : {};
}
function inferActionMissionStepStatus(actionMission, index, stepCount) {
  const payload = actionMission || {};
  const current = Number.isFinite(Number(payload.current_index)) ? Number(payload.current_index) : 0;
  const detail = actionMissionDetail(payload);
  const skippedSet = new Set((Array.isArray(detail.skipped_steps) ? detail.skipped_steps : []).map(s => s.index));
  if (skippedSet.has(index)) return "skipped";
  if (payload.done) return "done";
  if (payload.failed) {
    if (index < current) return "done";
    if (index === current) return "failed";
    return "pending";
  }
  if (payload.running && index === current && current < stepCount) return "running";
  if (index < current) return "done";
  return "pending";
}
function failurePolicyLabel(policy) {
  if (!policy || typeof policy !== "object") return "-";
  const action = policy.action || "fail";
  if (policy.target) return `${action}:${policy.target}`;
  if (policy.max_attempts !== undefined) return `${action} x${policy.max_attempts}`;
  return String(action);
}
function actionMissionStatusLabel(status) {
  return {
    pending: "待执行",
    running: "执行中",
    done: "已完成",
    failed: "失败",
    skipped: "已跳过",
    continued: "已继续",
  }[status] || status;
}
function renderActionMissionTimeline(actionMission, configuredSteps) {
  const element = $("actionMissionTimeline");
  if (!element) return [];
  const steps = Array.isArray(configuredSteps) ? configuredSteps : [];
  const detail = actionMissionDetail(actionMission);
  const attempts = detail.step_attempts || {};
  const skippedSet = new Set((Array.isArray(detail.skipped_steps) ? detail.skipped_steps : []).map(s => s.index));
  const current = Number.isFinite(Number(actionMission?.current_index)) ? Number(actionMission.current_index) : -1;
  const statuses = steps.map((step, index) => inferActionMissionStepStatus(actionMission || {}, index, steps.length));
  element.innerHTML = steps.map((step, index) => {
    const status = statuses[index];
    const reason = index === current ? (actionMission?.reason || "-")
      : skippedSet.has(index) ? "manual skip"
      : "-";
    return `<tr class="${index === current ? "current-step" : ""}" data-step-status="${status}">
      <td>${index}</td>
      <td><span class="step-status ${status}">${escapeHtml(actionMissionStatusLabel(status))}</span></td>
      <td>${escapeHtml(step.label || "-")}</td>
      <td>${escapeHtml(actionNameWithZh(step.name))}</td>
      <td>${escapeHtml(step.save_as || "-")}</td>
      <td>${escapeHtml(failurePolicyLabel(step.on_failed))}</td>
      <td>${escapeHtml(attempts[index] ?? attempts[String(index)] ?? "-")}</td>
      <td>${escapeHtml(reason)}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="8" class="hint">加载模板或粘贴任务 JSON 后预览步骤。</td></tr>`;
  return statuses;
}
function renderBlackboardKeys(actionMission) {
  const element = $("actionMissionBlackboardKeys");
  if (!element) return;
  const detail = actionMissionDetail(actionMission);
  const blackboard = actionMissionBlackboard(actionMission);
  const keys = Array.isArray(detail.blackboard_keys) ? detail.blackboard_keys : Object.keys(blackboard);
  element.innerHTML = keys.length
    ? keys.map(key => `<span class="blackboard-key">${escapeHtml(key)}</span>`).join("")
    : `<div class="hint">暂无黑板键。</div>`;
}
function getPathValue(source, path) {
  let current = source;
  for (const part of path) {
    if (current === null || current === undefined) return undefined;
    current = current[part];
  }
  return current;
}
function summarizeDropScan(blackboard) {
  const dropScan = blackboard.drop_scan || {};
  const objects = getPathValue(dropScan, ["localization", "objects"])
    || dropScan.localized_objects
    || dropScan.objects;
  if (!Array.isArray(objects)) return "";
  return `<div class="mission-result-group"><strong>投放区扫描</strong><div>已定位目标数：${objects.length}</div></div>`;
}
function summarizeDropTargets(blackboard) {
  const selected = getPathValue(blackboard, ["drop_targets", "selected_targets"]);
  if (!Array.isArray(selected)) return "";
  const rows = selected.slice(0, 6).map((target, index) => {
    const id = target.id ?? target.track_id ?? index + 1;
    const x = target.local_x ?? target.x ?? "--";
    const y = target.local_y ?? target.y ?? "--";
    return `<div>T${index + 1}: id=${escapeHtml(id)} x=${escapeHtml(x)} y=${escapeHtml(y)}</div>`;
  }).join("");
  return `<div class="mission-result-group"><strong>已选择投放目标</strong><div>投放目标数：${selected.length}</div>${rows}</div>`;
}
function summarizeReconReport(blackboard) {
  const report = getPathValue(blackboard, ["recon_scan", "recon_report"]);
  if (!report || typeof report !== "object") return "";
  const barrels = Array.isArray(report.barrels) ? report.barrels : [];
  const rows = barrels.slice(0, 8).map((barrel, index) => {
    const id = barrel.id || `recon_${index + 1}`;
    const content = barrel.content || barrel.class_name || "blank";
    const confidence = barrel.confidence !== undefined ? ` conf=${Number(barrel.confidence).toFixed(2)}` : "";
    return `<div>${escapeHtml(id)}: ${escapeHtml(content)}${escapeHtml(confidence)}</div>`;
  }).join("");
  return `<div class="mission-result-group"><strong>侦察报告</strong><div>侦察桶数：${barrels.length}</div>${rows}</div>`;
}
function renderActionMissionSummary(actionMission) {
  const element = $("actionMissionResults");
  if (!element) return;
  const blackboard = actionMissionBlackboard(actionMission);
  const html = [
    summarizeDropScan(blackboard),
    summarizeDropTargets(blackboard),
    summarizeReconReport(blackboard),
  ].filter(Boolean).join("");
  element.innerHTML = html || `<div class="hint">暂无任务结果详情。</div>`;
}
function updateActionMissionAutoTickButton() {
  const button = $("actionMissionAutoTick");
  if (!button) return;
  const enabled = Boolean(actionMissionAutoTickTimer);
  const running = Boolean(lastActionMissionStatus?.running);
  button.textContent = enabled ? (running ? "自动推进 开" : "自动推进 待命") : "自动推进 关";
  button.classList.toggle("warning", enabled);
}
function stopActionMissionAutoTick() {
  if (actionMissionAutoTickTimer) {
    clearInterval(actionMissionAutoTickTimer);
    actionMissionAutoTickTimer = null;
  }
  updateActionMissionAutoTickButton();
}
function renderActionMissionStatus(actionMission) {
  const payload = actionMission || {};
  const detail = actionMissionDetail(payload);
  const sendEnabled = Boolean(state?.controllers?.send_commands);
  lastActionMissionStatus = payload;
  const actionResult = detail.action_result || detail.previous_action_result || detail.failed_action_result || null;
  if (actionResult) lastActionMissionResult = actionResult;
  setOptionalText("actionMissionSystemSend", sendEnabled ? "ON" : "OFF");
  setOptionalText("actionMissionEnabled", boolText(Boolean(payload.enabled), "是", "否"));
  setOptionalText("actionMissionRunning", boolText(Boolean(payload.running), "是", "否"));
  setOptionalText("actionMissionDone", boolText(Boolean(payload.done), "是", "否"));
  setOptionalText("actionMissionFailed", boolText(Boolean(payload.failed), "是", "否"));
  setOptionalText("actionMissionIndex", payload.current_index ?? "--");
  setOptionalText("actionMissionCurrent", actionNameWithZh(payload.current_action));
  setOptionalText("actionMissionReason", payload.reason || "--");
  const warning = $("actionMissionSendWarning");
  if (warning) {
    warning.textContent = sendEnabled
      ? "警告：System SEND=ON，推进一次可能向飞控或仿真器下发命令。"
      : "干跑模式：推进不会下发飞控命令。";
    warning.classList.toggle("send-on", sendEnabled);
  }
  const skipButton = $("actionMissionSkipCurrent");
  if (skipButton) {
    const canSkip = Boolean(payload.enabled && payload.running && !payload.done && !payload.failed);
    skipButton.disabled = !canSkip;
  }
  const detailElement = $("actionMissionDetail");
  if (detailElement) detailElement.textContent = JSON.stringify(detail, null, 2);
  renderBlackboardKeys(payload);
  renderActionMissionSummary(payload);
  renderActionMissionTimeline(payload, currentActionMissionSteps);
  if (payload.done || payload.failed) stopActionMissionAutoTick();
  else updateActionMissionAutoTickButton();
}
function renderDashboardSummaries(next) {
  const actionLab = next.action_lab || window.UavActionLab.getLatestActionLab() || {};
  const actionStatus = actionLab?.status || actionLab || {};
  const actionLast = actionStatus?.last_result || {};
  const dispatch = dispatchFromActionLab(actionLab);
  const mission = next.action_mission || {};
  renderSummaryRows("dashboardActionSummary", [
    ["Action", actionNameWithZh(actionStatus.action_name), actionStatus.running ? "active" : ""],
    ["State", actionStatus.state || "--"],
    ["Reason", actionLast.reason || "--"],
    ["Done / Failed", `${Boolean(actionLast.done)} / ${Boolean(actionLast.failed)}`, actionLast.failed ? "danger" : ""],
  ]);
  renderSummaryRows("dashboardMissionSummary", [
    ["Enabled", String(Boolean(mission.enabled))],
    ["Running", String(Boolean(mission.running)), mission.running ? "active" : ""],
    ["Current", actionNameWithZh(mission.current_action)],
    ["Reason", mission.reason || "--"],
  ]);
  renderSummaryRows("dashboardDispatchSummary", [
    ["sent", JSON.stringify(dispatch.sent ?? "--"), dispatch.sent ? "ok" : ""],
    ["skipped", JSON.stringify(dispatch.skipped ?? "--")],
    ["errors", JSON.stringify(dispatch.errors ?? "--"), dispatch.errors ? "danger" : ""],
    ["note", actionLab.note || dispatch.note || "--"],
  ]);
  renderReconInspection(next.recon_inspection || {});
}
function renderReconInspection(result) {
  const element = $("reconInspectionResults");
  if (!element) return;
  const report = Array.isArray(result.report) ? result.report : [];
  element.innerHTML = report.length ? report.map((item, index) => {
    const x = pointX(item), y = pointY(item);
    const statusLabel = item.status === "detected"
      ? `${item.sign_class || item.content || "--"} ${num(item.confidence, 2)}`
      : item.status === "no_sign" ? "无标识"
        : item.status === "blank_or_uncertain" ? "空白"
        : item.status === "skipped_missing_target" ? "跳过" : "识别失败";
    return `<div>#${index + 1} &nbsp; x=${num(x, 2)} y=${num(y, 2)} &nbsp; ${escapeHtml(statusLabel)}</div>`;
  }).join("") : `<div class="hint">暂无侦察识别结果。</div>`;
}
function renderStatus(next) {
  state = next;
  const link = next.link || {};
  const drone = next.drone || {};
  const gimbal = next.gimbal || {};
  const target = next.perception || {};
  const controls = next.controllers || {};
  setBadge($("sourceBadge"), `SOURCE ${String(next.active_source || "--").toUpperCase()}`, next.active_source === "real" ? "warning" : "");
  setBadge($("linkBadge"), `LINK ${link.connected ? "OK" : "DOWN"}`, link.connected ? "ok" : "danger");
  setBadge($("sendBadge"), `SEND ${controls.send_commands ? "ON" : "OFF"}`, controls.send_commands ? "danger" : "ok");
  setBadge($("armBadge"), `ARM ${drone.armed ? "ON" : "OFF"}`, drone.armed ? "warning" : "");
  setBadge($("modeBadge"), `MODE ${drone.mode || "--"}`, drone.mode === "GUIDED" ? "warning" : "");
  setBadge($("batteryBadge"), `BAT ${drone.battery_valid ? `${drone.battery_remaining}%` : "--"}`, "");
  setBadge($("altitudeBadge"), `ALT ${num(drone.relative_altitude, 1, "m")}`, "");
  const actionStatus = (next.action_lab?.status || next.action_lab || {});
  setBadge($("actionBadge"), `ACTION ${actionStatus.running ? actionNameWithZh(actionStatus.action_name || "RUN") : "--"}`, actionStatus.running ? "active" : "");
  setBadge($("missionBadge"), `MISSION ${next.action_mission?.running ? actionNameWithZh(next.action_mission.current_action || "RUN") : "--"}`, next.action_mission?.running ? "active" : "");
  setOptionalText("missionName", next.mission || "--");
  setOptionalText("missionStage", next.stage || "--");
  setOptionalText("stageController", next.stage_controller || "--");
  setOptionalText("holdReason", next.hold_reason || "none");
  updateControlHighlights(next, drone, controls);
  renderFieldHeading(next);
  renderMissionSteps(next);
  $("targetCurrent").textContent = target.target_valid
    ? `当前锁定: ${target.class_name} #${target.track_id} (${Number(target.confidence).toFixed(2)})`
    : "当前锁定: --";
  const scene = next.scene || {};
  const detections = scene.detections || [];
  infoRows($("targetInfo"), [
    ["目标状态", target.target_valid ? "LOCKED" : (target.tracking_state || "--").toUpperCase()],
    ["Track ID", target.target_valid ? `#${target.track_id}` : "--"],
    ["类别/置信度", target.target_valid ? `${target.class_name || "--"} / ${num(target.confidence, 2)}` : "--"],
    ["Frame", `${scene.frame_id ?? target.frame_id ?? "--"}`],
    ["检测数", `${detections.length}`],
    ["图像尺寸", `${scene.image_width || target.image_width || "--"} x ${scene.image_height || target.image_height || "--"}`],
    ["中心 cx/cy", target.target_valid ? `${num(target.cx, 1)} / ${num(target.cy, 1)}` : "--"],
    ["框 w/h", target.target_valid ? `${num(target.w, 1)} / ${num(target.h, 1)}` : "--"],
    ["误差 ex/ey", target.target_valid ? `${num(target.ex, 3)} / ${num(target.ey, 3)}` : "--"],
    ["目标尺寸", target.target_valid ? num(target.target_size, 3) : "--"],
    ["丢失计数", `${target.lost_count ?? "--"}`],
    ["Scene 时间", stamp(scene.timestamp || target.timestamp)],
  ]);
  infoRows($("aircraftInfo"), [
    ["GPS", `${drone.gps_fix_type ?? "--"} fix / ${drone.satellites_visible ?? "--"} sats`],
    ["电池", drone.battery_valid ? `${num(drone.battery_voltage, 1, " V")} / ${drone.battery_remaining}%` : "--"],
    ["高度", `${num(drone.relative_altitude, 2, " m")} / ${num(drone.altitude, 2, " m")}`],
    ["飞控模式", drone.mode || "--"],
    ["解锁", boolText(drone.armed, "ARMED", "DISARMED")],
    ["当前 yaw", degNum(next.field_heading?.current_yaw_deg)],
    ["场地方向", next.field_heading?.field_heading_confirmed ? degNum(next.field_heading?.field_heading_yaw_deg) : "--"],
    ["yaw 偏差", degNum(next.field_heading?.delta_current_to_field_deg)],
  ]);
  renderDetections(scene, target);
  cards($("statusCards"), {
    "链路": `${link.status_text || "--"} / ${link.transport || "--"}`,
    "心跳": link.connected ? `${num(drone.hb_age_sec, 2, " s")} ago` : "--",
    "接收": link.connected ? `${num(drone.rx_age_sec, 2, " s")} ago` : "--",
    "目标系统": `${link.target_system ?? "--"}:${link.target_component ?? "--"}`,
    "飞控模式": drone.mode || "--",
    "解锁状态": drone.armed ? "ARMED" : "DISARMED",
    "姿态 R/P/Y": `${num(drone.roll, 3)} / ${num(drone.pitch, 3)} / ${num(drone.yaw, 3)}`,
    "高度": `${num(drone.relative_altitude, 2, " m")} / ${num(drone.altitude, 2, " m")}`,
    "速度 NED": `${num(drone.vx, 2)} / ${num(drone.vy, 2)} / ${num(drone.vz, 2)}`,
    "本地位置": drone.local_position_valid ? `${num(drone.local_x, 2)} / ${num(drone.local_y, 2)} / ${num(drone.local_z, 2)}` : "--",
    "GPS": `${drone.gps_fix_type ?? "--"} / ${drone.satellites_visible ?? "--"} sats`,
    "经纬度": drone.global_position_valid ? `${num(drone.lat, 7)}, ${num(drone.lon, 7)}` : "--",
    "电池": drone.battery_valid ? `${Number(drone.battery_voltage).toFixed(1)} V / ${drone.battery_remaining}%` : "--",
    "云台 Y/P/R": gimbal.gimbal_valid ? `${num(gimbal.yaw, 3)} / ${num(gimbal.pitch, 3)} / ${num(gimbal.roll, 3)}` : "--",
    "最新消息": drone.last_message_type || "--",
    "Mission": next.mission || "--", "Stage": next.stage || "--",
    "Target": target.target_valid ? `${target.class_name} #${target.track_id}` : "--",
    "Hold": next.hold_reason || "none"
  });
  const cmd = next.command || {};
  cards($("commandCards"), {
    "VX": Number(cmd.vx_cmd || 0).toFixed(3), "VY": Number(cmd.vy_cmd || 0).toFixed(3),
    "VZ": Number(cmd.vz_cmd || 0).toFixed(3), "Yaw": Number(cmd.yaw_rate_cmd || 0).toFixed(3),
    "Gimbal Y": Number(cmd.gimbal_yaw_rate_cmd || 0).toFixed(3),
    "Gimbal P": Number(cmd.gimbal_pitch_rate_cmd || 0).toFixed(3),
    "Active": String(Boolean(cmd.active)), "SEND": controls.send_commands ? "ON" : "OFF"
  });
  $("events").innerHTML = (next.events || []).map(item =>
    `<div class="log-line">${stamp(item.timestamp)} ${escapeHtml(item.level)} &nbsp; ${escapeHtml(item.message)}</div>`).join("");
  renderFieldMap(next);
  renderActionLabStatus(next.action_lab || null);
  renderActionMissionStatus(next.action_mission || null);
  renderDashboardSummaries(next);
}
function renderDetections(scene, target) {
  $("frameId").textContent = scene.frame_id ?? "--";
  const detections = scene.detections || [];
  $("detCount").textContent = detections.length;
  $("detections").innerHTML = detections.map(det => {
    const locked = target.target_valid && det.track_id === target.track_id;
    return `<button class="detection ${locked ? "locked" : ""}" data-track="${det.track_id}">
      <span>#${det.track_id} ${escapeHtml(det.class_name)}</span><span>${Number(det.confidence).toFixed(2)}</span></button>`;
  }).join("") || `<div class="hint">暂无目标</div>`;
  $("detections").querySelectorAll("[data-track]").forEach(button => button.onclick = () =>
    execute(`target lock ${button.dataset.track}`, "LIST"));
}
async function loadMissions() {
  missionCatalog = await json("/api/missions");
  if (!$("missionSelect")) return;
  $("missionSelect").innerHTML = missionCatalog.map(item =>
    `<option value="${item.name}" ${item.active ? "selected" : ""}>${item.name}</option>`).join("");
  renderMissionSteps(state || {});
}
// Audit log moved to log_panel.js (WU-7A)
// Config panel configure (WU-7B v2)
var loadConfigFiles = function () { return window.UavConfigPanel.loadConfigFiles(); };
var openConfig = function (path) { return window.UavConfigPanel.openConfig(path); };
var localDiff = function (before, after) { return window.UavConfigPanel.localDiff(before, after); };
var saveConfig = function (action) { return window.UavConfigPanel.saveConfig(action); };
var restoreConfig = function () { return window.UavConfigPanel.restoreConfig(); };
var actionForPath = function () { return window.UavConfigPanel.actionForPath(); };

// Video panel configure (WU-6 v2)
if (window.UavLogPanel && window.UavLogPanel.configure) {
  window.UavLogPanel.configure({
    api: window.UavApi,
    dom: window.UavDom,
    format: window.UavFormat,
    appState: window.UavAppState,
  });
}
var loadAudit = function () { return window.UavLogPanel.loadAudit(); };

// Config panel configure (WU-7B v2) — must be after loadAudit is defined
if (window.UavConfigPanel && window.UavConfigPanel.configure) {
  window.UavConfigPanel.configure({
    api: window.UavApi,
    dom: window.UavDom,
    format: window.UavFormat,
    loadAudit: loadAudit,
    setCompletionHint: function (text) { $("completionHint").textContent = text; },
    setConfigStatus: function (text) { var el = $("configStatus"); if (el) el.textContent = text; },
  });
}

// Video panel configure (WU-6 v2)
if (window.UavVideoPanel && window.UavVideoPanel.configure) {
  window.UavVideoPanel.configure({
    api: window.UavApi,
    dom: window.UavDom,
    format: window.UavFormat,
    getState: function () { return state; },
    execute: execute,
    loadAudit: loadAudit,
    setCompletionHint: function (text) { $("completionHint").textContent = text; },
  });
}
var refreshCameraRecordingStatus = function () { return window.UavVideoPanel.refreshCameraRecordingStatus(); };
var toggleCameraRecording = function () { return window.UavVideoPanel.toggleCameraRecording(); };
var renderCameraRecordingStatus = function (payload) { window.UavVideoPanel.renderCameraRecordingStatus(payload); };

// Action Lab moved to action_lab.js (WU-4 v4) — sole state owner
if (window.UavActionLab && window.UavActionLab.configure) {
  window.UavActionLab.configure({
    api: window.UavApi,
    dom: window.UavDom,
    format: window.UavFormat,
    appState: window.UavAppState,
    safetyHints: ACTION_SAFETY_HINTS,
    zhLabels: ACTION_ZH_LABELS,
    getState: function () { return state; },
    renderFieldMap: renderFieldMap,
    setCompletionHint: function (text) { $("completionHint").textContent = text; },
  });
}
var loadActionLab = function () { return window.UavActionLab.loadActionLab(); };
var cacheSelectedActionParams = function () { window.UavActionLab.cacheSelectedActionParams(); };
var selectAction = function (name) { return window.UavActionLab.selectAction(name); };
var refreshActionStatus = function () { return window.UavActionLab.refreshActionStatus(); };
var renderActionLabStatus = function (actionLab) { window.UavActionLab.renderActionLabStatus(actionLab); };
var nodeInside = function (element, node) { return window.UavActionLab.nodeInside(element, node); };
var actionStatusJsonHasSelection = function () { return window.UavActionLab.actionStatusJsonHasSelection(); };
var updateActionStatusJson = function (text) { window.UavActionLab.updateActionStatusJson(text); };
var parseActionParams = function () { return window.UavActionLab.parseActionParams(); };
var dispatchFromActionLab = function (actionLab) { return window.UavActionLab.dispatchFromActionLab(actionLab); };
var countDispatchItems = function (value) { return window.UavActionLab.countDispatchItems(value); };
function parseActionMissionInput(text) {
  const parsed = text.trim() ? JSON.parse(text) : [];
  if (Array.isArray(parsed)) return {name: "", steps: parsed};
  if (parsed && typeof parsed === "object" && Array.isArray(parsed.steps)) return parsed;
  throw new Error("Action Mission JSON 必须是步骤数组，或包含 steps 的对象");
}
function normalizeActionMissionSteps(input) {
  const steps = Array.isArray(input) ? input : input?.steps;
  if (!Array.isArray(steps)) throw new Error("steps 必须是 JSON 数组");
  if (!steps.length) throw new Error("steps 不能为空");
  return steps.map((step, index) => {
    if (!step || typeof step !== "object" || typeof step.name !== "string" || !step.name.trim()) {
      throw new Error(`step ${index + 1} 必须包含 name`);
    }
    if (step.params !== undefined && (step.params === null || Array.isArray(step.params) || typeof step.params !== "object")) {
      throw new Error(`step ${index + 1} params 必须是 object`);
    }
    if (step.save_as !== undefined && step.save_as !== null && typeof step.save_as !== "string") {
      throw new Error(`step ${index + 1} save_as 必须是 string`);
    }
    if (step.label !== undefined && step.label !== null && typeof step.label !== "string") {
      throw new Error(`step ${index + 1} label 必须是 string`);
    }
    if (step.on_failed !== undefined && step.on_failed !== null && (Array.isArray(step.on_failed) || typeof step.on_failed !== "object")) {
      throw new Error(`step ${index + 1} on_failed 必须是 object`);
    }
    return {
      name: step.name.trim(),
      params: step.params || {},
      ...(step.save_as ? {save_as: step.save_as} : {}),
      ...(step.label ? {label: step.label} : {}),
      ...(step.on_failed ? {on_failed: step.on_failed} : {}),
    };
  });
}
function parseActionMissionSteps() {
  try {
    const parsed = parseActionMissionInput($("actionMissionSteps").value);
    return normalizeActionMissionSteps(parsed);
  } catch (error) {
    $("completionHint").textContent = `Action Mission JSON 错误: ${error.message}`;
    return null;
  }
}
async function refreshActionMission() {
  const result = await json("/api/action-mission/status");
  if (!result.ok) throw new Error(result.error || "Action Mission 状态刷新失败");
  renderActionMissionStatus(result.action_mission || null);
  return result;
}
async function configureActionMission() {
  const steps = parseActionMissionSteps();
  if (steps === null) return;
  currentActionMission = parseActionMissionInput($("actionMissionSteps").value);
  currentActionMissionSteps = steps;
  const result = await json("/api/action-mission/configure", {
    method: "POST",
    body: JSON.stringify({steps}),
  });
  if (!result.ok) throw new Error(result.error || "Action Mission 配置失败");
  $("completionHint").textContent = "Action Mission 已配置";
  renderActionMissionStatus(result.action_mission || null);
}
async function startActionMission() {
  const confirmed = window.confirm(
    "确认启动 Action Mission？\n"
    + "它会按 step 顺序运行 Action。Action 是否实发仍受 send_actions 和系统 SEND 门控控制。"
  );
  if (!confirmed) return;
  const result = await json("/api/action-mission/start", {method: "POST", body: "{}"});
  if (!result.ok) throw new Error(result.error || "Action Mission 启动失败");
  $("completionHint").textContent = "Action Mission 已启动";
  renderActionMissionStatus(result.action_mission || null);
}
async function stopActionMission() {
  stopActionMissionAutoTick();
  const result = await json("/api/action-mission/stop", {method: "POST", body: "{}"});
  if (!result.ok) throw new Error(result.error || "Action Mission 停止失败");
  $("completionHint").textContent = "Action Mission 已停止";
  renderActionMissionStatus(result.action_mission || null);
}
async function resetActionMission() {
  stopActionMissionAutoTick();
  const result = await json("/api/action-mission/reset", {method: "POST", body: "{}"});
  if (!result.ok) throw new Error(result.error || "Action Mission 重置失败");
  $("completionHint").textContent = "Action Mission 已重置";
  renderActionMissionStatus(result.action_mission || null);
}
async function tickActionMission() {
  const result = await json("/api/action-mission/tick", {method: "POST", body: "{}"});
  if (!result.ok) throw new Error(result.error || "Action Mission 推进失败");
  $("completionHint").textContent = "Action Mission 推进完成";
  renderActionMissionStatus(result.action_mission || null);
}
async function skipCurrentActionMissionStep() {
  const current = lastActionMissionStatus || state.action_mission || {};
  const index = current.current_index ?? "--";
  const action = current.current_action || "--";
  const confirmed = window.confirm(
    `确认跳过当前 Action Mission 阶段？\n\n` +
    `当前序号: ${index}\n` +
    `当前动作: ${action}\n\n` +
    `该操作会停止当前 Action，清理连续控制/LOCAL_POSITION，并尝试保持当前位置，然后进入下一阶段。\n` +
    `不会清空 blackboard。`
  );
  if (!confirmed) return;
  const result = await json("/api/action-mission/skip-current", {
    method: "POST",
    body: "{}",
  });
  if (!result.ok) throw new Error(result.error || "skip current step failed");
  lastActionMissionStatus = result.action_mission || {};
  renderActionMissionStatus(lastActionMissionStatus);
  $("completionHint").textContent = `已跳过当前阶段：${lastActionMissionStatus.reason || "manual_skip"}`;
  await loadAudit();
}
function setActionMissionEditorValue(mission) {
  const editor = $("actionMissionSteps");
  if (!editor) return;
  currentActionMission = mission;
  currentActionMissionSteps = normalizeActionMissionSteps(mission);
  editor.value = JSON.stringify(mission, null, 2);
  renderActionMissionTimeline(lastActionMissionStatus || {}, currentActionMissionSteps);
}
async function loadActionMissionTemplates() {
  const element = $("actionMissionTemplateList");
  if (!element) return;
  try {
    const result = await json("/api/action-mission/templates");
    if (!result.ok) throw new Error(result.error || "模板列表加载失败");
    element.innerHTML = (result.templates || []).map(template =>
      `<div><strong>${escapeHtml(template.label || template.name)}</strong> · ${escapeHtml(template.step_count)} 个步骤<br>${escapeHtml(template.description || template.path)}</div>`
    ).join("");
  } catch (error) {
    element.textContent = `模板接口不可用：${error.message}`;
  }
}
async function loadActionMissionTemplate(name) {
  const current = $("actionMissionSteps")?.value.trim();
  const defaultText = JSON.stringify(DEFAULT_ACTION_MISSION_STEPS, null, 2).trim();
  if (current && current !== defaultText && !window.confirm("当前 Mission JSON 将被覆盖，确认？")) return;
  const result = await json(`/api/action-mission/template/${encodeURIComponent(name)}`);
  if (!result.ok) throw new Error(result.error || "模板加载失败");
  setActionMissionEditorValue(result.template);
  $("completionHint").textContent = "已加载比赛模板，请检查参数后配置";
}
function validateActionMissionJson() {
  const steps = parseActionMissionSteps();
  if (steps === null) return;
  currentActionMission = parseActionMissionInput($("actionMissionSteps").value);
  currentActionMissionSteps = steps;
  renderActionMissionTimeline(lastActionMissionStatus || {}, currentActionMissionSteps);
  $("completionHint").textContent = `Action Mission JSON 校验通过：${steps.length} 个步骤`;
}
function formatActionMissionJson() {
  const parsed = parseActionMissionInput($("actionMissionSteps").value);
  $("actionMissionSteps").value = JSON.stringify(parsed, null, 2);
  validateActionMissionJson();
}
async function copyText(text, message) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
  } else {
    const area = document.createElement("textarea");
    area.value = text;
    document.body.appendChild(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
  $("completionHint").textContent = message;
}
async function toggleActionMissionAutoTick() {
  if (actionMissionAutoTickTimer) {
    stopActionMissionAutoTick();
    return;
  }
  actionMissionAutoTickTimer = setInterval(() => {
    if (!lastActionMissionStatus?.running) {
      updateActionMissionAutoTickButton();
      return;
    }
    tickActionMission().catch(error => {
      stopActionMissionAutoTick();
      $("completionHint").textContent = error.message;
    });
  }, 500);
  updateActionMissionAutoTickButton();
  $("completionHint").textContent = lastActionMissionStatus?.running
    ? "自动推进已开启"
    : "自动推进已待命，启动任务后会自动推进";
}
function loadActionMissionPreset(name) {
  const preset = actionMissionPresets[name];
  const editor = $("actionMissionSteps");
  if (!preset || !editor) return;
  const current = editor.value.trim();
  const defaultText = JSON.stringify(DEFAULT_ACTION_MISSION_STEPS, null, 2).trim();
  if (current && current !== defaultText && !window.confirm("当前 Step JSON 将被覆盖，确认？")) {
    return;
  }
  setActionMissionEditorValue(preset);
  $("completionHint").textContent = "已加载模板，请检查参数后 Configure";
}
var selectedActionIsRunning = function () { return window.UavActionLab.selectedActionIsRunning(); };
var toggleActionLabRun = function () { return window.UavActionLab.toggleActionLabRun(); };
var startActionLabAction = function (sendActions) { return window.UavActionLab.startActionLabAction(sendActions); };
var stopActionLabAction = function () { return window.UavActionLab.stopActionLabAction(); };
var resetActionLabAction = function () { return window.UavActionLab.resetActionLabAction(); };

function startStatusUpdates() {
  let fallbackTimer = null;
  let actionTimer = null;
  const pollStatus = () => json("/api/status").then(renderStatus).catch(error => {
    $("completionHint").textContent = `状态刷新失败: ${error.message}`;
  });
  const startActionTimer = () => {
    if (actionTimer !== null) return;
    actionTimer = setInterval(() => refreshActionStatus().catch(error => {
      $("completionHint").textContent = `Action Lab 刷新失败: ${error.message}`;
    }), 1000);
  };
  const startFrPolling = () => {
    fetchFieldReferenceStatus();
    setInterval(fetchFieldReferenceStatus, 2000);
  };
  const startFallback = () => {
    if (fallbackTimer !== null) return;
    pollStatus();
    fallbackTimer = setInterval(pollStatus, 500);
    startActionTimer();
    startFrPolling();
  };
  try {
    const socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/status`);
    socket.onmessage = event => renderStatus(JSON.parse(event.data));
    socket.onerror = startFallback;
    socket.onclose = startFallback;
    socket.onopen = () => { startActionTimer(); startFrPolling(); };
  } catch {
    startFallback();
  }
}
var setupActionStatusJsonCopyGuard = function () { window.UavActionLab.setupActionStatusJsonCopyGuard(); };

async function init() {
  // Video panel setup moved to video_panel.js (WU-6 v2)
  window.UavVideoPanel.setupVideoPanel().catch(function (err) {
  console.warn("video panel setup failed", err);
});
  if (window.UavFieldProfiles && window.UavFieldProfiles.init) {
    window.UavFieldProfiles.init();
  }
  document.querySelectorAll("[data-command]").forEach(button => button.onclick = () => {
    if (button.dataset.confirm && !confirm(button.dataset.confirm)) return;
    execute(button.dataset.command, button.dataset.origin || "BUTTON");
  });
  document.querySelectorAll("[data-manual-move]").forEach(button => button.onclick = () =>
    executeManualMove(button.dataset.manualMove));
  document.querySelectorAll("[data-manual-yaw]").forEach(button => button.onclick = () =>
    executeManualYaw(button.dataset.manualYaw));
  $("takeoffButton").onclick = () => {
    const altitude = $("takeoffAltitude").value;
    if (confirm(`确认起飞至 ${altitude} m？`)) execute(`takeoff ${altitude}`, "BUTTON");
  };
  if ($("missionSwitch")) $("missionSwitch").onclick = () => execute(`mission switch ${$("missionSelect").value}`, "BUTTON").then(loadMissions);
  if ($("missionSelect")) $("missionSelect").onchange = () => renderMissionSteps(state || {});
  window.UavFieldRef.init();
  $("sendCommand").onclick = () => {
    const input = $("commandInput");
    execute(input.value, "CLI"); history.unshift(input.value); input.value = ""; historyIndex = -1;
  };
  $("commandInput").onkeydown = event => {
    if (event.key === "Enter") { event.preventDefault(); $("sendCommand").click(); }
    if (event.key === "Tab") {
      event.preventDefault();
      const match = completions.find(item => item.toLowerCase().startsWith(event.target.value.toLowerCase()));
      if (match) { event.target.value = match; $("completionHint").textContent = `补全: ${match}`; }
    }
    if (event.key === "ArrowUp" && history.length) {
      event.preventDefault(); historyIndex = Math.min(historyIndex + 1, history.length - 1); event.target.value = history[historyIndex];
    }
    if (event.key === "ArrowDown" && historyIndex >= 0) {
      event.preventDefault(); historyIndex -= 1; event.target.value = historyIndex < 0 ? "" : history[historyIndex];
    }
  };

  // Flight Safety command panel (PR F)
  const flightInput = $("flightCommandInput");
  const flightSend = $("flightSendCommand");
  const flightHint = $("flightCompletionHint");
  if (flightSend && flightInput) {
    flightSend.onclick = () => {
      const command = flightInput.value.trim();
      if (!command) return;
      execute(command, "FLIGHT_CLI").then(result => {
        if (flightHint) flightHint.textContent = result.message || "command sent";
      }).catch(error => {
        if (flightHint) flightHint.textContent = `命令失败: ${error.message}`;
      });
      history.unshift(flightInput.value);
      flightInput.value = "";
      historyIndex = -1;
    };
    flightInput.onkeydown = event => {
      if (event.key === "Enter") { event.preventDefault(); flightSend.click(); }
      if (event.key === "Tab") {
        event.preventDefault();
        const match = completions.find(item => item.toLowerCase().startsWith(event.target.value.toLowerCase()));
        if (match) { event.target.value = match; if (flightHint) flightHint.textContent = `补全: ${match}`; }
      }
      if (event.key === "ArrowUp" && history.length) {
        event.preventDefault(); historyIndex = Math.min(historyIndex + 1, history.length - 1); event.target.value = history[historyIndex];
      }
      if (event.key === "ArrowDown" && historyIndex >= 0) {
        event.preventDefault(); historyIndex -= 1; event.target.value = historyIndex < 0 ? "" : history[historyIndex];
      }
    };
  }
  document.querySelectorAll(".tab").forEach(tab => tab.onclick = () => {
    document.querySelectorAll(".tab").forEach(item => item.classList.toggle("active", item === tab));
    document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.id === `${tab.dataset.page}Page`));
  });
  $("previewConfig").onclick = function () { $("configDiff").textContent = window.UavConfigPanel.localDiff(window.UavConfigPanel.getCurrentOriginal(), $("yamlEditor").value); };
  $("saveConfig").onclick = () => saveConfig("save");
  $("applyConfig").onclick = () => saveConfig(actionForPath());
  $("restoreConfig").onclick = restoreConfig;
  $("reconnectTelemetry").onclick = () => confirm("重连通信将关闭自动发送，确认？") && json("/api/services/telemetry/reconnect", {method: "POST"}).then(loadAudit);
  $("restartYolo").onclick = () => confirm("确认重启 YOLO 服务？") && json("/api/services/yolo/restart", {method: "POST"}).then(loadAudit);
  $("restartApp").onclick = () => confirm("重启 App 将关闭自动发送并暂时断开网页，确认？") && json("/api/services/app/restart", {method: "POST"}).then(loadAudit);
  $("actionParams").oninput = () => cacheSelectedActionParams();
  setupActionStatusJsonCopyGuard();
  if ($("actionRunToggle")) $("actionRunToggle").onclick = () => toggleActionLabRun().catch(error => { $("completionHint").textContent = error.message; });
  if ($("actionDryRunStart")) $("actionDryRunStart").onclick = () => startActionLabAction(false).catch(error => { $("completionHint").textContent = error.message; });
  if ($("actionDispatchStart")) $("actionDispatchStart").onclick = () => startActionLabAction(true).catch(error => { $("completionHint").textContent = error.message; });
  if ($("actionStop")) $("actionStop").onclick = () => stopActionLabAction().catch(error => { $("completionHint").textContent = error.message; });
  $("actionReset").onclick = () => resetActionLabAction().catch(error => { $("completionHint").textContent = error.message; });
  $("actionRefresh").onclick = () => refreshActionStatus().catch(error => { $("completionHint").textContent = error.message; });
  if ($("actionMissionSteps")) setActionMissionEditorValue(DEFAULT_ACTION_MISSION_STEPS);
  if ($("actionMissionConfigure")) $("actionMissionConfigure").onclick = () => configureActionMission().catch(error => { $("completionHint").textContent = error.message; });
  if ($("actionMissionStart")) $("actionMissionStart").onclick = () => startActionMission().catch(error => { $("completionHint").textContent = error.message; });
  if ($("actionMissionStop")) $("actionMissionStop").onclick = () => stopActionMission().catch(error => { $("completionHint").textContent = error.message; });
  if ($("actionMissionReset")) $("actionMissionReset").onclick = () => resetActionMission().catch(error => { $("completionHint").textContent = error.message; });
  if ($("actionMissionTick")) $("actionMissionTick").onclick = () => tickActionMission().catch(error => { $("completionHint").textContent = error.message; });
  if ($("actionMissionAutoTick")) $("actionMissionAutoTick").onclick = () => toggleActionMissionAutoTick().catch(error => { $("completionHint").textContent = error.message; });
  if ($("actionMissionRefresh")) $("actionMissionRefresh").onclick = () => refreshActionMission().catch(error => { $("completionHint").textContent = error.message; });
  $("actionMissionSkipCurrent")?.addEventListener("click", () => {
    skipCurrentActionMissionStep().catch(error => {
      $("completionHint").textContent = `跳过当前阶段失败: ${error.message}`;
    });
  });
  if ($("actionMissionLoadCustom")) $("actionMissionLoadCustom").onclick = () => {
    $("actionMissionSteps").focus();
    $("completionHint").textContent = "请粘贴自定义任务 JSON，然后校验或配置";
  };
  if ($("actionMissionValidate")) $("actionMissionValidate").onclick = () => validateActionMissionJson();
  if ($("actionMissionFormatJson")) $("actionMissionFormatJson").onclick = () => formatActionMissionJson();
  if ($("actionMissionCopyJson")) $("actionMissionCopyJson").onclick = () => copyText($("actionMissionSteps").value, "任务 JSON 已复制").catch(error => { $("completionHint").textContent = error.message; });
  if ($("actionMissionCopyStatus")) $("actionMissionCopyStatus").onclick = () => copyText(JSON.stringify(lastActionMissionStatus || {}, null, 2), "Action Mission 状态已复制").catch(error => { $("completionHint").textContent = error.message; });
  if ($("actionMissionCopyResult")) $("actionMissionCopyResult").onclick = () => copyText(JSON.stringify(lastActionMissionResult || {}, null, 2), "Action Mission 最后结果已复制").catch(error => { $("completionHint").textContent = error.message; });
  document.querySelectorAll("[data-action-mission-template]").forEach(button => {
    button.onclick = () => loadActionMissionTemplate(button.dataset.actionMissionTemplate).catch(error => { $("completionHint").textContent = error.message; });
  });
  document.querySelectorAll("[data-action-mission-preset]").forEach(button => {
    button.onclick = () => loadActionMissionPreset(button.dataset.actionMissionPreset);
  });
  if ($("payloadReleaseSelect")) $("payloadReleaseSelect").onclick = () => {
    selectAction("payload_release");
    document.querySelectorAll(".tab").forEach(tab => tab.classList.toggle("active", tab.dataset.page === "actions"));
    document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.id === "actionsPage"));
  };
  if ($("payloadReleaseRun")) $("payloadReleaseRun").onclick = () => {
    selectAction("payload_release");
    startActionLabAction(true).catch(error => { $("completionHint").textContent = error.message; });
  };
  completions = (await json("/api/commands/completions")).commands;
  await Promise.all([loadAudit(), loadMissions(), loadConfigFiles(), loadActionLab(), loadActionMissionTemplates()]);
  startStatusUpdates();
}
init().catch(error => { $("completionHint").textContent = error.message; });
