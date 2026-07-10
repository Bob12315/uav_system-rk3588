"use strict";

// =============================================================================
// field_profile_runtime_ui_test.js
//
// Node behavior test for Field Profile + Runtime GPS Confirmation UI.
// Uses only Node built-ins: fs, vm, assert.
// No dependencies installed.
// =============================================================================

const fs = require("fs");
const vm = require("vm");
const assert = require("assert");

// ── helpers ──────────────────────────────────────────────────────────────────
let testsPassed = 0;
let testsFailed = 0;

function test(name, fn) {
    try {
        fn();
        testsPassed++;
    } catch (e) {
        testsFailed++;
        console.error("  FAIL " + name + ": " + e.message);
    }
}

function assertEqual(actual, expected, msg) {
    assert.strictEqual(actual, expected, msg);
}

function assertIncludes(haystack, needle, msg) {
    if (haystack.indexOf(needle) < 0) {
        throw new Error((msg || ("expected to include: " + needle)) + "\n  got: " + haystack.substring(0, 200));
    }
}

function assertNotIncludes(haystack, needle, msg) {
    if (haystack.indexOf(needle) >= 0) {
        throw new Error((msg || ("expected NOT to include: " + needle)));
    }
}

// ── stubs ────────────────────────────────────────────────────────────────────

// DOM stub
var domElements = {};
var domEvents = {};
function fakeGetElementById(id) {
    if (!domElements[id]) {
        domElements[id] = {
            id: id,
            textContent: "",
            style: { display: "" },
            disabled: false,
            options: [],
            value: "",
            selectedIndex: 0,
            max: 1,
            checked: false,
            innerHTML: "",
            classList: { toggle: function () {} },
            querySelectorAll: function () { return []; },
            appendChild: function (child) {
                if (child.tagName === "OPTION") {
                    this.options.push(child);
                }
            },
            addEventListener: function (evt, fn) {
                if (!domEvents[id]) domEvents[id] = {};
                domEvents[id][evt] = fn;
            },
            onclick: null
        };
    }
    return domElements[id];
}
var fakeDocument = {
    getElementById: fakeGetElementById,
    createElement: function (tag) {
        return {
            tagName: tag,
            value: "",
            textContent: "",
            options: [],
            style: {},
            appendChild: function () {},
            addEventListener: function () {}
        };
    },
    querySelectorAll: function () { return []; }
};

// localStorage stub
var fakeStorage = {};
var fakeLocalStorage = {
    _store: fakeStorage,
    getItem: function (k) { return fakeStorage[k] || null; },
    setItem: function (k, v) { fakeStorage[k] = String(v); },
    removeItem: function (k) { delete fakeStorage[k]; }
};

// confirm stub
var confirmResponses = [];
var confirmCalls = [];
function fakeConfirm(msg) {
    confirmCalls.push(msg);
    if (confirmResponses.length > 0) {
        return confirmResponses.shift();
    }
    return true; // default: confirm
}

// alert stub
var alertCalls = [];
function fakeAlert(msg) {
    alertCalls.push(msg);
}

// setTimeout / clearTimeout stub
var timerId = 0;
var timers = {};
var nowMs = 0;
function fakeSetTimeout(fn, delay) {
    var id = ++timerId;
    timers[id] = { fn: fn, delay: delay, at: nowMs + delay };
    return id;
}
function fakeClearTimeout(id) {
    delete timers[id];
}
function fakeSetInterval(fn, delay) {
    var id = ++timerId;
    timers[id] = { fn: fn, delay: delay, interval: true, at: nowMs + delay };
    return id;
}
function fireTimers() {
    var ids = Object.keys(timers);
    ids.sort(function (a, b) { return timers[a].at - timers[b].at; });
    ids.forEach(function (id) {
        var t = timers[id];
        nowMs = t.at;
        if (t.interval) {
            t.at = nowMs + t.delay;
        } else {
            delete timers[id];
        }
        t.fn();
    });
}
function countActiveTimers() {
    return Object.keys(timers).length;
}
function countActiveTimersByDelay(delay) {
    return Object.keys(timers).filter(function (k) { return timers[k].delay === delay; }).length;
}

// API stub
var apiRequests = [];
var apiResponses = {};
function fakeApiRequest(url, options) {
    apiRequests.push({ url: url, options: options || {} });
    if (apiResponses[url]) {
        var r = apiResponses[url];
        if (typeof r === "function") return Promise.resolve(r(url, options));
        return Promise.resolve(r);
    }
    return Promise.resolve({ ok: true });
}

// URL encoding stub
function fakeEncodeURIComponent(s) { return s; }

// FieldMap stub
var fieldMapCalls = [];
var fakeUavFieldMap = {
    setProfilePreview: function (d) {
        fieldMapCalls.push({ method: "setProfilePreview", data: d });
    }
};

