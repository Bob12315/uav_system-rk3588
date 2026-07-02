// config_panel.js — Config panel logic for UAV Action Console
// Extracted from app.js (WU-7B v2).  Uses configure() pattern.
(function () {
  "use strict";

  var cfg = {
    api: null,
    dom: null,
    format: null,
    loadAudit: null,
    setCompletionHint: null,
    setConfigStatus: null,
  };

  var configState = {
    currentConfigPath: "",
    currentOriginal: "",
  };

  function configure(options) {
    if (!options) return;
    if (options.api) cfg.api = options.api;
    if (options.dom) cfg.dom = options.dom;
    if (options.format) cfg.format = options.format;
    if (options.loadAudit) cfg.loadAudit = options.loadAudit;
    if (options.setCompletionHint) cfg.setCompletionHint = options.setCompletionHint;
    if (options.setConfigStatus) cfg.setConfigStatus = options.setConfigStatus;
  }

  function _api() { return cfg.api ? cfg.api.request : window.UavApi.request; }
  function _dom() { return cfg.dom || window.UavDom; }
  function _fmt() { return cfg.format || window.UavFormat; }
  function _setHint(text) { if (typeof cfg.setCompletionHint === "function") cfg.setCompletionHint(text); }
  function _setConfigStatus(text) { if (typeof cfg.setConfigStatus === "function") cfg.setConfigStatus(text); }
  function _loadAudit() { if (typeof cfg.loadAudit === "function") return cfg.loadAudit(); return Promise.resolve(); }

  function getCurrentConfigPath() { return configState.currentConfigPath; }
  function getCurrentOriginal() { return configState.currentOriginal; }

  // ------------------------------------------------------------------
  // config functions
  // ------------------------------------------------------------------

  async function loadConfigFiles() {
    var files = await _api()("/api/config/files");
    var $ = _dom().$;
    $("configFiles").innerHTML = files.map(function (path) {
      return "<button data-path=\"" + path + "\">" + path + "</button>";
    }).join("");
    $("configFiles").querySelectorAll("button").forEach(function (button) {
      button.onclick = function () { openConfig(button.dataset.path); };
    });
  }

  async function openConfig(path) {
    var file = await _api()("/api/config/file?path=" + encodeURIComponent(path));
    configState.currentConfigPath = path;
    configState.currentOriginal = file.content;
    var $ = _dom().$;
    $("editingPath").textContent = path;
    $("yamlEditor").value = file.content;
    $("configDiff").textContent = "";
    _setConfigStatus(file.has_backup ? "存在上一次保存前版本，可恢复。" : "尚无备份版本。");
    document.querySelectorAll("#configFiles button").forEach(function (b) {
      b.classList.toggle("active", b.dataset.path === path);
    });
    var action = path.startsWith("missions/") ? "保存并应用" :
      path === "config/telemetry.yaml" ? "保存并重连" :
      path === "config/yolo.yaml" ? "保存并重启 YOLO" :
      path === "config/app.yaml" ? "保存并重启 App" : "保存并应用";
    $("applyConfig").textContent = action;
  }

  function localDiff(before, after) {
    if (before === after) return "没有修改。";
    return "已修改配置；保存前后端会再次校验 YAML，并返回正式差异。";
  }

  async function saveConfig(action) {
    if (action === undefined) action = "save";
    if (!configState.currentConfigPath) return;
    var $ = _dom().$;
    if (action !== "save" && !confirm($("applyConfig").textContent + " 将可能停止命令发送或重启服务，确认继续？")) return;
    var result = await _api()("/api/config/file?path=" + encodeURIComponent(configState.currentConfigPath), {
      method: "PUT", body: JSON.stringify({content: $("yamlEditor").value, action: action})
    });
    configState.currentOriginal = $("yamlEditor").value;
    $("configDiff").textContent = result.diff || "保存成功，无文本差异。";
    _setConfigStatus(result.message);
    await _loadAudit();
  }

  async function restoreConfig() {
    if (!configState.currentConfigPath || !confirm("确认恢复上一次保存前版本？")) return;
    var action = configState.currentConfigPath.startsWith("missions/") ? "apply" : "save";
    var result = await _api()("/api/config/restore?path=" + encodeURIComponent(configState.currentConfigPath) + "&action=" + encodeURIComponent(action), {method: "POST"});
    _setConfigStatus(result.message);
    var $ = _dom().$;
    $("configDiff").textContent = result.diff;
    await openConfig(configState.currentConfigPath);
    await _loadAudit();
  }

  function actionForPath() {
    if (configState.currentConfigPath.startsWith("missions/")) return "apply";
    if (configState.currentConfigPath === "config/telemetry.yaml") return "reconnect";
    if (configState.currentConfigPath === "config/yolo.yaml" || configState.currentConfigPath === "config/app.yaml") return "restart";
    return "save";
  }

  // ------------------------------------------------------------------
  // public API
  // ------------------------------------------------------------------

  window.UavConfigPanel = {
    configure: configure,
    getCurrentConfigPath: getCurrentConfigPath,
    getCurrentOriginal: getCurrentOriginal,
    loadConfigFiles: loadConfigFiles,
    openConfig: openConfig,
    localDiff: localDiff,
    saveConfig: saveConfig,
    restoreConfig: restoreConfig,
    actionForPath: actionForPath,
  };
})();
