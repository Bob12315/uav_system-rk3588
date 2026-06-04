# 架构边界

本文定义各模块职责、允许依赖和禁止事项。后续改代码时优先遵守本文，再看具体实现。

## 总体原则

```text
missions 决定“现在做什么”
missions/<name>/stages 决定“当前阶段怎么飞”
command_shaper 决定“命令是否过猛”
executor 决定“怎么交给 telemetry_link”
telemetry_link 决定“怎么发 MAVLink”
```

任何模式输出都必须经过：

```text
MissionStage.update()
  -> FlightCommand raw
  -> CommandShaper.update()
  -> FlightCommand shaped
  -> FlightCommandExecutor.execute()
  -> telemetry_link.LinkManager
```

## app/

职责：

- `main.py`：总入口，只解析参数、加载配置、创建 `SystemRunner`。
- `system_runner.py`：系统主循环，串联服务、融合、mission runner、stage controller 和执行器。
- `mission_runner.py`：调用当前 mission，处理 `MissionAction` 的 once guard，并把 action 转发给 `LinkManager`。
- `service_manager.py`：启动和停止 YOLO UDP 接收、telemetry link、fusion manager。
- `health_monitor.py`：判断 vision/drone/gimbal/fusion/control 健康状态。
- `debug_runtime.py`：强制模式、强制通道开关和 dry-run 调试覆盖。
- `app_config.py`：统一加载 `config/*.yaml`。
- `stage_registry.py`：注册和获取 mission stage controller 实例。

允许依赖：

- `fusion`
- `telemetry_link`
- `missions`
- `uav_ui`
- `config/*.yaml`

禁止事项：

- 不写具体 PID/P 控制公式。
- 不直接构造 MAVLink message。
- 不直接调用 pymavlink。
- 不绕过 `CommandShaper` 和 `FlightCommandExecutor` 发送控制。

## missions/

职责：

- 定义任务流程接口和通用任务输出。
- 决定任务阶段、active stage controller 和一次性动作请求。
- `visual_tracking/mission.py`：保留现有视觉跟踪任务行为。
- `visual_tracking/stages/`：视觉跟踪任务的连续控制阶段，例如斜视接近、正上方悬停。
- `rescue_competition/mission.py`：比赛任务流程，包含起飞、投放区扫描建图、
  投放目标规划、低空微调投放、侦察区扫描建图、低空识别、返航和降落。
- `rescue_competition/stages/downward_align_descend/`：比赛任务专用固定下视相机
  微调下降，只输出机体前后、左右、上下速度，不持续控制云台，不输出偏航。
- `common/navigation.py`：任务层本地坐标转换和到点判断。

允许依赖：

- `missions.common.control.types.MissionStageInput`
- `fusion.models.PerceptionTarget`
- `telemetry_link.models.DroneState/GimbalState/LinkStatus`
- `app.health_monitor.HealthStatus`

禁止事项：

- Mission 不直接调用 pymavlink。
- Mission 不直接构造 MAVLink message。
- Mission 不写 PID 或控制律。
- Mission 只能通过 `MissionAction` 请求 `takeoff`、`land`、`local_position`、
  `set_servo`、`set_relay` 等通用动作。
- Mission 不应把具体控制命令绕过 `MissionRunner` 发给 `LinkManager`。

## missions/<mission_name>/stages/

职责：

- 定义任务内部阶段控制器。
- 将 `MissionStageInput` 转成 `FlightCommand`。
- 按任务阶段拆分控制逻辑，例如视觉跟踪任务里的斜视接近、正上方悬停。

允许依赖：

- `missions.common.control.types`

禁止事项：

- stage controller 里不得直接 import `telemetry_link.link_manager`。
- stage controller 里不得直接发送 MAVLink。
- stage controller 里不得读取 YAML。
- stage controller 里不得启动线程、socket 或 UI。
- stage controller 里不得决定全局任务流程跳转，任务跳转属于 mission。

## missions/common/control/