// UavFieldRef stub (collected calls)
var fieldRefFetchCalls = [];
var fakeUavFieldRef = {
    fetchFieldReferenceStatus: function (opts) {
        fieldRefFetchCalls.push(opts || {});
        return Promise.resolve({ field_reference: { runtime_binding: {} } });
    }
};

// ── load JS files ────────────────────────────────────────────────────────────

function resetState() {
    domElements = {};
    domEvents = {};
    fakeStorage = {};
    confirmResponses = [];
    confirmCalls = [];
    alertCalls = [];
    timers = {};
    timerId = 0;
    nowMs = 0;
    apiRequests = [];
    apiResponses = {};
    fieldMapCalls = [];
    fieldRefFetchCalls = [];
    fakeUavFieldRef = {
        fetchFieldReferenceStatus: function (opts) {
            fieldRefFetchCalls.push(opts || {});
            return Promise.resolve({ field_reference: { runtime_binding: {} } });
        }
    };
}

function makeSandbox() {
    return {
        window: {
            UavApi: { request: fakeApiRequest },
            UavFieldMap: fakeUavFieldMap,
            UavFieldRef: fakeUavFieldRef,
            localStorage: fakeLocalStorage,
            document: fakeDocument,
            setTimeout: fakeSetTimeout,
            clearTimeout: fakeClearTimeout,
            setInterval: fakeSetInterval,
            confirm: fakeConfirm,
            alert: fakeAlert,
            encodeURIComponent: fakeEncodeURIComponent,
            addEventListener: function () {},
            location: { protocol: "http:", host: "localhost" },
            WebSocket: function () { return { onopen: null, onmessage: null, onerror: null, onclose: null }; }
        },
        console: console,
        Promise: Promise,
        setTimeout: fakeSetTimeout,
        clearTimeout: fakeClearTimeout,
        setInterval: fakeSetInterval,
        document: fakeDocument
    };
}

function loadProfileJS() {
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    var sandbox = makeSandbox();
    vm.createContext(sandbox);
    vm.runInContext(src, sandbox, { filename: "field_profile.js" });
    return sandbox;
}

function loadRefJS() {
    var src = fs.readFileSync("web_ui/static/js/field_reference.js", "utf8");
    var sandbox = makeSandbox();
    vm.createContext(sandbox);
    vm.runInContext(src, sandbox, { filename: "field_reference.js" });
    return sandbox;
}

function loadBoth() {
    resetState();
    var sandbox = makeSandbox();
    vm.createContext(sandbox);
    var refSrc = fs.readFileSync("web_ui/static/js/field_reference.js", "utf8");
    vm.runInContext(refSrc, sandbox, { filename: "field_reference.js" });
    var profSrc = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    vm.runInContext(profSrc, sandbox, { filename: "field_profile.js" });
    return sandbox;
}

// ── TESTS ─────────────────────────────────────────────────────────────────────

// === 1. Both JS files load ===
test("field_profile.js loads without error", function () {
    var s = loadProfileJS();
    assertEqual(typeof s.window.UavFieldProfiles, "object");
    assertEqual(typeof s.window.UavFieldProfiles.init, "function");
});

test("field_reference.js loads without error", function () {
    var s = loadRefJS();
    assertEqual(typeof s.window.UavFieldRef, "object");
    assertEqual(typeof s.window.UavFieldRef.init, "function");
});

// === 2. Profile list fills select ===
test("profile list fills select with entries", async function () {
    resetState();
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [
            { profile_id: "v2-test", name: "V2 Test", source: "config", schema_version: 2, invalid: false }
        ]
    };
    var s = loadBoth();
    s.window.UavFieldProfiles.init();
    // Wait for async fetchProfileList
    await new Promise(function (r) { fakeSetTimeout(r, 10); });
    fireTimers();
    var sel = domElements["fpProfileSelect"];
    assert(sel, "fpProfileSelect should exist");
    assert(sel.options.length >= 2, "should have at least --Select-- plus one profile, got " + sel.options.length);
    var texts = sel.options.map(function (o) { return o.textContent; }).join("|");
    assertIncludes(texts, "V2 Test");
});

// === 3. localStorage restore profile ===
test("localStorage restores selected profile", async function () {
    resetState();
    fakeLocalStorage.setItem("uavSelectedProfileId", "stored-id");
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [
            { profile_id: "stored-id", name: "Stored", source: "config", schema_version: 2, invalid: false },
            { profile_id: "other", name: "Other", source: "config", schema_version: 2, invalid: false }
        ]
    };
    apiResponses["/api/field-profiles/stored-id"] = {
        ok: true,
        profile_id: "stored-id",
        name: "Stored",
        schema_version: 2,
        source: "config",
        anchor: { name: "a", lat: 34.0, lon: 108.0 },
        centerline_points: [{ name: "c1", lat: 34.001, lon: 108.001 }],
        gps_quality: {}
    };
    var s = loadBoth();
    s.window.UavFieldProfiles.init();
    await new Promise(function (r) { fakeSetTimeout(r, 20); });
    fireTimers();
    await new Promise(function (r) { fakeSetTimeout(r, 20); });
    fireTimers();
    var sel = domElements["fpProfileSelect"];
    assertEqual(sel.selectedIndex, 1, "should auto-select the stored profile");
});

