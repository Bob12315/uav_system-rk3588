"use strict";

// =============================================================================
// field_profile_runtime_ui_test.js
//
// Node behavior test for Field Profile + Runtime GPS Confirmation UI.
// Step 6.5.1 — async-aware runner, proper timer flush, real handler dispatch.
// Uses only Node built-ins: fs, vm, assert. No dependencies. Node 12+.
// =============================================================================

var fs = require("fs");
var vm = require("vm");
var assert = require("assert");

// ── async-aware test runner ──────────────────────────────────────────────────
var testDefs = [];
var testsPassed = 0;
var testsFailed = 0;

function test(name, fn) {
    testDefs.push({ name: name, fn: fn });
}

// ── assertions ───────────────────────────────────────────────────────────────
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

function assertOk(value, msg) {
    if (!value) throw new Error(msg || "expected truthy");
}

// ── microtask / timer primitives (no deadlock, Node 12 safe) ─────────────────

// Queue of pending microtask resolvers
var _microResolvers = [];

function _queueMicro(fn) {
    // Use Promise to schedule a microtask in Node 12+
    Promise.resolve().then(fn);
}

function flushPromises() {
    // Pump the microtask queue until drained.
    // We schedule a sentinel and flush everything before it.
    return new Promise(function (resolve) {
        _queueMicro(function () {
            // Keep pumping until the microtask queue is empty
            var count = 0;
            function pump() {
                // Schedule another microtask — if nothing new was enqueued,
                // we'll get here immediately after any pending ones.
                _queueMicro(function () {
                    count++;
                    if (count < 10) {
                        pump();
                    } else {
                        resolve();
                    }
                });
            }
            pump();
        });
    });
}

function delay(ms) {
    // Returns a promise that resolves after flushing microtasks.
    // The fake timer system doesn't advance real time;
    // use runTimersAndFlush for actual async progression.
    return flushPromises();
}

// ── stubs ────────────────────────────────────────────────────────────────────

var domElements = {};
var domEventListeners = {}; // id -> { eventName: [fn, ...] }

function fakeGetElementById(id) {
    if (!domElements[id]) {
        domElements[id] = {
            id: id,
            tagName: id === "fpProfileSelect" ? "SELECT" : "DIV",
            textContent: "",
            style: { display: "" },
            disabled: false,
            _options: [],
            value: "",
            _selectedIndex: 0,
            max: 1,
            checked: false,
            innerHTML: "",
            classList: {
                _classes: [],
                toggle: function (c) {
                    var idx = this._classes.indexOf(c);
                    if (idx >= 0) { this._classes.splice(idx, 1); }
                    else { this._classes.push(c); }
                }
            },
            querySelectorAll: function () { return []; },
            appendChild: function (child) {
                if (child.tagName === "OPTION") {
                    this._options.push(child);
                }
            },
            remove: function (index) {
                if (index >= 0 && index < this._options.length) {
                    this._options.splice(index, 1);
                }
            },
            addEventListener: function (evt, fn) {
                if (!domEventListeners[id]) domEventListeners[id] = {};
                if (!domEventListeners[id][evt]) domEventListeners[id][evt] = [];
                domEventListeners[id][evt].push(fn);
            },
            onclick: null,
            onchange: null
        };
        // Getters must be defined after object creation for 'options' and 'selectedIndex'
        Object.defineProperty(domElements[id], "options", {
            get: function () { return this._options; },
            enumerable: true, configurable: true
        });
        Object.defineProperty(domElements[id], "selectedIndex", {
            get: function () { return this._selectedIndex; },
            set: function (v) {
                this._selectedIndex = v;
                if (v > 0 && v < this._options.length) {
                    this.value = this._options[v].value || "";
                }
            },
            enumerable: true, configurable: true
        });
    }
    return domElements[id];
}

function dispatchEvent(id, eventName) {
    // Fire real registered handlers: onclick/onchange property first, then listeners
    var el = domElements[id];
    if (!el) return;
    // Property handler
    if (eventName === "click" && typeof el.onclick === "function") {
        el.onclick.call(el);
    }
    if (eventName === "change" && typeof el.onchange === "function") {
        el.onchange.call(el);
    }
    // addEventListener handlers
    var listeners = (domEventListeners[id] || {})[eventName];
    if (listeners) {
        listeners.forEach(function (fn) { fn.call(el); });
    }
}

var fakeDocument = {
    getElementById: fakeGetElementById,
    createElement: function (tag) {
        var upper = tag.toUpperCase();
        return {
            tagName: upper,
            value: "",
            textContent: "",
            options: [],
            style: {},
            appendChild: function () {},
            addEventListener: function () {},
            remove: function () {}
        };
    },
    querySelectorAll: function () { return []; }
};

// localStorage
var fakeStorage = {};
var fakeLocalStorage = {
    getItem: function (k) { return fakeStorage[k] || null; },
    setItem: function (k, v) { fakeStorage[k] = String(v); },
    removeItem: function (k) { delete fakeStorage[k]; }
};

// confirm (also available as global for bare calls)
var confirmResponses = [];
var confirmCalls = [];
function fakeConfirm(msg) {
    confirmCalls.push(msg);
    if (confirmResponses.length > 0) {
        return confirmResponses.shift();
    }
    return true;
}
// bare global confirm
var confirm = fakeConfirm;

// alert (also available as global for bare calls)
var alertCalls = [];
function fakeAlert(msg) {
    alertCalls.push(msg);
}
var alert = fakeAlert;

