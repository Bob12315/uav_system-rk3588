window.UavFieldRef = (function () {
    "use strict";
    var timer = null;
    var inFlight = false;
    var active = false;

    async function fetchFieldReferenceStatus(options) {
        options = options || {};
        if (inFlight) return null;
        inFlight = true;
        try {
            var data = await window.UavApi.request("/api/field-reference/status");
            if (window.UavFieldProfiles) window.UavFieldProfiles.onFieldReferenceStatus(data);
            if (options.scheduleNext !== false) schedule(data);
            return data;
        } catch (_) {
            if (options.scheduleNext !== false) schedule(null);
            return null;
        } finally { inFlight = false; }
    }

    function schedule(data) {
        if (!active) return;
        if (timer !== null) clearTimeout(timer);
        var state = (((data || {}).field_reference || {}).runtime_binding || {}).state;
        timer = setTimeout(function () { fetchFieldReferenceStatus({scheduleNext: true}); }, state === "sampling" ? 500 : 2000);
    }
    function startPolling() { if (!active) { active = true; fetchFieldReferenceStatus({scheduleNext: true}); } }
    function stopPolling() { active = false; if (timer !== null) clearTimeout(timer); timer = null; }
    function init() { startPolling(); window.addEventListener("beforeunload", stopPolling, {once: true}); }
    return {fetchFieldReferenceStatus: fetchFieldReferenceStatus, startPolling: startPolling, stopPolling: stopPolling, init: init};
})();