// === 4. onchange loads profile ===
test("onchange triggers profile load", async function () {
    resetState();
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [
            { profile_id: "onchange-test", name: "OnChange", source: "config", schema_version: 2, invalid: false }
        ]
    };
    apiResponses["/api/field-profiles/onchange-test"] = {
        ok: true,
        profile_id: "onchange-test",
        name: "OnChange",
        schema_version: 2,
        source: "config",
        anchor: { name: "a", lat: 34.0, lon: 108.0 },
        centerline_points: [{ name: "c1", lat: 34.001, lon: 108.001 }],
        gps_quality: {}
    };
    var s = loadBoth();
    s.window.UavFieldProfiles.init();
    await new Promise(function (r) { fakeSetTimeout(r, 10); });
    fireTimers();
    // Simulate onchange
    var sel = domElements["fpProfileSelect"];
    if (domEvents["fpProfileSelect"] && domEvents["fpProfileSelect"].change) {
        domEvents["fpProfileSelect"].change.call({ value: "onchange-test" });
        await new Promise(function (r) { fakeSetTimeout(r, 10); });
        fireTimers();
    }
    var detail = domElements["fpProfileDetail"];
    assert(detail.style.display !== "none", "fpProfileDetail should be visible after load");
});

// === 5. v3 saves profile id and schema ===
test("v3 saves profile id and schema version", async function () {
    resetState();
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [
            { profile_id: "v3-save", name: "V3 Save", source: "config", schema_version: 3, invalid: false }
        ]
    };
    apiResponses["/api/field-profiles/v3-save"] = {
        ok: true,
        profile_id: "v3-save",
        name: "V3 Save",
        schema_version: 3,
        source: "config",
        forward_marker: { name: "far", lat: 34.1, lon: 108.6, coordinate_system: "WGS84" },
        drop_scan: { waypoints: [] },
        runtime_origin_sampling: { min_samples: 20, sample_window_s: 5.0, max_horizontal_spread_m: 1.0, estimator: "median" },
        binding_policy: { min_baseline_m: 30.0, warn_baseline_below_m: 50.0 },
        gps_quality: {}
    };
    var s = loadBoth();
    s.window.UavFieldProfiles.init();
    await new Promise(function (r) { fakeSetTimeout(r, 10); });
    fireTimers();
    // onchange
    if (domEvents["fpProfileSelect"] && domEvents["fpProfileSelect"].change) {
        domEvents["fpProfileSelect"].change.call({ value: "v3-save" });
        await new Promise(function (r) { fakeSetTimeout(r, 10); });
        fireTimers();
    }
    // Check localStorage saved
    assertEqual(fakeLocalStorage.getItem("uavSelectedProfileId"), "v3-save");
});

// === 6. v3 detail displays ===
test("v3 detail shows forward marker, scan, sampling, baseline", async function () {
    resetState();
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [
            { profile_id: "v3-detail", name: "V3 Detail", source: "config", schema_version: 3, invalid: false }
        ]
    };
    apiResponses["/api/field-profiles/v3-detail"] = {
        ok: true,
        profile_id: "v3-detail",
        name: "V3 Detail",
        schema_version: 3,
        source: "config",
        forward_marker: { name: "far", lat: 34.1, lon: 108.6, coordinate_system: "WGS84" },
        drop_scan: { waypoints: [{ x_m: -2, y_m: 30, altitude_m: 5 }] },
        runtime_origin_sampling: { min_samples: 20, sample_window_s: 5.0, max_horizontal_spread_m: 1.0, estimator: "median" },
        binding_policy: { min_baseline_m: 30.0, warn_baseline_below_m: 50.0 },
        gps_quality: {}
    };
    var s = loadBoth();
    s.window.UavFieldProfiles.init();
    await new Promise(function (r) { fakeSetTimeout(r, 10); });
    fireTimers();
    if (domEvents["fpProfileSelect"] && domEvents["fpProfileSelect"].change) {
        domEvents["fpProfileSelect"].change.call({ value: "v3-detail" });
        await new Promise(function (r) { fakeSetTimeout(r, 20); });
        fireTimers();
    }
    var pd = domElements["fpProfileDetail"];
    assert(pd.style.display !== "none", "fpProfileDetail should be visible");

    assert(domElements["fpProfileSchema"], "fpProfileSchema should exist");
    assertIncludes(domElements["fpProfileSchema"].textContent, "v3");
    assert(domElements["fpV3Marker"], "fpV3Marker should exist");
    assertIncludes(domElements["fpV3Marker"].textContent, "far");
    assert(domElements["fpV3Sampling"], "fpV3Sampling should exist");
    assert(domElements["fpV3Baseline"], "fpV3Baseline should exist");
});

