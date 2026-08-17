// format_utils.js — Pure formatting helpers for UAV Action Console
// Extracted from app.js (WU-2A).  No side effects, no DOM access.
window.UavFormat = (function () {
  "use strict";

  function stamp(seconds) {
    return seconds ? new Date(seconds * 1000).toLocaleTimeString() : "--";
  }

  function escapeHtml(text) {
    return String(text ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
  }

  function num(value, digits, unit) {
    if (digits === undefined) digits = 2;
    if (unit === undefined) unit = "";
    return Number.isFinite(Number(value)) ? Number(value).toFixed(digits) + unit : "--";
  }

  function degNum(value, digits) {
    if (digits === undefined) digits = 1;
    return Number.isFinite(Number(value)) ? Number(value).toFixed(digits) + "°" : "--";
  }

  function xyzText(x, y, z, digits) {
    if (digits === undefined) digits = 2;
    return [x, y, z].every(function (v) { return Number.isFinite(Number(v)); })
      ? Number(x).toFixed(digits) + " / " + Number(y).toFixed(digits) + " / " + Number(z).toFixed(digits)
      : "--";
  }

  function boolText(value, yes, no) {
    if (yes === undefined) yes = "YES";
    if (no === undefined) no = "NO";
    return value ? yes : no;
  }

  return {
    stamp: stamp,
    escapeHtml: escapeHtml,
    num: num,
    degNum: degNum,
    xyzText: xyzText,
    boolText: boolText,
  };
})();
