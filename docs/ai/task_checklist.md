# 新会话必读清单

每次开启新的 AI 会话，先让 AI 阅读本文。本文的目标是让新会话快速建立项目边界，避免把控制、通信、感知和 UI 混在一起改。

## 必读核心文件

无论任务大小，都先阅读：

```text
README.md
docs/ai/README.md
docs/ai/architecture.md
docs/ai/interfaces.md
docs/ai/development_rules.md
docs/ai/control_flow.md
docs/reference/safety.md
```

读完后，AI 必须能说明：

- `app/`、`missions/visual_tracking/stages/`、`fusion/`、`telemetry_link/`、`yolo_app/`、`uav_ui/` 分别负责什么。
- `missions/` 与 `app/mission_runner.py` 分别负责什么。
- `MissionStageInput`、`FlightCommand`、`LinkManager` 的接口边界。
- 为什么 mission stage controller 不能直接调用 MAVLink。
- 为什么所有控制命令必须经过 `CommandShaper` 和 `FlightCommandExecutor`。
- 为什么 `send_commands` 默认不能打开。

## 推荐给 AI 的开场提示词

可以直接复制：

```text
你先阅读以下文件，严格遵守里面的架构边界、接口契约和 AI 开发规则，再开始改代码：

README.md
docs/ai/architecture.md
docs/ai/interfaces.md
docs/ai/development_rules.md
docs/ai/control_flow.md
docs/reference/safety.md

不要绕过 CommandShaper 和 FlightCommandExecutor。
不要让 mission stage controller 直接调用 telemetry_link。
不要默认打开 send_commands。
不要把 YOLO、fusion、telemetry、mission stage controller、UI 的职责混在一起。

看完后先用简短中文总结你理解的模块边界，再执行我的任务。
```

## 按任务追加阅读

### 改控制算法或 mission stage controller

追加阅读：

```text
missions/<mission_name>/config.yaml
missions/base_stage.py
missions/common/control/types.py
missions/common/control/input_adapter.py
missions/common/control/command_shaper.py
missions/common/control/executor.py
missions/visual_tracking/stages/approach_track/mode.py
missions/visual_tracking/stages/overhead_hold/mode.py
tests/test_approach_track.py
tests/test_overhead_hold.py
tests/test_command_shaper.py
```

允许主要修改：

```text
missions/visual_tracking/stages/
missions/<mission_name>/config.yaml
tests/test_*.py
```

不要碰：

```text
telemetry_link/command_sender.py
telemetry_link/mavlink_client.py
yolo_app/
```

### 改任务流程或模式切换

追加阅读：

```text
app/README.md
app/system_runner.py
app/mission_runner.py
app/stage_registry.py
app/health_monitor.py
missions/base.py
missions/visual_tracking/mission.py
missions/rescue_competition/mission.py
missions/common/navigation.py
config/app.yaml
missions/visual_tracking/config.yaml
missions/rescue_competition/config.yaml
tests/test_mission_runner.py
tests/test_visual_tracking_mission.py
tests/test_rescue_competition_mission.py
```

允许主要修改：

```text
missions/
app/mission_runner.py
app/system_runner.py
config/app.yaml
missions/<mission_name>/config.yaml
tests/test_*mission*.py
```

不要碰：

```text
telemetry_link/command_sender.py
yolo_app/
missions/visual_tracking/stages/<mode>/ 控制公式，除非任务明确要求
```

### 改 telemetry 或 MAVLink

追加阅读：

```text
telemetry_link/README.md
telemetry_link/COMMAND_AUDIT.md
telemetry_link/models.py
telemetry_link/link_manager.py
telemetry_link/command_queue.py
telemetry_link/command_sender.py
telemetry_link/state_cache.py
telemetry_link/telemetry_receiver.py
telemetry_link/mavlink_client.py
config/telemetry.yaml
```

允许主要修改：

```text
telemetry_link/
config/telemetry.yaml
telemetry_link/COMMAND_AUDIT.md
docs/ai/interfaces.md
```

不要碰：

```text
missions/visual_tracking/stages/<mode>/ 控制算法
yolo_app/
fusion/，除非 telemetry 状态接口变化
```

### 改 YOLO

追加阅读：

```text
yolo_app/README.md
config/yolo.yaml
yolo_app/main.py
yolo_app/models.py
yolo_app/udp_publisher.py
yolo_app/target_manager.py
app/service_manager.py
docs/ai/interfaces.md
```

允许主要修改：

```text
yolo_app/
config/yolo.yaml
docs/ai/interfaces.md，若 UDP 字段变化
```

不要碰：

```text
telemetry_link/
missions/visual_tracking/stages/
missions/
```

### 改 fusion

追加阅读：

```text
fusion/README.md
fusion/models.py
fusion/fusion_manager.py
fusion/rules.py
missions/common/control/input_adapter.py
docs/ai/interfaces.md
```

允许主要修改：

```text
fusion/
missions/common/control/input_adapter.py，若 FusedState 字段变化
docs/ai/interfaces.md
tests/
```

不要碰：

```text
telemetry_link/command_sender.py
yolo_app/ tracking 逻辑
missions/visual_tracking/stages/<mode>/ 控制公式，除非字段语义变化
```

### 改 UI

追加阅读：

```text
uav_ui/README.md
uav_ui/terminal_ui.py
uav_ui/ui_commands.py
uav_ui/control_switches.py
app/system_runner.py
app/service_manager.py
```

允许主要修改：

```text
uav_ui/
app/system_runner.py 的 UI 挂接部分
```

不要碰：

```text
missions/visual_tracking/stages/<mode>/ 控制公式
telemetry_link/command_sender.py
yolo_app/
```

### 改配置、安装或运行文档

追加阅读：

```text
docs/user/running.md
docs/user/install.md
docs/reference/configuration.md
config/app.yaml
missions/visual_tracking/config.yaml
missions/rescue_competition/config.yaml
missions/<mission_name>/config.yaml
config/telemetry.yaml
config/yolo.yaml
```

允许主要修改：

```text
README.md
docs/
config/
```

注意：

- bool 必须使用 YAML 原生 `true/false`。
- 不要把 `send_commands` 默认改成 true。

## 新会话执行前检查

AI 开始改代码前应回答：

```text
我将修改哪些文件？
这些文件属于哪个模块边界？
是否会影响 send_commands 或 MAVLink 发送？
需要增加或更新哪些测试？
```

## 常用验证命令

每次结构性修改后至少运行：

```bash
python -m pytest -q
python -m app.main --no-yolo-udp --run-seconds 1 --send-commands false
```

涉及 telemetry 嵌入时运行：

```bash
python -m app.main --connect-telemetry --no-yolo-udp --run-seconds 1 --send-commands false
python -m telemetry_link.main --help
```

涉及运行文档时，至少确认命令和当前 CLI 参数一致：

```bash
python -m app.main --help
python -m telemetry_link.main --help
```

## 禁止默认行为

- 禁止默认打开 `send_commands`。
- 禁止让 mission stage controller 直接调用 `LinkManager`。
- 禁止绕过 `CommandShaper`。
- 禁止绕过 `FlightCommandExecutor`。
- 禁止让 YOLO 进程连接 MAVLink。
- 禁止让 telemetry_link 读取 YOLO 或计算控制律。
- 禁止把 `.pt`、日志、`__pycache__` 当功能改动提交。