// Timer stubs — queue + fire, no real time
var _timerId = 0;
var _timerQueue = []; // { id, fn, at }
function fakeSetTimeout(fn, delayMs) {
    var id = ++_timerId;
    _timerQueue.push({ id: id, fn: fn, at: delayMs });
    return id;
}
function fakeClearTimeout(id) {
    for (var i = _timerQueue.length - 1; i >= 0; i--) {
        if (_timerQueue[i].id === id) { _timerQueue.splice(i, 1); break; }
    }
}
function fakeSetInterval(fn, delayMs) {
    // Not needed for field_profile/ref tests but must exist
    return fakeSetTimeout(fn, delayMs);
}
function countPendingTimers() {
    return _timerQueue.length;
}
function runAllTimers() {
    // Sort by at-time (FIFO approximation) and run all
    _timerQueue.sort(function (a, b) { return a.at - b.at; });
    while (_timerQueue.length > 0) {
        var t = _timerQueue.shift();
        try { t.fn(); } catch (e) { /* ignore timer errors */ }
    }
}
function runNextTimer() {
    if (_timerQueue.length === 0) return;
    _timerQueue.sort(function (a, b) { return a.at - b.at; });
    var t = _timerQueue.shift();
    try { t.fn(); } catch (e) { /* ignore */ }
}
function runTimersAndFlush() {
    // Run all timers, then flush microtasks — the standard "advance one async cycle"
    runAllTimers();
    return flushPromises();
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

function fakeEncodeURIComponent(s) { return s; }

// FieldMap stub
var fieldMapCalls = [];
var fakeUavFieldMap = {
    setProfilePreview: function (d) {
        fieldMapCalls.push({ method: "setProfilePreview", data: d });
    }
};

// UavFieldRef stub
var fieldRefFetchCalls = [];
var fakeUavFieldRef = {
    fetchFieldReferenceStatus: function (opts) {
        fieldRefFetchCalls.push(opts || {});
        return Promise.resolve({ field_reference: { runtime_binding: {} } });
    }
};

// ── state reset ──────────────────────────────────────────────────────────────
function resetAllState() {
    domElements = {};
    domEventListeners = {};
    // fakeStorage preserved (localStorage survives resets)
    confirmResponses = [];
    confirmCalls = [];
    alertCalls = [];
    _timerQueue = [];
    _timerId = 0;
    apiRequests = [];
    // apiResponses preserved across tests (not reset)
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
            WebSocket: function () {
                return { onopen: null, onmessage: null, onerror: null, onclose: null };
            }
        },
        console: console,
        Promise: Promise,
        setTimeout: fakeSetTimeout,
        clearTimeout: fakeClearTimeout,
        setInterval: fakeSetInterval,
        document: fakeDocument,
        alert: fakeAlert,
        confirm: fakeConfirm
    };
}

function loadBoth() {
    resetAllState();
    var sandbox = makeSandbox();
    vm.createContext(sandbox);
    var refSrc = fs.readFileSync("web_ui/static/js/field_reference.js", "utf8");
    vm.runInContext(refSrc, sandbox, { filename: "field_reference.js" });
    var profSrc = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    vm.runInContext(profSrc, sandbox, { filename: "field_profile.js" });
    return sandbox;
}

function loadProfileOnly() {
    resetAllState();
    var sandbox = makeSandbox();
    vm.createContext(sandbox);
    var profSrc = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    vm.runInContext(profSrc, sandbox, { filename: "field_profile.js" });
    return sandbox;
}

// ── helper: wait for profile init + list fetch to complete ───────────────────
async function initAndSettle(s) {
    s.window.UavFieldProfiles.init();
    // init calls fetchProfileList() which is async. We need to run timers to
    // flush the fake setTimeout used by Promise resolution, then flush microtasks.
    await runTimersAndFlush();
}

// ── helper: load a profile by dispatching onchange ───────────────────────────
async function selectProfile(profileId) {
    // Set up list response first
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [createProfileEntry(profileId)]
    };
    // Load a sandbox and init
    var s = loadBoth();
    await initAndSettle(s);

    // Now dispatch onchange on the select element
    var sel = domElements["fpProfileSelect"];
    sel.value = profileId;
    sel.selectedIndex = 1; // first non-placeholder option
    dispatchEvent("fpProfileSelect", "change");

    // Run timers to handle the async loadAndRenderProfile
    await runTimersAndFlush();
    return s;
}

function createProfileEntry(profileId, schemaVersion, name) {
    return {
        profile_id: profileId,
        name: name || profileId,
        source: "config",
        schema_version: schemaVersion || 2,
        invalid: false
    };
}

// ── v2 profile data ──────────────────────────────────────────────────────────
function v2ProfileData() {
    return {
        ok: true,
        profile_id: "v2-test",
        name: "V2 Test Profile",
        schema_version: 2,
        source: "config",
        anchor: { name: "anchor1", lat: 34.1234567, lon: 108.9876543 },
        centerline_points: [
            { name: "c1", lat: 34.124, lon: 108.988 },
            { name: "c2", lat: 34.125, lon: 108.989 }
        ],
        gps_quality: { min_fix_type: 3, min_satellites: 10, max_eph: 2.5, max_epv: 5.0 }
    };
}

