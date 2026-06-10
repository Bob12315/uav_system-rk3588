const $ = id => document.getElementById(id);
let state = {};
let completions = [];
let history = [];
let historyIndex = -1;
let currentConfigPath = "";
let currentOriginal = "";
let missionCatalog = [];
let actionSpecs = [];
let selectedActionName = "";
let actionParamCache = {};
let latestActionLab = null;
const fallbackStageModes = ["AUTO", "IDLE", "APPROACH_TRACK", "OVERHEAD_HOLD", "CORRIDOR_FOLLOW"];
const ACTION_SAFETY_HINTS = {
  goto_waypoint: "飞控移动命令：local_position / goto_local_ned，需要 SEND=ON 才实发。",
  survey_area: "会连续发送 local_position / goto_local_ned，需要 SEND=ON 才实发。",
  target_lock: "YOLO 锁定命令，不需要 SEND=ON，但需要 Dispatch。",
  align_descend: "BODY_NED 速度控制，需要 SEND=ON 才实发。",
  payload_release: "舵机 PWM 输出，需要 SEND=ON 才实发；确认 SERVO 输出通道和 PWM。",
};
const DEFAULT_ACTION_MISSION_STEPS = [
  {
    name: "goto_waypoint",
    params: {
      x: 0.0,
      y: 0.0,
      altitude_m: 1.5,
      yaw_mode: "hold",
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
        yaw_mode: "hold",
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
        yaw_mode: "hold",
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
        yaw_mode: "hold",
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
const FIELD_DEFAULTS = {
  bounds: {xMin: -8, xMax: 62, yMin: -6, yMax: 6},
  takeoff: {x: 0, y: 0, xLen: 8, yLen: 8, label: "起降区"},
  drop: {x: 30, y: 0, xLen: 5, yLen: 8, label: "投放区"},
  recce: {x: 55, y: 0, xLen: 5, yLen: 8, label: "侦察区"},
  dropSurvey: [
    {name: "D1", x: 28, y: -1.2},
    {name: "D2", x: 28, y: 1.2},
    {name: "D3", x: 32, y: -1.2},
    {name: "D4", x: 32, y: 1.2},
  ],
  recceSurvey: [
    {name: "R1", x: 53, y: -1.2},
    {name: "R2", x: 53, y: 1.2},
    {name: "R3", x: 57, y: -1.2},
    {name: "R4", x: 57, y: 1.2},
  ],
};

async function json(url, options = {}) {
  const response = await fetch(url, {headers: {"Content-Type": "application/json"}, ...options});
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "request failed");
  return data;
}
function stamp(seconds) {
  return seconds ? new Date(seconds * 1000).toLocaleTimeString() : "--";
}
function escapeHtml(text) {
  return String(text ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}
async function execute(command, source = "BUTTON") {
  if (!command) return;
  const result = await json("/api/commands/execute", {
    method: "POST", body: JSON.stringify({command, source})
  });
  $("completionHint").textContent = result.message;
  await loadAudit();
  return result;
}
function setBadge(element, text, cls) {
  element.textContent = text;
  element.className = `badge ${cls || ""}`;
}
function cards(target, values) {
  target.innerHTML = Object.entries(values).map(([label, value]) =>
    `<div class="card"><label>${escapeHtml(label)}</label>${escapeHtml(value)}</div>`).join("");
}
function infoRows(target, rows) {
  target.innerHTML = rows.map(([label, value]) =>
    `<div class="info-label">${escapeHtml(label)}</div><div class="info-value">${escapeHtml(value)}</div>`
  ).join("");
}
function num(value, digits = 2, unit = "") {
  return Number.isFinite(Number(value)) ? `${Number(value).toFixed(digits)}${unit}` : "--";
}
function boolText(value, yes = "YES", no = "NO") {
  return value ? yes : no;
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
  const offsets = {
    forward: [step, 0, 0],
    back: [-step, 0, 0],
    left: [0, -step, 0],
    right: [0, step, 0],
    up: [0, 0, -step],
    down: [0, 0, step],
  };
  const offset = offsets[direction];
  if (!offset) return;
  const yaw = Number(state?.drone?.yaw);
  if (!Number.isFinite(yaw) && (offset[0] !== 0 || offset[1] !== 0)) {
    $("completionHint").textContent = "缺少当前偏航姿态，无法换算机体系水平步长";
    return;
  }
  const localOffset = Number.isFinite(yaw) ? bodyOffsetToLocalOffset(offset, yaw) : offset;
  execute(`local_pos ${localOffset.map(commandNumber).join(" ")} offset`, "MANUAL_MOVE");
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
function setOptionalText(id, value) {
  const element = $(id);
  if (element) element.textContent = value;
}
function renderSummaryRows(id, rows) {
  const element = $(id);
  if (!element) return;
  element.innerHTML = rows.map(([label, value, tone]) =>
    `<div class="summary-row ${tone || ""}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`
  ).join("");
}
function dispatchFromActionLab(actionLab) {
  const payload = actionLab || latestActionLab || {};
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
function renderActionMissionStatus(actionMission) {
  const payload = actionMission || {};
  const detail = payload.detail || {};
  const sendEnabled = Boolean(state?.controllers?.send_commands);
  setOptionalText("actionMissionSystemSend", sendEnabled ? "ON" : "OFF");
  setOptionalText("actionMissionEnabled", String(Boolean(payload.enabled)));
  setOptionalText("actionMissionRunning", String(Boolean(payload.running)));
  setOptionalText("actionMissionDone", String(Boolean(payload.done)));
  setOptionalText("actionMissionFailed", String(Boolean(payload.failed)));
  setOptionalText("actionMissionIndex", payload.current_index ?? "--");
  setOptionalText("actionMissionCurrent", payload.current_action || "--");
  setOptionalText("actionMissionReason", payload.reason || "--");
  const warning = $("actionMissionSendWarning");
  if (warning) {
    warning.textContent = sendEnabled
      ? "WARNING: System SEND=ON. Tick once may dispatch vehicle/simulator commands."
      : "System SEND=OFF. Action dispatch requests remain gated.";
    warning.classList.toggle("send-on", sendEnabled);
  }
  const detailElement = $("actionMissionDetail");
  if (detailElement) detailElement.textContent = JSON.stringify(detail, null, 2);
}
function renderDashboardSummaries(next) {
  const actionLab = next.action_lab || latestActionLab || {};
  const actionStatus = actionLab?.status || actionLab || {};
  const actionLast = actionStatus?.last_result || {};
  const dispatch = dispatchFromActionLab(actionLab);
  const mission = next.action_mission || {};
  renderSummaryRows("dashboardActionSummary", [
    ["Action", actionStatus.action_name || "--", actionStatus.running ? "active" : ""],
    ["State", actionStatus.state || "--"],
    ["Reason", actionLast.reason || "--"],
    ["Done / Failed", `${Boolean(actionLast.done)} / ${Boolean(actionLast.failed)}`, actionLast.failed ? "danger" : ""],
  ]);
  renderSummaryRows("dashboardMissionSummary", [
    ["Enabled", String(Boolean(mission.enabled))],
    ["Running", String(Boolean(mission.running)), mission.running ? "active" : ""],
    ["Current", mission.current_action || "--"],
    ["Reason", mission.reason || "--"],
  ]);
  renderSummaryRows("dashboardDispatchSummary", [
    ["sent", JSON.stringify(dispatch.sent ?? "--"), dispatch.sent ? "ok" : ""],
    ["skipped", JSON.stringify(dispatch.skipped ?? "--")],
    ["errors", JSON.stringify(dispatch.errors ?? "--"), dispatch.errors ? "danger" : ""],
    ["note", actionLab.note || dispatch.note || "--"],
  ]);
}
function pointList(items, fallback, prefix) {
  return Array.isArray(items) && items.length
    ? items.map((item, index) => ({
        name: item.name || `${prefix}${index + 1}`,
        x: Number(item.x),
        y: Number(item.y),
      }))
    : fallback;
}
function fieldMapModel(next) {
  const detail = next.mission_detail || {};
  const route = detail.route || {};
  const dropCenter = route.drop_area_center || {};
  const recceCenter = route.recce_area_center || {};
  const home = route.home || {};
  const missionPosition = detail.mission_position || null;
  const drone = next.drone || {};
  const dronePosition = missionPosition || (
    drone.local_position_valid
      ? {x: Number(drone.local_x), y: Number(drone.local_y), z: Number(drone.local_z), fallback: true}
      : null
  );
  const dropTargets = Array.isArray(detail.drop_targets) ? detail.drop_targets : [];
  const recceTargets = Array.isArray(detail.recce_targets) ? detail.recce_targets : [];
  const recceResults = Array.isArray(detail.recce_results) ? detail.recce_results : [];
  const recceStatus = new Map(recceResults.map(item => [Number(item.target_id), item.status || "blank"]));
  return {
    bounds: FIELD_DEFAULTS.bounds,
    areas: {
      takeoff: {...FIELD_DEFAULTS.takeoff, x: Number(home.x ?? FIELD_DEFAULTS.takeoff.x), y: Number(home.y ?? FIELD_DEFAULTS.takeoff.y)},
      drop: {...FIELD_DEFAULTS.drop, x: Number(dropCenter.x ?? FIELD_DEFAULTS.drop.x), y: Number(dropCenter.y ?? FIELD_DEFAULTS.drop.y)},
      recce: {...FIELD_DEFAULTS.recce, x: Number(recceCenter.x ?? FIELD_DEFAULTS.recce.x), y: Number(recceCenter.y ?? FIELD_DEFAULTS.recce.y)},
    },
    dropSurvey: pointList(detail.drop_survey_points, FIELD_DEFAULTS.dropSurvey, "D"),
    recceSurvey: pointList(detail.recce_survey_points, FIELD_DEFAULTS.recceSurvey, "R"),
    dropTargets: dropTargets.filter(item => Number.isFinite(Number(item.x)) && Number.isFinite(Number(item.y)) && Number(item.seen_count || 0) > 0),
    recceTargets: recceTargets.filter(item => Number.isFinite(Number(item.x)) && Number.isFinite(Number(item.y)) && Number(item.seen_count || 0) > 0),
    recceStatus,
    drone: dronePosition,
    stage: next.stage || "--",
    dropCount: Number(detail.drop_count || 0),
    requiredDrops: Math.max(1, Number(detail.drop_required_count || 0) || (detail.payload_slots || []).length || 2),
    dropScanIndex: Number(detail.drop_scan_index || 0),
    recceScanIndex: Number(detail.recce_scan_index || 0),
    dropTargetIndex: Number(detail.drop_target_index || 0),
    recceTargetIndex: Number(detail.recce_target_index || 0),
    confirmedCount: recceResults.filter(item => item.status === "confirmed").length,
    requiredConfirmed: Math.max(1, Number(detail.recce_required_confirmed_count || 3)),
    hasMissionPosition: Boolean(missionPosition),
  };
}
function resizeFieldCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(1, Math.round(rect.width * ratio));
  const height = Math.max(1, Math.round(rect.height * ratio));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  return {ctx, rect};
}
function worldToCanvas(x, y, bounds, rect) {
  const pad = 42;
  const usableW = Math.max(1, rect.width - pad * 2);
  const usableH = Math.max(1, rect.height - pad * 2);
  const scale = Math.min(
    usableW / (bounds.yMax - bounds.yMin),
    usableH / (bounds.xMax - bounds.xMin),
  );
  const plotW = (bounds.yMax - bounds.yMin) * scale;
  const plotH = (bounds.xMax - bounds.xMin) * scale;
  const left = (rect.width - plotW) / 2;
  const top = (rect.height - plotH) / 2;
  return [
    left + (Number(y) - bounds.yMin) * scale,
    top + (bounds.xMax - Number(x)) * scale,
  ];
}
function drawFieldLabel(ctx, text, x, y, options = {}) {
  ctx.fillStyle = options.color || "#d7e6f5";
  ctx.font = options.font || "12px Consolas, monospace";
  ctx.textAlign = options.align || "center";
  ctx.textBaseline = options.baseline || "middle";
  ctx.fillText(text, x, y);
}
function drawArea(ctx, model, area, fill, stroke) {
  const [x1, y1] = worldToCanvas(area.x - area.xLen / 2, area.y - area.yLen / 2, model.bounds, model.rect);
  const [x2, y2] = worldToCanvas(area.x + area.xLen / 2, area.y + area.yLen / 2, model.bounds, model.rect);
  const left = Math.min(x1, x2);
  const top = Math.min(y1, y2);
  const width = Math.abs(x2 - x1);
  const height = Math.abs(y2 - y1);
  ctx.fillStyle = fill;
  ctx.strokeStyle = stroke;
  ctx.lineWidth = 1;
  ctx.fillRect(left, top, width, height);
  ctx.strokeRect(left, top, width, height);
  drawFieldLabel(ctx, area.label, left + width / 2, top + height / 2, {color: stroke});
}
function drawCoordinateTicks(ctx, model) {
  const bounds = model.bounds;
  ctx.strokeStyle = "rgba(147,168,191,.50)";
  ctx.fillStyle = "#93a8bf";
  ctx.lineWidth = 1;
  ctx.font = "11px Consolas, monospace";
  ctx.textBaseline = "middle";
  for (let x = 0; x <= bounds.xMax; x += 10) {
    const [leftX, leftY] = worldToCanvas(x, bounds.yMin, bounds, model.rect);
    const [rightX, rightY] = worldToCanvas(x, bounds.yMax, bounds, model.rect);
    ctx.beginPath();
    ctx.moveTo(leftX - 5, leftY);
    ctx.lineTo(leftX, leftY);
    ctx.moveTo(rightX, rightY);
    ctx.lineTo(rightX + 5, rightY);
    ctx.stroke();
    ctx.textAlign = "right";
    ctx.fillText(`x=${x}`, leftX - 8, leftY);
  }
  ctx.textBaseline = "top";
  for (let y = bounds.yMin; y <= bounds.yMax; y += 2) {
    const [tickX, tickY] = worldToCanvas(bounds.xMin, y, bounds, model.rect);
    ctx.beginPath();
    ctx.moveTo(tickX, tickY);
    ctx.lineTo(tickX, tickY + 5);
    ctx.stroke();
    ctx.textAlign = "center";
    ctx.fillText(`${y}`, tickX, tickY + 8);
  }
  drawFieldLabel(ctx, "x/m", 24, model.rect.height / 2, {color: "#93a8bf", align: "left"});
  drawFieldLabel(ctx, "y/m", model.rect.width / 2, model.rect.height - 16, {color: "#93a8bf"});
}
function drawField(ctx, model) {
  ctx.clearRect(0, 0, model.rect.width, model.rect.height);
  drawArea(ctx, model, model.areas.takeoff, "rgba(147,168,191,.10)", "rgba(147,168,191,.75)");
  drawArea(ctx, model, model.areas.drop, "rgba(57,200,191,.12)", "rgba(57,200,191,.82)");
  drawArea(ctx, model, model.areas.recce, "rgba(237,169,61,.14)", "rgba(237,169,61,.85)");
  const [x0a, y0a] = worldToCanvas(model.bounds.xMin, 0, model.bounds, model.rect);
  const [x0b, y0b] = worldToCanvas(model.bounds.xMax, 0, model.bounds, model.rect);
  ctx.strokeStyle = "rgba(147,168,191,.45)";
  ctx.setLineDash([5, 5]);
  ctx.beginPath();
  ctx.moveTo(x0a, y0a);
  ctx.lineTo(x0b, y0b);
  ctx.stroke();
  ctx.setLineDash([]);
  drawCoordinateTicks(ctx, model);
  drawFieldLabel(ctx, "+x 前方", model.rect.width - 56, 22, {color: "#93a8bf"});
  drawFieldLabel(ctx, "+y 右方", model.rect.width - 56, 40, {color: "#93a8bf"});
}
function drawSurveyPoints(ctx, model) {
  const drawPoint = (point, index, activeIndex, color) => {
    const [x, y] = worldToCanvas(point.x, point.y, model.bounds, model.rect);
    const done = index < activeIndex;
    const active = index === activeIndex;
    ctx.beginPath();
    ctx.arc(x, y, active ? 5 : 4, 0, Math.PI * 2);
    ctx.fillStyle = done ? color : "#08111a";
    ctx.strokeStyle = active ? "#e6edf6" : color;
    ctx.lineWidth = active ? 2 : 1;
    ctx.fill();
    ctx.stroke();
    drawFieldLabel(ctx, point.name, x, y - 12, {color});
  };
  model.dropSurvey.forEach((point, index) => drawPoint(point, index, model.dropScanIndex, "#39c8bf"));
  model.recceSurvey.forEach((point, index) => drawPoint(point, index, model.recceScanIndex, "#eda93d"));
}
function drawDrone(ctx, model) {
  if (!model.drone || !Number.isFinite(Number(model.drone.x)) || !Number.isFinite(Number(model.drone.y))) return;
  const [x, y] = worldToCanvas(model.drone.x, model.drone.y, model.bounds, model.rect);
  ctx.fillStyle = "#e6edf6";
  ctx.strokeStyle = "#08111a";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(x, y - 9);
  ctx.lineTo(x - 6, y + 7);
  ctx.lineTo(x, y + 4);
  ctx.lineTo(x + 6, y + 7);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  drawFieldLabel(ctx, `UAV ${num(model.drone.x, 1)}, ${num(model.drone.y, 1)}`, x + 46, y - 14, {align: "left"});
  drawFieldLabel(ctx, `z=${num(model.drone.z, 1)}`, x + 46, y + 2, {align: "left", color: "#93a8bf"});
}
function drawTargets(ctx, model) {
  const drawTarget = (target, kind, index) => {
    const isDrop = kind === "drop";
    const current = isDrop ? index === model.dropTargetIndex : index === model.recceTargetIndex;
    const visited = Boolean(target.visited);
    const status = isDrop ? "" : model.recceStatus.get(Number(target.target_id)) || "pending";
    const confirmed = status === "confirmed";
    const color = confirmed ? "#2bc277" : isDrop ? "#39c8bf" : "#eda93d";
    const [x, y] = worldToCanvas(target.x, target.y, model.bounds, model.rect);
    ctx.beginPath();
    ctx.arc(x, y, current ? 7 : 5, 0, Math.PI * 2);
    ctx.fillStyle = visited && !confirmed ? "rgba(147,168,191,.75)" : color;
    ctx.strokeStyle = current ? "#e6edf6" : "#08111a";
    ctx.lineWidth = current ? 2 : 1;
    ctx.fill();
    ctx.stroke();
    const label = `${isDrop ? "D" : "R"}-T${target.target_id}`;
    drawFieldLabel(ctx, label, x + 9, y - 10, {align: "left", color});
    drawFieldLabel(ctx, `seen=${target.seen_count ?? 0}`, x + 9, y + 5, {align: "left", color: "#93a8bf"});
  };
  model.dropTargets.forEach((target, index) => drawTarget(target, "drop", index));
  model.recceTargets.forEach((target, index) => drawTarget(target, "recce", index));
}
function drawTargetCoordinateList(ctx, model) {
  const targets = [
    ...model.dropTargets.map(target => ({...target, prefix: "D"})),
    ...model.recceTargets.map(target => ({...target, prefix: "R"})),
  ];
  if (!targets.length) return;
  const maxRows = 8;
  const rows = targets.slice(0, maxRows).map(target =>
    `${target.prefix}-T${target.target_id}: x=${num(target.x, 2)} y=${num(target.y, 2)}`
  );
  if (targets.length > maxRows) rows.push(`... +${targets.length - maxRows}`);
  const x = 16;
  const rowH = 16;
  const width = 188;
  const height = 28 + rows.length * rowH;
  const y = model.rect.height - height - 14;
  ctx.fillStyle = "rgba(8,17,26,.84)";
  ctx.strokeStyle = "rgba(147,168,191,.55)";
  ctx.lineWidth = 1;
  ctx.fillRect(x, y, width, height);
  ctx.strokeRect(x, y, width, height);
  drawFieldLabel(ctx, "筒坐标", x + 10, y + 14, {align: "left", color: "#e6edf6"});
  rows.forEach((row, index) => {
    drawFieldLabel(ctx, row, x + 10, y + 32 + index * rowH, {
      align: "left",
      color: "#93a8bf",
      font: "11px Consolas, monospace",
    });
  });
}
function renderFieldMap(next) {
  const canvas = $("fieldMap");
  if (!canvas) return;
  const {ctx, rect} = resizeFieldCanvas(canvas);
  const model = fieldMapModel(next);
  model.rect = rect;
  drawField(ctx, model);
  drawSurveyPoints(ctx, model);
  drawTargets(ctx, model);
  drawDrone(ctx, model);
  drawTargetCoordinateList(ctx, model);
  $("fieldMapEmpty").style.display = model.hasMissionPosition ? "none" : "block";
  $("fieldMapLegend").innerHTML = [
    `Stage: ${escapeHtml(model.stage)}`,
    `Drop: ${model.dropCount}/${model.requiredDrops}`,
    `Drop targets: ${model.dropTargets.length}`,
    `Recce confirmed: ${model.confirmedCount}/${model.requiredConfirmed}`,
    model.hasMissionPosition ? "Coord: mission" : "Coord: local fallback",
  ].map(item => `<span>${item}</span>`).join("");
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
  setBadge($("actionBadge"), `ACTION ${actionStatus.running ? (actionStatus.action_name || "RUN") : "--"}`, actionStatus.running ? "active" : "");
  setBadge($("missionBadge"), `MISSION ${next.action_mission?.running ? (next.action_mission.current_action || "RUN") : "--"}`, next.action_mission?.running ? "active" : "");
  setOptionalText("missionName", next.mission || "--");
  setOptionalText("missionStage", next.stage || "--");
  setOptionalText("stageController", next.stage_controller || "--");
  setOptionalText("holdReason", next.hold_reason || "none");
  updateControlHighlights(next, drone, controls);
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
function clickVideo(event) {
  const scene = state.scene || {};
  const img = $("video");
  if (!scene.image_width || !scene.image_height) return;
  const rect = img.getBoundingClientRect();
  const sourceRatio = scene.image_width / scene.image_height;
  const boxRatio = rect.width / rect.height;
  const shownWidth = sourceRatio > boxRatio ? rect.width : rect.height * sourceRatio;
  const shownHeight = sourceRatio > boxRatio ? rect.width / sourceRatio : rect.height;
  const offsetX = (rect.width - shownWidth) / 2;
  const offsetY = (rect.height - shownHeight) / 2;
  const displayX = event.clientX - rect.left - offsetX;
  const displayY = event.clientY - rect.top - offsetY;
  if (displayX < 0 || displayY < 0 || displayX > shownWidth || displayY > shownHeight) return;
  const x = displayX * scene.image_width / shownWidth;
  const y = displayY * scene.image_height / shownHeight;
  const hits = (scene.detections || []).filter(d => x >= d.x1 && x <= d.x2 && y >= d.y1 && y <= d.y2);
  if (!hits.length) {
    $("completionHint").textContent = "点击位置没有可锁定目标";
    return;
  }
  hits.sort((a, b) => (a.w * a.h) - (b.w * b.h));
  execute(`target lock ${hits[0].track_id}`, "VIDEO");
}
async function loadAudit() {
  const records = await json("/api/audit?limit=100");
  history = records.filter(r => ["CLI", "BUTTON"].includes(r.source)).map(r => r.action);
  $("auditLog").innerHTML = records.map(r =>
    `<div class="log-line ${r.ok ? "" : "bad"}">${stamp(r.timestamp)} ${escapeHtml(r.source)} &nbsp; ${escapeHtml(r.action)}</div>`).join("");
}
async function loadMissions() {
  missionCatalog = await json("/api/missions");
  if (!$("missionSelect")) return;
  $("missionSelect").innerHTML = missionCatalog.map(item =>
    `<option value="${item.name}" ${item.active ? "selected" : ""}>${item.name}</option>`).join("");
  renderMissionSteps(state || {});
}
async function loadActionLab() {
  const result = await json("/api/actions/list");
  actionSpecs = result.actions || [];
  $("actionButtons").innerHTML = actionSpecs.filter(spec => spec.name !== "payload_release").map(spec =>
    `<button data-action-name="${escapeHtml(spec.name)}">${escapeHtml(spec.label || spec.name)}</button>`
  ).join("");
  $("actionButtons").querySelectorAll("[data-action-name]").forEach(button => {
    button.onclick = () => selectAction(button.dataset.actionName);
  });
  if (actionSpecs.length) {
    const firstRegularAction = actionSpecs.find(spec => spec.name !== "payload_release") || actionSpecs[0];
    selectAction(firstRegularAction.name);
  }
}
function cacheSelectedActionParams() {
  if (!selectedActionName || !$("actionParams")) return;
  actionParamCache[selectedActionName] = $("actionParams").value;
}
function selectAction(name) {
  const spec = actionSpecs.find(item => item.name === name);
  if (!spec) return;
  cacheSelectedActionParams();
  selectedActionName = spec.name;
  if (actionParamCache[selectedActionName] === undefined) {
    actionParamCache[selectedActionName] = JSON.stringify(spec.default_params || {}, null, 2);
  }
  $("actionParams").value = actionParamCache[selectedActionName];
  let hint = spec.description || spec.label || spec.name;
  if (spec.name === "payload_release") {
    hint = `${hint} servo_outputs 是飞控 SERVO 输出通道配置，不是遥控器 RC 输入通道。舵机插在输出 8 就填 channel=8。`;
  } else if (spec.name === "goto_waypoint") {
    hint = `${hint} yaw_mode="arm_heading" 表示移动时机头保持解锁/ARM 时刻的朝向。`;
  }
  $("completionHint").textContent = hint;
  if ($("actionParamHint")) $("actionParamHint").textContent = hint;
  if ($("actionSafetyHint")) $("actionSafetyHint").textContent = ACTION_SAFETY_HINTS[spec.name] || "普通 Action；Dispatch 请求下发，实际发送仍受系统 SEND 和 dispatch 结果约束。";
  document.querySelectorAll("[data-action-name]").forEach(button =>
    button.classList.toggle("active-choice", button.dataset.actionName === selectedActionName));
  renderActionLabStatus(latestActionLab);
}
async function refreshActionStatus() {
  const result = await json("/api/actions/status");
  if (!result.ok) throw new Error(result.error || "action status failed");
  renderActionLabStatus(result.action_lab || null);
  return result;
}
function renderActionLabStatus(actionLab) {
  if (!$("actionState")) return;
  if (actionLab) latestActionLab = actionLab;
  const payload = latestActionLab || {};
  const status = payload?.status || payload || {};
  const last = status?.last_result || {};
  const detail = last.detail || {};
  const note = payload?.note || "";
  const dispatch = dispatchFromActionLab(payload);
  const sentCount = countDispatchItems(dispatch.sent);
  const skippedCount = countDispatchItems(dispatch.skipped);
  const errorCount = countDispatchItems(dispatch.errors);
  const runningAction = status?.running ? status?.action_name || "" : "";
  const selectedIsRunning = Boolean(runningAction && runningAction === selectedActionName);
  if ($("actionDryRun")) {
    $("actionDryRun").textContent = payload?.send_actions_effective
      ? `Dispatch enabled${note ? `: ${note}` : ""}`
      : `Dry-run${note ? `: ${note}` : ""}`;
  }
  $("actionState").textContent = status?.state || "--";
  $("actionSelected").textContent = selectedActionName || "--";
  $("actionRunningAction").textContent = runningAction || "--";
  $("actionRunning").textContent = String(Boolean(status?.running));
  $("actionReason").textContent = last.reason || "--";
  $("actionDone").textContent = String(Boolean(last.done));
  $("actionFailed").textContent = String(Boolean(last.failed));
  if ($("actionRunToggle")) {
    $("actionRunToggle").textContent = selectedIsRunning ? "停止" : "开始";
    $("actionRunToggle").classList.toggle("stop", selectedIsRunning);
  }
  if ($("actionStop")) $("actionStop").disabled = !Boolean(status?.running);
  setOptionalText("actionGateRequested", String(Boolean(payload?.send_actions_requested)));
  setOptionalText("actionGateEffective", String(Boolean(payload?.send_actions_effective)));
  setOptionalText("actionGateSystemSend", String(Boolean(state?.controllers?.send_commands)));
  setOptionalText("actionGateDryRun", String(Boolean(payload?.dry_run_only)));
  setOptionalText("actionGateSentCount", String(sentCount));
  setOptionalText("actionGateSkippedCount", String(skippedCount));
  setOptionalText("actionGateErrorCount", String(errorCount));
  setOptionalText("actionGateNote", note || dispatch.note || "--");
  if ($("actionSwitchHint")) {
    $("actionSwitchHint").textContent = runningAction && runningAction !== selectedActionName
      ? `当前运行：${runningAction}；当前选中：${selectedActionName || "--"}。点击“开始”将停止 ${runningAction} 并启动 ${selectedActionName || "--"}。`
      : "";
  }
  const highlights = {
    dispatch_state: errorCount > 0 ? "errors" : sentCount > 0 ? "已发送" : skippedCount > 0 ? "skipped" : undefined,
    sent: dispatch.sent,
    skipped: dispatch.skipped,
    errors: dispatch.errors,
    last_servo_command: payload.last_servo_command || detail.last_servo_command,
    command: detail.command,
    estimated_objects: detail.estimated_objects,
    channels: detail.channels,
    servo_channels: detail.servo_channels,
    servo_outputs: detail.servo_outputs,
    channel_semantics: detail.channel_semantics,
    release_sent: detail.release_sent,
    hold_sent: detail.hold_sent,
    release_time: detail.release_time,
  };
  $("actionHighlights").classList.toggle("has-errors", errorCount > 0);
  $("actionHighlights").classList.toggle("has-sent", sentCount > 0 && errorCount === 0);
  $("actionHighlights").classList.toggle("has-skipped", skippedCount > 0 && sentCount === 0 && errorCount === 0);
  $("actionHighlights").innerHTML = Object.entries(highlights)
    .filter(([, value]) => value !== undefined)
    .map(([key, value]) => `<div><span>${escapeHtml(key)}</span><code>${escapeHtml(JSON.stringify(value))}</code></div>`)
    .join("");
  $("actionStatusJson").textContent = JSON.stringify(payload || status || {}, null, 2);
}
function parseActionParams() {
  cacheSelectedActionParams();
  try {
    const value = $("actionParams").value.trim();
    return value ? JSON.parse(value) : {};
  } catch (error) {
    $("completionHint").textContent = `Action params JSON 错误: ${error.message}`;
    return null;
  }
}
function parseActionMissionSteps() {
  try {
    const value = $("actionMissionSteps").value.trim();
    const steps = value ? JSON.parse(value) : [];
    if (!Array.isArray(steps)) throw new Error("steps must be a JSON array");
    for (const [index, step] of steps.entries()) {
      if (!step || typeof step !== "object" || typeof step.name !== "string" || !step.name.trim()) {
        throw new Error(`step ${index + 1} must include name`);
      }
      if (step.params !== undefined && (step.params === null || Array.isArray(step.params) || typeof step.params !== "object")) {
        throw new Error(`step ${index + 1} params must be an object`);
      }
    }
    return steps.map(step => ({name: step.name, params: step.params || {}}));
  } catch (error) {
    $("completionHint").textContent = `Action Mission JSON 错误: ${error.message}`;
    return null;
  }
}
async function refreshActionMission() {
  const result = await json("/api/action-mission/status");
  if (!result.ok) throw new Error(result.error || "action mission status failed");
  renderActionMissionStatus(result.action_mission || null);
  return result;
}
async function configureActionMission() {
  const steps = parseActionMissionSteps();
  if (steps === null) return;
  const result = await json("/api/action-mission/configure", {
    method: "POST",
    body: JSON.stringify({steps}),
  });
  if (!result.ok) throw new Error(result.error || "action mission configure failed");
  $("completionHint").textContent = "Action Mission configured";
  renderActionMissionStatus(result.action_mission || null);
}
async function startActionMission() {
  const confirmed = window.confirm(
    "确认启动 Action Mission？\n"
    + "它会按 step 顺序运行 Action。Action 是否实发仍受 send_actions 和系统 SEND 门控控制。"
  );
  if (!confirmed) return;
  const result = await json("/api/action-mission/start", {method: "POST", body: "{}"});
  if (!result.ok) throw new Error(result.error || "action mission start failed");
  $("completionHint").textContent = "Action Mission started";
  renderActionMissionStatus(result.action_mission || null);
}
async function stopActionMission() {
  const result = await json("/api/action-mission/stop", {method: "POST", body: "{}"});
  if (!result.ok) throw new Error(result.error || "action mission stop failed");
  $("completionHint").textContent = "Action Mission stopped";
  renderActionMissionStatus(result.action_mission || null);
}
async function resetActionMission() {
  const result = await json("/api/action-mission/reset", {method: "POST", body: "{}"});
  if (!result.ok) throw new Error(result.error || "action mission reset failed");
  $("completionHint").textContent = "Action Mission reset";
  renderActionMissionStatus(result.action_mission || null);
}
async function tickActionMission() {
  const result = await json("/api/action-mission/tick", {method: "POST", body: "{}"});
  if (!result.ok) throw new Error(result.error || "action mission tick failed");
  $("completionHint").textContent = "Action Mission tick complete";
  renderActionMissionStatus(result.action_mission || null);
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
  editor.value = JSON.stringify(preset, null, 2);
  $("completionHint").textContent = "已加载模板，请检查参数后 Configure";
}
function selectedActionIsRunning() {
  const status = latestActionLab?.status || {};
  return Boolean(status?.running && status?.action_name === selectedActionName);
}
async function toggleActionLabRun() {
  if (selectedActionIsRunning()) {
    await stopActionLabAction();
  } else {
    await startActionLabAction(true);
  }
}
async function startActionLabAction(sendActions) {
  if (!selectedActionName) return;
  const params = parseActionParams();
  if (params === null) return;
  if (sendActions) {
    const confirmed = window.confirm(
      "这会请求 Action 实发。\n"
      + "如果系统 SEND=OFF，飞控命令仍不会发送。\n"
      + "如果系统 SEND=ON，local_position/body_velocity/set_servo 会实际发送到 vehicle/simulator。\n"
      + "确认继续？"
    );
    if (!confirmed) return;
  }
  const requestBody = {
    name: selectedActionName,
    params,
    send_actions: Boolean(sendActions),
  };
  console.log("Action Lab start request body", requestBody);
  const result = await json("/api/actions/start", {
    method: "POST",
    body: JSON.stringify(requestBody),
  });
  if (!result.ok) throw new Error(result.error || "action start failed");
  $("completionHint").textContent = result.note || (sendActions ? "action dispatch requested" : "action dry-run started");
  renderActionLabStatus(result.action_lab || result.status);
}
async function stopActionLabAction() {
  const result = await json("/api/actions/stop", {method: "POST", body: "{}"});
  if (!result.ok) throw new Error(result.error || "action stop failed");
  renderActionLabStatus(result.action_lab || result.status);
}
async function resetActionLabAction() {
  cacheSelectedActionParams();
  const result = await json("/api/actions/reset", {method: "POST", body: "{}"});
  if (!result.ok) throw new Error(result.error || "action reset failed");
  renderActionLabStatus(result.action_lab || result.status);
}
async function loadConfigFiles() {
  const files = await json("/api/config/files");
  $("configFiles").innerHTML = files.map(path => `<button data-path="${path}">${path}</button>`).join("");
  $("configFiles").querySelectorAll("button").forEach(button => button.onclick = () => openConfig(button.dataset.path));
}
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
  const startFallback = () => {
    if (fallbackTimer !== null) return;
    pollStatus();
    fallbackTimer = setInterval(pollStatus, 500);
    startActionTimer();
  };
  try {
    const socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/status`);
    socket.onmessage = event => renderStatus(JSON.parse(event.data));
    socket.onerror = startFallback;
    socket.onclose = startFallback;
    socket.onopen = startActionTimer;
  } catch {
    startFallback();
  }
}
async function openConfig(path) {
  const file = await json(`/api/config/file?path=${encodeURIComponent(path)}`);
  currentConfigPath = path;
  currentOriginal = file.content;
  $("editingPath").textContent = path;
  $("yamlEditor").value = file.content;
  $("configDiff").textContent = "";
  $("configStatus").textContent = file.has_backup ? "存在上一次保存前版本，可恢复。" : "尚无备份版本。";
  document.querySelectorAll("#configFiles button").forEach(b => b.classList.toggle("active", b.dataset.path === path));
  const action = path.startsWith("missions/") ? "保存并应用" :
    path === "config/telemetry.yaml" ? "保存并重连" :
    path === "config/yolo.yaml" ? "保存并重启 YOLO" :
    path === "config/app.yaml" ? "保存并重启 App" : "保存并应用";
  $("applyConfig").textContent = action;
}
function localDiff(before, after) {
  if (before === after) return "没有修改。";
  return "已修改配置；保存前后端会再次校验 YAML，并返回正式差异。";
}
async function saveConfig(action = "save") {
  if (!currentConfigPath) return;
  if (action !== "save" && !confirm(`${$("applyConfig").textContent} 将可能停止命令发送或重启服务，确认继续？`)) return;
  const result = await json(`/api/config/file?path=${encodeURIComponent(currentConfigPath)}`, {
    method: "PUT", body: JSON.stringify({content: $("yamlEditor").value, action})
  });
  currentOriginal = $("yamlEditor").value;
  $("configDiff").textContent = result.diff || "保存成功，无文本差异。";
  $("configStatus").textContent = result.message;
  await loadAudit();
}
function actionForPath() {
  if (currentConfigPath.startsWith("missions/")) return "apply";
  if (currentConfigPath === "config/telemetry.yaml") return "reconnect";
  if (currentConfigPath === "config/yolo.yaml" || currentConfigPath === "config/app.yaml") return "restart";
  return "save";
}
async function init() {
  const videoConfig = await json("/api/yolo/stream");
  const videoUrl = `${location.protocol}//${location.hostname}:${videoConfig.port}${videoConfig.path}`;
  $("video").src = videoUrl;
  $("video").onload = () => $("videoOffline").style.display = "none";
  $("video").onerror = () => {
    $("videoOffline").style.display = "block";
    setTimeout(() => { $("video").src = `${videoUrl}?retry=${Date.now()}`; }, 1500);
  };
  $("hitCanvas").onclick = clickVideo;
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
  $("sendCommand").onclick = () => {
    const input = $("commandInput");
    execute(input.value, "CLI"); input.value = ""; historyIndex = -1;
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
      flightInput.value = "";
    };
    flightInput.onkeydown = event => {
      if (event.key === "Enter") { event.preventDefault(); flightSend.click(); }
    };
  }

  document.querySelectorAll(".tab").forEach(tab => tab.onclick = () => {
    document.querySelectorAll(".tab").forEach(item => item.classList.toggle("active", item === tab));
    document.querySelectorAll(".page").forEach(page => page.classList.toggle("active", page.id === `${tab.dataset.page}Page`));
  });
  $("previewConfig").onclick = () => $("configDiff").textContent = localDiff(currentOriginal, $("yamlEditor").value);
  $("saveConfig").onclick = () => saveConfig("save");
  $("applyConfig").onclick = () => saveConfig(actionForPath());
  $("restoreConfig").onclick = async () => {
    if (!currentConfigPath || !confirm("确认恢复上一次保存前版本？")) return;
    const action = currentConfigPath.startsWith("missions/") ? "apply" : "save";
    const result = await json(`/api/config/restore?path=${encodeURIComponent(currentConfigPath)}&action=${action}`, {method: "POST"});
    $("configStatus").textContent = result.message; $("configDiff").textContent = result.diff; await openConfig(currentConfigPath); await loadAudit();
  };
  $("reconnectTelemetry").onclick = () => confirm("重连通信将关闭自动发送，确认？") && json("/api/services/telemetry/reconnect", {method: "POST"}).then(loadAudit);
  $("restartYolo").onclick = () => confirm("确认重启 YOLO 服务？") && json("/api/services/yolo/restart", {method: "POST"}).then(loadAudit);
  $("restartApp").onclick = () => confirm("重启 App 将关闭自动发送并暂时断开网页，确认？") && json("/api/services/app/restart", {method: "POST"}).then(loadAudit);
  $("actionParams").oninput = () => cacheSelectedActionParams();
  if ($("actionRunToggle")) $("actionRunToggle").onclick = () => toggleActionLabRun().catch(error => { $("completionHint").textContent = error.message; });
  if ($("actionDryRunStart")) $("actionDryRunStart").onclick = () => startActionLabAction(false).catch(error => { $("completionHint").textContent = error.message; });
  if ($("actionDispatchStart")) $("actionDispatchStart").onclick = () => startActionLabAction(true).catch(error => { $("completionHint").textContent = error.message; });
  if ($("actionStop")) $("actionStop").onclick = () => stopActionLabAction().catch(error => { $("completionHint").textContent = error.message; });
  $("actionReset").onclick = () => resetActionLabAction().catch(error => { $("completionHint").textContent = error.message; });
  $("actionRefresh").onclick = () => refreshActionStatus().catch(error => { $("completionHint").textContent = error.message; });
  if ($("actionMissionSteps")) $("actionMissionSteps").value = JSON.stringify(DEFAULT_ACTION_MISSION_STEPS, null, 2);
  if ($("actionMissionConfigure")) $("actionMissionConfigure").onclick = () => configureActionMission().catch(error => { $("completionHint").textContent = error.message; });
  if ($("actionMissionStart")) $("actionMissionStart").onclick = () => startActionMission().catch(error => { $("completionHint").textContent = error.message; });
  if ($("actionMissionStop")) $("actionMissionStop").onclick = () => stopActionMission().catch(error => { $("completionHint").textContent = error.message; });
  if ($("actionMissionReset")) $("actionMissionReset").onclick = () => resetActionMission().catch(error => { $("completionHint").textContent = error.message; });
  if ($("actionMissionTick")) $("actionMissionTick").onclick = () => tickActionMission().catch(error => { $("completionHint").textContent = error.message; });
  if ($("actionMissionRefresh")) $("actionMissionRefresh").onclick = () => refreshActionMission().catch(error => { $("completionHint").textContent = error.message; });
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
  await Promise.all([loadAudit(), loadMissions(), loadConfigFiles(), loadActionLab()]);
  startStatusUpdates();
}
init().catch(error => { $("completionHint").textContent = error.message; });