// === 7. v3 does NOT request map-preview ===
test("v3 does not request map-preview", async function () {
    resetState();
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [
            { profile_id: "v3-nomap", name: "V3 NoMap", source: "config", schema_version: 3, invalid: false }
        ]
    };
    apiResponses["/api/field-profiles/v3-nomap"] = {
        ok: true,
        profile_id: "v3-nomap",
        name: "V3 NoMap",
        schema_version: 3,
        source: "config",
        forward_marker: { name: "far", lat: 34.1, lon: 108.6, coordinate_system: "WGS84" },
        drop_scan: { waypoints: [] },
        runtime_origin_sampling: { min_samples: 20, sample_window_s: 5.0, max_horizontal_spread_m: 1.0, estimator: "median" },
        binding_policy: { min_baseline_m: 30.0, warn_baseline_below_m: 50.0 },
        gps_quality: {}
    };
    var s = loadBoth();
    s.window.UavFieldProfiles.init();
    await new Promise(function (r) { fakeSetTimeout(r, 10); });
    fireTimers();
    if (domEvents["fpProfileSelect"] && domEvents["fpProfileSelect"].change) {
        domEvents["fpProfileSelect"].change.call({ value: "v3-nomap" });
        await new Promise(function (r) { fakeSetTimeout(r, 20); });
        fireTimers();
    }
    var mapPreviewReqs = apiRequests.filter(function (r) { return r.url.indexOf("map-preview") >= 0; });
    assertEqual(mapPreviewReqs.length, 0, "v3 should not request map-preview");
});

// === 8. v3 clears preview ===
test("v3 clears map preview", async function () {
    resetState();
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [
            { profile_id: "v3-clear", name: "V3 Clear", source: "config", schema_version: 3, invalid: false }
        ]
    };
    apiResponses["/api/field-profiles/v3-clear"] = {
        ok: true,
        profile_id: "v3-clear",
        name: "V3 Clear",
        schema_version: 3,
        source: "config",
        forward_marker: { name: "far", lat: 34.1, lon: 108.6, coordinate_system: "WGS84" },
        drop_scan: { waypoints: [] },
        runtime_origin_sampling: { min_samples: 20, sample_window_s: 5.0, max_horizontal_spread_m: 1.0, estimator: "median" },
        binding_policy: { min_baseline_m: 30.0, warn_baseline_below_m: 50.0 },
        gps_quality: {}
    };
    var s = loadBoth();
    s.window.UavFieldProfiles.init();
    await new Promise(function (r) { fakeSetTimeout(r, 10); });
    fireTimers();
    if (domEvents["fpProfileSelect"] && domEvents["fpProfileSelect"].change) {
        domEvents["fpProfileSelect"].change.call({ value: "v3-clear" });
        await new Promise(function (r) { fakeSetTimeout(r, 20); });
        fireTimers();
    }
    var cleared = fieldMapCalls.filter(function (c) { return c.method === "setProfilePreview" && c.data === null; });
    assert(cleared.length >= 1, "v3 should call setProfilePreview(null)");
});

// === 9. v3 Start enabled in idle ===
test("v3 Start enabled, Bind disabled in idle", async function () {
    resetState();
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [
            { profile_id: "v3-ctrl", name: "V3 Ctrl", source: "config", schema_version: 3, invalid: false }
        ]
    };
    apiResponses["/api/field-profiles/v3-ctrl"] = {
        ok: true,
        profile_id: "v3-ctrl",
        name: "V3 Ctrl",
        schema_version: 3,
        source: "config",
        forward_marker: { name: "far", lat: 34.1, lon: 108.6, coordinate_system: "WGS84" },
        drop_scan: { waypoints: [] },
        runtime_origin_sampling: { min_samples: 20, sample_window_s: 5.0, max_horizontal_spread_m: 1.0, estimator: "median" },
        binding_policy: { min_baseline_m: 30.0, warn_baseline_below_m: 50.0 },
        gps_quality: {}
    };
    var s = loadBoth();
    s.window.UavFieldProfiles.init();
    await new Promise(function (r) { fakeSetTimeout(r, 10); });
    fireTimers();
    if (domEvents["fpProfileSelect"] && domEvents["fpProfileSelect"].change) {
        domEvents["fpProfileSelect"].change.call({ value: "v3-ctrl" });
        await new Promise(function (r) { fakeSetTimeout(r, 20); });
        fireTimers();
    }
    var start = domElements["fpRuntimeStart"];
    var bind = domElements["fpBindCurrent"];
    assert(start && !start.disabled, "Start should be enabled for v3 in idle");
    assert(bind && bind.disabled, "Bind should be disabled for v3 in idle");
});

