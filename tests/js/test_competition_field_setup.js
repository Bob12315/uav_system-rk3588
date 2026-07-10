"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const html = fs.readFileSync("web_ui/static/index.html", "utf8");
const realIds = new Set(Array.from(html.matchAll(/id="([^"]+)"/g), match => match[1]));
const tests = [];

function test(name, fn) { tests.push({name, fn}); }

function makeElement(id) {
  const listeners = Object.create(null);
  return {
    id,
    value: "",
    textContent: "",
    innerHTML: "",
    disabled: false,
    style: {display: ""},
    max: 1,
    options: [],
    listeners,
    addEventListener(type, handler) {
      (listeners[type] || (listeners[type] = [])).push(handler);
    },
    appendChild(child) { this.options.push(child); },
    remove(index) { this.options.splice(index, 1); },
    trigger(type) {
      return Promise.all((listeners[type] || []).map(handler => handler.call(this, {type, target: this})));
    },
  };
}

function makeHarness(options = {}) {
  const elements = new Map(Array.from(realIds, id => [id, makeElement(id)]));
  const requests = [];
  const alerts = [];
  const confirms = [];
  const timers = [];
  const windowListeners = Object.create(null);
  const handlers = new Map();
  let confirmResult = true;
  let timerId = 0;

  const defaultStatus = {
    field_reference: {
      is_frozen: false,
      is_confirmed: false,
      runtime_binding: {state: "idle", sampling: {}},
    },
    telemetry: {},
  };

  function nextResponse(url, requestOptions) {
    const configured = handlers.get(url);
    if (Array.isArray(configured)) {
      const next = configured.shift();
      return typeof next === "function" ? next(url, requestOptions) : next;
    }
    if (configured !== undefined) {
      return typeof configured === "function" ? configured(url, requestOptions) : configured;
    }
    if (url === "/api/field-reference/status") return defaultStatus;
    if (url === "/api/field-profiles/competition_runtime_v3") return {ok: false};
    return {ok: true};
  }

  const document = {
    getElementById(id) { return elements.get(id) || null; },
    createElement(tag) { return makeElement(tag.toUpperCase()); },
    querySelectorAll() { return []; },
  };
  const window = {
    document,
    UavApi: {
      request(url, requestOptions = {}) {
        requests.push({
          url,
          method: requestOptions.method || "GET",
          body: requestOptions.body,
        });
        try {
          return Promise.resolve(nextResponse(url, requestOptions));
        } catch (error) {
          return Promise.reject(error);
        }
      },
    },
    UavFieldMap: options.map || null,
    UavFieldRef: null,
    confirm(message) { confirms.push(message); return confirmResult; },
    addEventListener(type, handler) {
      (windowListeners[type] || (windowListeners[type] = [])).push(handler);
    },
    devicePixelRatio: 1,
  };
  const sandbox = {
    window,
    document,
    console,
    Promise,
    Math,
    JSON,
    Number,
    String,
    Object,
    Array,
    isFinite,
    encodeURIComponent,
    alert(message) { alerts.push(String(message)); },
    setTimeout(handler, delay) {
      const timer = {id: ++timerId, handler, delay, cleared: false};
      timers.push(timer);
      return timer.id;
    },
    clearTimeout(id) {
      const timer = timers.find(item => item.id === id);
      if (timer) timer.cleared = true;
    },
    requestAnimationFrame(handler) {
      const timer = {id: ++timerId, handler, delay: "animation", cleared: false};
      timers.push(timer);
      return timer.id;
    },
    $: id => document.getElementById(id),
    escapeHtml: value => String(value),
    num: value => String(value),
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);

  function load(path) {
    const source = fs.readFileSync(path, "utf8");
    vm.runInContext(source, sandbox, {filename: path});
  }
  load("web_ui/static/js/field_reference.js");
  load("web_ui/static/js/field_profile.js");

  return {
    sandbox,
    window,
    elements,
    requests,
    alerts,
    confirms,
    timers,
    handlers,
    setConfirm(value) { confirmResult = value; },
    element(id) {
      assert(realIds.has(id), `test requested non-existent DOM id ${id}`);
      return elements.get(id);
    },
    async settle() {
      for (let index = 0; index < 8; index += 1) await Promise.resolve();
    },
    loadMap() {
      load("web_ui/static/js/field_map.js");
      return window.UavFieldMap;
    },
  };
}

function status(state, options = {}) {
  return {
    field_reference: {
      is_frozen: Boolean(options.frozen),
      is_confirmed: state === "applied",
      runtime_binding: {
        state,
        sampling: {can_finalize: Boolean(options.canFinalize)},
        candidate_summary: options.candidateSummary || null,
      },
    },
    telemetry: {},
  };
}

function setCoordinates(harness, lat = "34.1234567", lon = "108.1234567") {
  harness.element("cfsForwardLat").value = lat;
  harness.element("cfsForwardLon").value = lon;
  return Promise.all([
    harness.element("cfsForwardLat").trigger("input"),
    harness.element("cfsForwardLon").trigger("input"),
  ]);
}

test("DOM mock never invents missing IDs and module load errors propagate", () => {
  const h = makeHarness();
  assert.strictEqual(h.sandbox.document.getElementById("not-in-index-html"), null);
  assert.ok(h.window.UavFieldProfiles);
  assert.ok(h.window.UavFieldRef);
});

test("empty input disables Start", async () => {
  const h = makeHarness();
  h.window.UavFieldProfiles.init();
  assert.strictEqual(h.element("cfsStart").disabled, true);
});

test("valid input enables Start", async () => {
  const h = makeHarness();
  h.window.UavFieldProfiles.init();
  await setCoordinates(h);
  assert.strictEqual(h.element("cfsStart").disabled, false);
});

test("invalid input disables Start", async () => {
  const h = makeHarness();
  h.window.UavFieldProfiles.init();
  await setCoordinates(h, "NaN", "108.0");
  assert.strictEqual(h.element("cfsStart").disabled, true);
});

test("Start confirm=false sends no request", async () => {
  const h = makeHarness();
  h.window.UavFieldProfiles.init();
  await setCoordinates(h);
  h.setConfirm(false);
  await h.element("cfsStart").trigger("click");
  await h.settle();
  assert.strictEqual(h.requests.filter(r => r.url.endsWith("runtime-sampling/start")).length, 0);
});

test("Start confirm=true sends exact POST JSON", async () => {
  const h = makeHarness();
  h.window.UavFieldProfiles.init();
  await setCoordinates(h);
  await h.element("cfsStart").trigger("click");
  await h.settle();
  const request = h.requests.find(r => r.url === "/api/field-reference/runtime-sampling/start");
  assert.deepStrictEqual(request, {
    url: "/api/field-reference/runtime-sampling/start",
    method: "POST",
    body: JSON.stringify({forward_marker_lat: 34.1234567, forward_marker_lon: 108.1234567}),
  });
});

for (const stateName of ["sampling", "sampling_failed"]) {
  test(`${stateName} locks B inputs`, async () => {
    const h = makeHarness();
    h.window.UavFieldProfiles.init();
    await setCoordinates(h);
    h.window.UavFieldProfiles.onFieldReferenceStatus(status(stateName));
    assert.strictEqual(h.element("cfsForwardLat").disabled, true);
    assert.strictEqual(h.element("cfsForwardLon").disabled, true);
  });
}

test("apply_failed exposes retry Finalize", () => {
  const h = makeHarness();
  h.window.UavFieldProfiles.init();
  h.window.UavFieldProfiles.onFieldReferenceStatus(status("apply_failed"));
  assert.strictEqual(h.element("cfsFinalize").disabled, false);
  assert.strictEqual(h.element("cfsFinalize").textContent, "重试确认并冻结");
});

test("applied enables only Reset", () => {
  const h = makeHarness();
  h.window.UavFieldProfiles.init();
  h.window.UavFieldProfiles.onFieldReferenceStatus(status("applied"));
  for (const id of ["cfsStart", "cfsFinalize", "cfsCancel"]) {
    assert.strictEqual(h.element(id).disabled, true);
  }
  assert.strictEqual(h.element("cfsReset").disabled, false);
});

for (const code of [409, 400]) {
  test(`HTTP ${code} alerts and preserves B`, async () => {
    const h = makeHarness();
    h.window.UavFieldProfiles.init();
    await setCoordinates(h);
    h.handlers.set("/api/field-reference/runtime-sampling/start", () => {
      throw new Error(`${code} lifecycle error`);
    });
    await h.element("cfsStart").trigger("click");
    await h.settle();
    assert.ok(h.alerts.some(message => message.includes(`${code} lifecycle error`)));
    assert.strictEqual(h.element("cfsForwardLat").value, "34.1234567");
    assert.strictEqual(h.element("cfsForwardLon").value, "108.1234567");
    assert.ok(h.requests.some(request => request.url === "/api/field-reference/status"));
  });
}

test("Reset ok=false preserves B", async () => {
  const h = makeHarness();
  h.window.UavFieldProfiles.init();
  await setCoordinates(h);
  h.handlers.set("/api/field-reference/reset", {ok: false, error: "reset rejected"});
  await h.element("cfsReset").trigger("click");
  await h.settle();
  assert.strictEqual(h.element("cfsForwardLat").value, "34.1234567");
  assert.ok(h.alerts.includes("reset rejected"));
});

test("Reset rejection preserves B", async () => {
  const h = makeHarness();
  h.window.UavFieldProfiles.init();
  await setCoordinates(h);
  h.handlers.set("/api/field-reference/reset", () => { throw new Error("network down"); });
  await h.element("cfsReset").trigger("click");
  await h.settle();
  assert.strictEqual(h.element("cfsForwardLon").value, "108.1234567");
  assert.ok(h.alerts.some(message => message.includes("network down")));
});

test("repeated init does not bind twice or add a second polling chain", async () => {
  const h = makeHarness();
  h.window.UavFieldProfiles.init();
  h.window.UavFieldProfiles.init();
  h.window.UavFieldRef.init();
  h.window.UavFieldRef.init();
  await h.settle();
  assert.strictEqual(h.element("cfsStart").listeners.click.length, 1);
  assert.strictEqual(h.requests.filter(r => r.url === "/api/field-reference/status").length, 1);
  assert.strictEqual(h.timers.filter(timer => timer.delay === 2000 && !timer.cleared).length, 1);
});

test("sampling polling uses 500ms and other states use 2000ms", async () => {
  const samplingHarness = makeHarness();
  samplingHarness.handlers.set("/api/field-reference/status", status("sampling"));
  samplingHarness.window.UavFieldRef.init();
  await samplingHarness.settle();
  assert.ok(samplingHarness.timers.some(timer => timer.delay === 500));

  const idleHarness = makeHarness();
  idleHarness.window.UavFieldRef.init();
  await idleHarness.settle();
  assert.ok(idleHarness.timers.some(timer => timer.delay === 2000));
});

test("pollInFlight prevents concurrent requests", async () => {
  const h = makeHarness();
  let resolveStatus;
  h.handlers.set("/api/field-reference/status", () => new Promise(resolve => { resolveStatus = resolve; }));
  const first = h.window.UavFieldRef.fetchFieldReferenceStatus({scheduleNext: false});
  const second = await h.window.UavFieldRef.fetchFieldReferenceStatus({scheduleNext: false});
  assert.strictEqual(second, null);
  assert.strictEqual(h.requests.filter(r => r.url === "/api/field-reference/status").length, 1);
  resolveStatus(status("idle"));
  await first;
});

function runtimeGeometry() {
  const point = (name, x, y, altitude = 0) => ({
    name, field_x_m: x, field_y_m: y, altitude_m: altitude,
    lat: 34 + y / 100000, lon: 108 + x / 100000,
  });
  return {
    home: point("HOME", 0, 0),
    forward_marker: point("runtime_forward_marker", 0, 50),
    drop_scan_waypoints: [1, 2, 3, 4].map(i => point(`DROP_SCAN_${i}`, i, 30 + i, 5)),
    drop_area_corners: [1, 2, 3, 4].map(i => point(`D${i}`, i, 35 + i)),
    recce_area_corners: [1, 2, 3, 4].map(i => point(`R${i}`, i, 55 + i)),
    heading: {yaw_rad: 0.2, degrees: 11.46},
    baseline: 50,
  };
}

test("HOME/B/SCAN1-4/D1-4/R1-4 enter the real drawing and info paths", () => {
  const h = makeHarness();
  const map = h.loadMap();
  map.setRuntimeGeometry(runtimeGeometry(), false);
  const model = map.fieldMapModel({});
  model.rect = {width: 800, height: 600};
  const drawnText = [];
  const ctx = {
    beginPath() {}, arc() {}, fill() {}, stroke() {},
    fillText(text) { drawnText.push(text); },
  };
  const labels = map.drawRuntimeGeometryPoints(ctx, model);
  assert.deepStrictEqual(Array.from(labels), [
    "HOME / A", "B / Forward Marker", "SCAN1", "SCAN2", "SCAN3", "SCAN4",
    "D1", "D2", "D3", "D4", "R1", "R2", "R3", "R4",
  ]);
  assert.deepStrictEqual(drawnText, Array.from(labels));
  assert.deepStrictEqual(Array.from(model.profilePreview.boxes, box => box.kind), ["drop_area", "recce_area"]);
  map.renderFieldMapInfoBox(model);
  const info = h.element("fieldMapInfoBox").innerHTML;
  for (const token of ["UNCONFIRMED", "A GPS", "B GPS", "baseline", "heading", "SCAN1", "SCAN4", "D1", "D4", "R1", "R4", "altitude="]) {
    assert.ok(info.includes(token), `missing ${token} from runtime geometry info`);
  }
  map.setRuntimeGeometry(runtimeGeometry(), true);
  const confirmedModel = map.fieldMapModel({});
  confirmedModel.rect = model.rect;
  map.renderFieldMapInfoBox(confirmedModel);
  assert.ok(h.element("fieldMapInfoBox").innerHTML.includes("CONFIRMED / FROZEN"));
});

(async () => {
  let failed = 0;
  for (const entry of tests) {
    try {
      await entry.fn();
      console.log(`PASS ${entry.name}`);
    } catch (error) {
      failed += 1;
      console.error(`FAIL ${entry.name}: ${error.stack || error}`);
    }
  }
  console.log(`\n${tests.length - failed} passed, ${failed} failed (${tests.length} total)`);
  if (!failed) console.log(`All ${tests.length} tests passed!`);
  process.exitCode = failed ? 1 : 0;
})();
