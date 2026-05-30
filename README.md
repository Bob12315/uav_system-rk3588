# UAV Vision Tracking Control System

这是一个面向无人机视觉跟踪任务的 Python 工程。系统由 YOLO 感知进程、MAVLink 遥测链路、融合层、mission/stage 控制层和总控编排层组成，当前主要支持：

- RK3588 NPU 上的 RKNN INT8 YOLO 目标检测与主目标选择。
- MAVLink2 遥测接入、状态缓存、动作命令和连续控制命令发送。
- 感知目标与飞控/云台状态融合。
- 斜视接近 `APPROACH_TRACK`。
- 正上方悬停 `OVERHEAD_HOLD`。
- 统一命令限幅、平滑和 dry-run 安全出口。
- curses 终端 UI 与手动控制命令。

## 架构概览

```text
yolo_app/                    telemetry_link/
RKNN INT8 YOLO (RK3588 NPU) MAVLink2 + state cache + command sender
        | UDP JSON                    |
        v                             v
fusion/ ------------------------------------------------+
PerceptionTarget + DroneState + GimbalState -> FusedState |
                                                           v
missions/common/control/input_adapter.py -> MissionStageInput
                                                           v
missions/<mission>/mission.py -> active stage
                                                           v
missions/<mission>/stages/<stage>/ -> raw FlightCommand
                                                           v
missions/common/control/command_shaper.py -> shaped FlightCommand
                                                           v
missions/common/control/executor.py -> telemetry_link.LinkManager
                                                           v
MAVLink control / gimbal commands
```

更详细的边界说明见 [docs/architecture.md](docs/architecture.md)，完整接口见 [docs/interfaces.md](docs/interfaces.md)。

## 目录结构

```text
app/              系统入口、服务编排、任务状态机、健康检查
missions/         mission、stage controller 和通用控制命令出口
fusion/           感知与遥测融合
telemetry_link/   MAVLink2 通讯、状态缓存、命令队列和发送
yolo_app/         RK3588 RKNN INT8 感知进程
uav_ui/           终端 UI 与人工命令分发
config/           新架构配置入口
tests/            单元测试
docs/             架构、接口、运行、安全和开发规则
```

## 安装环境

建议使用两个 conda 环境：`app` 环境和 `yolo` 环境。用户先自行安装适合 RK3588/aarch64 的 Miniconda/Anaconda 或 Miniforge，并自行创建两个环境；本仓库当前只提供 app 环境的一键依赖安装脚本。

```bash
conda create -n app python=3.10 -y
conda activate app
bash scripts/install_app_env.sh
```

```bash
conda create -n yolo python=3.10 -y
conda activate yolo
```

`yolo` 环境需安装 OpenCV、PyYAML、NumPy 及匹配板端 Runtime 的 `rknn-toolkit-lite2==2.3.2`。模型文件路径为：

```text
~/rk3588_yolo/rknn_model_zoo/examples/yolo11/model/best-int8-rk3588.rknn
```

大型 `.rknn`、日志、缓存文件不建议提交到 Git。

更完整的安装说明见 [docs/install.md](docs/install.md)。

## 快速运行

### 1. 启动 YOLO

```bash
conda activate yolo
cd ~/uav_project/uav_system-rk3588/yolo_app
DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0 \
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus python main.py
```

YOLO 默认通过 UDP JSON 输出主目标。控制端默认监听 `0.0.0.0:5005`，两边端口需要一致。

### 2. app dry-run，不连飞控

```bash
conda activate app
cd ~/uav_project/src
python -m app.main --send-commands false
```

### 3. app 连接 telemetry，但不发控制

```bash
python -m app.main --connect-telemetry --send-commands false
```

### 4. app 连接 telemetry 并打开终端 UI

```bash
python -m app.main --connect-telemetry --ui --send-commands false
```

UI 中可以在 app 运行时重载 mission stage 控制参数。修改 `missions/<mission_name>/config.yaml` 后输入：

```text
pid reload
```

这会重新读取 `input_adapter`、`approach_track`、`overhead_hold` 和 `shaper` 配置，并更新当前运行中的 controller。常用来现场调整 `kp_*`、`ki_*`、`kd_*`、限幅和死区参数。重载成功后，控制器内部积分/微分状态会被重置，配置文件本身不会被 UI 修改。

### 5. SITL 中实发控制

只在 SITL 或已确认安全的实机环境中使用：

```bash
python -m app.main --connect-telemetry --force-mode APPROACH_TRACK --send-commands true
```

更完整的运行手册见 [docs/running.md](docs/running.md)。

## 测试

```bash
cd ~/uav_project/src
python -m pytest -q
```

当前测试覆盖 input adapter、command shaper、mission stages、mission manager。

## 安全默认值

- `config/app.yaml` 中 `executor.send_commands` 默认应保持 `false`。
- 不传 `--connect-telemetry` 时，新 app 不连接 MAVLink。
- 不传 `--send-commands true` 时，不应向飞控发送连续控制命令。
- 所有 stage controller 输出必须经过 `CommandShaper` 和 `FlightCommandExecutor`。
- stage controller 禁止直接调用 MAVLink 或 `LinkManager`。

实机前请阅读 [docs/safety.md](docs/safety.md)。

## 文档索引

- [docs/new_session_checklist.md](docs/new_session_checklist.md)：每次开启新 AI 会话前必读。
- [docs/architecture.md](docs/architecture.md)：模块职责、依赖方向和边界。
- [docs/interfaces.md](docs/interfaces.md)：核心 dataclass、接口和单位。
- [docs/ai_development_rules.md](docs/ai_development_rules.md)：给 AI/开发者的修改规则。
- [docs/running.md](docs/running.md)：常用启动方式。
- [docs/install.md](docs/install.md)：环境和依赖安装。
- [docs/configuration.md](docs/configuration.md)：配置文件说明。
- [docs/control_flow.md](docs/control_flow.md)：从 YOLO 到 MAVLink 的数据流。
- [docs/safety.md](docs/safety.md)：安全边界和实机 checklist。
- [docs/sitl_test_plan.md](docs/sitl_test_plan.md)：SITL 测试顺序。