// ── v3 profile data ──────────────────────────────────────────────────────────
function v3ProfileData() {
    return {
        ok: true,
        profile_id: "v3-test",
        name: "V3 Test Profile",
        schema_version: 3,
        source: "config",
        forward_marker: { name: "far", lat: 34.104189, lon: 108.642674, coordinate_system: "WGS84" },
        drop_scan: {
            waypoints: [
                { x_m: -2.0, y_m: 31.25, altitude_m: 5.0 },
                { x_m: 2.0, y_m: 31.25, altitude_m: 5.0 },
                { x_m: 2.0, y_m: 33.75, altitude_m: 5.0 },
                { x_m: -2.0, y_m: 33.75, altitude_m: 5.0 }
            ]
        },
        field_geometry: {
            lane_half_width_m: 4.0,
            drop_area_y_min_m: 30.0, drop_area_y_max_m: 35.0,
            recce_area_y_min_m: 55.0, recce_area_y_max_m: 60.0
        },
        runtime_origin_sampling: {
            min_samples: 20, sample_window_s: 5.0,
            max_horizontal_spread_m: 1.0, estimator: "median"
        },
        binding_policy: {
            min_baseline_m: 30.0, warn_baseline_below_m: 50.0
        },
        gps_quality: { min_fix_type: 3, min_satellites: 10, max_eph: 2.5, max_epv: 5.0 }
    };
}

// ═══════════════════════════════════════════════════════════════════════════════
// TESTS
// ═══════════════════════════════════════════════════════════════════════════════

// ── 1. Module loading ────────────────────────────────────────────────────────
test("both JS files load without error", function () {
    var s = loadBoth();
    assertOk(s.window.UavFieldProfiles, "UavFieldProfiles missing");
    assertOk(s.window.UavFieldRef, "UavFieldRef missing");
    assertEqual(typeof s.window.UavFieldProfiles.init, "function");
    assertEqual(typeof s.window.UavFieldRef.init, "function");
});

test("profile module exports all methods", function () {
    var s = loadProfileOnly();
    var m = s.window.UavFieldProfiles;
    assertEqual(typeof m.init, "function");
    assertEqual(typeof m.fetchProfileList, "function");
    assertEqual(typeof m.loadAndRenderProfile, "function");
    assertEqual(typeof m.onFieldReferenceStatus, "function");
    assertEqual(typeof m.startRuntimeSampling, "function");
    assertEqual(typeof m.finalizeRuntimeSampling, "function");
    assertEqual(typeof m.cancelRuntimeSampling, "function");
    assertEqual(typeof m.updateRuntimeControls, "function");
    assertEqual(typeof m.getRuntimeUiState, "function");
});

// ── 2. Profile list populates select ─────────────────────────────────────────
test("profile list fills select with entries", async function () {
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [
            createProfileEntry("p1", 2, "Profile One"),
            createProfileEntry("p2", 3, "Profile Two")
        ]
    };
    var s = loadBoth();
    await initAndSettle(s);

    var sel = domElements["fpProfileSelect"];
    assertOk(sel, "fpProfileSelect should exist");
    // Should have --Select-- + 2 profiles = 3 options
    assertEqual(sel.options.length, 3);
    var texts = sel.options.map(function (o) { return o.textContent; }).join("|");
    assertIncludes(texts, "Profile One");
    assertIncludes(texts, "Profile Two");
});

test("profile list shows source, id, invalid markers", async function () {
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [
            { profile_id: "bad", name: "Bad", source: "manual", schema_version: 2, invalid: true }
        ]
    };
    var s = loadBoth();
    await initAndSettle(s);
    var texts = domElements["fpProfileSelect"].options.map(function (o) { return o.textContent; }).join("|");
    assertIncludes(texts, "[manual]");
    assertIncludes(texts, "bad");
    assertIncludes(texts, "(invalid)");
});

// ── 3. localStorage restore ──────────────────────────────────────────────────
test("localStorage restores selected profile on init", async function () {
    fakeLocalStorage.setItem("uavSelectedProfileId", "saved-prof");
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [
            createProfileEntry("saved-prof", 2, "Saved Profile"),
            createProfileEntry("other", 2, "Other")
        ]
    };
    apiResponses["/api/field-profiles/saved-prof"] = v2ProfileData();

    var s = loadBoth();
    await initAndSettle(s);
    // After init, fetchProfileList runs, renders, then restoreSelectedProfile
    // triggers loadAndRenderProfile. Need another timer cycle.
    await runTimersAndFlush();

    var sel = domElements["fpProfileSelect"];
    assertEqual(sel.selectedIndex, 1, "should auto-select the saved profile");
    assertIncludes(sel.options[1].textContent, "Saved Profile");
});

// ── 4. Real onchange triggers profile load ───────────────────────────────────
test("onchange dispatches to loadAndRenderProfile", async function () {
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [createProfileEntry("oc-test", 2, "OnChange")]
    };
    apiResponses["/api/field-profiles/oc-test"] = v2ProfileData();

    var s = loadBoth();
    await initAndSettle(s);

    // Select via dispatch
    var sel = domElements["fpProfileSelect"];
    sel.value = "oc-test";
    sel.selectedIndex = 1;
    dispatchEvent("fpProfileSelect", "change");
    await runTimersAndFlush();

    var pd = domElements["fpProfileDetail"];
    assertOk(pd.style.display !== "none", "fpProfileDetail should be visible");
    assertIncludes(domElements["fpProfileId"].textContent, "v2-test");
});

// ── 5. v2 detail: anchor shows lat AND lon ───────────────────────────────────
test("v2 fpOriginLatLon shows both latitude and longitude", async function () {
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [createProfileEntry("v2-anchor", 2, "V2 Anchor")]
    };
    var d = v2ProfileData();
    d.profile_id = "v2-anchor";
    d.name = "V2 Anchor";
    apiResponses["/api/field-profiles/v2-anchor"] = d;

    var s = loadBoth();
    await initAndSettle(s);
    dispatchEvent("fpProfileSelect", "change");
    var sel = domElements["fpProfileSelect"];
    sel.value = "v2-anchor";
    sel.selectedIndex = 1;
    dispatchEvent("fpProfileSelect", "change");
    await runTimersAndFlush();

    var txt = domElements["fpOriginLatLon"].textContent;
    assertIncludes(txt, "34.12345");
    assertIncludes(txt, "108.98765");
    // The gps2 format is "lat, lon"
    assertIncludes(txt, ",");
});

