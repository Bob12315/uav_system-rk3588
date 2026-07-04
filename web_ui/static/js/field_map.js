// field_map.js — Field Map panel logic for UAV Action Console
// Extracted from app.js (WU-5 v2).  Uses configure() pattern.
(function () {
  "use strict";

  var cfg = {
    dom: null,
    format: null,
    getState: null,
    getLatestActionLab: null,
    onClearLocalization: null,
    setCompletionHint: null,
  };

  function configure(options) {
    if (!options) return;
    if (options.dom) cfg.dom = options.dom;
    if (options.format) cfg.format = options.format;
    if (options.getState) cfg.getState = options.getState;
    if (options.getLatestActionLab) cfg.getLatestActionLab = options.getLatestActionLab;
    if (options.onClearLocalization) cfg.onClearLocalization = options.onClearLocalization;
    if (options.setCompletionHint) cfg.setCompletionHint = options.setCompletionHint;
  }

  function _state() { return cfg.getState ? cfg.getState() : {}; }
  function _latestActionLab() { return cfg.getLatestActionLab ? cfg.getLatestActionLab() : null; }
  function _setCompletionHint(text) { if (typeof cfg.setCompletionHint === "function") cfg.setCompletionHint(text); }
  function _clearLocalization() { if (typeof cfg.onClearLocalization === "function") return cfg.onClearLocalization(); }

const FIELD_DEFAULTS = {
  bounds: {xMin: -8, xMax: 8, yMin: -8, yMax: 62},
  takeoff: {x: 0, y: 0, xLen: 8, yLen: 8, label: "起降区"},
  drop: {x: 0, y: 30, xLen: 8, yLen: 5, label: "投放区"},
  recce: {x: 0, y: 55, xLen: 8, yLen: 5, label: "侦察区"},
  dropSurvey: [
    {name: "D1", x: -1.2, y: 28},
    {name: "D2", x: 1.2, y: 28},
    {name: "D3", x: -1.2, y: 32},
    {name: "D4", x: 1.2, y: 32},
  ],
  recceSurvey: [
    {name: "R1", x: -1.2, y: 53},
    {name: "R2", x: 1.2, y: 53},
    {name: "R3", x: -1.2, y: 57},
    {name: "R4", x: 1.2, y: 57},
  ],
};

function pointX(obj) {
  const fx = finiteNumber(obj.field_x);
  if (fx !== null) return fx;
  const lx = finiteNumber(obj.local_x);
  if (lx !== null) return lx;
  return finiteNumber(obj.x);
}
function pointY(obj) {
  const fy = finiteNumber(obj.field_y);
  if (fy !== null) return fy;
  const ly = finiteNumber(obj.local_y);
  if (ly !== null) return ly;
  return finiteNumber(obj.y);
}

// Convert FIELD coordinates to lat/lon using anchor + heading.
// Requires next.field_reference with origin_lat, origin_lon, field_heading_yaw_rad.
function fieldXYToLatLon(fieldX, fieldY, next) {
  const fr = (next || {}).field_reference || {};
  const lat = fr.origin_lat;
  const lon = fr.origin_lon;
  const heading = fr.field_heading_yaw_rad;
  if (lat == null || lon == null || heading == null) return null;
  // Inverse of ENU conversion
  const dNorth = fieldY * Math.cos(heading) - fieldX * Math.sin(heading);
  const dEast = fieldY * Math.sin(heading) + fieldX * Math.cos(heading);
  const latDegPerMeter = 1.0 / 111320.0;
  const lonDegPerMeter = 1.0 / (111320.0 * Math.cos(lat * Math.PI / 180.0));
  return {
    lat: lat + dNorth * latDegPerMeter,
    lon: lon + dEast * lonDegPerMeter,
  };
}
function localPointToField(point, next) {
  const tf = next.field_transform || {};
  if (!tf.confirmed) return null;
  const lx = finiteNumber(point.local_x ?? point.x);
  const ly = finiteNumber(point.local_y ?? point.y);
  const ox = finiteNumber(tf.origin_local_x);
  const oy = finiteNumber(tf.origin_local_y);
  const yaw = finiteNumber(tf.heading_yaw_rad);
  if ([lx, ly, ox, oy, yaw].some(value => value === null)) return null;
  const dx = lx - ox;
  const dy = ly - oy;
  return {
    x: -dx * Math.sin(yaw) + dy * Math.cos(yaw),
    y: dx * Math.cos(yaw) + dy * Math.sin(yaw),
  };
}
function pointForFieldMap(point, next) {
  if (!point) return null;
  if (point.valid === false) return null;
  if (point.status === "skipped_missing_target") return null;
  const fieldX = finiteNumber(point.field_x);
  const fieldY = finiteNumber(point.field_y);
  if (fieldX !== null && fieldY !== null) return {...point, x: fieldX, y: fieldY, field: true};
  const converted = localPointToField(point, next);
  if (converted) return {...point, ...converted, field_x: converted.x, field_y: converted.y, field: true};
  const x = pointX(point);
  const y = pointY(point);
  return x === null || y === null ? null : {...point, x, y};
}
function isSelectedDropTarget(obj, selectedTargets) {
  if (!Array.isArray(selectedTargets) || !selectedTargets.length) return false;
  const ox = pointX(obj);
  const oy = pointY(obj);
  return selectedTargets.some(target => {
    if (obj.id != null && target.id != null && String(obj.id) === String(target.id)) {
      return true;
    }
    const tx = pointX(target);
    const ty = pointY(target);
    if (ox === null || oy === null || tx === null || ty === null) return false;
    return Math.abs(ox - tx) < 0.15 && Math.abs(oy - ty) < 0.15;
  });
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

var profilePreview = null;

function setProfilePreview(data) {
  profilePreview = data || null;
  renderFieldMap();
}

const fieldMapView = {
  centerX: 0,
  centerY: 27,
  scale: 18,
  minScale: 4,
  maxScale: 120,
  isDragging: false,
  dragStartX: 0,
  dragStartY: 0,
  dragStartCenterX: 0,
  dragStartCenterY: 0,
  initialized: false,
};
function worldToCanvas(x, y, rect, view = fieldMapView) {
  const originX = rect.width / 2 - view.centerX * view.scale;
  const originY = rect.height / 2 + view.centerY * view.scale;
  return [
    originX + Number(x) * view.scale,
    originY - Number(y) * view.scale,
  ];
}
function canvasToWorld(screenX, screenY, rect, view = fieldMapView) {
  const originX = rect.width / 2 - view.centerX * view.scale;
  const originY = rect.height / 2 + view.centerY * view.scale;
  return {
    x: (screenX - originX) / view.scale,
    y: (originY - screenY) / view.scale,
  };
}
function finiteNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function actionLocalizationDetail(actionLab) {
  const payload = actionLab || _latestActionLab() || {};
  const status = payload?.status || payload || {};
  const candidates = [
    status?.last_result?.detail,
    status?.detail,
  ];
  for (const detail of candidates) {
    if (!detail || typeof detail !== "object") continue;
    if (Array.isArray(detail.raw_estimates)) {
      return {detail, estimates: detail.raw_estimates};
    }
  }
  for (const detail of candidates) {
    if (!detail || typeof detail !== "object") continue;
    if (Array.isArray(detail.localized_objects)) {
      return {detail, estimates: detail.localized_objects};
    }
  }
  return {detail: {}, estimates: []};
}
function actionLocalizationDrone(detail) {
  const drone = detail?.drone && typeof detail.drone === "object" ? detail.drone : {};
  const summary = detail?.summary && typeof detail.summary === "object" ? detail.summary : {};
  const x = finiteNumber(drone.local_x ?? drone.x ?? summary.drone_x);
  const y = finiteNumber(drone.local_y ?? drone.y ?? summary.drone_y);
  if (x === null || y === null) return null;
  return {x, y};
}
function actionLocalizationTargets(actionLab) {
  const {detail, estimates} = actionLocalizationDetail(actionLab);
  return {
    drone: actionLocalizationDrone(detail),
    targets: estimates
      .map((estimate, index) => {
        if (!estimate || typeof estimate !== "object") return null;
        const x = finiteNumber(estimate.local_x ?? estimate.x);
        const y = finiteNumber(estimate.local_y ?? estimate.y);
        if (x === null || y === null) return null;
        const source = estimate.source && typeof estimate.source === "object" ? estimate.source : {};
        return {
          index,
          x,
          y,
          class_name: estimate.class_name,
          confidence: finiteNumber(estimate.confidence),
          ex: finiteNumber(source.ex),
          ey: finiteNumber(source.ey),
        };
      })
      .filter(Boolean),
  };
}
function niceGridStep(scale) {
  const targetPx = 60;
  const raw = targetPx / scale;
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const normalized = raw / pow;
  if (normalized <= 1) return pow;
  if (normalized <= 2) return 2 * pow;
  if (normalized <= 5) return 5 * pow;
  return 10 * pow;
}
function fieldMapModel(next) {
  next = next || _state();
  const detail = next.mission_detail || {};
  const route = detail.route || {};
  const dropCenter = route.drop_area_center || {};
  const recceCenter = route.recce_area_center || {};
  const home = route.home || {};
  const rawFieldPosition = next.field_position || null;
  const fieldX = finiteNumber(rawFieldPosition?.x);
  const fieldY = finiteNumber(rawFieldPosition?.y);
  const fieldPosition = fieldX !== null && fieldY !== null ? {
    x: fieldX,
    y: fieldY,
    z: finiteNumber(rawFieldPosition.z ?? rawFieldPosition.local_z),
    local_x: finiteNumber(rawFieldPosition.local_x),
    local_y: finiteNumber(rawFieldPosition.local_y),
    field: true,
  } : null;
  const missionPosition = detail.mission_position || null;
  const drone = next.drone || {};
  const dronePosition = fieldPosition || missionPosition || (
    drone.local_position_valid
      ? {x: Number(drone.local_x), y: Number(drone.local_y), z: Number(drone.local_z), fallback: true}
      : null
  );
  const dropTargets = Array.isArray(detail.drop_targets) ? detail.drop_targets : [];
  const recceTargets = Array.isArray(detail.recce_targets) ? detail.recce_targets : [];
  const recceResults = Array.isArray(detail.recce_results) ? detail.recce_results : [];
  const recceStatus = new Map(recceResults.map(item => [Number(item.target_id), item.status || "blank"]));
  const localization = next.localization || {};
  const localizationObjects = Array.isArray(localization.objects) ? localization.objects : [];
  const singleViewLocalization = actionLocalizationTargets(next.action_lab || _latestActionLab());
  const fieldLocalizationObjects = localizationObjects.map(item => pointForFieldMap(item, next)).filter(Boolean);
  const fieldSingleViewTargets = singleViewLocalization.targets.map(item => pointForFieldMap(item, next)).filter(Boolean);
  const fieldSingleViewDrone = singleViewLocalization.drone
    ? pointForFieldMap(singleViewLocalization.drone, next)
    : null;
  const reconInspection = next.recon_inspection || {};
  const reconInspectionTargets = (Array.isArray(reconInspection.report) ? reconInspection.report : [])
    .map(item => pointForFieldMap(item, next)).filter(Boolean);

  // selected drop targets — priority: drop_targets.status, localization.selected_targets, action_lab detail fallback
  const dropTargetsStatus = next.drop_targets || {};
  let dropTargetsFromSelection = Array.isArray(dropTargetsStatus.selected_targets)
    ? dropTargetsStatus.selected_targets
    : Array.isArray(localization.selected_targets)
      ? localization.selected_targets
      : [];
  if (!dropTargetsFromSelection.length) {
    const alDetail = actionLocalizationDetail(next.action_lab || _latestActionLab()).detail;
    if (alDetail && Array.isArray(alDetail.selected_targets)) {
      dropTargetsFromSelection = alDetail.selected_targets;
    }
  }
  dropTargetsFromSelection = dropTargetsFromSelection.filter(item => pointX(item) !== null && pointY(item) !== null);

  return {
    bounds: FIELD_DEFAULTS.bounds,
    profilePreview: profilePreview,
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
    localizationTargets: fieldLocalizationObjects.filter(item =>
      Number.isFinite(Number(item.x)) &&
      Number.isFinite(Number(item.y))
    ),
    singleViewTargets: fieldSingleViewTargets,
    singleViewDrone: fieldSingleViewDrone,
    dropTargetsSelected: dropTargetsFromSelection.map(item => pointForFieldMap(item, next)).filter(Boolean),
    reconInspectionTargets,
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
function drawFieldLabel(ctx, text, x, y, options = {}) {
  ctx.fillStyle = options.color || "#d7e6f5";
  ctx.font = options.font || "12px Consolas, monospace";
  ctx.textAlign = options.align || "center";
  ctx.textBaseline = options.baseline || "middle";
  ctx.fillText(text, x, y);
}
function drawArea(ctx, model, area, fill, stroke) {
  const [x1, y1] = worldToCanvas(area.x - area.xLen / 2, area.y - area.yLen / 2, model.rect);
  const [x2, y2] = worldToCanvas(area.x + area.xLen / 2, area.y + area.yLen / 2, model.rect);
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
  const rect = model.rect;
  const view = fieldMapView;
  const step = niceGridStep(view.scale);
  const topLeft = canvasToWorld(0, 0, rect, view);
  const bottomRight = canvasToWorld(rect.width, rect.height, rect, view);
  const vxMin = Math.min(topLeft.x, bottomRight.x);
  const vxMax = Math.max(topLeft.x, bottomRight.x);
  const vyMin = Math.min(topLeft.y, bottomRight.y);
  const vyMax = Math.max(topLeft.y, bottomRight.y);

  ctx.strokeStyle = "rgba(147,168,191,.18)";
  ctx.fillStyle = "#93a8bf";
  ctx.lineWidth = 1;
  ctx.font = "11px Consolas, monospace";

  // vertical grid lines (constant x)
  const xStart = Math.floor(vxMin / step) * step;
  for (let x = xStart; x <= vxMax; x += step) {
    const [sx1, sy1] = worldToCanvas(x, vyMin, rect, view);
    const [sx2, sy2] = worldToCanvas(x, vyMax, rect, view);
    ctx.beginPath();
    ctx.moveTo(sx1, sy1);
    ctx.lineTo(sx2, sy2);
    ctx.stroke();
  }

  // horizontal grid lines (constant y)
  const yStart = Math.floor(vyMin / step) * step;
  for (let y = yStart; y <= vyMax; y += step) {
    const [sx1, sy1] = worldToCanvas(vxMin, y, rect, view);
    const [sx2, sy2] = worldToCanvas(vxMax, y, rect, view);
    ctx.beginPath();
    ctx.moveTo(sx1, sy1);
    ctx.lineTo(sx2, sy2);
    ctx.stroke();
  }

  // highlight y=0 axis
  ctx.strokeStyle = "rgba(147,168,191,.55)";
  ctx.setLineDash([5, 5]);
  const [x0a, y0a] = worldToCanvas(vxMin, 0, rect, view);
  const [x0b, y0b] = worldToCanvas(vxMax, 0, rect, view);
  ctx.beginPath();
  ctx.moveTo(x0a, y0a);
  ctx.lineTo(x0b, y0b);
  ctx.stroke();
  // x=0 axis
  const [x0c, y0c] = worldToCanvas(0, vyMin, rect, view);
  const [x0d, y0d] = worldToCanvas(0, vyMax, rect, view);
  ctx.beginPath();
  ctx.moveTo(x0c, y0c);
  ctx.lineTo(x0d, y0d);
  ctx.stroke();
  ctx.setLineDash([]);

  // edge labels
  ctx.strokeStyle = "rgba(147,168,191,.50)";
  // x labels at bottom
  ctx.textBaseline = "top";
  for (let x = xStart; x <= vxMax; x += step) {
    const [tickX, tickY] = worldToCanvas(x, vyMin, rect, view);
    ctx.beginPath();
    ctx.moveTo(tickX, tickY + 2);
    ctx.lineTo(tickX, tickY + 7);
    ctx.stroke();
    ctx.textAlign = "center";
    ctx.fillText(`${Math.round(x)}`, tickX, tickY + 9);
  }
  // y labels at left
  ctx.textBaseline = "middle";
  for (let y = yStart; y <= vyMax; y += step) {
    const [tickX, tickY] = worldToCanvas(vxMin, y, rect, view);
    ctx.beginPath();
    ctx.moveTo(tickX - 2, tickY);
    ctx.lineTo(tickX - 7, tickY);
    ctx.stroke();
    ctx.textAlign = "right";
    ctx.fillText(`${Math.round(y)}`, tickX - 9, tickY);
  }

  drawFieldLabel(ctx, "x/m", model.rect.width / 2, model.rect.height - 16, {color: "#93a8bf"});
  drawFieldLabel(ctx, "y/m", 24, model.rect.height / 2, {color: "#93a8bf", align: "left"});
}
function drawField(ctx, model) {
  ctx.clearRect(0, 0, model.rect.width, model.rect.height);
  drawCoordinateTicks(ctx, model);
  if (model.profilePreview) {
    drawProfilePreviewBoxes(ctx, model);
    drawProfileCornerPoints(ctx, model);
  } else {
    drawArea(ctx, model, model.areas.takeoff, "rgba(147,168,191,.10)", "rgba(147,168,191,.75)");
    drawArea(ctx, model, model.areas.drop, "rgba(57,200,191,.12)", "rgba(57,200,191,.82)");
    drawArea(ctx, model, model.areas.recce, "rgba(237,169,61,.14)", "rgba(237,169,61,.85)");
  }
  drawFieldLabel(ctx, "+x →", model.rect.width - 50, 22, {color: "#93a8bf"});
  drawFieldLabel(ctx, "+y ↑", model.rect.width - 50, 40, {color: "#93a8bf"});
}
function drawSurveyPoints(ctx, model) {
  const drawPoint = (point, index, activeIndex, color) => {
    const [x, y] = worldToCanvas(point.x, point.y, model.rect);
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
  const [x, y] = worldToCanvas(model.drone.x, model.drone.y, model.rect);
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
  const label = model.drone.field ? "UAV field" : model.drone.fallback ? "UAV LOCAL fallback" : "UAV";
  drawFieldLabel(ctx, `${label} ${num(model.drone.x, 1)}, ${num(model.drone.y, 1)}`, x + 46, y - 14, {align: "left"});
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
    const [x, y] = worldToCanvas(target.x, target.y, model.rect);
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
function drawLocalizationTargets(ctx, model) {
  model.localizationTargets.forEach((target, index) => {
    const tx = pointX(target);
    const ty = pointY(target);
    if (tx === null || ty === null) return;
    const [x, y] = worldToCanvas(tx, ty, model.rect);
    const id = target.id ?? target.target_id ?? index;
    const count = target.count ?? target.seen_count ?? 0;
    const selected = isSelectedDropTarget(target, model.dropTargetsSelected);
    const fillColor = selected ? "#ff3b30" : "#2bc277";
    const labelColor = selected ? "#ff3b30" : "#2bc277";
    ctx.beginPath();
    ctx.arc(x, y, selected ? 8 : 7, 0, Math.PI * 2);
    ctx.fillStyle = fillColor;
    ctx.strokeStyle = "#e6edf6";
    ctx.lineWidth = 2;
    ctx.fill();
    ctx.stroke();
    drawFieldLabel(ctx, `L${id} ${target.class_name || "obj"}`, x + 10, y - 12, {
      align: "left",
      color: labelColor,
    });
    drawFieldLabel(ctx, `x=${num(tx, 2)} y=${num(ty, 2)} n=${count}`, x + 10, y + 5, {
      align: "left",
      color: "#93a8bf",
      font: "11px Consolas, monospace",
    });
  });
}
function drawReconInspectionTargets(ctx, model) {
  model.reconInspectionTargets.forEach((target, index) => {
    const tx = pointX(target), ty = pointY(target);
    if (tx === null || ty === null) return;
    const [x, y] = worldToCanvas(tx, ty, model.rect);
    const detected = target.status === "detected";
    const noSign = target.status === "no_sign";
    const color = detected ? "#ffb347" : noSign ? "#93a8bf" : "#ff5b5b";
    const label = detected ? `${target.sign_class || "--"} ${num(target.confidence, 2)}`
      : noSign ? "无标识" : "识别失败";
    ctx.beginPath();
    ctx.arc(x, y, 7, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.strokeStyle = "#e6edf6";
    ctx.lineWidth = 2;
    ctx.fill();
    ctx.stroke();
    drawFieldLabel(ctx, `I${index + 1} ${label}`, x + 10, y - 10, {align: "left", color});
  });
}
function drawSingleViewTargets(ctx, model) {
  const targets = Array.isArray(model.singleViewTargets) ? model.singleViewTargets : [];
  if (!targets.length) return;
  const lineSource = model.singleViewDrone || (
    model.drone && Number.isFinite(Number(model.drone.x)) && Number.isFinite(Number(model.drone.y))
      ? {x: Number(model.drone.x), y: Number(model.drone.y)}
      : null
  );
  targets.forEach((target, index) => {
    const [x, y] = worldToCanvas(target.x, target.y, model.rect);
    if (lineSource) {
      const [sx, sy] = worldToCanvas(lineSource.x, lineSource.y, model.rect);
      ctx.beginPath();
      ctx.moveTo(sx, sy);
      ctx.lineTo(x, y);
      ctx.strokeStyle = "rgba(255,91,91,.55)";
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    ctx.beginPath();
    ctx.moveTo(x - 6, y);
    ctx.lineTo(x + 6, y);
    ctx.moveTo(x, y - 6);
    ctx.lineTo(x, y + 6);
    ctx.strokeStyle = "#ff5b5b";
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x, y, 4, 0, Math.PI * 2);
    ctx.fillStyle = "#08111a";
    ctx.strokeStyle = "#ff5b5b";
    ctx.lineWidth = 1;
    ctx.fill();
    ctx.stroke();

    const label = `SV${index}`;
    const meta = [];
    if (target.confidence !== null) meta.push(`conf=${num(target.confidence, 2)}`);
    if (target.ex !== null && target.ey !== null) meta.push(`ex=${num(target.ex, 2)} ey=${num(target.ey, 2)}`);
    drawFieldLabel(ctx, label, x + 10, y - 12, {align: "left", color: "#ff8a8a"});
    if (meta.length) {
      drawFieldLabel(ctx, meta.join(" "), x + 10, y + 5, {
        align: "left",
        color: "#ffb3b3",
        font: "11px Consolas, monospace",
      });
    }
  });
}

function drawProfilePreviewBoxes(ctx, model) {
  var preview = model.profilePreview;
  if (!preview || !Array.isArray(preview.boxes)) return;
  var colors = {
    field_bounds: {fill: "rgba(147,168,191,.10)", stroke: "rgba(147,168,191,.75)"},
    drop_area: {fill: "rgba(57,200,191,.12)", stroke: "rgba(57,200,191,.82)"},
    recce_area: {fill: "rgba(237,169,61,.14)", stroke: "rgba(237,169,61,.85)"},
  };
  preview.boxes.forEach(function (box) {
    var c = colors[box.kind] || {fill: "rgba(147,168,191,.08)", stroke: "rgba(147,168,191,.55)"};
    var xs = box.corners.map(function (pt) { return pt.field_x; });
    var ys = box.corners.map(function (pt) { return pt.field_y; });
    var fxMin = Math.min.apply(null, xs);
    var fxMax = Math.max.apply(null, xs);
    var fyMin = Math.min.apply(null, ys);
    var fyMax = Math.max.apply(null, ys);
    var area = {x: (fxMin + fxMax) / 2, y: (fyMin + fyMax) / 2, xLen: fxMax - fxMin, yLen: fyMax - fyMin, label: box.label};
    drawArea(ctx, model, area, c.fill, c.stroke);
  });
}

function drawProfileCornerPoints(ctx, model) {
  var preview = model.profilePreview;
  if (!preview || !Array.isArray(preview.boxes)) return;
  preview.boxes.forEach(function (box) {
    box.corners.forEach(function (pt) {
      var pos = worldToCanvas(pt.field_x, pt.field_y, model.rect);
      var cx = pos[0], cy = pos[1];
      ctx.beginPath();
      ctx.arc(cx, cy, 4, 0, Math.PI * 2);
      ctx.fillStyle = "#e6edf6";
      ctx.strokeStyle = "#08111a";
      ctx.lineWidth = 1.5;
      ctx.fill();
      ctx.stroke();
      drawFieldLabel(ctx, pt.name, cx + 8, cy - 8, {align: "left", color: "#e6edf6", font: "10px Consolas, monospace"});
    });
  });
}

function renderFieldMapInfoBox(model) {
  var el = $("fieldMapInfoBox");
  if (!el) return;
  var preview = model.profilePreview;
  if (!preview || !preview.ok) {
    el.style.display = "none";
    return;
  }
  el.style.display = "block";
  var lines = [];
  lines.push("Field Profile: " + escapeHtml(preview.profile_id || "--"));
  lines.push("Heading: " + (preview.reference && preview.reference.field_heading_deg != null ? preview.reference.field_heading_deg.toFixed(2) + "°" : "--"));
  lines.push("Origin O: " + (preview.reference ? preview.reference.origin_lat.toFixed(7) + ", " + preview.reference.origin_lon.toFixed(7) : "--"));
  lines.push("");

  var boxes = preview.boxes || [];
  var boxTags = {field_bounds: "Field corners", drop_area: "Drop area", recce_area: "Recce area"};
  boxes.forEach(function (box) {
    var tag = boxTags[box.kind] || box.label || box.id;
    lines.push(tag + ":");
    (box.corners || []).forEach(function (c) {
      var sx = c.field_x >= 0 ? "+" + c.field_x.toFixed(2) : c.field_x.toFixed(2);
      var sy = c.field_y >= 0 ? "+" + c.field_y.toFixed(2) : c.field_y.toFixed(2);
      lines.push(
        c.name + " x=" + sx + " y=" + sy +
        " GPS " + c.lat.toFixed(7) + ", " + c.lon.toFixed(7)
      );
    });
  });

  // Merge tube coordinates (drawTargetCoordinateList data)
  var dropTargets = (model.dropTargets || []).map(function (t) { return {prefix: "D", target: t}; });
  var recceTargets = (model.recceTargets || []).map(function (t) { return {prefix: "R", target: t}; });
  var locTargets = (model.localizationTargets || []).map(function (t) { return {prefix: "L", target: t}; });
  var allTargets = dropTargets.concat(recceTargets).concat(locTargets);
  if (allTargets.length) {
    lines.push("");
    lines.push("Targets:");
    var maxRows = 8;
    allTargets.slice(0, maxRows).forEach(function (item) {
      var t = item.target;
      var tid = t.target_id != null ? t.target_id : "?";
      var tx = num(pointX(t), 2);
      var ty = num(pointY(t), 2);
      lines.push(item.prefix + "-T" + tid + ": x=" + tx + " y=" + ty);
    });
    if (allTargets.length > maxRows) lines.push("... +" + (allTargets.length - maxRows));
  }

  el.innerHTML = lines.map(function (l) { return escapeHtml(l); }).join("<br>");
}

function drawTargetCoordinateList(ctx, model) {
  const targets = [
    ...model.dropTargets.map(target => ({...target, prefix: "D"})),
    ...model.recceTargets.map(target => ({...target, prefix: "R"})),
    ...model.localizationTargets.map(target => ({...target, prefix: "L"})),
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
function fitFieldMapToDefaults() {
  const bounds = FIELD_DEFAULTS.bounds;
  fieldMapView.centerX = (bounds.xMin + bounds.xMax) / 2;
  fieldMapView.centerY = (bounds.yMin + bounds.yMax) / 2;
  const canvas = $("fieldMap");
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  const pad = 70;
  const scaleX = Math.max(1, (rect.width - pad * 2) / (bounds.xMax - bounds.xMin));
  const scaleY = Math.max(1, (rect.height - pad * 2) / (bounds.yMax - bounds.yMin));
  fieldMapView.scale = Math.max(
    fieldMapView.minScale,
    Math.min(fieldMapView.maxScale, Math.min(scaleX, scaleY))
  );
  fieldMapView.initialized = true;
}
function setupFieldMapInteractions() {
  const canvas = $("fieldMap");
  if (!canvas || canvas.dataset.mapReady === "1") return;
  canvas.dataset.mapReady = "1";

  canvas.addEventListener("wheel", event => {
    event.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const mouseX = event.clientX - rect.left;
    const mouseY = event.clientY - rect.top;
    const before = canvasToWorld(mouseX, mouseY, rect);
    const zoomFactor = event.deltaY < 0 ? 1.15 : 1 / 1.15;
    fieldMapView.scale = Math.max(
      fieldMapView.minScale,
      Math.min(fieldMapView.maxScale, fieldMapView.scale * zoomFactor)
    );
    const after = canvasToWorld(mouseX, mouseY, rect);
    fieldMapView.centerX += after.x - before.x;
    fieldMapView.centerY += before.y - after.y;
    renderFieldMap();
  }, {passive: false});

  // mousemove: display FIELD x/y and lat/lon coordinates
  canvas.addEventListener("mousemove", event => {
    var rect = canvas.getBoundingClientRect();
    var world = canvasToWorld(event.clientX - rect.left, event.clientY - rect.top, rect);
    var next = _state();
    var latLon = fieldXYToLatLon(world.x, world.y, next);
    var coordEl = document.getElementById("fieldMapCoord");
    if (coordEl) {
      var latStr = latLon ? latLon.lat.toFixed(6) : "--";
      var lonStr = latLon ? latLon.lon.toFixed(6) : "--";
      coordEl.textContent =
        "FIELD x=" + world.x.toFixed(2) + " y=" + world.y.toFixed(2) +
        " | lat=" + latStr + " lon=" + lonStr;
    }
  });

  // Pointer Events: unify mouse + touch drag/pinch
  const activePointers = new Map();

  function pointerPoint(event) {
    const rect = canvas.getBoundingClientRect();
    return {
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      canvasX: event.clientX - rect.left,
      canvasY: event.clientY - rect.top,
    };
  }

  function pinchDistance(a, b) {
    return Math.hypot(a.x - b.x, a.y - b.y);
  }

  function pinchMidpoint(a, b) {
    return {
      x: (a.x + b.x) / 2,
      y: (a.y + b.y) / 2,
    };
  }

  fieldMapView.pinchStartDistance = 0;
  fieldMapView.pinchStartScale = fieldMapView.scale;
  fieldMapView.pinchStartWorld = null;

  canvas.addEventListener("pointerdown", event => {
    event.preventDefault();
    canvas.setPointerCapture(event.pointerId);
    activePointers.set(event.pointerId, pointerPoint(event));

    if (activePointers.size === 1) {
      fieldMapView.isDragging = true;
      fieldMapView.dragStartX = event.clientX;
      fieldMapView.dragStartY = event.clientY;
      fieldMapView.dragStartCenterX = fieldMapView.centerX;
      fieldMapView.dragStartCenterY = fieldMapView.centerY;
      canvas.classList.add("dragging");
    }

    if (activePointers.size === 2) {
      const points = Array.from(activePointers.values());
      const rect = canvas.getBoundingClientRect();
      const mid = pinchMidpoint(points[0], points[1]);
      fieldMapView.pinchStartDistance = Math.max(1, pinchDistance(points[0], points[1]));
      fieldMapView.pinchStartScale = fieldMapView.scale;
      fieldMapView.pinchStartWorld = canvasToWorld(mid.x - rect.left, mid.y - rect.top, rect);
    }
  });

  canvas.addEventListener("pointermove", event => {
    if (!activePointers.has(event.pointerId)) return;
    event.preventDefault();
    activePointers.set(event.pointerId, pointerPoint(event));

    if (activePointers.size === 1 && fieldMapView.isDragging) {
      const p = activePointers.get(event.pointerId);
      const dx = p.x - fieldMapView.dragStartX;
      const dy = p.y - fieldMapView.dragStartY;
      fieldMapView.centerX = fieldMapView.dragStartCenterX - dx / fieldMapView.scale;
      fieldMapView.centerY = fieldMapView.dragStartCenterY + dy / fieldMapView.scale;
      renderFieldMap();
      return;
    }

    if (activePointers.size >= 2) {
      const points = Array.from(activePointers.values()).slice(0, 2);
      const rect = canvas.getBoundingClientRect();
      const mid = pinchMidpoint(points[0], points[1]);
      const currentDistance = Math.max(1, pinchDistance(points[0], points[1]));
      const before = fieldMapView.pinchStartWorld || canvasToWorld(mid.x - rect.left, mid.y - rect.top, rect);

      fieldMapView.scale = Math.max(
        fieldMapView.minScale,
        Math.min(fieldMapView.maxScale, fieldMapView.pinchStartScale * currentDistance / fieldMapView.pinchStartDistance)
      );

      const after = canvasToWorld(mid.x - rect.left, mid.y - rect.top, rect);
      fieldMapView.centerX += after.x - before.x;
      fieldMapView.centerY += before.y - after.y;
      renderFieldMap();
    }
  });

  function endPointer(event) {
    activePointers.delete(event.pointerId);
    if (activePointers.size === 0) {
      fieldMapView.isDragging = false;
      fieldMapView.pinchStartWorld = null;
      canvas.classList.remove("dragging");
    } else if (activePointers.size === 1) {
      const p = Array.from(activePointers.values())[0];
      fieldMapView.isDragging = true;
      fieldMapView.dragStartX = p.x;
      fieldMapView.dragStartY = p.y;
      fieldMapView.dragStartCenterX = fieldMapView.centerX;
      fieldMapView.dragStartCenterY = fieldMapView.centerY;
    }
  }

  canvas.addEventListener("pointerup", endPointer);
  canvas.addEventListener("pointercancel", endPointer);
  canvas.addEventListener("lostpointercapture", endPointer);

  // button handlers
  $("fieldMapZoomIn")?.addEventListener("click", () => {
    fieldMapView.scale = Math.min(fieldMapView.maxScale, fieldMapView.scale * 1.2);
    renderFieldMap();
  });
  $("fieldMapZoomOut")?.addEventListener("click", () => {
    fieldMapView.scale = Math.max(fieldMapView.minScale, fieldMapView.scale / 1.2);
    renderFieldMap();
  });
  $("fieldMapReset")?.addEventListener("click", () => {
    fitFieldMapToDefaults();
    renderFieldMap();
  });
  $("clearLocalization")?.addEventListener("click", () => {
    _clearLocalization().catch(error => {
      _setCompletionHint("清空筒坐标失败: " + error.message);
    });
  });
}
function renderFieldMap(next) {
  next = next || _state();
  const canvas = $("fieldMap");
  if (!canvas) return;
  setupFieldMapInteractions();
  const {ctx, rect} = resizeFieldCanvas(canvas);
  const model = fieldMapModel(next);
  model.rect = rect;
  if (!fieldMapView.initialized) {
    fitFieldMapToDefaults();
  }
  drawField(ctx, model);
  drawSurveyPoints(ctx, model);
  drawTargets(ctx, model);
  drawLocalizationTargets(ctx, model);
  drawReconInspectionTargets(ctx, model);
  drawSingleViewTargets(ctx, model);
  drawDrone(ctx, model);
  if (model.profilePreview) {
    renderFieldMapInfoBox(model);
  } else {
    drawTargetCoordinateList(ctx, model);
    var infoEl = $("fieldMapInfoBox");
    if (infoEl) infoEl.style.display = "none";
  }
  $("fieldMapEmpty").style.display = model.hasMissionPosition ? "none" : "block";
  $("fieldMapLegend").innerHTML = [
    `Stage: ${escapeHtml(model.stage)}`,
    `Drop: ${model.dropCount}/${model.requiredDrops}`,
    `Drop targets: ${model.dropTargets.length}`,
    `Selected: ${model.dropTargetsSelected.length}`,
    `Recce confirmed: ${model.confirmedCount}/${model.requiredConfirmed}`,
    `Localization: ${model.localizationTargets.length}`,
    `SingleView: ${model.singleViewTargets.length}`,
    `Recon inspect: ${model.reconInspectionTargets.length}`,
    model.hasMissionPosition ? "Coord: mission" : "Coord: local fallback",
  ].map(item => `<span>${item}</span>`).join("");
}


  window.UavFieldMap = {
    configure: configure,
    FIELD_DEFAULTS: FIELD_DEFAULTS,
    fieldMapView: fieldMapView,
    finiteNumber: finiteNumber,
    pointX: pointX,
    pointY: pointY,
    localPointToField: localPointToField,
    pointForFieldMap: pointForFieldMap,
    isSelectedDropTarget: isSelectedDropTarget,
    fieldMapModel: fieldMapModel,
    canvasToWorld: canvasToWorld,
    fieldXYToLatLon: fieldXYToLatLon,
    worldToCanvas: worldToCanvas,
    fitFieldMapToDefaults: fitFieldMapToDefaults,
    setupFieldMapInteractions: setupFieldMapInteractions,
    renderFieldMap: renderFieldMap,
    setProfilePreview: setProfilePreview,
  };
})();
