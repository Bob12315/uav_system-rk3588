# AI 开发规则

本文给 AI 和开发者使用。修改代码前先判断任务属于哪个边界，再进入对应目录。

## 总原则

- 保持 Python 3.10 兼容。
- 不使用 `StrEnum`，枚举用 `class X(str, Enum)`。
- dataclass 优先使用 `slots=True`。
- 配置从 YAML 加载后必须转换成 dataclass。
- bool 配置必须严格解析，禁止 `bool("false")` 这种写法。
- 控制量单位必须明确：速度 `m/s`，角速度 `rad/s`。
- 不要把控制算法、MAVLink 发送、UI 和服务启动混在一个文件里。
- 不要为了短期方便绕过 `CommandShaper` 和 `FlightCommandExecutor`。

## 修改控制算法时

应该改：

- `missions/<mission_name>/stages/<stage_name>/`
- `missions/common/control/`
- `missions/<mission_name>/config.yaml`
- 对应 `tests/test_*.py`

不应该碰：

- `telemetry_link/command_sender.py`
- `telemetry_link/mavlink_client.py`
- `app/system_runner.py`，除非接口真的变了。
- `yolo_app/`。

要求：

- stage controller 输出 `FlightCommand`。
- 新参数放到对应 config dataclass 和 `missions/<mission_name>/config.yaml`。
- 添加或更新单元测试。

## 修改任务流程时

应该改：

- `missions/`
- `app/mission_runner.py`
- `app/system_runner.py`，仅当调度接口变化。
- `missions/<mission_name>/config.yaml`
- `tests/test_*mission*.py`

不应该碰：

- 具体控制公式。
- MAVLink 发送逻辑。
- YOLO tracking 逻辑。

要求：

- mission 只选择阶段、active mode 和通用 action，不计算速度。
- 任务动作必须用 `MissionAction`，由 `MissionRunner` 转发。
- 新状态必须有清晰进入/退出条件。

## 修改 MAVLink 或飞控通讯时

应该改：

- `telemetry_link/`
- `config/telemetry.yaml`
- `telemetry_link/COMMAND_AUDIT.md`
- 必要时更新 `docs/interfaces.md`

不应该碰：

- `missions/<mission_name>/stages/<stage_name>/` 控制算法。
- `fusion/`。
- `yolo_app/`。

要求：

- 保持 `LinkManager` 公开接口稳定。
- action 命令走 `ActionCommand`。
- 连续机体命令走 `ControlCommand`。
- 云台速率命令走 `GimbalRateCommand`。
- 断线时不应继续发送连续控制命令。

## 修改 YOLO 时

应该改：

- `yolo_app/`
- `config/yolo.yaml`
- 必要时更新 UDP JSON 协议文档。

不应该碰：

- `telemetry_link/`
- `missions/<mission_name>/stages/`
- `missions/`

要求：

- 保持 UDP JSON 字段兼容，尤其是 `target_valid`、`track_id`、`target_size`、`ex`、`ey`。
- 不在 YOLO 进程内连接 MAVLink。

## 修改 fusion 时

应该改：

- `fusion/`
- `tests/` 中相关融合测试。

不应该碰：

- MAVLink 发送器。
- mission stage controller 控制律，除非输出字段语义变化。

要求：

- `FusedState` 字段语义变化必须更新 [interfaces.md](interfaces.md)。
- 坐标系或单位变化必须全链路说明。

## 修改 UI 时

应该改：

- `uav_ui/`
- `app/system_runner.py` 中 UI 挂接部分，必要时。

不应该碰：

- 控制公式。
- MAVLink message 构造。

要求：

- UI 命令必须通过已有 manager/client 分发。
- UI 不直接访问底层 pymavlink。

## 新增 mission stage 流程

1. 在 `missions/<mission_name>/stages/<new_stage>/` 新建 `config.py` 和 `mode.py`。
2. 实现 `MissionStage` 接口。
3. 在 `app/stage_registry.py` 注册。
4. 在对应 mission 中增加进入/退出条件。
5. 在 `missions/<mission_name>/config.yaml`、`missions/<mission_name>/config.yaml` 和必要的 app 配置中加配置。
6. 增加 `tests/test_<new_mode>.py`。
7. 更新 [docs/interfaces.md](interfaces.md) 和 [docs/architecture.md](architecture.md)。

## 日志风格

- 主循环日志写 active mode、health、raw command、shaped command。
- telemetry 日志写 source、connection、target_system/component、reconnect 原因。
- dry-run 必须明确出现 `DRY` 或 `send_commands=false`。
- 不在高频循环中打印过长对象。

## 测试要求

每次结构性修改后运行：

```bash
python -m pytest -q
python -m app.main --no-yolo-udp --run-seconds 1 --send-commands false
```

涉及 telemetry 嵌入时运行：

```bash
python -m app.main --connect-telemetry --no-yolo-udp --run-seconds 1 --send-commands false
python -m telemetry_link.main --help
```

## 禁止清单

- 禁止 mission stage controller 直接调用 `LinkManager`。
- 禁止绕过 `CommandShaper`。
- 禁止默认打开真实控制发送。
- 禁止把 `.pt`、日志、`__pycache__` 作为功能变更提交。
- 禁止用单元测试依赖真实飞控、相机、GPU。
