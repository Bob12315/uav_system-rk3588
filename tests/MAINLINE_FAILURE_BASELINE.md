# Phase 2 collected-failure baseline

> Phase 2.5 resolution: all five groups below were resolved by aligning test
> expectations and fixtures with the current production contracts. No production
> code or deployment configuration was changed. The full suite now passes.

After retiring the 12 import-failing legacy modules, pytest collects 684 tests and
reports 656 passed / 28 failed. Phase 2 intentionally does not change production
behavior or rewrite these expectations.

| Group | Failures | Classification | Recommended follow-up | Blocks FieldReference? |
| --- | ---: | --- | --- | --- |
| `test_multi_photo_fusion.py` | 16 | Mostly stale expectations after fusion defaults changed to `cluster_radius_m=1.0`, `min_cluster_size=3`, `min_confidence=0.35`; older tests assume singleton clusters are accepted | Review desired standalone defaults, then update tests to pass explicit `min_cluster_size=1` when testing mechanics, or deliberately change defaults in a separate behavior decision | No |
| `test_multi_view_localize_action.py` | 5 | Downstream of fusion minimum cluster size: one/two synthetic observations produce no fused target | Decide whether Action standalone defaults or fixtures should provide an explicit fusion policy; do not change silently | No |
| `test_survey_area_action.py` | 3 | Same downstream fusion-policy mismatch; single observation is rejected by current minimum cluster size | Resolve together with fusion contract and Action default parameters | No |
| `test_target_localization.py` | 3 | Test defaults/sign expectations are stale versus current `76/61` FOV and `image_y_sign=-1`; Action Lab/templates also use flipped image Y | Confirm calibrated camera convention, then update expected values/signs in a dedicated localization test change | Coordinate-sensitive, but not a blocker for pure FIELD/LOCAL_NED extraction |
| `test_telemetry_link.py` | 1 | Environment/config expectation mismatch: tracked root config selects `real`, test expects `sitl` | Make the test assert parser consistency without assuming deployment profile, or use an explicit fixture config | No |

## Phase 2.5 decisions

- Camera localization uses unmirrored input, `ex_norm` right-positive,
  `ey_norm` down-positive, `image_x_sign=1`, and `image_y_sign=-1`.
- Current camera defaults remain 76° horizontal and 61° vertical FOV.
- Production fusion defaults remain `cluster_radius_m=1.0` and
  `min_cluster_size=3`; unit tests that exercise one-point mechanics now request
  `min_cluster_size=1` explicitly.
- Multi-view and survey single-observation fixtures declare the same explicit test policy.
- The tracked root telemetry config remains `real`; SITL expectations load
  `config/profiles/rk3588-sitl/telemetry.yaml` explicitly.
