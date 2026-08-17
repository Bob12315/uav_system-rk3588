// dom_utils.js — DOM helper functions for UAV Action Console
// Extracted from app.js (WU-2A).  No API calls, no state mutation.
// Depends on window.UavFormat (format_utils.js loaded first).
window.UavDom = (function () {
  "use strict";
  var fmt = window.UavFormat;

  function $(id) {
    return document.getElementById(id);
  }

  function setOptionalText(id, value) {
    var element = $(id);
    if (element) element.textContent = value;
  }

  function cards(target, values) {
    target.innerHTML = Object.entries(values).map(function (entry) {
      var label = entry[0];
      var value = entry[1];
      return "<div class=\"card\"><label>" + fmt.escapeHtml(label) + "</label>" + fmt.escapeHtml(value) + "</div>";
    }).join("");
  }

  function infoRows(target, rows) {
    target.innerHTML = rows.map(function (row) {
      var label = row[0];
      var value = row[1];
      return "<div class=\"info-label\">" + fmt.escapeHtml(label) + "</div><div class=\"info-value\">" + fmt.escapeHtml(value) + "</div>";
    }).join("");
  }

  function renderSummaryRows(id, rows) {
    var element = $(id);
    if (!element) return;
    element.innerHTML = rows.map(function (row) {
      var label = row[0];
      var value = row[1];
      var tone = row[2];
      return "<div class=\"summary-row " + (tone || "") + "\"><span>" + fmt.escapeHtml(label) + "</span><strong>" + fmt.escapeHtml(value) + "</strong></div>";
    }).join("");
  }

  return {
    $: $,
    setOptionalText: setOptionalText,
    cards: cards,
    infoRows: infoRows,
    renderSummaryRows: renderSummaryRows,
  };
})();
