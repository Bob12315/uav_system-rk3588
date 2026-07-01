// field_reference.js — Field Heading + Field Reference panel logic
// Extracted from app.js (WU-3A).  Does NOT change backend API, coordinate
// conversion, confirm/freeze/reset semantics, or MAVLink behavior.
window.UavFieldRef = (function () {
  "use strict";

  // ------------------------------------------------------------------
  // helpers (refer to globals loaded before this script)
  // ------------------------------------------------------------------

  function gpsText(lat, lon) {
    if (lat == null || lon == null) return "--";
    return Number(lat).toFixed(6) + " / " + Number(lon).toFixed(6);
  }

  // ------------------------------------------------------------------
  // Field Heading (legacy)
  // ------------------------------------------------------------------

  function renderFieldHeading(next) {
    var field = next.field_heading || {};
    window.UavDom.setOptionalText("fieldHeadingCurrentYaw", window.UavFormat.degNum(field.current_yaw_deg));
    window.UavDom.setOptionalText("fieldHeadingPreArmYaw", window.UavFormat.degNum(field.pre_arm_yaw_deg));
    window.UavDom.setOptionalText("fieldHeadingConfirmedYaw", window.UavFormat.degNum(field.field_heading_yaw_deg));
    window.UavDom.setOptionalText("fieldHeadingDelta", window.UavFormat.degNum(field.delta_current_to_field_deg));
    window.UavDom.setOptionalText("fieldHeadingOrigin", window.UavFormat.xyzText(field.origin_local_x, field.origin_local_y, field.origin_local_z));
    window.UavDom.setOptionalText("fieldHeadingCurrentField", window.UavFormat.xyzText(field.current_field_x, field.current_field_y, field.current_field_z));
    window.UavDom.setOptionalText("fieldHeadingConfirmed", field.field_heading_confirmed ? "YES" : "NO");
    window.UavDom.setOptionalText("fieldHeadingSource", field.field_heading_source || "--");
    window.UavDom.setOptionalText("fieldHeadingTime", window.UavFormat.stamp(field.field_heading_time));
    window.UavDom.setOptionalText("fieldHeadingAttitudeValid", field.attitude_valid ? "YES" : "NO");

    var $ = window.UavDom.$;
    var delta = Number(field.delta_current_to_field_deg);
    var deltaElement = $("fieldHeadingDelta");
    if (deltaElement) {
      deltaElement.classList.toggle("ok-text", Number.isFinite(delta) && Math.abs(delta) <= 2.0);
      deltaElement.classList.toggle("warning-text", Number.isFinite(delta) && Math.abs(delta) > 2.0 && Math.abs(delta) <= 8.0);
      deltaElement.classList.toggle("danger-text", Number.isFinite(delta) && Math.abs(delta) > 8.0);
    }

    var hint = $("fieldHeadingHint");
    if (hint) {
      if (!field.attitude_valid) {
        hint.textContent = "姿态 yaw 无效，无法确认场地方向。请检查 MAVLink ATTITUDE 数据。";
      } else if (field.local_position_valid === false) {
        hint.textContent = "无法确认原点：当前 LOCAL_NED 位置无效。请检查定位/LOCAL_POSITION_NED 数据。";
      } else if (!field.field_heading_confirmed) {
        hint.textContent = "未确认：起飞前把机头对准场地方向，然后点击确认。程序起飞也会自动确认。确认只记录内部 yaw 和任务坐标原点，不发 MAVLink。";
      } else if (Number.isFinite(delta)) {
        hint.textContent = "已确认：当前 yaw 与场地方向偏差 " + delta.toFixed(1) + "°。地面静止时建议接近 0°。";
      } else {
        hint.textContent = "已确认场地方向/原点。确认只记录 app 内部状态，不发 MAVLink。";
      }
    }
  }

  async function confirmFieldHeading() {
    var field = (typeof state !== "undefined" ? state.field_heading : null) || {};
    if (!field.attitude_valid) {
      window.UavDom.$("completionHint").textContent = "姿态 yaw 无效，无法确认场地方向";
      return;
    }
    var confirmed = window.confirm(
      "确认将当前机头 yaw 记录为场地方向？\n"
      + "并将当前 LOCAL_NED 位置记录为任务坐标原点。\n"
      + "请确保飞机放在地上，机头已经对准场地方向。\n"
      + "当前 yaw: " + window.UavFormat.degNum(field.current_yaw_deg)
    );
    if (!confirmed) return;
    var result = await window.UavApi.request("/api/field-heading/confirm", {method: "POST", body: "{}"});
    window.UavDom.$("completionHint").textContent = result.message || (result.ok ? "field heading confirmed" : "field heading confirm failed");
    if (typeof state !== "undefined" && result.field_heading) {
      state.field_heading = result.field_heading;
      renderFieldHeading(state);
    }
    if (typeof loadAudit === "function") await loadAudit();
  }

  // ------------------------------------------------------------------
  // Field Reference (new panel)
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
    set("frOriginLocal", f.xyzText(fr.origin_local_n_m, fr.origin_local_e_m, null));
    set("frOriginGps", gpsText(fr.origin_lat, fr.origin_lon));
    set("frForwardGps", gpsText(fr.forward_marker_lat, fr.forward_marker_lon));
    set("frDistance", fr.distance_m != null ? Number(fr.distance_m).toFixed(2) + " m" : "--");
    var w = fr.warnings || [];
    set("frWarnings", w.length ? w.join("; ") : "--");
    set("frGpsFix", (tele.gps_fix_type || 0) + " / " + (tele.satellites_visible || 0) + " sats");
    set("frGpsEphEpv", f.num(tele.gps_eph, 1) + " / " + f.num(tele.gps_epv, 1));
    set("frGpsValid", tele.global_position_valid ? "YES" : "NO");
    set("frHasLocal", tele.has_local_position ? "YES" : "NO");
    set("frOriginLocal", f.xyzText(fr.origin_local_n_m, fr.origin_local_e_m, fr.origin_local_z_m));
    var active = fr.active_source || "none";
    set("frActiveSource", active);
    set("frSynced", fr.synced_to_runtime ? "YES" : "NO");
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

  async function frSetManualHeading() {
    var deg = parseFloat(window.UavDom.$("frManualHeadingDeg").value);
    if (!Number.isFinite(deg)) { window.UavDom.$("frHint").textContent = "enter valid degrees"; return; }
    try {
      var result = await window.UavApi.request("/api/field-reference/set-manual-heading", {
        method: "POST",
        body: JSON.stringify({yaw_deg: deg}),
        headers: {"Content-Type": "application/json"},
      });
      window.UavDom.$("frHint").textContent = result.ok ? "manual heading set" : result.error || "failed";
      fetchFieldReferenceStatus();
    } catch (e) {
      window.UavDom.$("frHint").textContent = "request failed: " + e.message;
    }
  }

  // ------------------------------------------------------------------
  // init (bind DOM events for Field Heading + Field Reference)
  // ------------------------------------------------------------------

  function init() {
    var $ = window.UavDom.$;

    // Field Reference buttons
    if ($("frMarkOrigin")) $("frMarkOrigin").onclick = function () { frPost("/api/field-reference/mark-origin"); };
    if ($("frMarkForward")) $("frMarkForward").onclick = function () { frPost("/api/field-reference/mark-forward"); };
    if ($("frUseCurrentYaw")) $("frUseCurrentYaw").onclick = function () { frPost("/api/field-reference/use-current-yaw"); };
    if ($("frSetManualHeading")) $("frSetManualHeading").onclick = frSetManualHeading;
    if ($("frConfirm")) $("frConfirm").onclick = function () { frPost("/api/field-reference/confirm"); };
    if ($("frReset")) $("frReset").onclick = function () { frPost("/api/field-reference/reset"); };
    if ($("frFreeze")) $("frFreeze").onclick = function () { frPost("/api/field-reference/freeze"); };

    // Field Heading legacy confirm
    var confirmBtn = $("confirmFieldHeading");
    if (confirmBtn) {
      confirmBtn.addEventListener("click", function () {
        confirmFieldHeading().catch(function (error) {
          window.UavDom.$("completionHint").textContent = "确认场地方向失败: " + error.message;
        });
      });
    }
  }

  // ------------------------------------------------------------------
  // public API
  // ------------------------------------------------------------------

  return {
    gpsText: gpsText,
    renderFieldHeading: renderFieldHeading,
    confirmFieldHeading: confirmFieldHeading,
    fetchFieldReferenceStatus: fetchFieldReferenceStatus,
    renderFieldReference: renderFieldReference,
    frPost: frPost,
    frSetManualHeading: frSetManualHeading,
    init: init,
  };
})();