职责：

- `types.py`：公开 `MissionStageInput`、`FlightCommand`、`MissionStageStatus`。
- `input_adapter.py`：`FusedState -> MissionStageInput`。
- `command_shaper.py`：统一限幅、slew rate、disabled 通道归零。
- `executor.py`：将 shaped `FlightCommand` 交给 `telemetry_link`。
- `debug_config.py`：stage controller 层调试配置。

禁止事项：

- `command_shaper.py` 不应知道具体 mission 阶段。
- `executor.py` 不应计算控制律。
- `input_adapter.py` 不应发送命令。

## fusion/

职责：

- 接收 YOLO 主目标、DroneState、GimbalState。
- 输出统一 `FusedState`。
- 计算相机误差、机体系误差、数据有效性和控制允许状态。

允许依赖：

- `telemetry_link.models`
- `yolo_app` 输出协议对应的数据结构，当前通过 `PerceptionTarget` 表达。

禁止事项：

- 不决定任务阶段。
- 不生成控制命令。
- 不发送 MAVLink。
- 不启动 YOLO 或 telemetry 服务。

## telemetry_link/

职责：

- 建立 MAVLink2 连接。
- 维护 `DroneState`、`GimbalState`、`LinkStatus`。
- 管理连续控制命令、云台速率命令和 action 命令队列。
- 封装 ArduPilot/MAVLink 发送细节。
- 断线自动重连。

允许依赖：

- `pymavlink`
- Python 标准库
- `uav_ui` 仅用于终端 UI 展示和人工命令分发。

禁止事项：

- 不读取 YOLO UDP。
- 不计算目标跟踪控制律。
- 不依赖 mission stage controller 或 `app`。
- 不决定任务阶段或 `APPROACH_TRACK` / `OVERHEAD_HOLD`。

## yolo_app/

职责：

- 读取视频源。
- 在 RK3588 NPU 上调用 RKNNLite 执行 RKNN INT8 推理。
- 使用短时 IoU 关联维护跨帧 `track_id`。
- 维护主目标。
- 通过 UDP JSON 输出当前主目标。
- 接收目标选择相关的简单命令。
- 发布已经标注的 MJPEG 网页视频流。

禁止事项：

- 不连接 MAVLink。
- 不读取 telemetry 状态。
- 不生成飞控速度或云台控制命令。

## uav_ui/

职责：

- 终端状态展示。
- 人工命令输入。
- 将人工命令分发给 `telemetry_link` 或 YOLO command client。

禁止事项：

- 不直接解析 YOLO 图像。
- 不直接计算 stage controller 控制律。
- 不绕过 `telemetry_link` 发送 MAVLink。

## web_ui/

职责：

- 随 `app.main` 启动 FastAPI 浏览器控制台。
- 通过现有 UI 命令分发和 `SystemRunner` 受控操作执行人工动作。
- 推送结构化状态、重要事件和持久化操作审计。
- 仅对白名单 YAML 提供保存、单级恢复和应用操作。

禁止事项：

- 不直接构造或发送 MAVLink message。
- 不直接计算控制律。
- 不开放任意文件路径。
- 配置应用、通信重连或 app 重启前不得绕过 `SEND=OFF` 安全动作。

## config/

职责：

- `app.yaml`：运行时、服务开关、executor。
- `telemetry.yaml`：MAVLink 连接和消息频率。
- `../missions/<mission_name>/config.yaml`：具体 mission 的任务参数、input adapter、阶段控制器参数、shaper。

禁止事项：

- 不把大模型路径、视频源和 telemetry 混在一个没有边界的配置里。
- bool 值必须写 `true/false`，不要写字符串或拼错。

## tests/

职责：

- 覆盖纯逻辑和接口契约。
- 优先测试 input adapter、missions、mission runner、stage controller、command shaper。

禁止事项：

- 单元测试不应要求真实飞控。
- 单元测试不应要求 GPU、相机或 YOLO 模型。