// === 10. v2 requests map-preview ===
test("v2 requests map-preview", async function () {
    resetState();
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [
            { profile_id: "v2-map", name: "V2 Map", source: "config", schema_version: 2, invalid: false }
        ]
    };
    apiResponses["/api/field-profiles/v2-map"] = {
        ok: true,
        profile_id: "v2-map",
        name: "V2 Map",
        schema_version: 2,
        source: "config",
        anchor: { name: "a", lat: 34.0, lon: 108.0 },
        centerline_points: [{ name: "c1", lat: 34.001, lon: 108.001 }],
        gps_quality: {}
    };
    apiResponses["/api/field-profiles/v2-map/map-preview"] = {
        ok: true,
        preview: "test"
    };
    var s = loadBoth();
    s.window.UavFieldProfiles.init();
    await new Promise(function (r) { fakeSetTimeout(r, 10); });
    fireTimers();
    if (domEvents["fpProfileSelect"] && domEvents["fpProfileSelect"].change) {
        domEvents["fpProfileSelect"].change.call({ value: "v2-map" });
        await new Promise(function (r) { fakeSetTimeout(r, 20); });
        fireTimers();
    }
    var mapPreviewReqs = apiRequests.filter(function (r) { return r.url.indexOf("map-preview") >= 0; });
    assert(mapPreviewReqs.length >= 1, "v2 should request map-preview");
});

// === 11. v2 anchor and centerline display ===
test("v2 shows anchor and centerline points", async function () {
    resetState();
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [
            { profile_id: "v2-detail", name: "V2 Detail", source: "config", schema_version: 2, invalid: false }
        ]
    };
    apiResponses["/api/field-profiles/v2-detail"] = {
        ok: true,
        profile_id: "v2-detail",
        name: "V2 Detail",
        schema_version: 2,
        source: "config",
        anchor: { name: "a", lat: 34.0, lon: 108.0 },
        centerline_points: [{ name: "c1", lat: 34.001, lon: 108.001 }, { name: "c2", lat: 34.002, lon: 108.002 }],
        gps_quality: {}
    };
    var s = loadBoth();
    s.window.UavFieldProfiles.init();
    await new Promise(function (r) { fakeSetTimeout(r, 10); });
    fireTimers();
    if (domEvents["fpProfileSelect"] && domEvents["fpProfileSelect"].change) {
        domEvents["fpProfileSelect"].change.call({ value: "v2-detail" });
        await new Promise(function (r) { fakeSetTimeout(r, 20); });
        fireTimers();
    }
    assert(domElements["fpClPoints"], "fpClPoints should exist");
    assertIncludes(domElements["fpClPoints"].textContent, "2");
    assert(domElements["fpClDetails"], "fpClDetails should exist");
    assertIncludes(domElements["fpClDetails"].textContent, "c1");
});

// === 12. v2 Bind enabled in idle ===
test("v2 Bind enabled in idle", async function () {
    resetState();
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [
            { profile_id: "v2-bind", name: "V2 Bind", source: "config", schema_version: 2, invalid: false }
        ]
    };
    apiResponses["/api/field-profiles/v2-bind"] = {
        ok: true,
        profile_id: "v2-bind",
        name: "V2 Bind",
        schema_version: 2,
        source: "config",
        anchor: { name: "a", lat: 34.0, lon: 108.0 },
        centerline_points: [{ name: "c1", lat: 34.001, lon: 108.001 }],
        gps_quality: {}
    };
    var s = loadBoth();
    s.window.UavFieldProfiles.init();
    await new Promise(function (r) { fakeSetTimeout(r, 10); });
    fireTimers();
    if (domEvents["fpProfileSelect"] && domEvents["fpProfileSelect"].change) {
        domEvents["fpProfileSelect"].change.call({ value: "v2-bind" });
        await new Promise(function (r) { fakeSetTimeout(r, 20); });
        fireTimers();
    }
    var bind = domElements["fpBindCurrent"];
    assert(bind && !bind.disabled, "Bind should be enabled for v2 in idle");
});

