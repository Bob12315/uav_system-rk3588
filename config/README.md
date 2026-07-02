# Configuration

The active configuration files are tracked in Git and read directly by the
application:

```text
config/app.yaml         — 应用全局配置（executor、服务开关、系统参数）
config/telemetry.yaml   — MAVLink 遥测链接配置（连接参数、设备、端口）
config/yolo.yaml        — YOLO 感知配置（模型路径、阈值、视频源、输出）
```

## Action Mission Templates

```text
config/action_missions/*.json
```

`config/action_missions/` 存放 Action Mission JSON 模板。每个模板定义一组有序的
Action 步骤及其参数，由 Action Mission 页面加载执行。

当前模板：

| 文件 | 用途 |
| --- | --- |
| `drop_two_targets_v1.json` | 双目标投放任务 |
| `recon_inspect_5_targets_stepwise_v1.json` | 五目标侦察检查（分步） |
| `rescue_2026_full_auto.json` | 2026 救援比赛全自动任务 |

模板由 `scripts/validate_action_missions.py` 校验。

## Configuration Profiles

```text
config/profiles/rk3588-real/   — 实机部署配置档案
config/profiles/rk3588-sitl/   — SITL 仿真配置档案
```

Profiles 保存不同部署环境的 `telemetry.yaml`、`yolo.yaml` 和
`action_missions/*.json` 快照，通过 `scripts/config/apply_*.sh` 切换到工作区，
通过 `scripts/config/save_*.sh` 从工作区保存更新。

Mission-specific settings remain under `missions/<mission_name>/config.yaml`.
Generated logs, SITL state, and videos belong under `runtime/`.

## RK3588 Profiles

Use one of the explicit scripts to replace the active telemetry and YOLO
configuration:

```bash
bash scripts/config/apply_rk3588_real.sh
bash scripts/config/apply_rk3588_sitl.sh
```

After tuning the active files, save them back to a profile:

```bash
bash scripts/config/save_rk3588_real.sh
bash scripts/config/save_rk3588_sitl.sh
```

Both scripts refuse to switch profiles unless
`config/app.yaml executor.send_commands` is strictly `false`.

The real profile uses MAVLink `eth / udpin / 0.0.0.0:15001` and `/dev/video41`.
Update the camera source in `config/yolo.yaml` after applying the profile if
the board exposes a stable `/dev/v4l/by-id/...` path.

The SITL profile expects a PC to send MAVLink UDP to port `14550` and H264/RTP
video to port `5600` on the RK3588 board.

Profile save/apply manages:

```text
config/telemetry.yaml
config/yolo.yaml
config/action_missions/*.json
missions/*/config.yaml, when those mission configs exist
```

Review and commit profile changes after saving:

```bash
git diff -- config/profiles
git add config/profiles
git commit -m "Update RK3588 profile parameters"
```

## Deployment

Install or refresh the systemd user services:

```bash
bash scripts/deploy/install_systemd_user_services.sh --dry-run
bash scripts/deploy/install_systemd_user_services.sh
bash scripts/deploy/install_systemd_user_services.sh --enable-now
```

The installer renders the current repository path and Python paths into the
user service files. Override `APP_PYTHON` or `YOLO_PYTHON` if the conda
environments do not live under `~/anaconda3/envs/`.

Run the read-only board check after installation or configuration changes:

```bash
bash scripts/healthcheck/check_rk3588.sh
```
