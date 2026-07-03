// field_reference.js — Field Reference panel logic (centerline-only)
// Removed: legacy field-heading, mark-origin, mark-forward, use-current-yaw,
//          manual-heading, manual-confirm, and confirmFieldHeading paths.
window.UavFieldRef = (function () {
  "use strict";

  // ------------------------------------------------------------------
  // helpers
  // ------------------------------------------------------------------

  function gpsText(lat, lon) {
    if (lat == null || lon == null) return "--";
    return Number(lat).toFixed(6) + " / " + Number(lon).toFixed(6);
  }

  // ------------------------------------------------------------------
  // Field Reference (centerline only)
  // ------------------------------------------------------------------

  async function fetchFieldReferenceStatus() {
    try {
      var data = await window.UavApi.request("/api/field-reference/status");
      if (data && data.field_reference) renderFieldReference(data);
    } catch (e) { /* ignore */ }
  }

  function renderFieldReference(data) {
    var fr = data.field_reference || {};
    var tele = data.telemetry || {};
    var set = window.UavDom.setOptionalText;
    var f = window.UavFormat;
    set("frConfirmed", fr.is_confirmed ? "YES" : "NO");
    set("frFrozen", fr.is_frozen ? "YES" : "NO");
    set("frOriginSource", fr.origin_source || "--");
    set("frHeadingSource", fr.heading_source || "--");
    set("frHeadingDeg", f.degNum(fr.field_heading_deg));
    set("frOriginLocal", f.xyzText(fr.origin_local_n_m, fr.origin_local_e_m, fr.origin_local_z_m));
    set("frOriginGps", gpsText(fr.origin_lat, fr.origin_lon));
    set("frGpsFix", (tele.gps_fix_type || 0) + " / " + (tele.satellites_visible || 0) + " sats");
    set("frGpsEphEpv", f.num(tele.gps_eph, 1) + " / " + f.num(tele.gps_epv, 1));
    set("frGpsValid", tele.global_position_valid ? "YES" : "NO");
    set("frHasLocal", tele.has_local_position ? "YES" : "NO");
    var active = fr.active_source || "none";
    set("frActiveSource", active);
    set("frSynced", fr.synced_to_runtime ? "YES" : "NO");
    // Centerline-specific fields
    set("frStartError", fr.current_start_error_m != null ? Number(fr.current_start_error_m).toFixed(2) + " m" : "--");
    set("frYawError", fr.yaw_error_deg != null ? f.degNum(fr.yaw_error_deg) : "--");
    set("frMaxResidual", fr.max_residual_m != null ? Number(fr.max_residual_m).toFixed(3) + " m" : "--");
    set("frRmsResidual", fr.rms_residual_m != null ? Number(fr.rms_residual_m).toFixed(3) + " m" : "--");
    var w = fr.warnings || [];
    set("frWarnings", w.length ? w.join("; ") : "--");
    // Centerline residual table
    var residuals = fr.centerline_residuals || [];
    var tableHtml = "";
    if (residuals.length) {
      tableHtml = "<table class='fr-residual-table'><tr><th>Point</th><th>Residual (m)</th><th>Fitted Y (m)</th></tr>";
      for (var i = 0; i < residuals.length; i++) {
        var r = residuals[i];
        tableHtml += "<tr><td>" + (r.name || ("CL" + i)) + "</td>"
          + "<td>" + Number(r.residual_m).toFixed(3) + "</td>"
          + "<td>" + (r.fitted_field_y_m != null ? Number(r.fitted_field_y_m).toFixed(2) : "--") + "</td></tr>";
      }
      tableHtml += "</table>";
    }
    var residualEl = window.UavDom.$("frResidualTable");
    if (residualEl) residualEl.innerHTML = tableHtml;
  }

  async function frPost(url) {
    try {
      var result = await window.UavApi.request(url, {method: "POST", body: "{}"});
      window.UavDom.$("frHint").textContent = result.ok
        ? (result.message || "OK") + (result.warnings && result.warnings.length ? " Warnings: " + result.warnings.join("; ") : "")
        : result.error || "failed";
      fetchFieldReferenceStatus();
    } catch (e) {
      window.UavDom.$("frHint").textContent = "request failed: " + e.message;
    }
  }

  // ------------------------------------------------------------------
  // init (bind DOM events — centerline only)
  // ------------------------------------------------------------------

  function init() {
    var $ = window.UavDom.$;

    // Field Reference buttons (centerline only: reset + freeze)
    if ($("frReset")) $("frReset").onclick = function () { frPost("/api/field-reference/reset"); };
    if ($("frFreeze")) $("frFreeze").onclick = function () { frPost("/api/field-reference/freeze"); };
  }

  // ------------------------------------------------------------------
  // public API
  // ------------------------------------------------------------------

  return {
    gpsText: gpsText,
    fetchFieldReferenceStatus: fetchFieldReferenceStatus,
    renderFieldReference: renderFieldReference,
    frPost: frPost,
    init: init,
  };
})();
