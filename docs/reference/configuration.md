# 配置说明

## 当前配置分层

| 路径 | 用途 |
| --- | --- |
| `config/app.yaml` | app 生命周期、服务、Web UI、blackbox 和系统 SEND 默认值 |
| `config/telemetry.yaml` | MAVLink 数据源、端点、频率、超时和发送参数 |
| `config/yolo.yaml` | RKNN 模型、视频源、UDP、显示和录像 |
| `config/action_missions/*.json` | 当前 Action Mission 模板 |
| `config/profiles/rk3588-real/` | 实机 profile |
| `config/profiles/rk3588-sitl/` | SITL profile |

旧 `missions/<mission_name>/config.yaml` 属于 deprecated mission/stage 架构，不再作为
新任务配置位置。

## app.yaml

关键安全项：

```yaml
ui:
  web_enabled: true
  terminal_enabled: false

executor:
  send_commands: false
```

- Web UI 是正式操作入口。
- terminal/curses UI deprecated，虽然配置开关和代码尚待迁移清理。
- `send_commands` 默认必须为 false；连接 telemetry 不等于允许实发。
- `mission.name: visual_tracking` 是旧配置残留；当前依赖缺失时运行时降级为
  `action_lab_only`。后续配置清理阶段再修改 YAML，本阶段只记录事实。

## Action Mission JSON

模板由 Web UI 加载并交给 MissionOrchestrator。步骤引用
`missions/common/actions/` 注册的 Action，可包含 params、label、save_as、失败策略和
重试。修改后运行：

```bash
python scripts/validate_action_missions.py
```

新坐标参数方向见 [../ai/action_contracts.md](../ai/action_contracts.md)。

## telemetry.yaml

根配置选择 `real` 或 `sitl` 数据源；具体端点必须按硬件/仿真环境确认。
`control_send_rate_hz` 限制连续命令发送频率。断线时必须清空连续控制和云台速率
命令。切换数据源或重连后系统 SEND 保持关闭。

## yolo.yaml

当前部署模型是：

```text
data/models/cuadc-fp16.rknn
```

配置相对路径应为：

```yaml
model_path: "../data/models/cuadc-fp16.rknn"
```

已知冲突：根 `config/yolo.yaml` 当前仍指向不存在的
`cuadc2026-fp16.rknn`，而 real profile 和部署文件使用 `cuadc-fp16.rknn`。该 YAML
修改留到后续配置清理阶段。

RK3588/RKNN 可以支持 INT8，但本项目当前 INT8 模型已废弃。除非重新量化、校准并
验证检测正常，否则不得切回 INT8 默认部署。

## profile 切换

```bash
bash scripts/config/apply_rk3588_real.sh
bash scripts/config/apply_rk3588_sitl.sh
bash scripts/config/save_rk3588_real.sh
bash scripts/config/save_rk3588_sitl.sh
```

脚本执行前必须确认 `executor.send_commands: false`。不要把运行日志、录像或 SITL
产物写入 config/data；它们属于 `runtime/`。

## Web 配置编辑

Web UI 可以预览、保存和恢复允许的配置文件。应用/重连/重启前必须关闭 SEND，完成
后也不得自动重新开启。配置中的 bool 必须使用 YAML 原生 `true/false`，不能使用
字符串。
