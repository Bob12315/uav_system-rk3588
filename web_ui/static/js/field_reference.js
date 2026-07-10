window.UavFieldRef = (function () {
    "use strict";

    var pollTimer = null;
    var pollInFlight = false;
    var pollingStarted = false;

    // ── helpers ──────────────────────────────────────────────────────
    function $(id) { return document.getElementById(id); }
    function setEl(id, text) { var e = $(id); if (e) { var t = typeof text === "string" ? text : String(text||""); if (e.textContent !== t) e.textContent = t; } }
    var api = window.UavApi;

    // ── GPS text helper ──────────────────────────────────────────────
    function gpsText(lat, lon) {
        if (lat == null || lon == null) return "--";
        return Number(lat).toFixed(7) + ", " + Number(lon).toFixed(7);
    }

    // ── render ──────────────────────────────────────────────────────
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
            renderFieldReference(data);
            if (window.UavFieldProfiles && typeof window.UavFieldProfiles.onFieldReferenceStatus === "function") {
                window.UavFieldProfiles.onFieldReferenceStatus(data);
            }
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
            fetchFieldReferenceStatus({ scheduleNext: true });
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

    // ── posts ────────────────────────────────────────────────────────
    async function frPost(url) {
        var r = await api.request(url, { method: "POST", body: "{}" });
        fetchFieldReferenceStatus({ scheduleNext: false });
        return r;
    }

    // ── init ──────────────────────────────────────────────────────────
    function init() {
        var r = $("frReset");
        if (r) r.onclick = async function () {
            if (!window.confirm("将清除 Field Reference、runtime sampling 和冻结状态。\n不会发送飞控命令。")) return;
            await frPost("/api/field-reference/reset");
        };
        var f = $("frFreeze");
        if (f) f.onclick = async function () {
            await frPost("/api/field-reference/freeze");
        };
        window.addEventListener("beforeunload", stopPolling, { once: true });
        startPolling();
    }

    return {
        gpsText: gpsText,
        renderFieldReference: renderFieldReference,
        fetchFieldReferenceStatus: fetchFieldReferenceStatus,
        startPolling: startPolling,
        stopPolling: stopPolling,
        frPost: frPost,
        init: init
    };
})();