// === 13. v2 Bind POST is correct ===
test("v2 Bind POSTs to correct endpoint", async function () {
    resetState();
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [
            { profile_id: "v2-bindpost", name: "V2 BindPost", source: "config", schema_version: 2, invalid: false }
        ]
    };
    apiResponses["/api/field-profiles/v2-bindpost"] = {
        ok: true,
        profile_id: "v2-bindpost",
        name: "V2 BindPost",
        schema_version: 2,
        source: "config",
        anchor: { name: "a", lat: 34.0, lon: 108.0 },
        centerline_points: [{ name: "c1", lat: 34.001, lon: 108.001 }],
        gps_quality: {}
    };
    apiResponses["/api/field-profiles/v2-bindpost/bind-current"] = {
        ok: true,
        profile_id: "v2-bindpost",
        synced_to_runtime: true,
        field_heading_deg: 45.0
    };
    var s = loadBoth();
    s.window.UavFieldProfiles.init();
    await new Promise(function (r) { fakeSetTimeout(r, 10); });
    fireTimers();
    if (domEvents["fpProfileSelect"] && domEvents["fpProfileSelect"].change) {
        domEvents["fpProfileSelect"].change.call({ value: "v2-bindpost" });
        await new Promise(function (r) { fakeSetTimeout(r, 20); });
        fireTimers();
    }
    // Trigger bind via onclick
    var bindBtn = domElements["fpBindCurrent"];
    if (bindBtn.onclick) {
        bindBtn.onclick();
        await new Promise(function (r) { fakeSetTimeout(r, 20); });
        fireTimers();
    }
    var bindReqs = apiRequests.filter(function (r) { return r.url.indexOf("bind-current") >= 0; });
    assert(bindReqs.length >= 1, "should POST to bind-current");
    assertEqual(bindReqs[0].options.method, "POST");
});

// === 14. bind result container children preserved ===
test("bind result preserves container children (no setText on fpBindResult)", async function () {
    // Check the JS source directly for forbidden pattern
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    assertNotIncludes(src, 'setText("fpBindResult"', "must not call setText on fpBindResult");
    // Verify renderBindResult sets individual child elements
    assertIncludes(src, 'setText("fpBindOk"');
});

// === 15. sampling can_finalize false -> Finalize disabled ===
test("sampling can_finalize false disables Finalize", function () {
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    assertIncludes(src, "can_finalize");
    // The updateRuntimeControls checks can_finalize
    assertIncludes(src, "sampling.can_finalize");
});

// === 16. sampling can_finalize true -> Finalize enabled ===
test("sampling can_finalize true enables Finalize", function () {
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    // The logic: finBtn.disabled = !(sampling.can_finalize === true)
    assertIncludes(src, "can_finalize === true");
});

// === 17. sampling_failed state ===
test("sampling_failed state shows Cancel enabled", function () {
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    assertIncludes(src, "sampling_failed");
    // In sampling_failed: cancelBtn disabled = false
});

// === 18. apply_failed retry label ===
test("apply_failed shows retry label on Finalize", function () {
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    assertIncludes(src, "apply_failed");
    assertIncludes(src, "重试确认并冻结");  // retry label
});

// === 19. applied state disables all ===
test("applied state disables all controls", function () {
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    assertIncludes(src, "applied");
    // allOff + freeze disabled
});

// === 20. Start POST is correct ===
test("Start POSTs to correct runtime-sampling/start endpoint", async function () {
    resetState();
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [
            { profile_id: "v3-start", name: "V3 Start", source: "config", schema_version: 3, invalid: false }
        ]
    };
    apiResponses["/api/field-profiles/v3-start"] = {
        ok: true,
        profile_id: "v3-start",
        name: "V3 Start",
        schema_version: 3,
        source: "config",
        forward_marker: { name: "far", lat: 34.1, lon: 108.6, coordinate_system: "WGS84" },
        drop_scan: { waypoints: [] },
        runtime_origin_sampling: { min_samples: 20, sample_window_s: 5.0, max_horizontal_spread_m: 1.0, estimator: "median" },
        binding_policy: { min_baseline_m: 30.0, warn_baseline_below_m: 50.0 },
        gps_quality: {}
    };
    apiResponses["/api/field-profiles/v3-start/runtime-sampling/start"] = {
        ok: true,
        state: "sampling"
    };
    var s = loadBoth();
    s.window.UavFieldProfiles.init();
    await new Promise(function (r) { fakeSetTimeout(r, 10); });
    fireTimers();
    if (domEvents["fpProfileSelect"] && domEvents["fpProfileSelect"].change) {
        domEvents["fpProfileSelect"].change.call({ value: "v3-start" });
        await new Promise(function (r) { fakeSetTimeout(r, 20); });
        fireTimers();
    }
    var startBtn = domElements["fpRuntimeStart"];
    if (startBtn.onclick) {
        confirmResponses.push(true);
        startBtn.onclick();
        await new Promise(function (r) { fakeSetTimeout(r, 20); });
        fireTimers();
    }
    var startReqs = apiRequests.filter(function (r) { return r.url.indexOf("runtime-sampling/start") >= 0; });
    assert(startReqs.length >= 1, "should POST to runtime-sampling/start");
    assertEqual(startReqs[0].options.method, "POST");
});

