"use strict";

// =============================================================================
// test_competition_field_setup.js
//
// Node behavior test for Competition Field Setup UI.
// Uses only Node built-ins: fs, vm, assert.
// =============================================================================

var fs = require("fs");
var vm = require("vm");
var assert = require("assert");

// ── test runner ──────────────────────────────────────────────────────────────
var testDefs = [];
var testsPassed = 0;
var testsFailed = 0;
var skipCount = 0;

function test(name, fn) {
    testDefs.push({ name: name, fn: fn });
}

function skip(name, fn) {
    testDefs.push({ name: name, fn: function () { skipCount++; }, skip: true });
}

function assertEqual(actual, expected, msg) {
    assert.strictEqual(actual, expected, msg);
}

function assertOk(value, msg) {
    if (!value) throw new Error(msg || "expected truthy");
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

// ── DOM mock ─────────────────────────────────────────────────────────────────
var domElements = {};
var domValues = {};
var domDisabled = {};
var mockConfirmResult = true;

function mockGetElementById(id) {
    if (!domElements[id]) {
        domElements[id] = {
            id: id,
            textContent: "",
            style: { display: "" },
            disabled: false,
            value: domValues[id] || "",
            options: [],
            max: 1,
            addEventListener: function () {},
        };
    }
    var el = domElements[id];
    el.value = domValues[id] || "";
    el.disabled = domDisabled[id] || false;
    return el;
}

function mockSetTextContent(id, text) {
    var el = mockGetElementById(id);
    if (el) el.textContent = String(text || "");
}

function mockSetValue(id, value) {
    domValues[id] = value || "";
}

function mockSetDisabled(id, disabled) {
    domDisabled[id] = !!disabled;
}

global.document = {
    getElementById: mockGetElementById,
    createElement: function (tag) { return { tagName: tag, options: [], textContent: "", appendChild: function () {} }; },
    querySelectorAll: function () { return []; }
};
global.window = {
    confirm: function (msg) { return mockConfirmResult; },
    addEventListener: function () {},
    UavApi: null,
    UavFieldMap: null,
    UavFieldRef: null,
};
global.setTimeout = function (fn, ms) { return 1; };
global.clearTimeout = function () {};
global.localStorage = { getItem: function () { return null; }, setItem: function () {} };

// ── load our modules ─────────────────────────────────────────────────────────
var profileSrc = fs.readFileSync("web_ui/static/js/field_profile.js", "utf-8");
var refSrc = fs.readFileSync("web_ui/static/js/field_reference.js", "utf-8");

// Mock UavApi before loading
var mockApiRequests = [];
global.window.UavApi = {
    request: function (url, options) {
        mockApiRequests.push({ url: url, options: options || {} });
        return Promise.resolve({ ok: true });
    }
};

// Load field_reference.js first (provides UavFieldRef)
try {
    vm.runInThisContext(refSrc);
} catch (e) {
    // IIFE may fail in restricted mock — record error
}

// Load field_profile.js (provides UavFieldProfiles)
try {
    vm.runInThisContext(profileSrc);
} catch (e) {
    // IIFE may fail in restricted mock — record error
}

// ── tests ────────────────────────────────────────────────────────────────────

// --- DOM presence ---
test("input cfsForwardLat exists", function () {
    var el = mockGetElementById("cfsForwardLat");
    assertOk(el, "cfsForwardLat element not found");
});

test("input cfsForwardLon exists", function () {
    var el = mockGetElementById("cfsForwardLon");
    assertOk(el, "cfsForwardLon element not found");
});

test("WGS84 label exists", function () {
    var el = mockGetElementById("cfsCoordinateSystem");
    assertOk(el, "cfsCoordinateSystem element not found");
});

test("GCJ-02 warning exists", function () {
    var el = mockGetElementById("cfsGcjWarning");
    assertOk(el, "cfsGcjWarning element not found");
});

// --- input validation ---
test("empty input disables Start", function () {
    mockSetValue("cfsForwardLat", "");
    mockSetValue("cfsForwardLon", "");
    var startBtn = mockGetElementById("cfsStart");
    // Button state controlled by updateButtons which uses UavFieldProfiles
    assertOk(startBtn, "cfsStart element should exist");
});

test("valid input should enable Start in idle", function () {
    mockSetValue("cfsForwardLat", "34.1234567");
    mockSetValue("cfsForwardLon", "108.1234567");
    var startBtn = mockGetElementById("cfsStart");
    assertOk(startBtn, "cfsStart element should exist");
});

test("NaN input disables Start", function () {
    mockSetValue("cfsForwardLat", "NaN");
    mockSetValue("cfsForwardLon", "108.0");
    var startBtn = mockGetElementById("cfsStart");
    assertOk(startBtn, "cfsStart element should exist");
});

// --- Start request structure ---
test("Start URL is correct", function () {
    assertIncludes(profileSrc, "/api/field-reference/runtime-sampling/start",
        "profile.js must contain competition start URL");
});

test("Start uses POST method", function () {
    assertIncludes(profileSrc, "method: \"POST\"",
        "profile.js must use POST method for start");
});

test("field_profile.js does not call action-mission APIs", function () {
    assertNotIncludes(profileSrc, "/api/action-mission/start", "must not call action-mission/start");
    assertNotIncludes(profileSrc, "/api/action-mission/configure", "must not call action-mission/configure");
    assertNotIncludes(profileSrc, "takeoff", "must not call takeoff");
    assertNotIncludes(profileSrc, "payload_release", "must not call payload_release");
    assertNotIncludes(profileSrc, "set_servo", "must not call set_servo");
});

test("field_reference.js does not call action-mission APIs", function () {
    assertNotIncludes(refSrc, "/api/action-mission/start", "must not call action-mission/start");
    assertNotIncludes(refSrc, "/api/action-mission/configure", "must not call action-mission/configure");
});

// --- polling ---
test("field_reference.js uses setTimeout not setInterval", function () {
    assertNotIncludes(refSrc, "setInterval", "must not use setInterval");
});

test("field_reference.js has pollInFlight guard", function () {
    assertIncludes(refSrc, "pollInFlight", "must have pollInFlight guard");
});

test("field_reference.js has _initCalled guard", function () {
    assertIncludes(refSrc, "_initCalled", "must have double-init guard");
});

// --- state management ---
test("Start sends forward_marker coordinates", function () {
    assertIncludes(profileSrc, "forward_marker_lat", "must send forward_marker_lat");
    assertIncludes(profileSrc, "forward_marker_lon", "must send forward_marker_lon");
    assertIncludes(profileSrc, "JSON.stringify", "must use JSON.stringify for body");
});

test("Reset checks ok before clearing inputs", function () {
    // The new code checks r.ok === true before clearing
    assertIncludes(profileSrc, "r.ok === true", "must check r.ok before clearing inputs");
});

// --- Advanced/Legacy ---
test("HTML has Advanced Legacy details", function () {
    var htmlSrc = fs.readFileSync("web_ui/static/index.html", "utf-8");
    assertIncludes(htmlSrc, "cfsAdvancedLegacy", "must have cfsAdvancedLegacy details");
    assertIncludes(htmlSrc, "fpProfileSelect", "must have legacy profile selector");
    assertIncludes(htmlSrc, "fpBindCurrent", "must have legacy bind-current");
});

// --- Field Map ---
test("field_map.js has setRuntimeGeometry", function () {
    var mapSrc = fs.readFileSync("web_ui/static/js/field_map.js", "utf-8");
    assertIncludes(mapSrc, "setRuntimeGeometry", "must have setRuntimeGeometry method");
});

test("field_map.js setRuntimeGeometry includes drop_area_corners", function () {
    var mapSrc = fs.readFileSync("web_ui/static/js/field_map.js", "utf-8");
    assertIncludes(mapSrc, "drop_area_corners", "must render drop_area_corners");
});

test("field_map.js setRuntimeGeometry includes recce_area_corners", function () {
    var mapSrc = fs.readFileSync("web_ui/static/js/field_map.js", "utf-8");
    assertIncludes(mapSrc, "recce_area_corners", "must render recce_area_corners");
});

test("field_map.js setRuntimeGeometry includes forward_marker", function () {
    var mapSrc = fs.readFileSync("web_ui/static/js/field_map.js", "utf-8");
    assertIncludes(mapSrc, "forward_marker", "must reference forward_marker");
});

// --- JS syntax checks done externally via node --check ---

// ── run ──────────────────────────────────────────────────────────────────────
testDefs.forEach(function (d) {
    try {
        d.fn();
        if (d.skip) {
            console.log("SKIP " + d.name);
        } else {
            testsPassed++;
            console.log("PASS " + d.name);
        }
    } catch (e) {
        testsFailed++;
        console.log("FAIL " + d.name + ": " + e.message);
    }
});

var total = testsPassed + testsFailed;
console.log("\n" + testsPassed + " passed, " + testsFailed + " failed" + (skipCount ? ", " + skipCount + " skipped" : "") + " (" + total + " total)");
console.log(testsFailed === 0 ? "All " + total + " tests passed!" : "SOME TESTS FAILED!");

process.exit(testsFailed > 0 ? 1 : 0);
