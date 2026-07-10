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


    // ── Runtime GPS Sampling (integrated) ─────────────────────────────

    var selectedProfileId = null;
    var selectedProfileSchema = null;
    var selectedProfileData = null;
    var lastFieldReferenceStatus = null;
    var requestBusy = false;
    var lastGeometryJson = "";

    function setText(id, text) {
        var el = document.getElementById(id);
        if (el) el.textContent = String(text);
    }

    function updateRuntimeControls() {
        var fr = (lastFieldReferenceStatus || {}).field_reference || {};
        var runtime = fr.runtime_binding || {};
        var sampling = runtime.sampling || {};
        var busy = requestBusy;
        var schema = selectedProfileSchema;
        var frozen = fr.is_frozen === true;
        var state = runtime.state || "idle";

        var startBtn = document.getElementById("fpRuntimeStart");
        var finBtn = document.getElementById("fpRuntimeFinalize");
        var cancelBtn = document.getElementById("fpRuntimeCancel");
        var bindBtn = document.getElementById("fpBindCurrent");
        var freezeBtn = document.getElementById("frFreeze");

        function allOff() {
            if (startBtn) startBtn.disabled = true;
            if (finBtn) { finBtn.disabled = true; finBtn.textContent = "确认并冻结"; }
            if (cancelBtn) cancelBtn.disabled = true;
            if (bindBtn) bindBtn.disabled = true;
            if (freezeBtn) freezeBtn.disabled = true;
        }

        if (busy) { allOff(); return; }
        if (state === "applied") { allOff(); return; }

        var isV3 = schema === 3;
        if (state === "idle") {
            allOff();
            if (isV3) { if (startBtn) startBtn.disabled = false; }
            else { if (bindBtn) bindBtn.disabled = false; }
            if (freezeBtn) freezeBtn.disabled = !(fr.is_confirmed && !frozen);
            return;
        }
        if (state === "sampling") {
            allOff();
            if (cancelBtn) cancelBtn.disabled = false;
            if (finBtn) finBtn.disabled = !(sampling.can_finalize === true);
            return;
        }
        if (state === "sampling_failed") { allOff(); if (cancelBtn) cancelBtn.disabled = false; return; }
        if (state === "apply_failed") {
            allOff();
            if (finBtn) { finBtn.disabled = false; finBtn.textContent = "重试确认并冻结"; }
            if (cancelBtn) cancelBtn.disabled = false;
            return;
        }
        allOff();
    }

    async function startRuntimeSampling() {
        var pid = selectedProfileId;
        if (selectedProfileSchema !== 3) { alert("请先选择 Schema v3 Profile"); return; }
        if (!pid) { alert("未选择 Profile"); return; }
        if (requestBusy) return;
        if (!confirm("将使用当前飞行器 WGS84 GPS 采样动态原点。\n采样不会启动 Mission，不会发送飞控命令。\n采样期间请保持无人机静止。")) return;
        requestBusy = true; updateRuntimeControls();
        try {
            var r = await window.UavApi.request("POST", "/api/field-profiles/" + encodeURIComponent(pid) + "/runtime-sampling/start");
            showRuntimeResult(r);
            if (window.UavFieldRef) window.UavFieldRef.fetchFieldReferenceStatus();
        } finally { requestBusy = false; updateRuntimeControls(); }
    }

    async function finalizeRuntimeSampling() {
        if (requestBusy) return;
        if (!confirm("将结束 GPS 采样，应用动态原点和场地方向并冻结 Field Reference。\n成功后如需更改，必须执行完整重置。\n该操作不会启动 Mission，不会发送飞控命令。")) return;
        requestBusy = true; updateRuntimeControls();
        try {
            var r = await window.UavApi.request("POST", "/api/field-reference/runtime-sampling/finalize");
            showRuntimeResult(r);
            if (window.UavFieldRef) window.UavFieldRef.fetchFieldReferenceStatus();
        } finally { requestBusy = false; updateRuntimeControls(); }
    }

    async function cancelRuntimeSampling() {
        if (requestBusy) return;
        if (!confirm("取消当前 GPS 采样？\n已应用并冻结的 reference 不能通过取消清除。")) return;
        requestBusy = true; updateRuntimeControls();
        try {
            var r = await window.UavApi.request("POST", "/api/field-reference/runtime-sampling/cancel");
            showRuntimeResult(r);
            if (window.UavFieldRef) window.UavFieldRef.fetchFieldReferenceStatus();
        } finally { requestBusy = false; updateRuntimeControls(); }
    }

    function showRuntimeResult(r) {
        if (!r.ok) {
            var msg = "Error: " + (r.error || "unknown") + "\nState: " + (r.state || "--");
            if (r.rollback_ok !== undefined) msg += "\nRollback: " + (r.rollback_ok ? "OK" : "FAILED");
            alert(msg);
        }
    }

    function onFieldReferenceStatus(data) {
        lastFieldReferenceStatus = data;
        var fr = data.field_reference || {};
        var runtime = fr.runtime_binding || {};
        var sampling = runtime.sampling || {};
        var result = runtime.last_result || runtime.candidate_summary;

        var panel = document.getElementById("fpRuntimeSampling");
        if (panel) panel.style.display = runtime.state && runtime.state !== "idle" ? "" : "none";

        setText("fpSamplingState", runtime.state || "--");
        setText("fpSamplingElapsed", sampling.elapsed_s != null ? sampling.elapsed_s.toFixed(1) + " / " + (sampling.sample_window_s || 0) + " s" : "--");
        setText("fpSamplingAccepted", sampling.accepted_samples + " / " + (sampling.min_samples || 20));
        setText("fpSamplingRejected", sampling.rejected_samples != null ? sampling.rejected_samples : "--");
        setText("fpSamplingDuplicate", sampling.duplicate_samples != null ? sampling.duplicate_samples : "--");
        setText("fpSamplingWindowComplete", sampling.window_complete ? "YES" : "no");
        setText("fpSamplingCanFinalize", sampling.can_finalize ? "YES" : "no");
        setText("fpSamplingLastRejection", sampling.last_rejection_reason || "--");

        var progress = document.getElementById("fpSamplingProgress");
        if (progress) { progress.max = Math.max(Number(sampling.sample_window_s) || 1, 1); progress.value = Math.min(Number(sampling.elapsed_s) || 0, progress.max); }

        var rp = document.getElementById("fpRuntimeResult");
        if (rp) rp.style.display = result ? "" : "none";
        if (result) {
            setText("fpRuntimeOrigin", result.origin_lat != null ? result.origin_lat.toFixed(7) + ", " + result.origin_lon.toFixed(7) : "--");
            setText("fpRuntimeMarker", result.forward_marker_lat != null ? result.forward_marker_lat.toFixed(7) + ", " + result.forward_marker_lon.toFixed(7) : "--");
            setText("fpRuntimeHeading", result.field_heading_deg != null ? result.field_heading_deg.toFixed(2) + " deg" : "--");
            setText("fpRuntimeBaseline", result.baseline_m != null ? result.baseline_m.toFixed(2) + " m" : "--");
            setText("fpRuntimeSpread", result.horizontal_spread_m != null ? result.horizontal_spread_m.toFixed(3) + " m" : "--");
            setText("fpRuntimeSampleCount", result.sample_count || "--");
            setText("fpRuntimeWarnings", result.warnings && result.warnings.length ? result.warnings.join("; ") : "--");
            if (result.geometry) {
                var geomStr = JSON.stringify(result.geometry, null, 2);
                var geomPre = document.getElementById("fpRuntimeGeometry");
                if (geomPre && geomPre.textContent !== geomStr) geomPre.textContent = geomStr;
            }
        }

        updateRuntimeControls();
    }

    // ── Hook profile loading ───────────────────────────────────────────

    var _origLoadAndRender = loadAndRenderProfile;
    loadAndRenderProfile = async function(id) {
        var result = await _origLoadAndRender(id);
        if (result && result.profile_id) {
            selectedProfileId = result.profile_id;
            selectedProfileSchema = Number(result.schema_version);
            selectedProfileData = result;
            if (result.schema_version === 3 && window.UavFieldMap && window.UavFieldMap.setProfilePreview) {
                window.UavFieldMap.setProfilePreview(null);
            }
        } else {
            selectedProfileId = selectedProfileSchema = selectedProfileData = null;
        }
        updateRuntimeControls();
        return result;
    };

    // Wire buttons on load
    document.addEventListener("DOMContentLoaded", function() {
        var startBtn = document.getElementById("fpRuntimeStart");
        var finBtn = document.getElementById("fpRuntimeFinalize");
        var cancelBtn = document.getElementById("fpRuntimeCancel");
        if (startBtn) startBtn.addEventListener("click", startRuntimeSampling);
        if (finBtn) finBtn.addEventListener("click", finalizeRuntimeSampling);
        if (cancelBtn) cancelBtn.addEventListener("click", cancelRuntimeSampling);
        updateRuntimeControls();
    });

    return {
        init: init,
        fetchProfileList: fetchProfileList,
        loadAndRenderProfile: loadAndRenderProfile,
        onFieldReferenceStatus: onFieldReferenceStatus,
        startRuntimeSampling: startRuntimeSampling,
        finalizeRuntimeSampling: finalizeRuntimeSampling,
        cancelRuntimeSampling: cancelRuntimeSampling,
        updateRuntimeControls: updateRuntimeControls
    };
})();