test("v2 shows centerline points and requests map-preview", async function () {
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [createProfileEntry("v2-cl", 2, "V2 CL")]
    };
    var d = v2ProfileData();
    d.profile_id = "v2-cl";
    apiResponses["/api/field-profiles/v2-cl"] = d;
    apiResponses["/api/field-profiles/v2-cl/map-preview"] = { ok: true };

    var s = loadBoth();
    await initAndSettle(s);
    var sel = domElements["fpProfileSelect"];
    sel.value = "v2-cl";
    sel.selectedIndex = 1;
    dispatchEvent("fpProfileSelect", "change");
    await runTimersAndFlush();

    assertIncludes(domElements["fpClPoints"].textContent, "2 pts");
    assertIncludes(domElements["fpClDetails"].textContent, "c1");
    // map-preview should have been requested
    var mapReqs = apiRequests.filter(function (r) { return r.url.indexOf("map-preview") >= 0; });
    assertOk(mapReqs.length >= 1, "v2 should request map-preview");
});

// ── 6. v3 detail: field_geometry displayed ───────────────────────────────────
test("v3 shows field_geometry", async function () {
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [createProfileEntry("v3-geo", 3, "V3 Geo")]
    };
    var d = v3ProfileData();
    d.profile_id = "v3-geo";
    apiResponses["/api/field-profiles/v3-geo"] = d;

    var s = loadBoth();
    await initAndSettle(s);
    var sel = domElements["fpProfileSelect"];
    sel.value = "v3-geo";
    sel.selectedIndex = 1;
    dispatchEvent("fpProfileSelect", "change");
    await runTimersAndFlush();

    var geoText = domElements["fpV3Geometry"].textContent;
    assertIncludes(geoText, "lane=4");
    assertIncludes(geoText, "4");
    assertIncludes(geoText, "drop_y=30");
    assertIncludes(geoText, "recce_y=55");

    var markerText = domElements["fpV3Marker"].textContent;
    assertIncludes(markerText, "far");
    assertIncludes(markerText, "WGS84");

    var sampText = domElements["fpV3Sampling"].textContent;
    assertIncludes(sampText, "20 samples");
    assertIncludes(sampText, "median");
});

test("v3 does not request map-preview", async function () {
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [createProfileEntry("v3-nomap", 3, "V3 NoMap")]
    };
    apiResponses["/api/field-profiles/v3-nomap"] = v3ProfileData();

    var s = loadBoth();
    await initAndSettle(s);
    var sel = domElements["fpProfileSelect"];
    sel.value = "v3-nomap";
    sel.selectedIndex = 1;
    dispatchEvent("fpProfileSelect", "change");
    await runTimersAndFlush();

    var mapReqs = apiRequests.filter(function (r) { return r.url.indexOf("map-preview") >= 0; });
    assertEqual(mapReqs.length, 0, "v3 should not request map-preview");
});

test("v3 clears map preview", async function () {
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [createProfileEntry("v3-clear", 3, "V3 Clear")]
    };
    apiResponses["/api/field-profiles/v3-clear"] = v3ProfileData();

    var s = loadBoth();
    await initAndSettle(s);
    var sel = domElements["fpProfileSelect"];
    sel.value = "v3-clear";
    sel.selectedIndex = 1;
    dispatchEvent("fpProfileSelect", "change");
    await runTimersAndFlush();

    var cleared = fieldMapCalls.filter(function (c) {
        return c.method === "setProfilePreview" && c.data === null;
    });
    assertOk(cleared.length >= 1, "v3 should call setProfilePreview(null)");
});

// ── 7. v2↔v3 switching cleans old fields ─────────────────────────────────────
test("v2→v3 switch hides v2-specific fields", async function () {
    // Load v2 first, then switch to v3
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [
            createProfileEntry("v2-switch", 2, "V2 Switch"),
            createProfileEntry("v3-switch", 3, "V3 Switch")
        ]
    };
    var d2 = v2ProfileData(); d2.profile_id = "v2-switch";
    apiResponses["/api/field-profiles/v2-switch"] = d2;
    var d3 = v3ProfileData(); d3.profile_id = "v3-switch";
    apiResponses["/api/field-profiles/v3-switch"] = d3;

    var s = loadBoth();
    await initAndSettle(s);

    // Load v2
    var sel = domElements["fpProfileSelect"];
    sel.value = "v2-switch"; sel.selectedIndex = 1;
    dispatchEvent("fpProfileSelect", "change");
    await runTimersAndFlush();
    assertIncludes(domElements["fpProfileSchema"].textContent, "v2");

    // Switch to v3
    sel.value = "v3-switch"; sel.selectedIndex = 2;
    dispatchEvent("fpProfileSelect", "change");
    await runTimersAndFlush();
    assertIncludes(domElements["fpProfileSchema"].textContent, "v3");

    // v2-specific fields should be cleared
    assertEqual(domElements["fpOriginField"].textContent, "--", "fpOriginField should be cleared for v3");
    assertEqual(domElements["fpClDetails"].textContent, "--", "fpClDetails should be cleared for v3");
});

