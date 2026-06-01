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

更详细的边界说明见 [docs/ai/architecture.md](docs/ai/architecture.md)，完整接口见 [docs/ai/interfaces.md](docs/ai/interfaces.md)。

## 目录结构

```text
app/              系统入口、服务编排、任务状态机、健康检查
missions/         mission、stage controller 和通用控制命令出口
fusion/           感知与遥测融合
telemetry_link/   MAVLink2 通讯、状态缓存、命令队列和发送
yolo_app/         RK3588 RKNN INT8 感知进程
uav_ui/           终端 UI 与人工命令分发
web_ui/           浏览器控制台、配置编辑和操作审计
config/           当前生效的系统配置与 RK3588 配置模板
data/             跟踪提交的 RKNN 模型和 SITL 地形数据
scripts/          配置切换、安装、部署和健康检查脚本
deploy/           systemd 用户服务模板
runtime/          日志、视频和 SITL 运行产物，不提交 Git
tests/            单元测试
docs/             用户手册、参考文档和 AI 接管材料
```

## 安装环境

建议使用两个 conda 环境：`app` 环境和 `yolo` 环境。用户先自行安装适合 RK3588/aarch64 的 Miniconda/Anaconda 或 Miniforge，并自行创建两个环境；仓库为两个环境分别提供依赖安装脚本。

```bash
conda create -n app python=3.10 -y
conda activate app
bash scripts/install/install_app_env.sh
```

```bash
conda create -n yolo python=3.10 -y
conda activate yolo
bash scripts/install/install_yolo_env.sh
```

`yolo` 环境需安装 OpenCV、PyYAML、NumPy 及匹配板端 Runtime 的 `rknn-toolkit-lite2==2.3.2`。仓库已包含部署模型：

```text
data/models/best-int8-rk3588.rknn
```

运行状态、日志、缓存和生成视频统一写入 `runtime/`，不提交到 Git。

更完整的安装说明见 [docs/user/install.md](docs/user/install.md)。

安装用户级 systemd 服务并执行板端健康检查：

```bash
bash scripts/deploy/install_systemd_user_services.sh --enable-now
bash scripts/healthcheck/check_rk3588.sh
```

## 使用 AI 部署

在 RK3588 板端打开 AI 编程助手，并将工作目录切换到本仓库后，可以直接发送
下面的提示词。AI 应先检查环境，再执行能够安全确认的安装和部署步骤；涉及
`sudo`、硬件参数或飞控实发控制时，需要先向用户说明并等待确认。

```text
请在当前仓库完成 RK3588 板端部署。

部署规则：
1. 本项目只支持 Linux ARM64 RK3588。YOLO 只能使用 RKNNLite、RK3588 NPU
   和 data/models/best-int8-rk3588.rknn，不要添加 x86、CUDA、PyTorch 或 GPU
   推理路径。
2. 先阅读 AGENTS.md、docs/user/install.md、docs/user/running.md 和
   docs/reference/safety.md，再检查 git status。不要覆盖我已有的本地配置，
   不要使用 git reset --hard 或 git checkout --。
3. 检查 app 和 yolo conda 环境。缺少环境时，按 README 创建 Python 3.10
   环境，并分别执行 scripts/install/install_app_env.sh 和
   scripts/install/install_yolo_env.sh。
4. 检查 config/app.yaml、config/telemetry.yaml 和 config/yolo.yaml。
   executor.send_commands 必须保持 false。摄像头、飞控端点或网络参数无法确认时，
   列出需要我补充的信息，不要猜测。
5. 先运行 bash scripts/deploy/install_systemd_user_services.sh --dry-run，
   确认生成内容后再安装用户级 systemd 服务。需要执行 sudo loginctl
   enable-linger "$USER" 时，先说明用途并等待我确认。
6. 运行 bash scripts/healthcheck/check_rk3588.sh，并检查两个用户服务的状态和日志。
   能安全修复的问题直接修复；涉及硬件、sudo 或飞控控制的问题先向我确认。
7. 不要开启飞控指令发送，不要把 executor.send_commands 改为 true。
8. 最后汇报：执行过的命令、修改过的文件、服务状态、健康检查结果、仍需人工确认
   的硬件参数，以及如何访问 Web UI。
```

部署后的 Web UI 默认地址为：

```text
http://<RK3588 局域网 IP>:8080/
```

## 快速运行

### 1. 启动 YOLO

```bash
conda activate yolo
cd ~/uav_project/uav_system-rk3588
DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0 \
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus python -m yolo_app.main
```

YOLO 默认通过 UDP JSON 输出主目标。控制端默认监听 `0.0.0.0:5005`，两边端口需要一致。

### 2. app dry-run，不连飞控

```bash
conda activate app
cd ~/uav_project/uav_system-rk3588
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

这会重新读取 `input_adapter`、健康监控阈值、`approach_track`、
`overhead_hold` 和 `shaper` 配置，并更新当前运行中的 controller。常用来现场
调整 `kp_*`、`ki_*`、`kd_*`、限幅和死区参数。重载成功后，控制器内部
积分/微分状态会被重置，配置文件本身不会被 UI 修改。

### 5. SITL 中实发控制

只在 SITL 或已确认安全的实机环境中使用：

```bash
python -m app.main --connect-telemetry --force-mode APPROACH_TRACK --send-commands true
```

更完整的运行手册见 [docs/user/running.md](docs/user/running.md)。

## 测试

开发机或需要运行测试的板端先安装开发依赖：

```bash
python -m pip install -r requirements-dev.txt
```

然后运行：

```bash
cd ~/uav_project/uav_system-rk3588
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

当前测试覆盖 input adapter、command shaper、missions、stage controllers、UI、
telemetry 和 RKNN 接口。

## 安全默认值

- `config/app.yaml` 中 `executor.send_commands` 默认应保持 `false`。
- 是否连接 telemetry 由 `config/app.yaml` 的 `services.connect_telemetry` 决定；
  `--connect-telemetry` 可以临时打开连接。
- 不传 `--send-commands true` 时，不应向飞控发送连续控制命令。
- 所有 stage controller 输出必须经过 `CommandShaper` 和 `FlightCommandExecutor`。
- stage controller 禁止直接调用 MAVLink 或 `LinkManager`。

实机前请阅读 [docs/reference/safety.md](docs/reference/safety.md)。

## 文档索引

- [docs/README.md](docs/README.md)：完整文档索引。
- [docs/user/README.md](docs/user/README.md)：用户快速上手说明。
- [docs/ai/README.md](docs/ai/README.md)：AI 快速接管入口。
- [docs/reference/configuration.md](docs/reference/configuration.md)：配置说明。
- [docs/reference/safety.md](docs/reference/safety.md)：安全边界和实机 checklist。