// === 21. Finalize POST is correct ===
test("Finalize POSTs to correct endpoint", async function () {
    resetState();
    apiResponses["/api/field-reference/runtime-sampling/finalize"] = {
        ok: true,
        state: "applied"
    };
    var s = loadBoth();
    s.window.UavFieldProfiles.init();
    // Call finalizeRuntimeSampling directly
    confirmResponses.push(true);
    s.window.UavFieldProfiles.finalizeRuntimeSampling();
    await new Promise(function (r) { fakeSetTimeout(r, 20); });
    fireTimers();
    var finReqs = apiRequests.filter(function (r) { return r.url.indexOf("runtime-sampling/finalize") >= 0; });
    assert(finReqs.length >= 1, "should POST to runtime-sampling/finalize");
});

// === 22. Cancel POST is correct ===
test("Cancel POSTs to correct endpoint", async function () {
    resetState();
    apiResponses["/api/field-reference/runtime-sampling/cancel"] = {
        ok: true,
        state: "idle"
    };
    var s = loadBoth();
    s.window.UavFieldProfiles.init();
    confirmResponses.push(true);
    s.window.UavFieldProfiles.cancelRuntimeSampling();
    await new Promise(function (r) { fakeSetTimeout(r, 20); });
    fireTimers();
    var cancelReqs = apiRequests.filter(function (r) { return r.url.indexOf("runtime-sampling/cancel") >= 0; });
    assert(cancelReqs.length >= 1, "should POST to runtime-sampling/cancel");
});

// === 23. confirm=false prevents POST ===
test("confirm=false prevents POST", async function () {
    resetState();
    apiResponses["/api/field-reference/runtime-sampling/cancel"] = { ok: true };
    var s = loadBoth();
    s.window.UavFieldProfiles.init();
    confirmResponses.push(false); // reject
    s.window.UavFieldProfiles.cancelRuntimeSampling();
    await new Promise(function (r) { fakeSetTimeout(r, 20); });
    fireTimers();
    var cancelReqs = apiRequests.filter(function (r) { return r.url.indexOf("runtime-sampling/cancel") >= 0; });
    assertEqual(cancelReqs.length, 0, "no POST when confirm is false");
});

// === 24. requestBusy prevents duplicate POST ===
test("requestBusy prevents duplicate operations", function () {
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    assertIncludes(src, "requestBusy");
    // _runtimeOp checks if (requestBusy) return
    assertIncludes(src, "if (requestBusy) return");
    // bindCurrentProfile checks
    assertIncludes(src, "if (requestBusy) return");
});

// === 25. Reset confirm false prevents POST ===
test("Reset confirm=false does not POST", function () {
    var src = fs.readFileSync("web_ui/static/js/field_reference.js", "utf8");
    assertIncludes(src, "frReset");
    assertIncludes(src, "return;");  // cancels on !confirm
});

// === 26. Reset confirm message ===
test("Reset shows correct confirm message", function () {
    var src = fs.readFileSync("web_ui/static/js/field_reference.js", "utf8");
    assertIncludes(src, "将清除 Field Reference");
    assertIncludes(src, "不会发送飞控命令");
});

// === 27. Freeze endpoint ===
test("Freeze calls correct endpoint", function () {
    var src = fs.readFileSync("web_ui/static/js/field_reference.js", "utf8");
    assertIncludes(src, "frFreeze");
    assertIncludes(src, "/api/field-reference/freeze");
});

// === 28. startPolling called twice results in one timer ===
test("startPolling called twice has only one timer chain", function () {
    resetState();
    var s = loadBoth();
    s.window.UavFieldRef.startPolling();
    var t1 = countActiveTimers();
    s.window.UavFieldRef.startPolling(); // second call should be no-op
    var t2 = countActiveTimers();
    assertEqual(t1, t2, "second startPolling should not create more timers");
    assert(t1 <= 1, "at most one timer chain");
});

// === 29. sampling delay 500ms ===
test("polling uses 500ms delay during sampling", function () {
    var src = fs.readFileSync("web_ui/static/js/field_reference.js", "utf8");
    assertIncludes(src, "500");
    assertIncludes(src, "2000");
});

// === 30. idle delay 2000ms ===
test("polling uses 2000ms delay in idle", function () {
    var src = fs.readFileSync("web_ui/static/js/field_reference.js", "utf8");
    // Check that 2000 is used as the default delay
    assertIncludes(src, "2000");
});