test("v3→v2 switch hides v3-specific fields", async function () {
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [
            createProfileEntry("v3-sw2", 3, "V3 First"),
            createProfileEntry("v2-sw2", 2, "V2 Second")
        ]
    };
    var d3 = v3ProfileData(); d3.profile_id = "v3-sw2";
    apiResponses["/api/field-profiles/v3-sw2"] = d3;
    var d2 = v2ProfileData(); d2.profile_id = "v2-sw2";
    apiResponses["/api/field-profiles/v2-sw2"] = d2;

    var s = loadBoth();
    await initAndSettle(s);

    // Load v3
    var sel = domElements["fpProfileSelect"];
    sel.value = "v3-sw2"; sel.selectedIndex = 1;
    dispatchEvent("fpProfileSelect", "change");
    await runTimersAndFlush();
    assertIncludes(domElements["fpProfileSchema"].textContent, "v3");
    assertOk(domElements["fpV3Marker"].textContent !== "--", "v3 marker should be populated");

    // Switch to v2
    sel.value = "v2-sw2"; sel.selectedIndex = 2;
    dispatchEvent("fpProfileSelect", "change");
    await runTimersAndFlush();
    assertIncludes(domElements["fpProfileSchema"].textContent, "v2");

    // v3-specific fields should be cleared
    assertEqual(domElements["fpV3Marker"].textContent, "--", "fpV3Marker should be cleared for v2");
    assertEqual(domElements["fpV3Scan"].textContent, "--", "fpV3Scan should be cleared for v2");
    assertEqual(domElements["fpV3Sampling"].textContent, "--", "fpV3Sampling should be cleared for v2");
    assertEqual(domElements["fpV3Baseline"].textContent, "--", "fpV3Baseline should be cleared for v2");
    assertEqual(domElements["fpV3Geometry"].textContent, "--", "fpV3Geometry should be cleared for v2");
});

// ── 8. Freeze enablement ─────────────────────────────────────────────────────
test("v2 legacy Freeze enabled when confirmed", async function () {
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [createProfileEntry("v2-freeze", 2, "V2 Freeze")]
    };
    apiResponses["/api/field-profiles/v2-freeze"] = v2ProfileData();

    var s = loadBoth();
    await initAndSettle(s);
    var sel = domElements["fpProfileSelect"];
    sel.value = "v2-freeze"; sel.selectedIndex = 1;
    dispatchEvent("fpProfileSelect", "change");
    await runTimersAndFlush();

    // Simulate confirmed field reference status
    s.window.UavFieldProfiles.onFieldReferenceStatus({
        field_reference: {
            is_confirmed: true,
            is_frozen: false,
            runtime_binding: { state: "idle" }
        }
    });
    await flushPromises();

    var freezeBtn = domElements["frFreeze"];
    assertOk(freezeBtn && !freezeBtn.disabled, "Freeze should be enabled for confirmed v2");
});

test("v3 Freeze always disabled", async function () {
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [createProfileEntry("v3-nofreeze", 3, "V3 NoFreeze")]
    };
    apiResponses["/api/field-profiles/v3-nofreeze"] = v3ProfileData();

    var s = loadBoth();
    await initAndSettle(s);
    var sel = domElements["fpProfileSelect"];
    sel.value = "v3-nofreeze"; sel.selectedIndex = 1;
    dispatchEvent("fpProfileSelect", "change");
    await runTimersAndFlush();

    // Simulate confirmed + not frozen — v3 must still disable Freeze
    s.window.UavFieldProfiles.onFieldReferenceStatus({
        field_reference: {
            is_confirmed: true,
            is_frozen: false,
            runtime_binding: { state: "idle" }
        }
    });
    await flushPromises();

    var freezeBtn = domElements["frFreeze"];
    assertOk(freezeBtn && freezeBtn.disabled, "Freeze must be disabled for v3 even when confirmed");
});

// ── 9. v3 Start/Bind controls ────────────────────────────────────────────────
test("v3 idle: Start enabled, Bind disabled", async function () {
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [createProfileEntry("v3-ctrl", 3, "V3 Ctrl")]
    };
    apiResponses["/api/field-profiles/v3-ctrl"] = v3ProfileData();

    var s = loadBoth();
    await initAndSettle(s);
    var sel = domElements["fpProfileSelect"];
    sel.value = "v3-ctrl"; sel.selectedIndex = 1;
    dispatchEvent("fpProfileSelect", "change");
    await runTimersAndFlush();

    assertOk(!domElements["fpRuntimeStart"].disabled, "Start should be enabled for v3 idle");
    assertOk(domElements["fpBindCurrent"].disabled, "Bind should be disabled for v3 idle");
});

test("v2 idle: Bind enabled, Start disabled", async function () {
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [createProfileEntry("v2-ctrl", 2, "V2 Ctrl")]
    };
    apiResponses["/api/field-profiles/v2-ctrl"] = v2ProfileData();

    var s = loadBoth();
    await initAndSettle(s);
    var sel = domElements["fpProfileSelect"];
    sel.value = "v2-ctrl"; sel.selectedIndex = 1;
    dispatchEvent("fpProfileSelect", "change");
    await runTimersAndFlush();

    assertOk(domElements["fpRuntimeStart"].disabled, "Start should be disabled for v2 idle");
    assertOk(!domElements["fpBindCurrent"].disabled, "Bind should be enabled for v2 idle");
});

// ── 10. Start/Finalize/Cancel click handlers ─────────────────────────────────
test("Start click POSTs to runtime-sampling/start", async function () {
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [createProfileEntry("v3-start", 3, "V3 Start")]
    };
    apiResponses["/api/field-profiles/v3-start"] = v3ProfileData();
    apiResponses["/api/field-profiles/v3-start/runtime-sampling/start"] = { ok: true, state: "sampling" };

    var s = loadBoth();
    await initAndSettle(s);
    var sel = domElements["fpProfileSelect"];
    sel.value = "v3-start"; sel.selectedIndex = 1;
    dispatchEvent("fpProfileSelect", "change");
    await runTimersAndFlush();

    confirmResponses.push(true);
    dispatchEvent("fpRuntimeStart", "click");
    await runTimersAndFlush();

    var reqs = apiRequests.filter(function (r) { return r.url.indexOf("runtime-sampling/start") >= 0; });
    assertEqual(reqs.length, 1);
    assertEqual(reqs[0].options.method, "POST");
});

