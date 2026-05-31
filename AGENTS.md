# AI Development Entry

This repository targets Linux ARM64 boards with RK3588 only.

## Platform Rules

- YOLO inference uses `RKNNLite` with an INT8 `.rknn` model on the RK3588 NPU.
- Do not add x86, CUDA, PyTorch, or GPU inference paths.
- The tracked deployment model is `data/models/best-int8-rk3588.rknn`.
- Runtime state, logs, SITL files, generated videos, and blackbox data belong under `runtime/`.

## Safety Rules

- Keep `executor.send_commands: false` as the default.
- Mission stages must return `FlightCommand`.
- All continuous commands must pass through `CommandShaper` and `FlightCommandExecutor`.
- Mission stages must not call MAVLink or `telemetry_link.LinkManager` directly.
- `yolo_app/` must not connect to MAVLink or generate flight commands.

## Configuration

- App configuration: `config/app.yaml`
- Telemetry configuration: `config/telemetry.yaml`
- YOLO configuration: `yolo_app/config.yaml`
- Mission configuration: `missions/<mission_name>/config.yaml`

## Read Before Editing

1. `README.md`
2. `docs/architecture.md`
3. `docs/interfaces.md`
4. `docs/ai_development_rules.md`
5. `docs/control_flow.md`
6. `docs/safety.md`

Use `docs/new_session_checklist.md` to select additional files for the task.
