})();

// ── Polling (integrated into UavFieldRef) ──

var pollTimer = null;
var pollInFlight = false;
var pollingStarted = false;

window.UavFieldRef.fetchFieldReferenceStatus = function(options) {
    options = options || {};
    if (pollInFlight && options.scheduleNext !== false) {
        return Promise.resolve(null);
    }
    pollInFlight = true;
    return fetch("/api/field-reference/status")
        .then(function(r) { return r.json(); })
        .then(function(data) {
            window.UavFieldRef.renderFieldReference(data);
            if (window.UavFieldProfiles && window.UavFieldProfiles.onFieldReferenceStatus) {
                window.UavFieldProfiles.onFieldReferenceStatus(data);
            }
            var runtime = ((data || {}).field_reference || {}).runtime_binding || {};
            var delay = (runtime.state === "sampling") ? 500 : 2000;
            if (options.scheduleNext !== false) scheduleNextPoll(delay);
            return data;
        })
        .catch(function() {
            if (options.scheduleNext !== false) scheduleNextPoll(2000);
            return null;
        })
        .finally(function() { pollInFlight = false; });
};

window.UavFieldRef.renderFieldReference = function(data) {
    var fr = (data || {}).field_reference || {};
    var runtime = fr.runtime_binding || {};
    setEl("frGpsReady", fr.is_ready_for_field_to_gps ? "YES" : "no");
    setEl("frLocalReady", fr.is_ready_for_field_to_local ? "YES" : "no");
    setEl("frForwardMarkerGps", fr.forward_marker_lat != null ? fr.forward_marker_lat.toFixed(7)+", "+fr.forward_marker_lon.toFixed(7) : "--");
    setEl("frRuntimeState", runtime.state || "--");
    setEl("frRuntimeProfile", runtime.profile_id || "--");
    setEl("frRuntimeError", runtime.last_error || "--");
    setEl("frConfirmed", fr.is_confirmed ? "YES" : "no");
    setEl("frFrozen", fr.is_frozen ? "YES" : "no");
    setEl("frOriginSource", fr.origin_source || "--");
    setEl("frHeadingSource", fr.heading_source || "--");
    setEl("frActiveSource", fr.active_source || "--");
    setEl("frSynced", fr.synced_to_runtime ? "YES" : "no");
    setEl("frOriginGps", fr.origin_lat != null ? fr.origin_lat.toFixed(7)+", "+fr.origin_lon.toFixed(7) : "--");
    setEl("frHeadingDeg", fr.field_heading_yaw_rad != null ? (fr.field_heading_yaw_rad*180/Math.PI).toFixed(2)+" deg" : "--");
};

function setEl(id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = String(text);
}

function scheduleNextPoll(delayMs) {
    if (!pollingStarted) return;
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = setTimeout(function() {
        pollTimer = null;
        window.UavFieldRef.fetchFieldReferenceStatus({scheduleNext: true});
    }, delayMs);
}

window.UavFieldRef.startPolling = function() {
    if (pollingStarted) return;
    pollingStarted = true;
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
    window.UavFieldRef.fetchFieldReferenceStatus({scheduleNext: true});
};

window.UavFieldRef.stopPolling = function() {
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
    pollingStarted = false;
};

window.UavFieldRef.frPost = async function(url) {
    var r = await fetch(url, {method: "POST"});
    return r.json();
};

// Start on DOM ready
if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", function() {
            window.UavFieldRef.startPolling();
        });
    } else {
        window.UavFieldRef.startPolling();
    }
}
