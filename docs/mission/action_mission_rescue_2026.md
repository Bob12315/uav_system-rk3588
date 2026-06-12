# Action Mission Rescue 2026

## Overview

The current full rescue competition Action Mission runs this flow:

```text
takeoff
multi_view_localize
select_drop_targets
drop target 0
drop target 1
recon_scan
return_home
land
```

The mission templates are:

```text
config/action_missions/drop_two_targets_v1.json
config/action_missions/rescue_2026_full_auto.json
```

## Architecture

The control chain is:

```text
Action Mission JSON
  -> MissionOrchestrator
  -> MissionBlackboard
  -> ActionRuntimeService
  -> ActionRunner
  -> Action.update()
  -> ActionResult
  -> ActionDispatcher
  -> LinkManager
  -> Flight Controller / YOLO / Servo
```

Mission code does not call pymavlink directly. Mission code does not call `LinkManager` directly. Flight-controller commands only flow through `ActionDispatcher`. Payload drop commands only flow through `payload_release -> set_servo -> set_servo_output_pwm`.

## Template Data Flow

The blackboard data flow is:

```text
multi_view_localize save_as drop_scan
  -> drop_scan.localized_objects

select_drop_targets save_as drop_targets
  -> drop_targets.selected_targets

recon_scan save_as recon_scan
  -> recon_scan.recon_report
```

Example parameter references:

```json
{
  "x": "$drop_targets.selected_targets.0.local_x",
  "y": "$drop_targets.selected_targets.0.local_y"
}
```

## Mission Step Fields

Mission steps support these fields:

```json
{
  "name": "action_name",
  "label": "optional_label",
  "save_as": "optional_blackboard_key",
  "on_failed": {
    "action": "retry_current"
  },
  "params": {}
}
```

`name` is the registered Action name. `params` is passed to `Action.start`. `save_as` stores `ActionResult.detail` in the blackboard. `label` is a jump target for failure recovery. `on_failed` selects the failure policy for that step.

## Failure Policies

Supported policies are:

```text
fail
retry_current
jump_to
continue
```

Retry the current step:

```json
{
  "on_failed": {
    "action": "retry_current",
    "max_attempts": 2
  }
}
```

Jump to a labeled step:

```json
{
  "on_failed": {
    "action": "jump_to",
    "target": "goto_target_0",
    "max_attempts": 1
  }
}
```

Continue after a failed step:

```json
{
  "on_failed": {
    "action": "continue"
  }
}
```

Recommended use:

- Drop-zone scan failure can retry.
- Target selection failure can jump back to scan.
- `target_lock` or `align_descend` failure can jump back above the target.
- `payload_release` failure must fail the mission.
- `recon_scan` failure can continue to return home and land.

## Safety Notes

Configure does not send flight commands. Start and Tick advance the mission. `SEND=OFF` is dry-run mode. Commands may be sent only when `SEND=ON` and `send_actions` is enabled. Run SITL before real flight. Test without payload before mounting payload. The drop channel is flight-controller SERVO output, not RC input. `release_payload()` is forbidden for competition drops. Do not bypass the dispatcher with direct pymavlink calls.

## Coordinates

Mission `altitude_m` values are positive upward. Actions convert altitude to LOCAL_NED with `z_down_m = -altitude_m`. `x` and `y` are LOCAL_NED local coordinates. Do not infer flight-controller coordinates from the Web UI map display direction. Before real flight, verify the field coordinate directions with `goto_waypoint`.

## Dry-run Validation

Validate all templates offline:

```bash
python scripts/validate_action_missions.py
```

Validate one template:

```bash
python scripts/validate_action_missions.py config/action_missions/rescue_2026_full_auto.json
```

The validator only performs offline checks. It does not connect to the flight controller and does not send commands.

## Recommended Test Order

```text
1. pytest unit tests
2. validate_action_missions.py offline template checks
3. Web UI Configure dry-run
4. Action Mission SEND=OFF dry-run
5. SITL SEND=ON
6. Real vehicle without payload
7. Real vehicle with payload mounted but drop disconnected
8. Real vehicle formal payload drop
```

## Known Limitations

- There is no complex if/else DSL yet.
- Parameter references only support a whole-string `$path`; string interpolation is not supported.
- The first target-selection version ranks by class score and observation stability.
- The first `recon_scan` version conservatively outputs blank when uncertain.
- Paper report generation is not automated.
- Coordinates still require calibration for the actual field.
- `tests/test_action_lab_dispatch.py` still has an existing environment issue unrelated to the current Action Mission mainline.
