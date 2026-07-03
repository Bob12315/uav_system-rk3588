/* Field Profile — UI logic for /api/field-profiles endpoints.
   Phase D — web_ui/static/js/field_profile.js */

window.UavFieldProfiles = (function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var api = window.UavApi;
  var dom = window.UavDom;
  var fmt = window.UavFormat;

  // ------------------------------------------------------------------
  // helpers
  // ------------------------------------------------------------------

  function gpsText(lat, lon) {
    if (lat == null || lon == null) return "--";
    return fmt.gps ? fmt.gps(lat, lon) : lat.toFixed(6) + ", " + lon.toFixed(6);
  }

  function fieldText(x, y) {
    if (x == null || y == null) return "--";
    return (x >= 0 ? "+" : "") + x.toFixed(2) + " / " + (y >= 0 ? "+" : "") + y.toFixed(2);
  }

  function pointHas(pt) {
    return pt && pt.lat != null && pt.lon != null;
  }

  // ------------------------------------------------------------------
  // fetch profile list
  // ------------------------------------------------------------------

  async function fetchProfileList() {
    try {
      var data = await api.request("/api/field-profiles");
      renderProfileList(data);
    } catch (e) {
      dom.setText($("fpHint"), "获取 profile 列表失败: " + e.message, "danger-text");
    }
  }

  function renderProfileList(data) {
    var sel = $("fpProfileSelect");
    if (!sel) return;
    sel.innerHTML = '<option value="">-- 选择 Profile --</option>';
    if (!data.ok || !Array.isArray(data.profiles)) {
      dom.setText($("fpHint"), "profile 列表不可用", "warning-text");
      return;
    }
    data.profiles.forEach(function (p) {
      var opt = document.createElement("option");
      opt.value = p.profile_id;
      var label = "[" + p.source + "] " + p.profile_id;
      if (!p.valid) label += " (invalid)";
      opt.textContent = label;
      sel.appendChild(opt);
    });
  }

  // ------------------------------------------------------------------
  // load / validate profile
  // ------------------------------------------------------------------

  async function loadAndRenderProfile(id) {
    if (!id) return;
    try {
      var data = await api.request("/api/field-profiles/" + encodeURIComponent(id));
      renderProfileDetail(data);
    } catch (e) {
      dom.setText($("fpHint"), "读取 profile 失败: " + e.message, "danger-text");
    }
  }

  function renderProfileDetail(data) {
    var detail = $("fpProfileDetail");
    if (!detail) return;
    if (!data.ok) {
      dom.setText($("fpHint"), "Profile 不可用: " + (data.error || "未知错误"), "danger-text");
      detail.style.display = "none";
      return;
    }
    detail.style.display = "block";
    dom.setText($("fpProfileId"), data.profile_id);
    dom.setText($("fpProfileName"), data.name);
    dom.setText($("fpProfileSource"), "loaded");
    dom.setText($("fpProfileSchema"), data.schema_version);

    var pts = data.points || {};
    var o = pts.origin;
    var f = pts.forward;
    var l = pts.left_check;
    var r = pts.right_check;

    dom.setText($("fpOriginLatLon"), pointHas(o) ? gpsText(o.lat, o.lon) : "--");
    dom.setText($("fpOriginField"), pointHas(o) ? fieldText(o.field_x_m, o.field_y_m) : "--");
    dom.setText($("fpForwardLatLon"), pointHas(f) ? gpsText(f.lat, f.lon) : "--");
    dom.setText($("fpForwardField"), pointHas(f) ? fieldText(f.field_x_m, f.field_y_m) : "--");
    dom.setText($("fpLeftLatLon"), pointHas(l) ? gpsText(l.lat, l.lon) : "(无)");
    dom.setText($("fpLeftField"), pointHas(l) ? fieldText(l.field_x_m, l.field_y_m) : "(无)");
    dom.setText($("fpRightLatLon"), pointHas(r) ? gpsText(r.lat, r.lon) : "(无)");
    dom.setText($("fpRightField"), pointHas(r) ? fieldText(r.field_x_m, r.field_y_m) : "(无)");

    var gq = data.gps_quality || {};
    dom.setText($("fpGpsQualityFixSats"), "fix≥" + (gq.min_fix_type != null ? gq.min_fix_type : "?") + " sats≥" + (gq.min_satellites != null ? gq.min_satellites : "?"));
    dom.setText($("fpGpsQualityEphEpv"), "eph≤" + (gq.max_eph != null ? gq.max_eph : "?") + " epv≤" + (gq.max_epv != null ? gq.max_epv : "?"));
  }

  async function validateProfile() {
    var id = $("fpProfileSelect").value;
    if (!id) { dom.setText($("fpHint"), "请先选择 Profile", "warning-text"); return; }
    try {
      var data = await api.request("/api/field-profiles/" + encodeURIComponent(id) + "/validate");
      dom.setText($("fpHint"),
        "验证 " + (data.ok ? "通过" : "失败") +
        (data.errors && data.errors.length ? " errors: " + JSON.stringify(data.errors) : "") +
        (data.warnings && data.warnings.length ? " warnings: " + JSON.stringify(data.warnings) : ""));
    } catch (e) {
      dom.setText($("fpHint"), "验证请求失败: " + e.message, "danger-text");
    }
  }

  // ------------------------------------------------------------------
  // bind-current
  // ------------------------------------------------------------------

  async function bindCurrentProfile() {
    var id = $("fpProfileSelect").value;
    if (!id) { dom.setText($("fpHint"), "请先选择 Profile", "warning-text"); return; }

    try {
      var data = await api.request("/api/field-profiles/" + encodeURIComponent(id) + "/bind-current", {
        method: "POST",
        body: "{}",
      });
      renderBindResult(data);
      // Refresh field-reference status after bind
      if (window.UavFieldRef && window.UavFieldRef.fetchFieldReferenceStatus) {
        window.UavFieldRef.fetchFieldReferenceStatus();
      }
    } catch (e) {
      dom.setText($("fpHint"), "bind-current 请求失败: " + e.message, "danger-text");
    }
  }

  function renderBindResult(data) {
    var panel = $("fpBindResult");
    if (!panel) return;
    panel.style.display = "block";

    dom.setText($("fpBindOk"), data.ok ? "true" : "false",
      data.ok ? "ok-text" : "danger-text");
    dom.setText($("fpBindProfileId"), data.profile_id || "--");
    dom.setText($("fpBindSynced"), data.synced_to_runtime != null ? String(data.synced_to_runtime) : "--",
      data.synced_to_runtime ? "ok-text" : "warning-text");
    dom.setText($("fpBindHeading"), data.field_heading_deg != null ? data.field_heading_deg.toFixed(2) + "°" : "--");
    dom.setText($("fpBindOriginLocal"),
      data.origin_local_n_m != null
        ? data.origin_local_n_m.toFixed(2) + ", " + data.origin_local_e_m.toFixed(2) + ", " + (data.origin_local_z_m != null ? data.origin_local_z_m.toFixed(2) : "--")
        : "--");
    dom.setText($("fpBindCurrentField"),
      data.current_field_x_m != null
        ? fieldText(data.current_field_x_m, data.current_field_y_m)
        : "--");
    dom.setText($("fpBindBaseline"), data.baseline_m != null ? data.baseline_m.toFixed(2) + " m" : "--");

    var warnings = data.warnings || [];
    dom.setText($("fpBindWarnings"), warnings.length ? warnings.join("; ") : "无");

    var errors = data.errors || [];
    dom.setText($("fpBindErrors"), errors.length ? errors.join("; ") : "无",
      errors.length ? "danger-text" : "ok-text");

    var diag = data.diagnostics || {};
    var diagErrors = diag.errors || [];
    var diagWarnings = diag.warnings || [];
    dom.setText($("fpBindDiagnostics"),
      (diagErrors.length ? "E:" + diagErrors.join("; ") : "") +
      (diagWarnings.length ? " W:" + diagWarnings.join("; ") : "无"));

    dom.setText($("fpHint"),
      data.ok
        ? "绑定成功 — Field Reference 已更新。Mission 启动前需 freeze（由 Mission start 自动执行）。"
        : "绑定失败 — 见上方 errors。Field Reference 未修改。",
      data.ok ? "ok-text" : "danger-text");
  }

  // ------------------------------------------------------------------
  // init
  // ------------------------------------------------------------------

  function init() {
    if ($("fpRefreshList")) $("fpRefreshList").onclick = fetchProfileList;
    if ($("fpValidateProfile")) $("fpValidateProfile").onclick = validateProfile;
    if ($("fpBindCurrent")) {
      $("fpBindCurrent").addEventListener("click", function () {
        if (confirm($("fpBindCurrent").getAttribute("data-confirm") || "确认绑定？")) {
          bindCurrentProfile();
        }
      });
    }
    if ($("fpProfileSelect")) {
      $("fpProfileSelect").onchange = function () {
        loadAndRenderProfile(this.value);
      };
    }
    // Initial fetch
    fetchProfileList();
    fetchFieldReferenceStatus();
  }

  async function fetchFieldReferenceStatus() {
    try {
      var data = await api.request("/api/field-reference/status");
      if (data && data.field_reference && data.field_reference.profile_id) {
        dom.setText($("fpHint"),
          "当前绑定 profile: " + data.field_reference.profile_id +
          " binding_ok=" + data.field_reference.profile_binding_ok +
          " synced=" + data.field_reference.synced_to_runtime);
      }
    } catch (e) { /* ignore polling errors */ }
  }

  return { init, fetchProfileList, fetchFieldReferenceStatus };
})();
