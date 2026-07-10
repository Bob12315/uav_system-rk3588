# Drop V2 GPS-First Runtime Field and Flight Contract

## 1. Scope

This contract applies **only** to `drop_two_targets_v2` and compatible
extensions to shared components (`missions/common/actions/`,
`app/field_reference.py`, `app/coordinate_transform.py`,
`app/field_profile_service.py`).

- `drop_two_targets_v1` **must remain unchanged** throughout this
  transformation.
- The Action-first architecture (Action → ActionDispatcher → LinkManager)
  **remains unchanged**.

## 2. Target Runtime Flow

```
1. Drone stabilises on the field centreline start point.
2. Config holds a single forward marker B (WGS84).
3. A (dynamic origin sampled from stationary GPS) → B defines FIELD +Y heading.
4. FIELD metric scan waypoints are converted to GLOBAL GPS at runtime.
5. GLOBAL GPS four-point scan.
6. Capture-instant GPS / yaw / altitude / ex / ey → single-frame target GPS.
7. GPS-derived ENU clustering / fusion.
8. Select two drop targets from fusion results only.
9. GLOBAL GPS fly-to above each target and stabilise (velocity + position hold).
10. image_center lock on the target.
11. BODY_NED alignment descent (no yaw hold, no LOCAL_NED).
12. Drop on alignment success; zero + drop on timeout.
13. GLOBAL GPS return to dynamic origin A.
```

## 3. Prohibited Dependencies

V2 mission decisions MUST NOT depend on:

- `drone.local_x`
- `drone.local_y`
- `drone.local_z`
- `LOCAL_POSITION` waypoints
- `LOCAL_NED` visual descent velocity
- Pre-surveyed field origin GPS (hardcoded in config)
- Pre-surveyed 4 centreline GPS points (hardcoded in config)
- Single-frame raw_estimate direct target selection for drop

## 4. Allowed Dependencies

- GLOBAL GPS waypoints (`MAV_FRAME_GLOBAL_RELATIVE_ALT_INT`)
- `relative_altitude` (from telemetry)
- Actual attitude yaw (from telemetry, attitude_valid=true)
- GPS-derived ENU metric coordinates (for clustering only)
- BODY_NED visual velocity commands
- ArduPilot internal EKF (for local position — never exposed to mission logic)

### FieldReference readiness split (step 4)

- :
  confirmed + finite LOCAL origin N/E + finite field heading.

- :
  confirmed + finite WGS84 origin lat/lon + finite field heading.
  It does not require LOCAL_NED or the original forward marker once
  heading has been derived.

- :
  backward-compatible alias for .

GPS readiness does not require LOCAL_NED.
LOCAL readiness does not require GPS.
Neither readiness requires frozen.
Mission execution will require frozen at the runtime-binding layer.



GPS readiness does not require LOCAL_NED.
LOCAL readiness does not require GPS.
Neither readiness requires frozen.
Mission execution will require frozen at the runtime-binding layer.

### Runtime GPS sampling semantics (step 5A)

- Sampling uses  for unique GPS-message
  identification.
- The five-second session window uses caller-supplied observation time.
- Repeated reads of the same GPS message are duplicates, not samples.
- Only samples passing global-position and profile GPS-quality checks
  are accepted.
- Runtime origin latitude and longitude are coordinate-wise medians.
-  is the maximum horizontal radius from the
  median origin to any accepted sample.
- The candidate is not confirmed, frozen, or written into runtime
  state until step 5B.

## 5. Dynamic Field Contract

### Config (on-disk, minimal)

```json
{
  "schema_version": 3,
  "coordinate_convention": {
    "field_x_positive": "right",
    "field_y_positive": "forward",
    "altitude_positive": "up"
  },
  "forward_marker": {
    "name": "far_centerline_marker",
    "lat": 34.1030000,
    "lon": 108.6435000,
    "coordinate_system": "WGS84"
  },
  "field_geometry": {
    "lane_half_width_m": 4.0,
    "drop_area_y_min_m": 30.0,
    "drop_area_y_max_m": 35.0,
    "drop_center_y_m": 32.5,
    "recce_area_y_min_m": 55.0,
    "recce_area_y_max_m": 60.0,
    "recce_center_y_m": 57.5
  },
  "drop_scan": {
    "waypoints": [
      {"x_m": -2.0, "y_m": 31.25, "altitude_m": 5.0},
      {"x_m":  2.0, "y_m": 31.25, "altitude_m": 5.0},
      {"x_m":  2.0, "y_m": 33.75, "altitude_m": 5.0},
      {"x_m": -2.0, "y_m": 33.75, "altitude_m": 5.0}
    ]
  },
  "gps_quality": {
    "min_fix_type": 3,
    "min_satellites": 10,
    "max_eph": 2.5,
    "max_epv": 5.0
  },
  "runtime_origin_sampling": {
    "min_samples": 20,
    "sample_window_s": 5.0,
    "max_horizontal_spread_m": 1.0,
    "estimator": "median"
  },
  "binding_policy": {
    "min_baseline_m": 30.0,
    "warn_baseline_below_m": 50.0
  }
}
```

