/* Field Profile — UI logic for /api/field-profiles endpoints.
   Phase D — v2 centerline schema */

window.UavFieldProfiles = (function () {
  "use strict";

  var $ = function (id) { return document.getElementById(id); };
  var api = window.UavApi;
  var dom = window.UavDom;
  var fmt = window.UavFormat;

  var SELECTED_PROFILE_KEY = "uav.field_profile.selected_id";

  function setText(element, value, tone) {
    if (!element) return;
    element.textContent = value == null ? "" : String(value);
    element.classList.remove("ok-text", "warning-text", "danger-text");
    if (tone) element.classList.add(tone);
  }

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

  // ------------------------------------------------------------------
  // fetch profile list
  // ------------------------------------------------------------------

  async function fetchProfileList() {
    try {
      var data = await api.request("/api/field-profiles");
      renderProfileList(data);
    } catch (e) {
      setText($("fpHint"), "获取 profile 列表失败: " + e.message, "danger-text");
    }
  }

  function renderProfileList(data) {
    var sel = $("fpProfileSelect");
    if (!sel) return;
    sel.innerHTML = '<option value="">-- 选择 Profile --</option>';
    if (!data.ok || !Array.isArray(data.profiles)) {
      setText($("fpHint"), "profile 列表不可用", "warning-text");
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
    restoreSelectedProfile(sel);
  }

  function restoreSelectedProfile(sel) {
    var savedId = null;
    try { savedId = localStorage.getItem(SELECTED_PROFILE_KEY); } catch (e) { /* ignore */ }
    if (!savedId) return;
    var found = false;
    for (var i = 0; i < sel.options.length; i++) {
      if (sel.options[i].value === savedId) { found = true; break; }
    }
    if (found) {
      sel.value = savedId;
      loadAndRenderProfile(savedId);
    } else {
      try { localStorage.removeItem(SELECTED_PROFILE_KEY); } catch (e) { /* ignore */ }
    }
  }

  // ------------------------------------------------------------------
  // load / validate profile
  // ------------------------------------------------------------------

  async function loadAndRenderProfile(id) {
    if (!id) return;
    try {
      var data = await api.request("/api/field-profiles/" + encodeURIComponent(id));
      renderProfileDetail(data);
      if (data.ok) {
        fetchMapPreview(id);
      }
    } catch (e) {
      setText($("fpHint"), "读取 profile 失败: " + e.message, "danger-text");
    }
  }

  async function fetchMapPreview(id) {
    try {
      var data = await api.request("/api/field-profiles/" + encodeURIComponent(id) + "/map-preview");
      if (!data.ok) {
        setText($("fpHint"), "map-preview 加载失败: " + (data.error || "未知错误"), "warning-text");
        return;
      }
      if (window.UavFieldMap && window.UavFieldMap.setProfilePreview) {
        window.UavFieldMap.setProfilePreview(data);
      }
      setText($("fpHint"), "map-preview 已加载: " + data.profile_id, "ok-text");
    } catch (e) {
      setText($("fpHint"), "map-preview 加载失败: " + e.message, "warning-text");
    }
  }

  function renderProfileDetail(data) {
    var detail = $("fpProfileDetail");
    if (!detail) return;
    if (!data.ok) {
      setText($("fpHint"), "Profile 不可用: " + (data.error || "未知错误"), "danger-text");
      detail.style.display = "none";
      return;
    }
    detail.style.display = "block";
    setText($("fpProfileId"), data.profile_id);
    setText($("fpProfileName"), data.name);
    setText($("fpProfileSource"), "loaded");
    setText($("fpProfileSchema"), data.schema_version);

    // v2 anchor
    var anchor = data.anchor || {};
    if (anchor.lat != null) {
      setText($("fpOriginLatLon"), gpsText(anchor.lat, anchor.lon));
      setText($("fpOriginField"), fieldText(anchor.field_x_m, anchor.field_y_m));
    } else {
      setText($("fpOriginLatLon"), "--");
      setText($("fpOriginField"), "--");
    }

    // v2 centerline_points
    var cl = data.centerline_points || [];
    setText($("fpClPoints"), cl.length + " points");
    if (cl.length) {
      var lines = cl.map(function (pt, i) {
        var ey = pt.expected_field_y_m != null ? pt.expected_field_y_m.toFixed(2) : "--";
        return "CL_" + (i + 1) + " " + pt.name + " lat=" + pt.lat.toFixed(6) + " lon=" + pt.lon.toFixed(6) + " ey=" + ey;
      });
      setText($("fpClDetails"), lines.join("\n"));
    } else {
      setText($("fpClDetails"), "--");
    }

    var gq = data.gps_quality || {};
    setText($("fpGpsQualityFixSats"), "fix≥" + (gq.min_fix_type != null ? gq.min_fix_type : "?") + " sats≥" + (gq.min_satellites != null ? gq.min_satellites : "?"));
    setText($("fpGpsQualityEphEpv"), "eph≤" + (gq.max_eph != null ? gq.max_eph : "?") + " epv≤" + (gq.max_epv != null ? gq.max_epv : "?"));
  }

  async function validateProfile() {
    var id = $("fpProfileSelect").value;
    if (!id) { setText($("fpHint"), "请先选择 Profile", "warning-text"); return; }
    try {
      var data = await api.request("/api/field-profiles/" + encodeURIComponent(id) + "/validate");
      setText($("fpHint"),
        "验证 " + (data.ok ? "通过" : "失败") +
        (data.errors && data.errors.length ? " errors: " + JSON.stringify(data.errors) : "") +
        (data.warnings && data.warnings.length ? " warnings: " + JSON.stringify(data.warnings) : ""));
      // Refresh profile detail to show updated state
      loadAndRenderProfile(id);
    } catch (e) {
      setText($("fpHint"), "验证请求失败: " + e.message, "danger-text");
    }
  }

  // ------------------------------------------------------------------
  // bind-current
  // ------------------------------------------------------------------

  async function bindCurrentProfile() {
    var id = $("fpProfileSelect").value;
    if (!id) { setText($("fpHint"), "请先选择 Profile", "warning-text"); return; }

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
      setText($("fpHint"), "bind-current 请求失败: " + e.message, "danger-text");
    }
  }

  function renderBindResult(data) {
    var panel = $("fpBindResult");
    if (!panel) return;
    panel.style.display = "block";

    setText($("fpBindOk"), data.ok ? "true" : "false",
      data.ok ? "ok-text" : "danger-text");
    setText($("fpBindProfileId"), data.profile_id || "--");
    setText($("fpBindSynced"), data.synced_to_runtime != null ? String(data.synced_to_runtime) : "--",
      data.synced_to_runtime ? "ok-text" : "warning-text");
    setText($("fpBindHeading"), data.field_heading_deg != null ? data.field_heading_deg.toFixed(2) + "°" : "--");
    setText($("fpBindOriginLocal"),
      data.origin_local_n_m != null
        ? data.origin_local_n_m.toFixed(2) + ", " + data.origin_local_e_m.toFixed(2) + ", " + (data.origin_local_z_m != null ? data.origin_local_z_m.toFixed(2) : "--")
        : "--");
    setText($("fpBindCurrentField"),
      data.current_field_x_m != null
        ? fieldText(data.current_field_x_m, data.current_field_y_m)
        : "--");
    setText($("fpBindBaseline"), data.baseline_m != null ? data.baseline_m.toFixed(2) + " m" : "--");

    // v2 new fields
    setText($("fpBindStartError"), data.current_start_error_m != null ? data.current_start_error_m.toFixed(2) + " m" : "--");
    setText($("fpBindYawError"), data.yaw_error_deg != null ? data.yaw_error_deg.toFixed(2) + "°" : "--");
    setText($("fpBindMaxResidual"), data.max_residual_m != null ? data.max_residual_m.toFixed(3) + " m" : "--");
    setText($("fpBindRmsResidual"), data.rms_residual_m != null ? data.rms_residual_m.toFixed(3) + " m" : "--");

    var residuals = data.centerline_residuals || [];
    if (residuals.length) {
      var lines = residuals.map(function (r) {
        return r.name + " resid=" + (r.residual_m != null ? r.residual_m.toFixed(3) : "--") + "m" +
          (r.expected_field_y_m != null ? " ey=" + r.expected_field_y_m.toFixed(2) : "") +
          (r.fitted_field_y_m != null ? " fy=" + r.fitted_field_y_m.toFixed(2) : "");
      });
      setText($("fpBindResiduals"), lines.join("\n"));
    } else {
      setText($("fpBindResiduals"), "--");
    }

    var warnings = data.warnings || [];
    setText($("fpBindWarnings"), warnings.length ? warnings.join("; ") : "无");

    var errors = data.errors || [];
    setText($("fpBindErrors"), errors.length ? errors.join("; ") : "无",
      errors.length ? "danger-text" : "ok-text");

    var diag = data.diagnostics || {};
    var diagErrors = diag.errors || [];
    var diagWarnings = diag.warnings || [];
    setText($("fpBindDiagnostics"),
      (diagErrors.length ? "E:" + diagErrors.join("; ") : "") +
      (diagWarnings.length ? " W:" + diagWarnings.join("; ") : "无"));

    setText($("fpHint"),
      data.ok
        ? "绑定成功 — Field Reference 已更新。请手动点击 freeze 后再启动 Mission。"
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
        var id = this.value;
        if (id) {
          try { localStorage.setItem(SELECTED_PROFILE_KEY, id); } catch (e) { /* ignore */ }
          loadAndRenderProfile(id);
        } else {
          try { localStorage.removeItem(SELECTED_PROFILE_KEY); } catch (e) { /* ignore */ }
          if (window.UavFieldMap && window.UavFieldMap.setProfilePreview) {
            window.UavFieldMap.setProfilePreview(null);
          }
        }
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
        setText($("fpHint"),
          "当前绑定 profile: " + data.field_reference.profile_id +
          " binding_ok=" + data.field_reference.profile_binding_ok +
          " synced=" + data.field_reference.synced_to_runtime);
      }
    } catch (e) { /* ignore polling errors */ }
  }

  return { init, fetchProfileList, fetchFieldReferenceStatus };
})();
