# 当前模块边界

架构总裁决见 [current_architecture.md](current_architecture.md)。

## app

- `main.py`：加载配置并创建 `SystemRunner`。
- `system_runner.py`：当前生命周期总控；文件过大，后续机械拆分。
- `action_runtime.py`：管理 ActionRunner 生命周期及结果派发。
- `mission_orchestrator.py`：编排 Action Mission 步骤、黑板和失败跳转。
- `action_dispatcher.py`：当前 Action request 到 LinkManager 的唯一 app 层路由。
- `runtime_context.py`：构造 Action context；暂存 Field Reference 第一版，后续抽离。
- `service_manager.py`：YOLO UDP、fusion 和 telemetry 服务。

app 不构造 MAVLink message。ActionDispatcher 只能调用 LinkManager 公开接口，并保留
SEND 双门控、停止和清队列语义。

## missions/common/actions

这里是当前 Action 实现位置。Action 读取 context，返回 `ActionResult` 及结构化
request；不直接调用 LinkManager/pymavlink，不启动 UI、socket 或后台线程。

不得新增 `missions/<mission>/mission.py` 或 `missions/<mission>/stages/<stage>`。

## web_ui

唯一正式人工操作入口，提供状态、Action Lab、Action Mission、安全操作、地图、
视频、日志和配置页面。UI 操作必须通过 SystemRunner/API 进入既有业务边界。

## telemetry_link

维护 DroneState/GimbalState/LinkStatus、命令队列和 MAVLink 发送。不读取 YOLO，不做
目标识别、任务编排或 FIELD 坐标业务决策。

## fusion

融合感知和飞控/云台状态，不编排 Action、不发送命令。

## yolo_app

使用 RKNNLite 在 RK3588 NPU 推理并发布 UDP JSON/MJPEG。不连接 MAVLink，不生成
飞行命令。默认部署模型为 `data/models/cuadc-fp16.rknn`。

## uav_ui

terminal/curses UI deprecated，Web UI 已取代正式入口。但 `control_switches.py`、
`ui_commands.py`、`yolo_command_client.py` 等仍被 app 导入，因此目录暂时不能删除；
应先迁至中立 app 模块并完成 Web 功能覆盖检查。

## 安全未决项

旧 CommandShaper/FlightCommandExecutor 不在当前 Action 主线。连续 BODY_NED 和
`flight_command` 的 Action-compatible shaping/限幅边界需要另行裁决，不能在清理旧
代码时顺手恢复或省略。见 [../reference/safety.md](../reference/safety.md)。
