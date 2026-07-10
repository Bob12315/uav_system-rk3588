# Drop V2 GPS-First Known Test Failures

## Baseline Information

- **branch**: `reasonix/drop-v2-gps-global-align-v1`
- **baseline HEAD**: `faedb6092aadb61a1542f1aef6629c79402938d3`
- **Python interpreter**: `/home/level6/anaconda3/envs/app/bin/python`
- **Python version**: 3.10.20
- **Recorded date**: 2026-07-10

## Collection Errors (3)

These three test files fail during collection due to an environment-level
incompatibility between `annotated_types==0.4.0` (installed) and the
`pydantic==2.13.4` / `fastapi` stack which requires `annotated_types.Not`
(introduced in `annotated_types>=0.5.0`).

| # | Test File | Error | Root Cause |
|---|---|---|---|
| 1 | `tests/current/test_field_profile_backend_api.py` | `AttributeError: module 'annotated_types' has no attribute 'Not'` | `annotated_types==0.4.0` incompatible with `pydantic>=2.10` |
| 2 | `tests/integration/test_action_lab_only_startup.py` | `AttributeError: module 'annotated_types' has no attribute 'Not'` | same; import chain: `web_ui.server` → `fastapi` |
| 3 | `tests/integration/test_web_ui.py` | `AttributeError: module 'annotated_types' has no attribute 'Not'` | same; direct `fastapi` import |

**Import chains for each error:**

1. `test_field_profile_backend_api.py:4` → `from fastapi import HTTPException` → pydantic model construction → `annotated_types.Not`
2. `test_action_lab_only_startup.py:6` → `from web_ui.server import create_app` → `web_ui/server.py:11` → `from fastapi import ...` → pydantic → `annotated_types.Not`
3. `test_web_ui.py:6` → `from fastapi import HTTPException` → pydantic → `annotated_types.Not`

**Treatment:**
These three files are temporarily excluded from test runs via `--ignore=<file>`.
All are fastapi-dependent; none are related to the v2 GPS-first transformation.

> **Policy: 不得在本飞行改造分支安装、升级或降级 `annotated_types`、
> `pydantic`、`fastapi`。**

## Known Failures (11)

All 11 failures are pre-existing at baseline `faedb609` and are classified as
category **A: v2 mission static expectations obsolete vs. current branch**.

| # | pytest node id | Failure Summary | Category | Currently Allowed |
|---|---|---|---|---|
| 1 | `tests/current/test_action_dispatcher_takeoff_land.py::test_global_goto_dispatches_for_goto_waypoint` | `FakeLinkManager.global_goto()` does not accept `yaw_rad` keyword (dispatcher test fixture out of sync) | A | Yes — pre-existing |
| 2 | `tests/current/test_action_lab_registry.py::test_create_action_lab_registry_lists_supported_actions` | Registry list expects `yaw_align` before `validate_target`; actual sorted list differs (new action added) | A | Yes — pre-existing |
| 3 | `tests/current/test_action_mission_templates.py::test_drop_two_targets_v2_outer_gotos_use_local_targets` | Expects label `goto_first_scan_point` (local); got `goto_first_scan_point_gps` (global) | A | Yes — pre-existing |
| 4 | `tests/current/test_action_mission_templates.py::test_drop_two_targets_v2_contains_resolve_gps_targets` | Expects >=3 `resolve_gps_targets` steps; got 2 | A | Yes — pre-existing |
| 5 | `tests/current/test_action_mission_templates.py::test_drop_two_targets_v2_selects_fused_localized_objects` | Expects `$drop_scan.localized_objects`; got `$drop_buckets.resolved_targets` | A | Yes — pre-existing |
| 6 | `tests/current/test_action_mission_templates.py::test_drop_two_targets_v2_no_global_target_frame` | Expects no step uses `target_frame=global`; `goto_first_scan_point_gps` does | A | Yes — pre-existing |
| 7 | `tests/current/test_action_mission_templates.py::test_drop_two_targets_v2_aggressive_scoring_flags` | Expects `drop_sequence` step with aggressive scoring flags; no `drop_sequence` exists | A | Yes — pre-existing |
| 8 | `tests/current/test_action_mission_templates.py::test_drop_two_targets_v2_multi_view_localize_retries_then_returns_home` | Expects `on_failed.target == "return_home"`; got `"return_home_gps"` | A | Yes — pre-existing |
| 9 | `tests/current/test_action_mission_templates.py::test_drop_two_targets_v2_sitl_profile_matches_base` | SITL profile and base profile differ (base has GPS-first description/steps; SITL has old aggressive scoring) | A | Yes — pre-existing |
| 10 | `tests/current/test_action_mission_templates.py::test_drop_two_targets_v2_select_drop_targets_zone_center_mode_field` | Expects `zone_center_mode` key; not present in current v2 `select_drop_targets` params | A | Yes — pre-existing |
| 11 | `tests/current/test_drop_sequence_action.py::test_drop_sequence_goto_uses_absolute_waypoint_mode` | Expects `drop_sequence` step in v2 template; none exists | A | Yes — pre-existing |

**Classification legend:**
- **A**: v2 mission static expectations are obsolete vs. current branch (old test expects pre-GPS-first design)
- **B**: Real code bug (none identified in this list)
- **C**: Environment-caused (none in this list, those are in collection errors above)
- **D**: Cannot determine (none)

## Post-Transformation Regression Standard

1. The 3 known collection errors are temporarily excluded via `--ignore` flags.
2. Only the 11 failures listed in this document are allowed in the full test run.
3. No new failures may be introduced by any transformation step.
4. Every step's new or modified targeted tests must all pass.
5. When a pre-existing failure is resolved by the transformation, it must be
   removed from this whitelist.
6. Old tests must not be deleted, skipped, or weakened to reduce the failure
   count.
