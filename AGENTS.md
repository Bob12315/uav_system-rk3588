# AI Development Entry

This repository targets Linux ARM64 RK3588 boards only.

## Current Architecture

- Action Mission is the only current mission mainline.
- Web UI is the only formal human-operation entry.
- Actions live in `missions/common/actions/`.
- Mission templates live in `config/action_missions/*.json`.
- The current send path is `Action output -> ActionDispatcher -> LinkManager -> telemetry_link`.
- Read `docs/ai/current_architecture.md` and `docs/ai/deprecated_paths.md` before changing architecture.

Do not restore or add the deprecated mission/stage/control stack, including
`missions/<mission>/mission.py`, `missions/<mission>/stages/<stage>`,
`MissionRunner`, `StageRegistry`, `CommandShaper`, or `FlightCommandExecutor`.

## Platform Rules

- YOLO inference uses `RKNNLite` with an RKNN `.rknn` model on the RK3588 NPU.
- Do not add x86, CUDA, PyTorch, or GPU inference paths.
- The current deployment model is `data/models/cuadc-fp16.rknn`.
- RK3588 can support INT8, but this project's current INT8 models are deprecated and must not become the default without new calibration and detection validation.
- Runtime state, logs, SITL files, generated videos, and blackbox data belong under `runtime/`.

## Safety Rules

- Keep `executor.send_commands: false` as the default.
- Preserve the system SEND and Action send-actions double gate.
- Actions must not call pymavlink or `LinkManager` directly; dispatch goes through `ActionRuntimeService` and `ActionDispatcher`.
- Continuous BODY_NED commands must stop with an explicit zero/stop command and stale commands must be cleared.
- The old CommandShaper/FlightCommandExecutor path is not active. Do not reintroduce it without an explicit architecture decision; the Action-compatible shaping/safety replacement remains a documented gap.
- Payload release is only `payload_release` Action -> `set_servo`; do not use `release_payload` or RC override.
- `yolo_app/` must not connect to MAVLink or generate flight commands.

## Configuration

- App: `config/app.yaml`
- Telemetry: `config/telemetry.yaml`
- YOLO: `config/yolo.yaml`
- Action Mission templates: `config/action_missions/*.json`

## Read Before Editing

1. `README.md`
2. `docs/ai/README.md`
3. `docs/ai/current_architecture.md`
4. `docs/ai/action_contracts.md`
5. `docs/ai/deprecated_paths.md`
6. `docs/reference/coordinate_frames.md`
7. `docs/reference/field_origin_heading.md`
8. `docs/reference/safety.md`

Use `docs/ai/task_checklist.md` for task-specific files.
