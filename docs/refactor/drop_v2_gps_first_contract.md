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
1. Drone stabilises; current GPS = dynamic origin A.
2. Config holds remote centreline point(s) B (WGS84).
3. A → B defines FIELD +Y heading.
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

## 5. Dynamic Field Contract

### Config (on-disk, minimal)

```json
{
  "schema_version": 3,
  "remote_centreline": [
    {"lat": 34.1036, "lon": 108.6430, "name": "far_marker"}
  ],
  "field_geometry": {
    "scan_points_field_m": [
      {"x": 4.0, "y": 0.0},
      {"x": 0.0, "y": 0.0},
      {"x": 0.0, "y": 3.0},
      {"x": 4.0, "y": 3.0}
    ]
  },
  "gps_quality": {
    "min_satellites": 8,
    "max_hdop": 1.5
  },
  "sampling": {
    "samples": 10,
    "interval_s": 0.5
  }
}
```

### Runtime (dynamic, derived from current GPS)

- `origin_lat` / `origin_lon` — sampled from current GPS at takeoff
- `forward_marker_lat` / `forward_marker_lon` — read from config remote centreline
- `field_heading_yaw_rad` — computed from A → B bearing
- `baseline_m` — distance from A to farthest centreline point
- GPS sampling diagnostics (mean, stddev, satellite count, hdop)
- `confirmed` — true after sampling passes quality thresholds
- `frozen` — true after confirmation; prevents accidental re-binding

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

| Condition | Threshold |
|---|---|
| Horizontal position error | <= `tolerance_xy_m` |
| Altitude error | <= `tolerance_z_m` |
| Horizontal speed | <= `max_arrival_speed_mps` (e.g. 0.3) |
| Vertical speed | <= `max_arrival_vz_mps` (e.g. 0.2) |
| Consecutive stable ticks | >= `min_stable_updates` (e.g. 8) |

### AlignDescend MUST:

- `require_target_locked = true`
- `match_mode = image_center` (not local_x/local_y distance)
- Frame: `BODY_NED` (no yaw hold)
- No LOCAL_NED conversion in dispatcher
- No `yaw_hold_rad` attached to command

## 8. Payload Release Contract

### Normal path

```
altitude <= finish_altitude_m
→ stop descent (zero velocity)
→ continue alignment
→ alignment hold >= hold_updates_required
→ zero velocity
→ payload_release
```

### Timeout path

```
update_count > max_updates
→ zero velocity
→ align_descend returns failed (reason: timeout)
→ on_failed = continue
→ payload_release
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
| Dynamic origin A | Not implemented | GPS sampling at takeoff | Steps 3–5 |
| Schema v3 | Schema v2 (anchor + 4 centreline) | Remote centreline only | Step 2 |
| FIELD → GLOBAL | Partially (waypoint_mode=absolute + target_frame=global with hardcoded GPS) | Dynamic GPS reference from runtime origin | Steps 3–7 |
| MultiView GPS-first | Single-frame local_x/local_y localization | GPS-based localization at capture instant | Steps 8–10 |
| Post-fusion selection | select_drop_targets reads resolved_targets (1:1 with raw_estimates) | select_drop_targets reads localized_objects (fusion only) | Step 11 |
| Velocity-stabilised arrival | min_hold_updates=1, no speed check | Speed + position hold with >=8 stable ticks | Step 12 |
| image_center lock | TargetLock uses local_x/local_y distance matching | TargetLock uses image_center proximity matching | Step 13 |
| BODY_NED align | BODY_NED with yaw_hold → dispatcher converts to LOCAL_NED | Pure BODY_NED, no yaw_hold | Step 14 |
| Align complete/timeout drop | Done path uses _inactive_command; timeout continues to payload_release | Same behaviour, verified with integration tests | Step 15 |
