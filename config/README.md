# Configuration

The active configuration files are tracked in Git and read directly by the
application:

```text
config/app.yaml
config/telemetry.yaml
config/yolo.yaml
```

Mission-specific settings remain under `missions/<mission_name>/config.yaml`.
Generated logs, SITL state, and videos belong under `runtime/`.

## RK3588 Profiles

Use one of the explicit scripts to replace the active telemetry and YOLO
configuration:

```bash
bash scripts/config/apply_rk3588_real.sh
bash scripts/config/apply_rk3588_sitl.sh
```

Both scripts refuse to switch profiles unless
`config/app.yaml executor.send_commands` is strictly `false`.

The real profile uses MAVLink `eth / udpin / 0.0.0.0:15001` and `/dev/video41`.
Update the camera source in `config/yolo.yaml` after applying the profile if
the board exposes a stable `/dev/v4l/by-id/...` path.

The SITL profile expects a PC to send MAVLink UDP to port `14550` and H264/RTP
video to port `5600` on the RK3588 board.
