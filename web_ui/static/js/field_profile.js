window.UavFieldProfiles = (function () {
    "use strict";

    var selectedProfileId = null;
    var selectedProfileSchema = null;
    var selectedProfileData = null;
    var lastFieldReferenceStatus = null;
    var requestBusy = false;
    var lastGeometryJson = "";

    function $(id) { return document.getElementById(id); }
    function setText(id, text) { var e = $(id); if (e) e.textContent = typeof text === "string" ? text : String(text || ""); }
    var api = window.UavApi;

    function gps2(x, y) { return x != null && y != null ? Number(x).toFixed(7) + ", " + Number(y).toFixed(7) : "--"; }

    // ── profile list ─────────────────────────────────────────────────
    async function fetchProfileList() {
        try {
            var data = await api.request("/api/field-profiles");
            var profiles = (data && data.ok === true && Array.isArray(data.profiles)) ? data.profiles : [];
            renderProfileList(profiles);
            return profiles;
        } catch (e) { return []; }
    }

    function renderProfileList(profiles) {
        var sel = $("fpProfileSelect");
        if (!sel) return;
        while (sel.options.length) sel.remove(0);
        var opt = document.createElement("option"); opt.value = ""; opt.textContent = "-- Select --"; sel.appendChild(opt);
        profiles.forEach(function (p) {
            var o = document.createElement("option");
            o.value = p.profile_id || "";
            o.textContent = (p.source ? "[" + p.source + "] " : "") + (p.profile_id || "") + " — " + (p.name || "");
            if (p.invalid) o.textContent += " (invalid)";
            sel.appendChild(o);
        });
        restoreSelectedProfile(sel);
    }

    function restoreSelectedProfile(sel) {
        if (!sel) return;
        try { var saved = window.localStorage.getItem("uavSelectedProfileId"); } catch (e) { var saved = null; }
        if (saved) {
            for (var i = 0; i < sel.options.length; i++) {
                if (sel.options[i].value === saved) { sel.selectedIndex = i; break; }
            }
        }
        if (sel.selectedIndex > 0) {
            loadAndRenderProfile(sel.value);
        } else {
            $("fpProfileDetail").style.display = "none";
        }
    }

    // ── profile loading ──────────────────────────────────────────────
    async function loadAndRenderProfile(id) {
        if (!id) {
            selectedProfileId = selectedProfileSchema = selectedProfileData = null;
            var pd = $("fpProfileDetail"); if (pd) pd.style.display = "none";
            updateRuntimeControls();
            return null;
        }
        try {
            var data = await api.request("/api/field-profiles/" + encodeURIComponent(id));
            if (!data || data.ok !== true) {
                selectedProfileId = selectedProfileSchema = selectedProfileData = null;
                var pd = $("fpProfileDetail"); if (pd) pd.style.display = "none";
                updateRuntimeControls();
                return data || null;
            }
            selectedProfileId = data.profile_id;
            selectedProfileSchema = Number(data.schema_version);
            selectedProfileData = data;
            try { window.localStorage.setItem("uavSelectedProfileId", String(id)); } catch (e) {}
            renderProfileDetail(data);
            updateRuntimeControls();
            return data;
        } catch (err) {
            selectedProfileId = selectedProfileSchema = selectedProfileData = null;
            var pd = $("fpProfileDetail"); if (pd) pd.style.display = "none";
            updateRuntimeControls();
            return null;
        }
    }

    function fetchMapPreview(id) {
        return api.request("/api/field-profiles/" + encodeURIComponent(id) + "/map-preview").then(function (d) {
            if (window.UavFieldMap && window.UavFieldMap.setProfilePreview) {
                window.UavFieldMap.setProfilePreview(d);
            }
        }).catch(function () { });
    }

    function renderProfileDetail(data) {
        if (!data || data.ok !== true) return;
        var sv = Number(data.schema_version);
        setText("fpProfileId", data.profile_id || "--");
        setText("fpProfileName", data.name || "--");
        setText("fpProfileSchema", sv === 3 ? "v3 Runtime GPS" : sv === 2 ? "v2 Legacy Centerline" : String(sv));
        setText("fpProfileSource", data.source || "--");
        var pd = $("fpProfileDetail"); if (pd) pd.style.display = "";

        // GPS quality (both v2 and v3)
        var gq = data.gps_quality || {};
        setText("fpGpsQualityFixSats", "fix\u2265" + (gq.min_fix_type||"--") + " sats\u2265" + (gq.min_satellites||"--"));
        setText("fpGpsQualityEphEpv", "eph\u2264" + (gq.max_eph||"--") + " epv\u2264" + (gq.max_epv||"--"));

        if (sv === 2) {
            var anc = data.anchor || {};
            setText("fpOriginLatLon", anc.lat != null ? anc.lat.toFixed(7) : "--");
            setText("fpOriginField", "(0,0) init");
            var cl = data.centerline_points || [];
            setText("fpClPoints", cl.length + " pts");
            setText("fpClDetails", cl.map(function (p) { return p.name + " (" + p.lat.toFixed(7) + "," + p.lon.toFixed(7) + ")"; }).join("\\n") || "--");
            fetchMapPreview(selectedProfileId);
        } else if (sv === 3) {
            var fm = data.forward_marker || {};
            setText("fpOriginLatLon", gps2(fm.lat, fm.lon));
            setText("fpV3Marker", (fm.name||"--") + " (" + gps2(fm.lat, fm.lon) + ") WGS84");
            var ds = data.drop_scan || {};
            setText("fpClPoints", "4 scan pts");
            setText("fpV3Scan", (ds.waypoints || []).map(function (w, i) { return "pt" + (i + 1) + " (" + w.x_m + "," + w.y_m + "," + w.altitude_m + ")"; }).join("\\n") || "--");
            var ros = data.runtime_origin_sampling || {};
            setText("fpV3Sampling", ros.min_samples + " samples " + ros.sample_window_s + "s window spread<" + ros.max_horizontal_spread_m + " " + ros.estimator);
            var bp = data.binding_policy || {};
            setText("fpV3Baseline", "min=" + (bp.min_baseline_m||"--") + "m warn=" + (bp.warn_baseline_below_m||"--") + "m");
            if (window.UavFieldMap && window.UavFieldMap.setProfilePreview) window.UavFieldMap.setProfilePreview(null);
            setText("fpHint", "\u52a8\u6001 GPS \u573a\u5730\u56fe\u5c06\u5728 runtime reference \u786e\u8ba4\u540e\u7531 Step 7 \u63a5\u5165\u3002");
        }
    }

    // ── legacy bind ──────────────────────────────────────────────────
    async function validateProfile() {
        if (!selectedProfileId) { alert("请先选择 Profile"); return; }
        try {
            var d = await api.request("/api/field-profiles/" + encodeURIComponent(selectedProfileId) + "/validate");
            alert("Validate: " + (d && d.ok === true ? "PASS" : ("FAIL — " + ((d||{}).error || "unknown"))));
        } catch (e) { alert("Validate error: " + e.message); }
    }

    async function bindCurrentProfile() {
        if (!selectedProfileId || selectedProfileSchema !== 2) { alert("仅 Schema v2 支持 bind-current"); return; }
        if (requestBusy) return;
        if (!confirm("将使用当前无人机 GPS + LOCAL_NED 绑定所选 Field Profile。\\n该操作不会启动 Mission，不会发送飞控命令。")) return;
        requestBusy = true; updateRuntimeControls();
        try {
            var r = await api.request("/api/field-profiles/" + encodeURIComponent(selectedProfileId) + "/bind-current", { method: "POST", body: "{}" });
            renderBindResult(r);
            if (window.UavFieldRef && window.UavFieldRef.fetchFieldReferenceStatus) {
                window.UavFieldRef.fetchFieldReferenceStatus({ scheduleNext: false });
            }
        } finally { requestBusy = false; updateRuntimeControls(); }
    }

    function renderBindResult(data) {
        if (!data || data.ok !== true) return;
        // Bind result is a grid container — do NOT replace its textContent
        setText("fpBindOk", "YES");
        setText("fpBindProfileId", data.profile_id || "--");
        setText("fpBindSynced", data.synced_to_runtime ? "YES" : "no");
        setText("fpBindHeading", data.field_heading_deg != null ? data.field_heading_deg.toFixed(2) + " deg" : "--");
        setText("fpBindOriginLocal", data.origin_local_n_m != null ? data.origin_local_n_m.toFixed(2) + ", " + data.origin_local_e_m.toFixed(2) : "--");
        setText("fpBindCurrentField", data.current_field_x_m != null ? data.current_field_x_m.toFixed(2) + ", " + data.current_field_y_m.toFixed(2) : "--");
        var rdiv = $("fpBindResult"); if (rdiv) rdiv.style.display = "";
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
        var bindBtn = $("fpBindCurrent"), freezeBtn = $("frFreeze"), validateBtn = $("fpValidateProfile");

        function allOff() {
            if (startBtn) { startBtn.disabled = true; }
            if (finBtn) { finBtn.disabled = true; finBtn.textContent = "确认并冻结"; }
            if (cancelBtn) cancelBtn.disabled = true;
            if (bindBtn) bindBtn.disabled = true;
            if (freezeBtn) freezeBtn.disabled = true;
            if (validateBtn) validateBtn.disabled = false;
        }

        if (busy) { allOff(); return; }
        if (state === "applied") { allOff(); if (freezeBtn) freezeBtn.disabled = true; return; }

        var isV3 = schema === 3;
        if (state === "idle") {
            allOff();
            if (isV3) { if (startBtn) startBtn.disabled = false; if (bindBtn) bindBtn.disabled = true; }
            else { if (bindBtn) bindBtn.disabled = false; if (startBtn) startBtn.disabled = true; }
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

    async function _runtimeOp(url, confirmMsg) {
        if (requestBusy) return;
        if (!confirm(confirmMsg)) return;
        requestBusy = true; updateRuntimeControls();
        try {
            var r = await api.request(url, { method: "POST", body: "{}" });
            if (r && r.ok === false) {
                var msg = r.error || "unknown error";
                if (r.rollback_ok !== undefined) msg += "\nRollback: " + (r.rollback_ok ? "OK" : "FAILED");
                alert(msg);
            }
            if (window.UavFieldRef && window.UavFieldRef.fetchFieldReferenceStatus) {
                window.UavFieldRef.fetchFieldReferenceStatus({ scheduleNext: false });
            }
        } finally { requestBusy = false; updateRuntimeControls(); }
    }

    function startRuntimeSampling() {
        if (selectedProfileSchema !== 3) { alert("请先选择 Schema v3 Profile"); return; }
        _runtimeOp("/api/field-profiles/" + encodeURIComponent(selectedProfileId) + "/runtime-sampling/start",
            "将使用当前飞行器 WGS84 GPS 采样动态原点。\n采样不会启动 Mission，不会发送飞控命令。\n采样期间请保持无人机静止。");
    }

    function finalizeRuntimeSampling() {
        _runtimeOp("/api/field-reference/runtime-sampling/finalize",
            "将结束 GPS 采样，应用动态原点和场地方向并冻结 Field Reference。\n成功后如需更改，必须执行完整重置。\n该操作不会启动 Mission，不会发送飞控命令。");
    }

    function cancelRuntimeSampling() {
        _runtimeOp("/api/field-reference/runtime-sampling/cancel",
            "取消当前 GPS 采样？\n已应用并冻结的 reference 不能通过取消清除。");
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
        setText("fpSamplingElapsed", sampling.elapsed_s != null ? sampling.elapsed_s.toFixed(1) + " / " + (sampling.sample_window_s || 0) + " s" : "--");
        setText("fpSamplingAccepted", sampling.accepted_samples + " / " + (sampling.min_samples || 20));
        setText("fpSamplingRejected", sampling.rejected_samples != null ? sampling.rejected_samples : "--");
        setText("fpSamplingDuplicate", sampling.duplicate_samples != null ? sampling.duplicate_samples : "--");
        setText("fpSamplingWindowComplete", sampling.window_complete ? "YES" : "no");
        setText("fpSamplingCanFinalize", sampling.can_finalize ? "YES" : "no");
        setText("fpSamplingLastRejection", sampling.last_rejection_reason || "--");
        var prog = $("fpSamplingProgress");
        if (prog) { prog.max = Math.max(Number(sampling.sample_window_s) || 1, 1); prog.value = Math.min(Number(sampling.elapsed_s) || 0, prog.max); }

        var result = runtime.last_result || runtime.candidate_summary;
        var rp = $("fpRuntimeResult");
        if (rp) rp.style.display = result ? "" : "none";
        if (result) {
            setText("fpRuntimeOrigin", gps2(result.origin_lat, result.origin_lon));
            setText("fpRuntimeMarker", gps2(result.forward_marker_lat, result.forward_marker_lon));
            setText("fpRuntimeHeading", result.field_heading_deg != null ? result.field_heading_deg.toFixed(2) + " deg" : "--");
            setText("fpRuntimeBaseline", result.baseline_m != null ? result.baseline_m.toFixed(2) + " m" : "--");
            setText("fpRuntimeSpread", result.horizontal_spread_m != null ? result.horizontal_spread_m.toFixed(3) + " m" : "--");
            setText("fpRuntimeSampleCount", result.sample_count || "--");
            setText("fpRuntimeWarnings", (result.warnings || []).length ? result.warnings.join("; ") : "--");
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
        var sel = $("fpProfileSelect");
        if (sel) sel.onchange = function () { loadAndRenderProfile(this.value || null); };
        var rb = $("fpRefreshList"); if (rb) rb.addEventListener("click", fetchProfileList);
        var vb = $("fpValidateProfile"); if (vb) vb.addEventListener("click", validateProfile);
        var bb = $("fpBindCurrent"); if (bb) bb.addEventListener("click", bindCurrentProfile);

        var sb = $("fpRuntimeStart"); if (sb) sb.addEventListener("click", startRuntimeSampling);
        var fb = $("fpRuntimeFinalize"); if (fb) fb.addEventListener("click", finalizeRuntimeSampling);
        var cb = $("fpRuntimeCancel"); if (cb) cb.addEventListener("click", cancelRuntimeSampling);

        fetchProfileList();
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
