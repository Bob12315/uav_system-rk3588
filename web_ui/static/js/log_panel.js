// log_panel.js — Audit log panel logic for UAV Action Console
// Extracted from app.js (WU-7A).  Uses configure() pattern.
(function () {
  "use strict";

  var cfg = {
    api: null,
    dom: null,
    format: null,
    appState: null,
    setCompletionHint: null,
  };

  function configure(options) {
    if (!options) return;
    if (options.api) cfg.api = options.api;
    if (options.dom) cfg.dom = options.dom;
    if (options.format) cfg.format = options.format;
    if (options.appState) cfg.appState = options.appState;
    if (options.setCompletionHint) cfg.setCompletionHint = options.setCompletionHint;
  }

  function _api() { return cfg.api ? cfg.api.request : window.UavApi.request; }
  function _dom() { return cfg.dom || window.UavDom; }
  function _fmt() { return cfg.format || window.UavFormat; }
  function _history() {
    var appState = cfg.appState || window.UavAppState || {};
    return Array.isArray(appState.history) ? appState.history : null;
  }

  async function loadAudit() {
    var records = await _api()("/api/audit?limit=100");
    var h = _history();
    if (h) {
      var next = records.filter(function (r) { return r.source === "CLI" || r.source === "BUTTON"; }).map(function (r) { return r.action; });
      h.splice(0, h.length);
      Array.prototype.push.apply(h, next);
    }
    var fmt = _fmt();
    _dom().$("auditLog").innerHTML = records.map(function (r) {
      return "<div class=\"log-line " + (r.ok ? "" : "bad") + "\">" + fmt.stamp(r.timestamp) + " " + fmt.escapeHtml(r.source) + " &nbsp; " + fmt.escapeHtml(r.action) + "</div>";
    }).join("");
  }

  window.UavLogPanel = {
    configure: configure,
    loadAudit: loadAudit,
  };
})();