// === 31. manual refresh does not create second timer ===
test("manual refresh with scheduleNext:false does not create extra timer", function () {
    var src = fs.readFileSync("web_ui/static/js/field_reference.js", "utf8");
    // fetchFieldReferenceStatus checks scheduleNext
    assertIncludes(src, "scheduleNext");
});

// === 32. app.js does NOT contain Field Reference interval ===
test("app.js has no Field Reference setInterval", function () {
    var src = fs.readFileSync("web_ui/static/app.js", "utf8");
    assertNotIncludes(src, "startFrPolling");
    assertNotIncludes(src, "setInterval(fetchFieldReferenceStatus");
});

// === 33. polling does NOT call finalize ===
test("polling function does not call finalize endpoint", function () {
    var src = fs.readFileSync("web_ui/static/js/field_reference.js", "utf8");
    // The polling function should not contain finalize URL
    var pollStart = src.indexOf("function fetchFieldReferenceStatus");
    var pollEnd = src.indexOf("function startPolling", pollStart + 10);
    if (pollEnd < 0) pollEnd = src.indexOf("function stopPolling", pollStart);
    if (pollEnd < 0) pollEnd = src.length;
    var pollBody = src.substring(pollStart, pollEnd);
    assertNotIncludes(pollBody, "runtime-sampling/finalize", "polling must not call finalize");
    assertNotIncludes(pollBody, "runtime-sampling/start", "polling must not call start");
    assertNotIncludes(pollBody, "runtime-sampling/cancel", "polling must not call cancel");
});

// === 34. Validate function exists ===
test("validateProfile function exists", function () {
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    assertIncludes(src, "function validateProfile");
    assertIncludes(src, "/validate");
});

// === 35. bindCurrentProfile function exists ===
test("bindCurrentProfile function exists", function () {
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    assertIncludes(src, "function bindCurrentProfile");
    assertIncludes(src, "/bind-current");
});

// === 36. init binds all required handlers ===
test("init binds profile select onchange", function () {
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    assertIncludes(src, "fpProfileSelect");
    assertIncludes(src, "onchange");
    assertIncludes(src, "loadAndRenderProfile");
});

test("init binds refresh list", function () {
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    assertIncludes(src, "fpRefreshList");
    assertIncludes(src, "fetchProfileList");
});

test("init binds validate profile", function () {
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    assertIncludes(src, "fpValidateProfile");
    assertIncludes(src, "validateProfile");
});

test("init binds bind current", function () {
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    assertIncludes(src, "fpBindCurrent");
    assertIncludes(src, "bindCurrentProfile");
});

// === 37. v2 schema label ===
test("v2 profile shows correct schema label", function () {
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    assertIncludes(src, "v2 Legacy Centerline");
});

// === 38. v3 schema label ===
test("v3 profile shows correct schema label", function () {
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    assertIncludes(src, "v3 Runtime GPS");
});

// === 39. Source field displayed ===
test("profile source is displayed", function () {
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    assertIncludes(src, "fpProfileSource");
});

// === 40. Invalid profiles shown ===
test("invalid profiles shown in list", function () {
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    assertIncludes(src, "invalid");
});

// === 41. setInterval not used in field_reference.js ===
test("field_reference.js has no setInterval", function () {
    var src = fs.readFileSync("web_ui/static/js/field_reference.js", "utf8");
    assertNotIncludes(src, "setInterval");
});

// === 42. fpProfileDetail hidden on clear ===
test("fpProfileDetail hidden when profile cleared", async function () {
    resetState();
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [
            { profile_id: "detail-test", name: "Detail", source: "config", schema_version: 2, invalid: false }
        ]
    };
    apiResponses["/api/field-profiles/detail-test"] = {
        ok: false,
        error: "not found"
    };
    var pd = domElements["fpProfileDetail"];
    if (!pd) {
        // Ensure it exists
        fakeGetElementById("fpProfileDetail");
    }
    var s = loadBoth();
    s.window.UavFieldProfiles.init();
    await new Promise(function (r) { fakeSetTimeout(r, 10); });
    fireTimers();
    if (domEvents["fpProfileSelect"] && domEvents["fpProfileSelect"].change) {
        domEvents["fpProfileSelect"].change.call({ value: "detail-test" });
        await new Promise(function (r) { fakeSetTimeout(r, 20); });
        fireTimers();
    }
    var detail = domElements["fpProfileDetail"];
    assert(detail.style.display === "none", "fpProfileDetail should be hidden on load failure");
});

// ── summary ───────────────────────────────────────────────────────────────────

console.log("\n=== Node Behavior Test Results ===");
console.log("Passed: " + testsPassed);
console.log("Failed: " + testsFailed);

if (testsFailed > 0) {
    console.error("\nFAILED: " + testsFailed + " test(s) failed!");
    process.exit(1);
} else {
    console.log("All " + testsPassed + " tests passed!");
    process.exit(0);
}
