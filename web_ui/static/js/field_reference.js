window.UavFieldRef = (function () {
    "use strict";

    var pollTimer = null;
    var pollInFlight = false;
    var pollingStarted = false;
    var _initCalled = false;

    // ── helpers ──────────────────────────────────────────────────────
    function $(id) { return document.getElementById(id); }
    function setEl(id, text) {
        var e = $(id);
        if (e) {
            var t = typeof text === "string" ? text : String(text || "");
            if (e.textContent !== t) e.textContent = t;
        }
    }
    var api = window.UavApi;

    function gpsText(lat, lon) {
        if (lat == null || lon == null) return "--";
        return Number(lat).toFixed(7) + ", " + Number(lon).toFixed(7);
    }

    // ── render (legacy only) ────────────────────────────────────────
    function renderFieldReference(data) {
        var fr = (data || {}).field_reference || {};
        var runtime = fr.runtime_binding || {};

        setEl("frConfirmed", fr.is_confirmed ? "YES" : "no");
        setEl("frFrozen", fr.is_frozen ? "YES" : "no");
        setEl("frGpsReady", fr.is_ready_for_field_to_gps ? "YES" : "no");
        setEl("frLocalReady", fr.is_ready_for_field_to_local ? "YES" : "no");
        setEl("frOriginSource", fr.origin_source || "--");
        setEl("frHeadingSource", fr.heading_source || "--");
        setEl("frActiveSource", fr.active_source || "--");
        setEl("frSynced", fr.synced_to_runtime ? "YES" : "no");
        setEl("frOriginGps", gpsText(fr.origin_lat, fr.origin_lon));
        setEl("frForwardMarkerGps", gpsText(fr.forward_marker_lat, fr.forward_marker_lon));
        setEl("frHeadingDeg", fr.field_heading_yaw_rad != null ? (fr.field_heading_yaw_rad * 180 / Math.PI).toFixed(2) + " deg" : "--");
        setEl("frRuntimeState", runtime.state || "--");
        setEl("frRuntimeProfile", runtime.profile_id || "--");
        setEl("frRuntimeError", runtime.last_error || "--");
    }

    // ── fetch ────────────────────────────────────────────────────────
    async function fetchFieldReferenceStatus(options) {
        options = options || {};
        if (pollInFlight) return null;
        pollInFlight = true;
        try {
            var data = await api.request("/api/field-reference/status");
            // Broadcast to competition panel (primary consumer)
            if (window.UavFieldProfiles && typeof window.UavFieldProfiles.onFieldReferenceStatus === "function") {
                window.UavFieldProfiles.onFieldReferenceStatus(data);
            }
            // Also render legacy panel (inside <details>)
            renderFieldReference(data);
            var runtime = ((data || {}).field_reference || {}).runtime_binding || {};
            var delay = (runtime.state === "sampling") ? 500 : 2000;
            if (options.scheduleNext !== false) scheduleNextPoll(delay);
            return data;
        } catch (e) {
            if (options.scheduleNext !== false) scheduleNextPoll(2000);
            return null;
        } finally { pollInFlight = false; }
    }

    function scheduleNextPoll(delayMs) {
        if (!pollingStarted) return;
        if (pollTimer !== null) clearTimeout(pollTimer);
        pollTimer = setTimeout(function () {
            pollTimer = null;
            if (pollingStarted) fetchFieldReferenceStatus({ scheduleNext: true });
        }, delayMs);
    }

    function startPolling() {
        if (pollingStarted) return;
        pollingStarted = true;
        if (pollTimer !== null) { clearTimeout(pollTimer); pollTimer = null; }
        fetchFieldReferenceStatus({ scheduleNext: true });
    }

    function stopPolling() {
        if (pollTimer !== null) { clearTimeout(pollTimer); pollTimer = null; }
        pollingStarted = false;
    }

    // ── init ──────────────────────────────────────────────────────────
    function init() {
        if (_initCalled) return; // prevent double init
        _initCalled = true;

        // Legacy button wiring (inside <details>)
        var r = $("frReset");
        if (r) r.onclick = async function () {
            if (!window.confirm("将清除 Field Reference、runtime sampling 和冻结状态。\n不会发送飞控命令。")) return;
            await api.request("/api/field-reference/reset", { method: "POST", body: "{}" });
            fetchFieldReferenceStatus({ scheduleNext: false });
        };
        var f = $("frFreeze");
        if (f) f.onclick = async function () {
            await api.request("/api/field-reference/freeze", { method: "POST", body: "{}" });
            fetchFieldReferenceStatus({ scheduleNext: false });
        };

        // Legacy profile panel handlers (inside <details>)
        var sel = $("fpProfileSelect");
        if (sel) {
            sel.onchange = function () {
                var id = this.value || null;
                if (id) {
                    api.request("/api/field-profiles/" + encodeURIComponent(id)).then(function (d) {
                        if (d && d.ok === true) {
                            // minimal legacy render
                            setEl("fpProfileId", d.profile_id || "--");
                            setEl("fpProfileName", d.name || "--");
                            var pd = $("fpProfileDetail"); if (pd) pd.style.display = "";
                        }
                    }).catch(function () {});
                }
            };
        }
        var rb = $("fpRefreshList");
        if (rb) {
            rb.addEventListener("click", function () {
                api.request("/api/field-profiles").then(function (data) {
                    var profiles = (data && data.ok === true && Array.isArray(data.profiles)) ? data.profiles : [];
                    var selEl = $("fpProfileSelect");
                    if (!selEl) return;
                    while (selEl.options.length) selEl.remove(0);
                    var opt = document.createElement("option"); opt.value = ""; opt.textContent = "-- Select --"; selEl.appendChild(opt);
                    profiles.forEach(function (p) {
                        var o = document.createElement("option");
                        o.value = p.profile_id || "";
                        o.textContent = (p.source ? "[" + p.source + "] " : "") + (p.profile_id || "") + " — " + (p.name || "");
                        selEl.appendChild(o);
                    });
                }).catch(function () {});
            });
        }
        var vb = $("fpValidateProfile");
        if (vb) vb.addEventListener("click", function () {
            var id = ($("fpProfileSelect") || {}).value;
            if (!id) { alert("请先选择 Profile"); return; }
            api.request("/api/field-profiles/" + encodeURIComponent(id) + "/validate").then(function (d) {
                alert("Validate: " + (d && d.ok === true ? "PASS" : ("FAIL — " + ((d || {}).error || "unknown"))));
            }).catch(function (e) { alert("Validate error: " + e.message); });
        });
        var bb = $("fpBindCurrent");
        if (bb) bb.addEventListener("click", async function () {
            var id = ($("fpProfileSelect") || {}).value;
            if (!id) { alert("请先选择 Schema v2 Profile"); return; }
            if (!window.confirm("将使用当前无人机 GPS + LOCAL_NED 绑定所选 Field Profile。\n该操作不会启动 Mission，不会发送飞控命令。")) return;
            try {
                var r = await api.request("/api/field-profiles/" + encodeURIComponent(id) + "/bind-current", { method: "POST", body: "{}" });
                if (r && r.ok === true) { setEl("fpBindOk", "YES"); setEl("fpBindProfileId", r.profile_id || "--"); }
                fetchFieldReferenceStatus({ scheduleNext: false });
            } catch (e) { alert("Bind error: " + e.message); }
        });

        // Legacy runtime sampling buttons
        var rsb = $("fpRuntimeStart");
        if (rsb) rsb.addEventListener("click", async function () {
            var id = ($("fpProfileSelect") || {}).value;
            if (!id) { alert("请先选择 Schema v3 Profile"); return; }
            if (!window.confirm("将使用当前飞行器 WGS84 GPS 采样动态原点。\n采样不会启动 Mission，不会发送飞控命令。")) return;
            await api.request("/api/field-profiles/" + encodeURIComponent(id) + "/runtime-sampling/start", { method: "POST", body: "{}" });
            fetchFieldReferenceStatus({ scheduleNext: false });
        });
        var rfb = $("fpRuntimeFinalize");
        if (rfb) rfb.addEventListener("click", async function () {
            if (!window.confirm("将结束 GPS 采样，应用动态原点和场地方向并冻结 Field Reference。\n成功后如需更改，必须执行完整重置。\n该操作不会启动 Mission，不会发送飞控命令。")) return;
            await api.request("/api/field-reference/runtime-sampling/finalize", { method: "POST", body: "{}" });
            fetchFieldReferenceStatus({ scheduleNext: false });
        });
        var rcb = $("fpRuntimeCancel");
        if (rcb) rcb.addEventListener("click", async function () {
            if (!window.confirm("取消当前 GPS 采样？")) return;
            await api.request("/api/field-reference/runtime-sampling/cancel", { method: "POST", body: "{}" });
            fetchFieldReferenceStatus({ scheduleNext: false });
        });

        window.addEventListener("beforeunload", stopPolling, { once: true });
        startPolling();
    }

    return {
        gpsText: gpsText,
        renderFieldReference: renderFieldReference,
        fetchFieldReferenceStatus: fetchFieldReferenceStatus,
        startPolling: startPolling,
        stopPolling: stopPolling,
        init: init
    };
})();