test("Finalize click POSTs to runtime-sampling/finalize", async function () {
    apiResponses["/api/field-reference/runtime-sampling/finalize"] = { ok: true, state: "applied" };
    var s = loadBoth();
    s.window.UavFieldProfiles.init();

    confirmResponses.push(true);
    dispatchEvent("fpRuntimeFinalize", "click");
    await runTimersAndFlush();

    var reqs = apiRequests.filter(function (r) { return r.url.indexOf("runtime-sampling/finalize") >= 0; });
    assertEqual(reqs.length, 1);
});

test("Cancel click POSTs to runtime-sampling/cancel", async function () {
    apiResponses["/api/field-reference/runtime-sampling/cancel"] = { ok: true, state: "idle" };
    var s = loadBoth();
    s.window.UavFieldProfiles.init();

    confirmResponses.push(true);
    dispatchEvent("fpRuntimeCancel", "click");
    await runTimersAndFlush();

    var reqs = apiRequests.filter(function (r) { return r.url.indexOf("runtime-sampling/cancel") >= 0; });
    assertEqual(reqs.length, 1);
});

// ── 11. confirm=false prevents POST ──────────────────────────────────────────
test("confirm=false prevents Start POST", async function () {
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [createProfileEntry("v3-noconf", 3, "V3 NoConf")]
    };
    apiResponses["/api/field-profiles/v3-noconf"] = v3ProfileData();

    var s = loadBoth();
    await initAndSettle(s);
    var sel = domElements["fpProfileSelect"];
    sel.value = "v3-noconf"; sel.selectedIndex = 1;
    dispatchEvent("fpProfileSelect", "change");
    await runTimersAndFlush();

    confirmResponses.push(false);
    dispatchEvent("fpRuntimeStart", "click");
    await runTimersAndFlush();

    var reqs = apiRequests.filter(function (r) { return r.url.indexOf("runtime-sampling/start") >= 0; });
    assertEqual(reqs.length, 0, "no POST when confirm is false");
});

test("confirm=false prevents Cancel POST", async function () {
    var s = loadBoth();
    s.window.UavFieldProfiles.init();
    confirmResponses.push(false);
    dispatchEvent("fpRuntimeCancel", "click");
    await runTimersAndFlush();
    var reqs = apiRequests.filter(function (r) { return r.url.indexOf("runtime-sampling/cancel") >= 0; });
    assertEqual(reqs.length, 0, "no POST when confirm is false");
});

// ── 12. requestBusy — real behavior with deferred Promise ─────────────────
test("requestBusy prevents duplicate POST with deferred resolve", async function () {
    var v3d = v3ProfileData();
    v3d.profile_id = "v3-busy2";
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [createProfileEntry("v3-busy2", 3, "V3 Busy2")]
    };
    apiResponses["/api/field-profiles/v3-busy2"] = v3d;

    // Deferred: track calls
    var callCount = 0;
    var deferredResolve;
    apiResponses["/api/field-profiles/v3-busy2/runtime-sampling/start"] = function () {
        callCount++;
        return new Promise(function (resolve) { deferredResolve = resolve; });
    };

    var s = loadBoth();
    await initAndSettle(s);
    var sel = domElements["fpProfileSelect"];
    sel.value = "v3-busy2"; sel.selectedIndex = 1;
    dispatchEvent("fpProfileSelect", "change");
    await runTimersAndFlush();

    // Directly call startRuntimeSampling twice, confirm both times
    confirmResponses.push(true);
    s.window.UavFieldProfiles.startRuntimeSampling();
    await runTimersAndFlush();
    assertEqual(callCount, 1, "first call: api called once");

    confirmResponses.push(true);
    s.window.UavFieldProfiles.startRuntimeSampling();
    await runTimersAndFlush();
    assertEqual(callCount, 1, "second call while pending: api NOT called again, got " + callCount);

    // Resolve the pending request
    deferredResolve({ ok: true, state: "sampling" });
    await runTimersAndFlush();

    // Now requestBusy should be false, can call again
    confirmResponses.push(true);
    s.window.UavFieldProfiles.startRuntimeSampling();
    await runTimersAndFlush();
    assertEqual(callCount, 2, "third call after resolve: api called again, got " + callCount);
});

test("requestBusy source check (still present)", function () {
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    assertIncludes(src, "requestBusy");
    assertIncludes(src, "if (requestBusy) return");
});


// ── 13. Reset ────────────────────────────────────────────────────────────────
test("Reset button has confirm and calls reset endpoint", async function () {
    apiResponses["/api/field-reference/reset"] = { ok: true };
    var s = loadBoth();
    s.window.UavFieldRef.init();

    confirmResponses.push(true);
    dispatchEvent("frReset", "click");
    await runTimersAndFlush();

    var reqs = apiRequests.filter(function (r) { return r.url.indexOf("/api/field-reference/reset") >= 0; });
    assertEqual(reqs.length, 1);
    // Check confirm message
    var confMsg = confirmCalls[0] || "";
    assertIncludes(confMsg, "将清除 Field Reference");
    assertIncludes(confMsg, "不会发送飞控命令");
});

