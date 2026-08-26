// FIELD map: a strict FIELD-only display with cached static rendering.
(function () {
  "use strict";

  const Model = window.UavFieldModel;
  const Render = window.UavFieldRender;
  const DEFAULT_BOUNDS = {xMin: -8, xMax: 8, yMin: -8, yMax: 62};
  const MAP_DEMO_ENABLED = new URLSearchParams(window.location.search).get("demo-field-map") === "1";
  const MAP_DEMO = Object.freeze({
    drone: {x: 1.8, y: 8.4, zUp: 5.6, yaw: 0.62},
    boxes: [
      {label: "主跑道", color: "#93a8bf", points: [{x: -4, y: 0}, {x: 4, y: 0}, {x: 4, y: 55}, {x: -4, y: 55}]},
      {label: "投放区", color: "#39c8bf", points: [{x: -4, y: 30}, {x: 4, y: 30}, {x: 4, y: 35}, {x: -4, y: 35}]},
      {label: "侦察区", color: "#eda93d", points: [{x: -4, y: 55}, {x: 4, y: 55}, {x: 4, y: 60}, {x: -4, y: 60}]},
    ],
    startPoint: {x: 0, y: 1.5, label: "起点 A"},
    localization: [
      {id: "01", x: -1.35, y: 32.10},
      {id: "02", x: 2.20, y: 33.45},
    ],
  });
  const view = {centerX: 0, centerY: 27, scale: 16, minScale: 4, maxScale: 100, initialized: false};
  const cfg = {dom: null, getState: null, onClearLocalization: null, setCompletionHint: null};
  let runtimeGeometry = null;
  let runtimeGeometryConfirmed = false;
  let latestState = null;
  let renderQueued = false;
  let resizeDirty = true;
  let baseCanvas = null;
  let baseKey = "";
  let canvasRect = null;
  let pixelRatio = 1;
  let infoKey = "";

  function configure(options) { if (options) Object.assign(cfg, options); }
  function $(id) { return cfg.dom ? cfg.dom.$(id) : document.getElementById(id); }
  function state() { return latestState || (cfg.getState ? cfg.getState() : {}); }
  function finite(value) { return Model.finiteNumber(value); }
  function fieldPoint(value) { return Model.pointForFieldMap(value); }
  function fieldReady(reference) {
    return Boolean(reference && reference.is_confirmed && reference.is_frozen
      && reference.is_ready_for_field_to_gps && reference.synced_to_runtime);
  }
  function normalizeRadians(value) { return Math.atan2(Math.sin(value), Math.cos(value)); }

  function setRuntimeGeometry(geometry, confirmed) {
    runtimeGeometry = geometry || null;
    runtimeGeometryConfirmed = Boolean(confirmed);
    baseKey = "";
    queueRender();
  }
  // Compatibility hook: geometry now comes exclusively from runtime Field Setup.
  function setProfilePreview() { queueRender(); }

  function geometryBoxes() {
    if (!runtimeGeometry) return [];
    return [
      {label: "投放区", color: "#39c8bf", points: runtimeGeometry.drop_area_corners},
      {label: "侦察区", color: "#eda93d", points: runtimeGeometry.recce_area_corners},
    ].map(function (box) {
      return {...box, points: Array.isArray(box.points) ? box.points.map(fieldPoint).filter(Boolean) : []};
    }).filter(function (box) { return box.points.length >= 3; });
  }

  function fieldMapModel(next) {
    next = next || state();
    if (MAP_DEMO_ENABLED) return {
      ready: true, reference: {}, drone: MAP_DEMO.drone, boxes: MAP_DEMO.boxes,
      startPoint: MAP_DEMO.startPoint, localization: MAP_DEMO.localization, recon: [], stage: "DEMO", source: "DEMO 假数据（不连接飞控）",
    };
    const reference = next.field_reference || {};
    const ready = fieldReady(reference);
    const position = next.field_position || {};
    const x = finite(position.x), y = finite(position.y), localZ = finite(position.local_z);
    const yaw = finite(next.field_heading && next.field_heading.current_yaw_rad);
    const fieldYaw = finite(reference.field_heading_yaw_rad);
    const drone = ready && x !== null && y !== null && yaw !== null && fieldYaw !== null
      ? {x, y, zUp: localZ === null ? null : -localZ, yaw: normalizeRadians(yaw - fieldYaw)} : null;
    const localization = Array.isArray(next.drop_localization?.objects)
      ? next.drop_localization
      : (next.localization || {});
    const recon = next.recon_localization || {};
    const toField = function (items) { return ready && Array.isArray(items) ? items.map(fieldPoint).filter(Boolean) : []; };
    return {
      ready, reference, drone, boxes: geometryBoxes(),
      startPoint: null, localization: toField(localization.objects), recon: toField(recon.objects),
      stage: next.stage || "--", source: ready ? "FIELD via GPS" : "FIELD unavailable",
    };
  }

  function queueRender(next) {
    latestState = next || latestState || (cfg.getState ? cfg.getState() : {});
    if (renderQueued) return;
    renderQueued = true;
    requestAnimationFrame(function () { renderQueued = false; renderNow(latestState || {}); });
  }
  function renderFieldMap(next) { queueRender(next); }

  function ensureCanvas(canvas) {
    if (!resizeDirty && canvasRect) return;
    const rect = canvas.getBoundingClientRect();
    const rawRatio = window.devicePixelRatio || 1;
    pixelRatio = Math.min(rawRatio, window.matchMedia && window.matchMedia("(pointer: coarse)").matches ? 1.25 : 2);
    canvasRect = {width: Math.max(1, rect.width), height: Math.max(1, rect.height)};
    const width = Math.round(canvasRect.width * pixelRatio), height = Math.round(canvasRect.height * pixelRatio);
    if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
    resizeDirty = false;
    baseKey = "";
  }
  function toCanvas(x, y) { return Render.worldToCanvas(x, y, canvasRect, view); }
  function toWorld(x, y) { return Render.canvasToWorld(x, y, canvasRect, view); }
  function drawLabel(ctx, text, x, y, color, align) {
    ctx.fillStyle = color || "#d7e6f5";
    ctx.font = "11px Consolas, monospace";
    ctx.textAlign = align || "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, x, y);
  }
  function baseCacheKey(model) {
    return JSON.stringify({
      w: Math.round(canvasRect.width), h: Math.round(canvasRect.height), dpr: pixelRatio,
      cx: Number(view.centerX.toFixed(3)), cy: Number(view.centerY.toFixed(3)), scale: Number(view.scale.toFixed(3)),
      boxes: model.boxes.map(function (box) { return [box.label, box.points.map(function (p) { return [p.x, p.y]; })]; }),
      confirmed: runtimeGeometryConfirmed,
    });
  }
  function drawGrid(ctx) {
    const step = Render.niceGridStep(view.scale);
    const a = toWorld(0, 0), b = toWorld(canvasRect.width, canvasRect.height);
    const minX = Math.min(a.x, b.x), maxX = Math.max(a.x, b.x), minY = Math.min(a.y, b.y), maxY = Math.max(a.y, b.y);
    ctx.strokeStyle = "rgba(147,168,191,.18)"; ctx.lineWidth = 1;
    for (let x = Math.floor(minX / step) * step; x <= maxX; x += step) {
      const p = toCanvas(x, minY), q = toCanvas(x, maxY); ctx.beginPath(); ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]); ctx.stroke();
    }
    for (let y = Math.floor(minY / step) * step; y <= maxY; y += step) {
      const p = toCanvas(minX, y), q = toCanvas(maxX, y); ctx.beginPath(); ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]); ctx.stroke();
    }
    ctx.strokeStyle = "rgba(147,168,191,.55)"; ctx.setLineDash([5, 5]);
    let p = toCanvas(0, minY), q = toCanvas(0, maxY); ctx.beginPath(); ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]); ctx.stroke();
    p = toCanvas(minX, 0); q = toCanvas(maxX, 0); ctx.beginPath(); ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]); ctx.stroke();
    ctx.setLineDash([]);
    drawLabel(ctx, "+X →", canvasRect.width - 16, 18, "#93a8bf", "right");
    drawLabel(ctx, "+Y ↑", canvasRect.width - 16, 35, "#93a8bf", "right");
  }
  function drawBoxes(ctx, boxes) {
    boxes.forEach(function (box) {
      const screen = box.points.map(function (point) { return toCanvas(point.x, point.y); });
      ctx.beginPath();
      screen.forEach(function (point, index) { if (index) ctx.lineTo(point[0], point[1]); else ctx.moveTo(point[0], point[1]); });
      ctx.closePath();
      ctx.fillStyle = box.color === "#39c8bf" ? "rgba(57,200,191,.12)"
        : box.color === "#eda93d" ? "rgba(237,169,61,.14)" : "rgba(147,168,191,.12)";
      ctx.strokeStyle = box.color; ctx.lineWidth = 1.5; ctx.fill(); ctx.stroke();
      const center = box.points.reduce(function (sum, point) { return {x: sum.x + point.x, y: sum.y + point.y}; }, {x: 0, y: 0});
      const point = toCanvas(center.x / box.points.length, center.y / box.points.length);
      drawLabel(ctx, box.label + (runtimeGeometryConfirmed ? "" : "（预览）"), point[0], point[1], box.color);
    });
  }
  function refreshBase(model) {
    const key = baseCacheKey(model);
    if (key === baseKey && baseCanvas) return;
    baseKey = key;
    baseCanvas = document.createElement("canvas");
    baseCanvas.width = Math.round(canvasRect.width * pixelRatio); baseCanvas.height = Math.round(canvasRect.height * pixelRatio);
    const ctx = baseCanvas.getContext("2d");
    ctx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    ctx.clearRect(0, 0, canvasRect.width, canvasRect.height);
    drawGrid(ctx); drawBoxes(ctx, model.boxes);
  }
  function drawDrone(ctx, drone) {
    if (!drone) return;
    const point = toCanvas(drone.x, drone.y);
    ctx.save(); ctx.translate(point[0], point[1]); ctx.rotate(drone.yaw);
    ctx.beginPath(); ctx.moveTo(0, -11); ctx.lineTo(-7, 8); ctx.lineTo(0, 4); ctx.lineTo(7, 8); ctx.closePath();
    ctx.fillStyle = "#e6edf6"; ctx.strokeStyle = "#08111a"; ctx.lineWidth = 1.5; ctx.fill(); ctx.stroke(); ctx.restore();
    drawLabel(ctx, "UAV", point[0] + 16, point[1] - 12, "#e6edf6", "left");
    drawLabel(ctx, "x=" + drone.x.toFixed(2) + " y=" + drone.y.toFixed(2), point[0] + 16, point[1] + 3, "#93a8bf", "left");
  }
  function drawStartPoint(ctx, startPoint) {
    if (!startPoint) return;
    const point = toCanvas(startPoint.x, startPoint.y);
    ctx.beginPath(); ctx.arc(point[0], point[1], 8, 0, Math.PI * 2);
    ctx.fillStyle = "#08111a"; ctx.strokeStyle = "#e6edf6"; ctx.lineWidth = 2; ctx.fill(); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(point[0] - 4, point[1]); ctx.lineTo(point[0] + 4, point[1]); ctx.moveTo(point[0], point[1] - 4); ctx.lineTo(point[0], point[1] + 4); ctx.stroke();
    drawLabel(ctx, startPoint.label, point[0] + 12, point[1] - 12, "#e6edf6", "left");
  }
  function drawObjects(ctx, objects, color, prefix) {
    objects.slice(0, 64).forEach(function (point, index) {
      const p = toCanvas(point.x, point.y);
      ctx.beginPath();
      if (prefix === "筒") ctx.rect(p[0] - 6, p[1] - 6, 12, 12);
      else ctx.arc(p[0], p[1], 6, 0, Math.PI * 2);
      ctx.fillStyle = color; ctx.strokeStyle = "#08111a"; ctx.lineWidth = 1.5; ctx.fill(); ctx.stroke();
      const id = point.id ?? point.target_id ?? index + 1;
      drawLabel(ctx, prefix + " " + id, p[0] + 10, p[1] - 8, color, "left");
      if (prefix === "筒") drawLabel(ctx, "x=" + point.x.toFixed(2) + " y=" + point.y.toFixed(2), p[0] + 10, p[1] + 7, "#93a8bf", "left");
    });
  }
  function updateInfo(model) {
    const info = $("fieldMapInfoBox");
    if (info) {
      const text = MAP_DEMO_ENABLED ? "DEMO 假数据：未连接飞控，不能用于操作。"
        : model.ready ? "坐标：FIELD via GPS（已确认并冻结）"
        : runtimeGeometry ? "场地几何：预览；飞机和目标坐标已隐藏，等待确认/冻结。" : "等待 Field Reference 确认、同步并冻结。";
      if (text !== infoKey) { info.textContent = text; infoKey = text; }
      info.style.display = "block";
    }
    const legend = $("fieldMapLegend");
    if (legend) legend.innerHTML = ["Coord: " + model.source, "Stage: " + model.stage, "筒: " + model.localization.length, "Recon: " + model.recon.length]
      .map(function (text) { return "<span>" + text + "</span>"; }).join("");
    const empty = $("fieldMapEmpty");
    if (empty) empty.style.display = model.ready || runtimeGeometry ? "none" : "block";
  }
  function renderNow(next) {
    const canvas = $("fieldMap");
    if (!canvas) return;
    ensureCanvas(canvas); setupFieldMapInteractions();
    const model = fieldMapModel(next);
    if (!view.initialized) fitFieldMapToDefaults();
    refreshBase(model);
    const ctx = canvas.getContext("2d");
    ctx.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    ctx.clearRect(0, 0, canvasRect.width, canvasRect.height);
    ctx.drawImage(baseCanvas, 0, 0, baseCanvas.width, baseCanvas.height, 0, 0, canvasRect.width, canvasRect.height);
    drawStartPoint(ctx, model.startPoint); drawObjects(ctx, model.localization, "#2bc277", "筒"); drawObjects(ctx, model.recon, "#eda93d", "侦察"); drawDrone(ctx, model.drone);
    updateInfo(model);
  }

  function fitFieldMapToDefaults() {
    view.centerX = (DEFAULT_BOUNDS.xMin + DEFAULT_BOUNDS.xMax) / 2;
    view.centerY = (DEFAULT_BOUNDS.yMin + DEFAULT_BOUNDS.yMax) / 2;
    if (!canvasRect) return;
    const padding = 60;
    view.scale = Math.max(view.minScale, Math.min(view.maxScale,
      Math.min((canvasRect.width - padding * 2) / (DEFAULT_BOUNDS.xMax - DEFAULT_BOUNDS.xMin),
        (canvasRect.height - padding * 2) / (DEFAULT_BOUNDS.yMax - DEFAULT_BOUNDS.yMin))));
    view.initialized = true; baseKey = "";
  }
  function updateCursor(event) {
    const canvas = $("fieldMap"); if (!canvas || !canvasRect) return;
    const rect = canvas.getBoundingClientRect(), world = toWorld(event.clientX - rect.left, event.clientY - rect.top);
    const el = $("fieldMapCoord");
    if (el) el.textContent = "FIELD x=" + world.x.toFixed(2) + " y=" + world.y.toFixed(2) + " m";
  }
  function setupFieldMapInteractions() {
    const canvas = $("fieldMap");
    if (!canvas || canvas.dataset.mapReady === "1") return;
    canvas.dataset.mapReady = "1";
    if (window.ResizeObserver) new ResizeObserver(function () { resizeDirty = true; queueRender(); }).observe(canvas);
    const pointers = new Map(); let drag = null; let pinch = null; let moveQueued = false; let pendingMove = null;
    function pointerDistance(points) { return Math.hypot(points[0].clientX - points[1].clientX, points[0].clientY - points[1].clientY); }
    function pointerMidpoint(points) { return {x: (points[0].clientX + points[1].clientX) / 2, y: (points[0].clientY + points[1].clientY) / 2}; }
    function queueMove(event) {
      pendingMove = event; if (moveQueued) return; moveQueued = true;
      requestAnimationFrame(function () {
        moveQueued = false; const current = pendingMove; pendingMove = null; if (!current) return;
        updateCursor(current);
        if (pointers.size >= 2 && pinch) {
          const points = Array.from(pointers.values()).slice(0, 2), rect = canvas.getBoundingClientRect();
          const mid = pointerMidpoint(points), distance = Math.max(1, pointerDistance(points));
          view.scale = Math.max(view.minScale, Math.min(view.maxScale, pinch.scale * distance / pinch.distance));
          const after = toWorld(mid.x - rect.left, mid.y - rect.top);
          view.centerX += after.x - pinch.world.x; view.centerY += pinch.world.y - after.y;
          baseKey = ""; queueRender();
        } else if (pointers.size === 1 && drag) {
          view.centerX = drag.centerX - (current.clientX - drag.x) / view.scale;
          view.centerY = drag.centerY + (current.clientY - drag.y) / view.scale;
          baseKey = ""; queueRender();
        }
      });
    }
    canvas.addEventListener("wheel", function (event) {
      event.preventDefault(); const rect = canvas.getBoundingClientRect();
      const before = toWorld(event.clientX - rect.left, event.clientY - rect.top);
      view.scale = Math.max(view.minScale, Math.min(view.maxScale, view.scale * (event.deltaY < 0 ? 1.15 : 1 / 1.15)));
      const after = toWorld(event.clientX - rect.left, event.clientY - rect.top);
      view.centerX += after.x - before.x; view.centerY += before.y - after.y; baseKey = ""; queueRender();
    }, {passive: false});
    canvas.addEventListener("pointerdown", function (event) {
      canvas.setPointerCapture(event.pointerId); pointers.set(event.pointerId, event);
      if (pointers.size === 1) drag = {x: event.clientX, y: event.clientY, centerX: view.centerX, centerY: view.centerY};
      if (pointers.size === 2) {
        const points = Array.from(pointers.values()), rect = canvas.getBoundingClientRect(), mid = pointerMidpoint(points);
        pinch = {distance: Math.max(1, pointerDistance(points)), scale: view.scale, world: toWorld(mid.x - rect.left, mid.y - rect.top)};
      }
    });
    canvas.addEventListener("pointermove", function (event) { if (pointers.has(event.pointerId)) pointers.set(event.pointerId, event); queueMove(event); });
    function finish(event) {
      pointers.delete(event.pointerId);
      if (!pointers.size) { drag = null; pinch = null; return; }
      const remaining = pointers.values().next().value;
      drag = {x: remaining.clientX, y: remaining.clientY, centerX: view.centerX, centerY: view.centerY};
      pinch = null;
    }
    ["pointerup", "pointercancel", "lostpointercapture"].forEach(function (name) { canvas.addEventListener(name, finish); });
    $("fieldMapZoomIn")?.addEventListener("click", function () { view.scale = Math.min(view.maxScale, view.scale * 1.2); baseKey = ""; queueRender(); });
    $("fieldMapZoomOut")?.addEventListener("click", function () { view.scale = Math.max(view.minScale, view.scale / 1.2); baseKey = ""; queueRender(); });
    $("fieldMapReset")?.addEventListener("click", function () { fitFieldMapToDefaults(); queueRender(); });
    $("clearLocalization")?.addEventListener("click", function () {
      if (typeof cfg.onClearLocalization !== "function") return;
      cfg.onClearLocalization().catch(function (error) { if (typeof cfg.setCompletionHint === "function") cfg.setCompletionHint("清空筒坐标失败: " + error.message); });
    });
  }

  window.UavFieldMap = {
    configure, FIELD_DEFAULTS: {bounds: DEFAULT_BOUNDS}, fieldMapView: view,
    finiteNumber: finite, pointX: Model.pointX, pointY: Model.pointY, pointForFieldMap: fieldPoint,
    fieldXYToLatLon: Model.fieldXYToLatLon, fieldMapModel,
    canvasToWorld: function (x, y) { return toWorld(x, y); }, worldToCanvas: function (x, y) { return toCanvas(x, y); },
    fitFieldMapToDefaults, setupFieldMapInteractions, renderFieldMap, setProfilePreview, setRuntimeGeometry,
    renderFieldMapInfoBox: updateInfo,
  };
})();
