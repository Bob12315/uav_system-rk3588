# UAV System for RK3588

面向 Linux ARM64 RK3588 的无人机感知、Action Mission 编排和 MAVLink 通讯工程。
YOLO 使用 RKNNLite 在 RK3588 NPU 上推理；正式人工操作入口是 Web UI。

## 当前架构

```text
yolo_app (RKNNLite / RK3588 NPU)
  → UDP perception
  → fusion + app runtime context
  → Web UI / Action Lab / Action Mission
  → ActionRuntimeService
  → ActionRunner
  → missions/common/actions/*
  → ActionDispatcher
  → LinkManager
  → telemetry_link / MAVLink / ArduPilot
```

- Action Mission 是当前唯一任务主线。
- Action 实现在 `missions/common/actions/`。
- 任务模板在 `config/action_missions/*.json`。
- Web UI 是当前唯一正式人工操作入口。
- 旧 mission/stage/CommandShaper/FlightCommandExecutor 链路已 deprecated，且依赖
  大量缺失，不得恢复或新增。
- terminal/curses UI 已 deprecated；`uav_ui/` 仍有 app 共用工具，迁移完成前不能删除。

详细裁决见 [当前架构](docs/ai/current_architecture.md) 和
[deprecated 路径](docs/ai/deprecated_paths.md)。

## 目录

| 目录 | 当前职责 |
| --- | --- |
| `app/` | 启动、服务编排、Action runtime、任务编排、状态和 Web UI 挂接 |
| `missions/common/actions/` | Action 实现 |
| `config/action_missions/` | Action Mission JSON 模板 |
| `web_ui/` | 正式浏览器控制台 |
| `telemetry_link/` | MAVLink 状态、队列和发送 |
| `fusion/` | 感知与遥测融合 |
| `yolo_app/` | RKNNLite 感知与 UDP 输出 |
| `uav_ui/` | deprecated terminal UI 与尚待迁出的共用工具 |
| `runtime/` | 日志、视频、SITL 和 blackbox 运行产物 |

## 平台与模型

本项目只支持 Linux ARM64 RK3588，不新增 x86、CUDA、PyTorch 或 GPU 推理路径。
当前默认部署模型是：

```text
data/models/cuadc-fp16.rknn
```

RK3588/RKNN 本身可以支持 INT8，但本项目当前 INT8 模型已废弃。除非重新完成量化
校准并验证检测正常，否则不要切回 INT8。

## 安装

```bash
conda create -n app python=3.10 -y
conda activate app
bash scripts/install/install_app_env.sh

conda create -n yolo python=3.10 -y
conda activate yolo
bash scripts/install/install_yolo_env.sh
```

完整安装说明见 [docs/user/install.md](docs/user/install.md)。

## 安全运行

默认必须保持：

```yaml
executor:
  send_commands: false
```

dry-run：

```bash
python -m app.main --no-yolo-udp --no-ui --run-seconds 1 \
  --send-commands false --blackbox-enabled false
```

连接 telemetry 但不发送控制：

```bash
python -m app.main --connect-telemetry --send-commands false
```

Web UI 默认地址：

```text
http://<RK3588 局域网 IP>:8080/
```

系统 SEND 和 Action send-actions 双门控必须同时满足才允许 Action 实发。连续速度
停止时必须发送 zero/stop 并清理旧命令。投放只允许
`payload_release` Action → `set_servo`；禁止 `release_payload` 和 RC override。

实机前阅读 [docs/reference/safety.md](docs/reference/safety.md)。

## 坐标系

- LOCAL_NED：北/东/下为正。
- BODY_NED：前/右/下为正。
- FIELD：`+Y` 场地前方，`+X` 场地右方。
- `altitude_m` 向上为正，`z_down_m = -altitude_m`。

详见 [坐标系规范](docs/reference/coordinate_frames.md) 和
[Field Reference](docs/reference/field_origin_heading.md)。

## 验证

```bash
python -m compileall app missions telemetry_link fusion yolo_app web_ui scripts
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
python scripts/validate_action_missions.py
```

当前基线仍有旧架构测试收集失败及若干既有主线测试失败，见
[Phase 0 基线](docs/refactor/phase0_baseline.md)。不要通过忽略它们假装全绿。

## 文档

- [文档索引](docs/README.md)
- [AI 快速接管](docs/ai/README.md)
- [当前架构](docs/ai/current_architecture.md)
- [Action 契约](docs/ai/action_contracts.md)
- [配置说明](docs/reference/configuration.md)
- [安全边界](docs/reference/safety.md)
