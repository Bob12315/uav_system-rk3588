# 任务阅读清单

所有任务先读：

```text
README.md
AGENTS.md
docs/ai/current_architecture.md
docs/ai/action_contracts.md
docs/ai/deprecated_paths.md
docs/developer/coordinate_frames.md
docs/developer/field_origin_heading.md
docs/developer/safety.md
```

## Action 行为

追加：目标 `missions/common/actions/*.py`、`base.py`、`result.py`、`runner.py`、
`application/action_runtime.py`、`guidance/`、相关 `tests/unit/mission/` 与 `tests/unit/domain/`。

## Action Mission

追加：`missions/engine.py`、`config/action_missions/*.json`、
`scripts/validate_action_missions.py` 和 orchestrator/template 测试。

## 派发和连续命令

追加：`execution/dispatcher.py`、`execution/policy.py`、`application/action_runtime.py`、
`telemetry_link/link_manager.py`、`command_queue.py`、`command_sender.py`、相关测试。
这是高风险边界；确认 stop/zero、双门控和断线清理。

## Field Reference/坐标

追加：`field/context.py`、`missions/common/actions/goto_waypoint.py`、涉及 FIELD 的
Action、Web UI Field Heading 代码和坐标测试。不得复制第三份转换公式。

## Web UI

追加：`application/web_services.py`、`web_ui/server.py`、`web_ui/api_routers.py`、
`web_ui/routers/`、`static/index.html`、`static/app.js`、`static/js/` 和 Web contract/integration tests。
不要把 terminal UI 当正式入口，也不要把 SystemRunner 注入 Web。

## YOLO

追加：`yolo_app/README.md`、`config/yolo.yaml`、`yolo_app/config.py`、
`rknn_detector.py`、publisher/receiver 协议和 YOLO 测试。

## 禁止按旧清单工作

以下路径 missing/deprecated，不得新增以满足旧测试：

```text
missions/<mission>/mission.py
missions/<mission>/stages/<stage>
missions.visual_tracking
missions.rescue_competition
missions.common.control
```