test("Reset confirm=false does not POST", async function () {
    var s = loadBoth();
    s.window.UavFieldRef.init();
    confirmResponses.push(false);
    dispatchEvent("frReset", "click");
    await runTimersAndFlush();
    var reqs = apiRequests.filter(function (r) { return r.url.indexOf("/api/field-reference/reset") >= 0; });
    assertEqual(reqs.length, 0);
});

// ── 14. Polling single chain — real behavior ──────────────────────────────
test("startPolling first call creates exactly 1 timer", async function () {
    var s = loadBoth();
    s.window.UavFieldRef.startPolling();
    await runTimersAndFlush();
    assertEqual(countPendingTimers(), 1, "first startPolling should create 1 timer");
});

test("startPolling second call does not add timer", async function () {
    var s = loadBoth();
    s.window.UavFieldRef.startPolling();
    await runTimersAndFlush();
    s.window.UavFieldRef.startPolling();
    assertEqual(countPendingTimers(), 1, "second startPolling should not add timer");
});

test("manual fetch with scheduleNext:false does not add timer", async function () {
    var s = loadBoth();
    s.window.UavFieldRef.startPolling();
    var t1 = countPendingTimers();
    await s.window.UavFieldRef.fetchFieldReferenceStatus({ scheduleNext: false });
    await runTimersAndFlush();
    // After the fetch, the original poll timer should still be the only one
    // (scheduleNext=false so no new timer from the manual fetch)
    var t2 = countPendingTimers();
    assertOk(t2 <= 1, "manual fetch should not add extra timer");
});

// ── 15. Polling delay — real behavior, not just source search ───────────────
test("polling delay is 500ms when runtime state=sampling", async function () {
    var s = loadBoth();
    apiResponses["/api/field-reference/status"] = {
        field_reference: {
            runtime_binding: { state: "sampling", sampling: {} }
        }
    };
    s.window.UavFieldRef.startPolling();
    await runTimersAndFlush();
    // After fetch completes, next poll should be scheduled with 500ms delay
    var timers = _timerQueue.slice();
    assertOk(timers.length >= 1, "should have scheduled next poll, got " + timers.length);
    var found500 = timers.some(function (t) { return t.at === 500; });
    assertOk(found500, "next poll delay should be 500ms for sampling state, delays: " + JSON.stringify(timers.map(function(t){return t.at;})));
});

test("polling delay is 2000ms when runtime state=idle", async function () {
    var s = loadBoth();
    apiResponses["/api/field-reference/status"] = {
        field_reference: {
            runtime_binding: { state: "idle", sampling: {} }
        }
    };
    s.window.UavFieldRef.startPolling();
    await runTimersAndFlush();
    var timers = _timerQueue.slice();
    assertOk(timers.length >= 1, "should have scheduled next poll, got " + timers.length);
    var found2000 = timers.some(function (t) { return t.at === 2000; });
    assertOk(found2000, "next poll delay should be 2000ms for idle state, delays: " + JSON.stringify(timers.map(function(t){return t.at;})));
});


// ── 16. app.js no Field Reference interval ───────────────────────────────────
test("app.js has no Field Reference setInterval", function () {
    var src = fs.readFileSync("web_ui/static/app.js", "utf8");
    assertNotIncludes(src, "startFrPolling");
    assertNotIncludes(src, "setInterval(fetchFieldReferenceStatus");
});

// ── 17. No auto-finalize ─────────────────────────────────────────────────────
test("polling function does not call finalize/start/cancel endpoints", function () {
    var src = fs.readFileSync("web_ui/static/js/field_reference.js", "utf8");
    var pollStart = src.indexOf("function fetchFieldReferenceStatus");
    var pollEnd = src.indexOf("function startPolling", pollStart + 10);
    if (pollEnd < 0) pollEnd = src.indexOf("function stopPolling", pollStart);
    if (pollEnd < 0) pollEnd = src.length;
    var pollBody = src.substring(pollStart, pollEnd);
    assertNotIncludes(pollBody, "runtime-sampling/finalize");
    assertNotIncludes(pollBody, "runtime-sampling/start");
    assertNotIncludes(pollBody, "runtime-sampling/cancel");
});

// ── 18. Bind result preserves children ───────────────────────────────────────
test("no setText on fpBindResult container", function () {
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    assertNotIncludes(src, 'setText("fpBindResult"');
    assertIncludes(src, 'setText("fpBindOk"');
});

// ── 19. fpOriginGps not used ─────────────────────────────────────────────────
test("fpOriginGps not in field_profile.js", function () {
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    assertNotIncludes(src, "fpOriginGps");
});

// ── 20. setInterval not used in field_reference.js ────────────────────────────
test("field_reference.js has no setInterval", function () {
    var src = fs.readFileSync("web_ui/static/js/field_reference.js", "utf8");
    assertNotIncludes(src, "setInterval");
});

// ── 21. Source text checks ───────────────────────────────────────────────────
test("source contains validateProfile function", function () {
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    assertIncludes(src, "function validateProfile");
    assertIncludes(src, "/validate");
});

test("source contains bindCurrentProfile function", function () {
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    assertIncludes(src, "function bindCurrentProfile");
    assertIncludes(src, "/bind-current");
});

test("init registers all button handlers", function () {
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    assertIncludes(src, "fpRefreshList");
    assertIncludes(src, "fpValidateProfile");
    assertIncludes(src, "fpBindCurrent");
    assertIncludes(src, "fpRuntimeStart");
    assertIncludes(src, "fpRuntimeFinalize");
    assertIncludes(src, "fpRuntimeCancel");
    assertIncludes(src, "fpProfileSelect");
    assertIncludes(src, "fetchProfileList();");
    assertIncludes(src, "updateRuntimeControls();");
});

