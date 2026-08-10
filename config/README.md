# 比赛系统配置

程序直接读取 `config/` 下的生效配置。修改实机参数前应保存当前版本，并始终保持
`config/app.yaml` 中 `executor.send_commands: false`，直到完成干跑和 SITL 验证。

## 生效配置

| 路径 | 用途 |
| --- | --- |
| `config/app.yaml` | app 生命周期、服务、Web UI、blackbox 和系统 SEND |
| `config/telemetry.yaml` | MAVLink 数据源、端点、频率和超时 |
| `config/yolo.yaml` | RKNN 模型、摄像头、阈值、UDP 和视频流 |
| `config/action_missions/*.json` | 完整比赛和分项 Action Mission 模板 |
| `config/field_profiles/*.json` | 比赛场地、现场初始化模板和 SITL 场地 |

旧 `missions/<mission_name>/config.yaml` 属于 deprecated mission/stage 架构，不再是
比赛任务配置入口，也不得新增以恢复旧任务栈。

## Action Mission 模板

| 文件 | 定位 |
| --- | --- |
| `rescue_2026_full_auto_v2.json` | 当前完整 GPS-first 比赛流程 |
| `drop_two_targets_v2.json` | 双目标投放分项流程 |
| `recon_gps_v2.json` | GPS 危险标识侦察分项流程 |
| `rescue_2026_full_auto.json` | 第一版完整任务，回归参考 |
| `drop_two_targets_v1.json` | 第一版双目标投放，稳定性参考 |
| `recon_sequence_v1.json` | 第一版侦察组合流程 |
| `recon_inspect_5_targets_stepwise_v1.json` | 旧分步五目标检查流程 |
| `recon_inspect_5_targets_stepwise_v2.json` | 第二版分步侦察与报告流程 |

模板由 Web UI 加载并交给 `MissionOrchestrator`。修改后必须运行：

```bash
python scripts/validate_action_missions.py
```

validator 只检查模板结构和引用，不代表通过 SITL 或实飞验证。

## Field Profile

- `competition_runtime_v3.json`：比赛现场初始化模板；输入 forward marker GPS，并在
  起飞点采样动态原点。
- `XSYU.json`：已测绘的 schema v2 固定场地 profile。
- `sitl_centerline_lane.json`：SITL 场地 profile。
- `example_*.json`：格式示例，不作为正式比赛默认值。

场地绑定完成前不得实发 FIELD 航点。详细契约见
`docs/developer/field_origin_heading.md`。

## RK3588 Profiles

```text
config/profiles/rk3588-real/   — 实机配置快照
config/profiles/rk3588-sitl/   — SITL 配置快照
```

切换生效配置：

```bash
bash scripts/config/apply_rk3588_real.sh
bash scripts/config/apply_rk3588_sitl.sh
```

保存当前调参结果到 profile：

```bash
bash scripts/config/save_rk3588_real.sh
bash scripts/config/save_rk3588_sitl.sh
```

profile apply/save 脚本在 `executor.send_commands` 不是严格 `false` 时应拒绝执行。
实机 profile 使用 `cuadc2026-fp16.rknn` 和实机 MAVLink/摄像头；SITL profile 使用
`gazebo_dataset-fp16.rknn`、UDP 14550 和仿真视频源。

## 部署

安装或刷新 systemd 用户服务：

```bash
bash scripts/deploy/install_systemd_user_services.sh --dry-run
bash scripts/deploy/install_systemd_user_services.sh --enable-now
```

配置变化后执行只读板卡检查：

```bash
bash scripts/healthcheck/check_rk3588.sh
```

日志、录像、SITL 状态和 blackbox 数据属于 `runtime/`，不得写入配置目录或提交为
正式配置。
