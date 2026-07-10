window.UavFieldProfiles = (function () {
    "use strict";

    // ── state ────────────────────────────────────────────────────────
    var selectedProfileId = null;
    var selectedProfileSchema = null;
    var selectedProfileData = null;
    var lastFieldReferenceStatus = null;
    var requestBusy = false;
    var lastGeometryJson = "";

    // ── helpers ──────────────────────────────────────────────────────
    function $(id) { return document.getElementById(id); }
    function setText(id, text) { var e = $(id); if (e) e.textContent = typeof text === "string" ? text : String(text || ""); }
    var api = window.UavApi;

    // ── profile loading ──────────────────────────────────────────────
    async function fetchProfileList() {
        try {
            var data = await api.request("/api/field-profiles");
            if (!data || data.ok !== true) return [];
            return data.profiles || [];
        } catch (e) { return []; }
    }

    async function loadAndRenderProfile(id) {
        if (!id) {
            selectedProfileId = selectedProfileSchema = selectedProfileData = null;
            updateRuntimeControls();
            return null;
        }
        try {
            var data = await api.request("/api/field-profiles/" + encodeURIComponent(id));
            if (!data || data.ok !== true) {
                selectedProfileId = selectedProfileSchema = selectedProfileData = null;
                updateRuntimeControls();
                return data || null;
            }
            selectedProfileId = data.profile_id;
            selectedProfileSchema = Number(data.schema_version);
            selectedProfileData = data;
            renderProfileDetail(data);
            if (selectedProfileSchema === 2) { await fetchMapPreview(id); }
            else if (selectedProfileSchema === 3) {
                if (window.UavFieldMap && window.UavFieldMap.setProfilePreview) window.UavFieldMap.setProfilePreview(null);
                setText("fpHint", "动态 GPS 场地图将在 runtime reference 确认后由 Step 7 接入。");
            }
            updateRuntimeControls();
            return data;
        } catch (err) {
            selectedProfileId = selectedProfileSchema = selectedProfileData = null;
            updateRuntimeControls();
            return null;
        }
    }

    async function fetchMapPreview(id) {
        try {
            var d = await api.request("/api/field-profiles/" + encodeURIComponent(id) + "/map-preview");
            if (window.UavFieldMap && window.UavFieldMap.setProfilePreview) window.UavFieldMap.setProfilePreview(d);
        } catch (e) { }
    }

    function renderProfileDetail(data) {
        if (!data || data.ok !== true) return;
        var sv = Number(data.schema_version);
        setText("fpProfileId", data.profile_id || "--");
        setText("fpProfileName", data.name || "--");
        setText("fpProfileSchema", sv === 3 ? "v3 Runtime GPS" : sv === 2 ? "v2 Legacy Centerline" : "--");

        if (sv === 2) {
            var anc = data.anchor || {};
            setText("fpOriginGps", anc.lat != null ? "anchor lat="+anc.lat.toFixed(7)+" lon="+anc.lon.toFixed(7) : "--");
            setText("fpClPoints", (data.centerline_points || []).length + " pts");
        } else if (sv === 3) {
            var fm = data.forward_marker || {};
            setText("fpOriginGps", "Forward Marker: " + (fm.name||"--") + " " + (fm.lat||"--") + ", " + (fm.lon||"--") + " (" + (fm.coordinate_system||"--") + ")");
            var ds = data.drop_scan || {};
            var wps = (ds.waypoints || []).map(function(w) { return "("+w.x_m+", "+w.y_m+", "+w.altitude_m+")"; }).join("; ");
            setText("fpClPoints", "Scan: " + wps);
            var ros = data.runtime_origin_sampling || {};
            setText("fpBindResult", "采样: " + (ros.min_samples||"--") + " samples, " + (ros.sample_window_s||"--") + "s window, spread<" + (ros.max_horizontal_spread_m||"--"));
            setText("fpGpsQualityFixSats", "GPS fix≥" + ((data.gps_quality||{}).min_fix_type||"--") + " sats≥" + ((data.gps_quality||{}).min_satellites||"--"));
            setText("fpGpsQualityEphEpv", "eph≤" + ((data.gps_quality||{}).max_eph||"--") + " epv≤" + ((data.gps_quality||{}).max_epv||"--"));
            var bp = data.binding_policy || {};
            setText("fpBindCurrentField", "baseline min=" + (bp.min_baseline_m||"--") + " warn=" + (bp.warn_baseline_below_m||"--"));
        }
    }

    // ── runtime controls ──────────────────────────────────────────────
    function updateRuntimeControls() {
        var fr = (lastFieldReferenceStatus || {}).field_reference || {};
        var runtime = fr.runtime_binding || {};
        var sampling = runtime.sampling || {};
        var busy = requestBusy;
        var schema = selectedProfileSchema;
        var frozen = fr.is_frozen === true;
        var state = runtime.state || "idle";

        var startBtn = $("fpRuntimeStart"), finBtn = $("fpRuntimeFinalize"), cancelBtn = $("fpRuntimeCancel");
        var bindBtn = $("fpBindCurrent"), freezeBtn = $("frFreeze");

        function allOff() {
            if (startBtn) { startBtn.disabled = true; }
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
        if (selectedProfileSchema !== 3) { alert("请先选择 Schema v3 Profile"); return; }
        if (!selectedProfileId || requestBusy) return;
        if (!confirm("将使用当前飞行器 WGS84 GPS 采样动态原点。\n采样不会启动 Mission，不会发送飞控命令。\n采样期间请保持无人机静止。")) return;
        requestBusy = true; updateRuntimeControls();
        try {
            var r = await api.request("/api/field-profiles/" + encodeURIComponent(selectedProfileId) + "/runtime-sampling/start", {method:"POST", body:"{}"});
            showResult(r);
            if (window.UavFieldRef && window.UavFieldRef.fetchFieldReferenceStatus) window.UavFieldRef.fetchFieldReferenceStatus();
        } finally { requestBusy = false; updateRuntimeControls(); }
    }

    async function finalizeRuntimeSampling() {
        if (requestBusy) return;
        if (!confirm("将结束 GPS 采样，应用动态原点和场地方向并冻结 Field Reference。\n成功后如需更改，必须执行完整重置。\n该操作不会启动 Mission，不会发送飞控命令。")) return;
        requestBusy = true; updateRuntimeControls();
        try {
            var r = await api.request("/api/field-reference/runtime-sampling/finalize", {method:"POST", body:"{}"});
            showResult(r);
            if (window.UavFieldRef && window.UavFieldRef.fetchFieldReferenceStatus) window.UavFieldRef.fetchFieldReferenceStatus();
        } finally { requestBusy = false; updateRuntimeControls(); }
    }

    async function cancelRuntimeSampling() {
        if (requestBusy) return;
        if (!confirm("取消当前 GPS 采样？\n已应用并冻结的 reference 不能通过取消清除。")) return;
        requestBusy = true; updateRuntimeControls();
        try {
            var r = await api.request("/api/field-reference/runtime-sampling/cancel", {method:"POST", body:"{}"});
            showResult(r);
            if (window.UavFieldRef && window.UavFieldRef.fetchFieldReferenceStatus) window.UavFieldRef.fetchFieldReferenceStatus();
        } finally { requestBusy = false; updateRuntimeControls(); }
    }

    function showResult(r) {
        if (!r || r.ok === false) {
            var msg = "Error: " + (r ? (r.error||"unknown") : "no response") + "\nState: " + (r ? r.state||"--" : "--");
            if (r && r.rollback_ok !== undefined) msg += "\nRollback: " + (r.rollback_ok ? "OK" : "FAILED");
            alert(msg);
        }
    }

    // ── status rendering ──────────────────────────────────────────────
    function onFieldReferenceStatus(data) {
        lastFieldReferenceStatus = data;
        var fr = (data || {}).field_reference || {};
        var runtime = fr.runtime_binding || {};
        var sampling = runtime.sampling || {};

        var panel = $("fpRuntimeSampling");
        if (panel) panel.style.display = runtime.state && runtime.state !== "idle" ? "" : "none";

        setText("fpSamplingState", runtime.state || "--");
        setText("fpSamplingElapsed", sampling.elapsed_s != null ? sampling.elapsed_s.toFixed(1) + " / " + (sampling.sample_window_s||0) + " s" : "--");
        setText("fpSamplingAccepted", sampling.accepted_samples + " / " + (sampling.min_samples||20));
        setText("fpSamplingRejected", sampling.rejected_samples != null ? sampling.rejected_samples : "--");
        setText("fpSamplingDuplicate", sampling.duplicate_samples != null ? sampling.duplicate_samples : "--");
        setText("fpSamplingWindowComplete", sampling.window_complete ? "YES" : "no");
        setText("fpSamplingCanFinalize", sampling.can_finalize ? "YES" : "no");
        setText("fpSamplingLastRejection", sampling.last_rejection_reason || "--");
        var prog = $("fpSamplingProgress");
        if (prog) { prog.max = Math.max(Number(sampling.sample_window_s)||1, 1); prog.value = Math.min(Number(sampling.elapsed_s)||0, prog.max); }

        var result = runtime.last_result || runtime.candidate_summary;
        var rp = $("fpRuntimeResult");
        if (rp) rp.style.display = result ? "" : "none";
        if (result) {
            setText("fpRuntimeOrigin", result.origin_lat != null ? result.origin_lat.toFixed(7)+", "+result.origin_lon.toFixed(7) : "--");
            setText("fpRuntimeMarker", result.forward_marker_lat != null ? result.forward_marker_lat.toFixed(7)+", "+result.forward_marker_lon.toFixed(7) : "--");
            setText("fpRuntimeHeading", result.field_heading_deg != null ? result.field_heading_deg.toFixed(2)+" deg" : "--");
            setText("fpRuntimeBaseline", result.baseline_m != null ? result.baseline_m.toFixed(2)+" m" : "--");
            setText("fpRuntimeSpread", result.horizontal_spread_m != null ? result.horizontal_spread_m.toFixed(3)+" m" : "--");
            setText("fpRuntimeSampleCount", result.sample_count||"--");
            setText("fpRuntimeWarnings", (result.warnings||[]).length ? result.warnings.join("; ") : "--");
            if (result.geometry) {
                var gs = JSON.stringify(result.geometry, null, 2);
                var gp = $("fpRuntimeGeometry");
                if (gp && gp.textContent !== gs) gp.textContent = gs;
            }
        }
        updateRuntimeControls();
    }

    function getRuntimeUiState() {
        return { selectedProfileId: selectedProfileId, selectedProfileSchema: selectedProfileSchema, requestBusy: requestBusy };
    }

    // ── init ──────────────────────────────────────────────────────────
    function init() {
        var btns = [["fpRuntimeStart", startRuntimeSampling], ["fpRuntimeFinalize", finalizeRuntimeSampling], ["fpRuntimeCancel", cancelRuntimeSampling]];
        btns.forEach(function(p) { var b = $(p[0]); if (b) b.addEventListener("click", p[1]); });
        updateRuntimeControls();
    }

    return {
        init: init,
        fetchProfileList: fetchProfileList,
        loadAndRenderProfile: loadAndRenderProfile,
        onFieldReferenceStatus: onFieldReferenceStatus,
        startRuntimeSampling: startRuntimeSampling,
        finalizeRuntimeSampling: finalizeRuntimeSampling,
        cancelRuntimeSampling: cancelRuntimeSampling,
        updateRuntimeControls: updateRuntimeControls,
        getRuntimeUiState: getRuntimeUiState
    };
})();