// ── 22. sampling state labels ────────────────────────────────────────────────
test("source contains sampling state labels", function () {
    var src = fs.readFileSync("web_ui/static/js/field_profile.js", "utf8");
    assertIncludes(src, "sampling_failed");
    assertIncludes(src, "apply_failed");
});

// ── 23. Freeze endpoint in field_reference.js ────────────────────────────────
test("field_reference.js has Freeze endpoint", function () {
    var src = fs.readFileSync("web_ui/static/js/field_reference.js", "utf8");
    assertIncludes(src, "frFreeze");
    assertIncludes(src, "/api/field-reference/freeze");
});

// ── 24. Freeze boundary tests ─────────────────────────────────────────────
test("v2 confirmed: Freeze enabled", async function () {
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [createProfileEntry("v2-freeze-on", 2, "V2 FreezeOn")]
    };
    apiResponses["/api/field-profiles/v2-freeze-on"] = v2ProfileData();
    var s = loadBoth();
    await initAndSettle(s);
    var sel = domElements["fpProfileSelect"];
    sel.value = "v2-freeze-on"; sel.selectedIndex = 1;
    dispatchEvent("fpProfileSelect", "change");
    await runTimersAndFlush();
    s.window.UavFieldProfiles.onFieldReferenceStatus({
        field_reference: { is_confirmed: true, is_frozen: false, runtime_binding: { state: "idle" } }
    });
    await flushPromises();
    assertOk(!domElements["frFreeze"].disabled, "v2 confirmed: Freeze should be enabled");
});

test("v3 confirmed: Freeze disabled", async function () {
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [createProfileEntry("v3-freeze-off", 3, "V3 FreezeOff")]
    };
    apiResponses["/api/field-profiles/v3-freeze-off"] = v3ProfileData();
    var s = loadBoth();
    await initAndSettle(s);
    var sel = domElements["fpProfileSelect"];
    sel.value = "v3-freeze-off"; sel.selectedIndex = 1;
    dispatchEvent("fpProfileSelect", "change");
    await runTimersAndFlush();
    s.window.UavFieldProfiles.onFieldReferenceStatus({
        field_reference: { is_confirmed: true, is_frozen: false, runtime_binding: { state: "idle" } }
    });
    await flushPromises();
    assertOk(domElements["frFreeze"].disabled, "v3 confirmed: Freeze must be disabled");
});

test("no profile + confirmed: Freeze disabled", async function () {
    var s = loadBoth();
    s.window.UavFieldProfiles.init();
    await runTimersAndFlush();
    s.window.UavFieldProfiles.onFieldReferenceStatus({
        field_reference: { is_confirmed: true, is_frozen: false, runtime_binding: { state: "idle" } }
    });
    await flushPromises();
    assertOk(domElements["frFreeze"].disabled, "no profile + confirmed: Freeze must be disabled");
});

test("unknown schema + confirmed: Freeze disabled", async function () {
    apiResponses["/api/field-profiles"] = {
        ok: true,
        profiles: [createProfileEntry("unk-schema", 99, "Unknown Schema")]
    };
    apiResponses["/api/field-profiles/unk-schema"] = {
        ok: true, profile_id: "unk-schema", name: "Unknown", schema_version: 99,
        source: "config", gps_quality: {}
    };
    var s = loadBoth();
    await initAndSettle(s);
    var sel = domElements["fpProfileSelect"];
    sel.value = "unk-schema"; sel.selectedIndex = 1;
    dispatchEvent("fpProfileSelect", "change");
    await runTimersAndFlush();
    s.window.UavFieldProfiles.onFieldReferenceStatus({
        field_reference: { is_confirmed: true, is_frozen: false, runtime_binding: { state: "idle" } }
    });
    await flushPromises();
    assertOk(domElements["frFreeze"].disabled, "unknown schema + confirmed: Freeze must be disabled");
});

// ── 24. HTML has v3 detail IDs ───────────────────────────────────────────────
test("index.html has v3 detail and geometry IDs", function () {
    var html = fs.readFileSync("web_ui/static/index.html", "utf8");
    assertIncludes(html, "fpV3Marker");
    assertIncludes(html, "fpV3Scan");
    assertIncludes(html, "fpV3Sampling");
    assertIncludes(html, "fpV3Baseline");
    assertIncludes(html, "fpV3Geometry");
});

// ═══════════════════════════════════════════════════════════════════════════════
// RUNNER: collect, await all async tests, then report
// ═══════════════════════════════════════════════════════════════════════════════

async function runAllTests() {
    for (var i = 0; i < testDefs.length; i++) {
        var t = testDefs[i];
        try {
            var result = t.fn();
            if (result && typeof result.then === "function") {
                await result;
            }
            testsPassed++;
        } catch (e) {
            testsFailed++;
            console.error("  FAIL " + t.name + ": " + e.message);
        }
    }
}

// Check if SELF_PROOF environment variable is set
var selfProofFail = process.env.SELF_PROOF_FAIL === "1";

runAllTests().then(function () {
    console.log("\n=== Node Behavior Test Results ===");
    console.log("Passed: " + testsPassed);
    console.log("Failed: " + testsFailed);

    if (selfProofFail) {
        // In self-proof mode, fail intentionally
        console.error("\nSELF_PROOF: forcing non-zero exit");
        process.exit(1);
    }

    if (testsFailed > 0) {
        console.error("\nFAILED: " + testsFailed + " test(s) failed!");
        process.exit(1);
    } else {
        console.log("All " + testsPassed + " tests passed!");
        process.exit(0);
    }
}).catch(function (e) {
    console.error("Runner error: " + e.message);
    process.exit(2);
});
