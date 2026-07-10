// api_client.js — Unified frontend API client for UAV Action Console
// Extracted from app.js (WU-1).  All API URL / method / body / response
// semantics are preserved exactly as they were in the original app.js.
window.UavApi = (function () {
  "use strict";

  // ------------------------------------------------------------------
  // generic fetch + JSON wrapper (was `json()` in app.js)
  // ------------------------------------------------------------------
  async function request(url, options) {
    if (options === undefined) options = {};
    const fetchOptions = Object.assign({headers: {"Content-Type": "application/json"}}, options);
    const timeoutMs = Number(fetchOptions.timeoutMs || 10000);
    delete fetchOptions.timeoutMs;
    const controller = !fetchOptions.signal && typeof AbortController !== "undefined"
      ? new AbortController()
      : null;
    if (controller) fetchOptions.signal = controller.signal;
    const timeout = controller && timeoutMs > 0
      ? setTimeout(function () { controller.abort(); }, timeoutMs)
      : null;
    try {
      const response = await fetch(url, fetchOptions);
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "request failed");
      return data;
    } catch (error) {
      if (error && error.name === "AbortError") throw new Error("request timeout");
      throw error;
    } finally {
      if (timeout !== null) clearTimeout(timeout);
    }
  }

  // ------------------------------------------------------------------
  // System / Status
  // ------------------------------------------------------------------
  function getStatus() {
    return request("/api/status");
  }
  function getAudit(limit) {
    return request("/api/audit?limit=" + (limit || 100));
  }
  function getEvents() {
    return request("/api/events");
  }
  function getCommandCompletions() {
    return request("/api/commands/completions");
  }
  function executeCommand(command, source) {
    return request("/api/commands/execute", {
      method: "POST",
      body: JSON.stringify({command: command, source: source || "BUTTON"}),
    });
  }

  // ------------------------------------------------------------------
  // Missions (legacy — still available)
  // ------------------------------------------------------------------
  function getMissions() {
    return request("/api/missions");
  }

  // ------------------------------------------------------------------
  // Action Lab
  // ------------------------------------------------------------------
  function listActions() {
    return request("/api/actions/list");
  }
  function getActionStatus() {
    return request("/api/actions/status");
  }
  function startAction(name, params, sendActions) {
    return request("/api/actions/start", {
      method: "POST",
      body: JSON.stringify({
        name: name,
        params: params,
        send_actions: Boolean(sendActions),
      }),
    });
  }
  function stopAction() {
    return request("/api/actions/stop", {method: "POST", body: "{}"});
  }
  function resetAction() {
    return request("/api/actions/reset", {method: "POST", body: "{}"});
  }

  // ------------------------------------------------------------------
  // Action Mission
  // ------------------------------------------------------------------
  function getActionMissionStatus() {
    return request("/api/action-mission/status");
  }
  function getActionMissionTemplates() {
    return request("/api/action-mission/templates");
  }
  function getActionMissionTemplate(name) {
    return request("/api/action-mission/template/" + encodeURIComponent(name));
  }
  function configureActionMission(steps) {
    return request("/api/action-mission/configure", {
      method: "POST",
      body: JSON.stringify({steps: steps}),
    });
  }
  function startActionMission() {
    return request("/api/action-mission/start", {method: "POST", body: "{}"});
  }
  function stopActionMission() {
    return request("/api/action-mission/stop", {method: "POST", body: "{}"});
  }
  function resetActionMission() {
    return request("/api/action-mission/reset", {method: "POST", body: "{}"});
  }
  function tickActionMission() {
    return request("/api/action-mission/tick", {method: "POST", body: "{}"});
  }
  function skipCurrentActionMission() {
    return request("/api/action-mission/skip-current", {
      method: "POST",
      body: "{}",
    });
  }

  // ------------------------------------------------------------------
  // Field Heading (legacy)
  // ------------------------------------------------------------------

  function getFieldReferenceStatus() {
    return request("/api/field-reference/status");
  }
  function resetFieldReference() {
    return request("/api/field-reference/reset", {method: "POST", body: "{}"});
  }
  function freezeFieldReference() {
    return request("/api/field-reference/freeze", {method: "POST", body: "{}"});
  }

  // ------------------------------------------------------------------
  // Manual / Localization
  // ------------------------------------------------------------------
  function manualStepMove(direction, stepM) {
    return request("/api/manual-step-move", {
      method: "POST",
      body: JSON.stringify({direction: direction, step_m: stepM}),
    });
  }
  function clearLocalization() {
    return request("/api/localization/clear", {method: "POST", body: "{}"});
  }

  // ------------------------------------------------------------------
  // YOLO Stream
  // ------------------------------------------------------------------
  function getYoloStreamUrl() {
    return request("/api/yolo/stream");
  }

  // ------------------------------------------------------------------
  // Camera Recording
  // ------------------------------------------------------------------
  function getCameraRecordingStatus() {
    return request("/api/camera-recording/status");
  }
  function toggleCameraRecording() {
    return request("/api/camera-recording/toggle", {method: "POST", body: "{}"});
  }

  // ------------------------------------------------------------------
  // Config
  // ------------------------------------------------------------------
  function getConfigFiles() {
    return request("/api/config/files");
  }
  function getConfigFile(path) {
    return request("/api/config/file?path=" + encodeURIComponent(path));
  }
  function saveConfigFile(path, content, action) {
    return request("/api/config/file?path=" + encodeURIComponent(path), {
      method: "PUT",
      body: JSON.stringify({content: content, action: action}),
    });
  }
  function restoreConfigFile(path, action) {
    return request("/api/config/restore?path=" + encodeURIComponent(path) + "&action=" + encodeURIComponent(action || "save"), {method: "POST"});
  }

  // ------------------------------------------------------------------
  // Services
  // ------------------------------------------------------------------
  function reconnectTelemetry() {
    return request("/api/services/telemetry/reconnect", {method: "POST"});
  }
  function restartYolo() {
    return request("/api/services/yolo/restart", {method: "POST"});
  }
  function restartApp() {
    return request("/api/services/app/restart", {method: "POST"});
  }

  // ------------------------------------------------------------------
  // public API surface
  // ------------------------------------------------------------------
  return {
    request: request,

    getStatus: getStatus,
    getAudit: getAudit,
    getEvents: getEvents,
    getCommandCompletions: getCommandCompletions,
    executeCommand: executeCommand,

    getMissions: getMissions,

    listActions: listActions,
    getActionStatus: getActionStatus,
    startAction: startAction,
    stopAction: stopAction,
    resetAction: resetAction,

    getActionMissionStatus: getActionMissionStatus,
    getActionMissionTemplates: getActionMissionTemplates,
    getActionMissionTemplate: getActionMissionTemplate,
    configureActionMission: configureActionMission,
    startActionMission: startActionMission,
    stopActionMission: stopActionMission,
    resetActionMission: resetActionMission,
    tickActionMission: tickActionMission,
    skipCurrentActionMission: skipCurrentActionMission,


    getFieldReferenceStatus: getFieldReferenceStatus,
    resetFieldReference: resetFieldReference,
    freezeFieldReference: freezeFieldReference,

    manualStepMove: manualStepMove,
    clearLocalization: clearLocalization,

    getYoloStreamUrl: getYoloStreamUrl,

    getCameraRecordingStatus: getCameraRecordingStatus,
    toggleCameraRecording: toggleCameraRecording,

    getConfigFiles: getConfigFiles,
    getConfigFile: getConfigFile,
    saveConfigFile: saveConfigFile,
    restoreConfigFile: restoreConfigFile,

    reconnectTelemetry: reconnectTelemetry,
    restartYolo: restartYolo,
    restartApp: restartApp,
  };
})();