### Runtime (dynamic, derived at field confirmation)

- `origin_lat` / `origin_lon` — sampled while stationary during pre-mission
  field confirmation (median of valid GPS samples)
- `forward_marker_lat` / `forward_marker_lon` — from config `forward_marker`
- `field_heading_yaw_rad` — bearing from dynamic origin A to forward marker B
- `baseline_m` — distance from dynamic origin A to the single forward marker B
- `gps_sample_count` — number of valid GPS samples used
- `gps_horizontal_spread_m` — max horizontal spread across samples
- `gps_fix_type` — GPS fix type at confirmation time
- `gps_satellites` — satellite count at confirmation time
- `gps_eph` — horizontal position estimate error (m)
- `gps_epv` — vertical position estimate error (m)
- `field_reference_mode` — `runtime_origin_forward_marker`
- `confirmed` — true after sampling passes quality thresholds
- `frozen` — true after confirmation; prevents accidental re-binding

### Origin sampling rules

- Drone is stationary on the field centreline start point.
- Sampling occurs during field confirmation, NOT after takeoff.
- Only valid GPS samples are accepted (fix type, satellites, eph/epv within
  thresholds).
- Dynamic origin A is the median latitude/longitude of accepted samples.
- If horizontal spread across samples exceeds `max_horizontal_spread_m`,
  confirmation is rejected.
- After confirmation, the origin is frozen — no re-sampling or drift during
  mission execution.

### Baseline rules

- `baseline_m` = distance from dynamic origin A to the single forward marker B.
- If baseline < `min_baseline_m` (30 m): confirmation fails.
- If `min_baseline_m` ≤ baseline < `warn_baseline_below_m` (50 m): allowed with
  warning.
- If baseline ≥ `warn_baseline_below_m`: normal.

## 6. Localisation & Fusion Contract

```
raw_estimate   = single-frame GPS target estimate
                 (lat, lon, ex, ey, drone_lat, drone_lon, yaw_rad, altitude_m)
localized_object = multi-view GPS/ENU fusion target
                 (fused from >= min_cluster_size raw_estimates)
```

`select_drop_targets` MUST read only `localized_objects` (fusion results).

### Fusion Object Mandatory Fields

| Field | Type | Description |
|---|---|---|
| `lat` | float | WGS84 latitude |
| `lon` | float | WGS84 longitude |
| `north_m` | float | ENU north from origin (m) |
| `east_m` | float | ENU east from origin (m) |
| `class_name` | str | Detected class label |
| `seen_count` | int | Number of fused raw estimates (>= min_cluster_size) |
| `raw_count` | int | Total raw estimates in cluster |
| `view_count` | int | Number of distinct viewpoints |
| `track_ids` | list[int] | Associated track IDs |
| `weight` | float | Fusion weight |

## 7. Arrival & Control Contract

### GLOBAL goto target-above completion

These strict parameters apply to fly-over above each drop target. Scan points
and return-to-home may use different tolerances, but still use GLOBAL GPS.

| Condition | Threshold |
|---|---|
| Horizontal position error | <= `tolerance_xy_m` (0.25 m) |
| Altitude error | <= `tolerance_z_m` (0.25 m) |
| Horizontal speed | <= `max_horizontal_speed_mps` (0.15 m/s) |
| Vertical speed | <= `max_vertical_speed_mps` (0.10 m/s) |
| Consecutive stable ticks | >= `min_hold_updates` (5) |
| Require velocity valid | `require_velocity_valid = true` |

### TargetLock Contract

- `match_mode = image_center` — locate target by proximity to image centre,
  NOT by local_x/local_y distance.
- Pre-filter detections by target `class_name`.
- Select the detection with minimum `sqrt(ex² + ey²)` distance from image
  centre.
- Require a valid `track_id` on the selected detection.
- Require the same `track_id` for `stable_track_updates = 3` consecutive frames.
- If the candidate track changes, reset the counter.
- Reject locking if `sqrt(ex² + ey²)` exceeds `max_center_distance`.
- Do NOT read `target.local_x` or `target.local_y`.

### AlignDescend Contract

- `require_target_locked = true`
- `yaw_control_mode = ignore` — no yaw hold.
- Output frame: `BODY_NED`.
- Do NOT attach `yaw_hold_rad` to the command.
- All paths (target invalid, retry, done, failed) must use consistent BODY_NED
  command semantics.
- Do NOT convert to `LOCAL_NED` in the dispatcher.

## 8. Payload Release Contract

### Normal path

```
1. altitude <= finish_altitude_m;
2. Set vz to 0, stop further descent;
3. Continue BODY_NED vx/vy horizontal alignment;
4. aligned condition satisfied for hold_updates_required consecutive ticks;
5. Send BODY_NED zero velocity;
6. AlignDescend returns done, reason = aligned_at_min_altitude;
7. Mission transitions to payload_release.
```

### Timeout path

```
1. update_count exceeds max_updates;
2. Send BODY_NED zero velocity;
3. AlignDescend returns failed, reason = align_descend_timeout;
4. Mission on_failed = continue;
5. Transition to payload_release.
```

### Target lost path

```
Target lost (lost_timeout_updates exceeded without detection) is not the same
as overall align timeout. Whether to continue to payload_release after target
lost must be explicitly configured and tested by the mission policy.
Current v2 keeps on_failed=continue, but final integration testing must cover
this path separately.
```

## 9. V1 Protection Baseline

```
config/action_missions/drop_two_targets_v1.json
SHA256: 6aa0e0f006248db11bc65de4e1a6e38fdc92e8a50e3e2cd135bc769e4de04257
```

The v1 mission file must not be modified by any step in this transformation.

## 10. Current State vs. Target State Matrix

| Contract Item | Current faedb609 State | Target State | Planned Steps |
|---|---|---|---|
| FieldReference readiness | single local-only is_ready before step 4 | separate GPS/local readiness implemented in step 4; runtime GPS sampling and binding still not connected | steps 4–5 |
| Runtime GPS sampling | not implemented before step 5A | pure deterministic sampler and binding candidate implemented; controller/runtime application not connected | steps 5A–5B |
| Dynamic origin A | Not implemented | GPS sampling while stationary during pre-mission confirmation | Steps 3–5 |
| Schema v3 | Schema v2 (anchor + 4 centreline GPS points) | Schema v3 pure data/parse/validation implemented in step 2; runtime binding not yet implemented | Step 2 |
| FIELD → GLOBAL | `field_to_gps` utility exists, but current v2 scan uses hardcoded absolute GPS waypoints | Pure runtime A/B heading and FIELD→GLOBAL geometry implemented in step 3; FieldReference lifecycle and runtime binding are not yet connected. | Steps 3–7 |
| MultiView GPS-first | Single-frame local_x/local_y localization | GPS-based localization at capture instant | Steps 8–10 |
| Post-fusion selection | select_drop_targets reads resolved_targets (1:1 with raw_estimates) | select_drop_targets reads localized_objects (fusion only) | Step 11 |
| Velocity-stabilised arrival | min_hold_updates=1, no speed check | 0.25 m XY / 0.25 m Z / 0.15 m/s horizontal / 0.10 m/s vertical / 5 consecutive updates | Step 12 |
| image_center lock | TargetLock uses local_x/local_y distance matching | TargetLock uses image_centre proximity matching with stable_track_updates=3 | Step 13 |
| BODY_NED align | BODY_NED with yaw_hold → dispatcher converts to LOCAL_NED | Pure BODY_NED, yaw_control_mode=ignore | Step 14 |
| Align complete/timeout drop | Minimum altitude can return done without aligned hold; frame differs between normal/invalid/retry paths; zero-stop transition lacks end-to-end integration proof | Min altitude stops descent but continues horizontal alignment; done only after aligned hold; timeout zeroes then continues to release; all paths use consistent BODY_NED semantics | Step 15 |
