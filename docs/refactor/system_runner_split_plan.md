# SystemRunner 拆分分析计划

> **基线**：`efef363` — `merge: remove terminal ui dependency`
> **文件**：`app/system_runner.py` ~1924 行，85 个方法（41 个 private，36 个 public，8 个 property）
> **数据来源**：完整方法清单 + 外部依赖审计 + web_ui/server.py 端点映射

---

## 1. 当前职责图

```
┌─────────────────────────────────────────────────────────────────────┐
│                     app/system_runner.py                           │
│                       SystemRunner                                 │
├─────────────────────────────────────────────────────────────────────┤
│ A. Bootstrap / Shutdown          G. Legacy Field Heading           │
│   __init__, run, stop,             field_heading_status,           │
│   _stop_external_processes         confirm_field_heading_manual,   │
│                                    _with_field_coordinates         │
│ B. Main Control Loop                                                │
│   _control_loop,                 H. Command Handling               │
│   _action_lab_only_loop,           web_execute_command,            │
│   _update_active_mode,             _execute_yolo_command,          │
│   _apply_controller_switches,      _handle_mission_command,        │
│   _maybe_recenter_gimbal           _set_stage_override             │
│                                                                     │
│ C. Blackbox / Logging            I. Mission Orchestration          │
│   _record_blackbox_cycle,          configure_action_mission,       │
│   _blackbox_debug_payload,         action_mission_*,               │
│   _format_control_command,         _switch_mission,                │
│   _record_event                    _reset_mission_runtime,         │
│                                    _reload_mission_stage_config    │
│ D. Web Status / Snapshot                                            │
│   web_status_snapshot,           J. Action Lab Management          │
│   web_missions,                    action_lab_tick,                │
│   _web_stage_modes,                _maybe_save_*_result,           │
│   _json_safe                       action_lab_start/stop/reset     │
│                                                                     │
│ E. Field Reference API           K. Manual Step Move               │
│   field_reference_status,          manual_step_move                │
│   field_reference_mark_origin,                                     │
│   field_reference_mark_forward,  L. Camera Recording               │
│   field_reference_use_current_     camera_recording_toggle,        │
│     yaw,                           camera_recording_status         │
│   field_reference_set_manual_                                      │
│     heading,                     M. Backward-Compatible Properties │
│   field_reference_confirm,         8× prop/setter delegates        │
│   field_reference_reset,                                           │
│   field_reference_freeze          N. Config Reload                 │
│                                    apply_active_mission_config,    │
│ F. External Process Mgmt           reconnect_telemetry_from_       │
│   restart_external_service,          saved_config                  │
│   _stop_external_process
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. 方法分组表

| 职责区 | 方法数 | 公开 API | 关键文件 |
|--------|--------|----------|----------|
| A. Bootstrap/Shutdown | 5 | `run`, `stop` | `service_manager`, `web_ui/server` |
| B. Main Control Loop | 6 | 0 | `mission_runner`, `stage_registry`, `command_shaper`, `executor` |
| C. Blackbox/Logging | 5 | 0 | `blackbox_recorder` |
| D. Web Status | 7 | `web_status_snapshot`, `web_missions` | `runtime_context`, `action_runtime` |
| **E. Field Reference** | **9** | **8 API methods** | **`field_reference_service`**, **`runtime_context`** |
| F. External Process | 2 | `restart_external_service` | `subprocess` |
| G. Legacy Field Heading | 4 | `field_heading_status` | `runtime_context_builder` |
| H. Command Handling | 5 | `web_execute_command` | `ui_commands`, `yolo_command_client` |
| I. Mission Orchestration | 12 | `configure_action_mission`, `action_mission_*` | `mission_orchestrator`, `mission_runner` |
| J. Action Lab | 7 | `action_lab_start/stop/reset` | `action_runtime` |
| K. Manual Step | 1 | `manual_step_move` | `link_manager`, `action_runtime` |
| L. Camera | 2 | `camera_recording_toggle` | `yolo_command_client` |
| M. Backward Props | 8 | 8 properties | `action_runtime`, `runtime_context_builder` |
| N. Config Reload | 2 | `apply_active_mission_config` | `mission_runner`, `stage_registry` |

---

## 3. 外部依赖：谁调用 SystemRunner

### 3.1 `web_ui/server.py` — 25 个端点对应 25 个方法

| HTTP 方法 | 端点 | SystemRunner 方法 |
|-----------|------|-------------------|
| GET | `/api/status` | `web_status_snapshot` |
| GET | `/api/missions` | `web_missions` |
| POST | `/api/commands/execute` | `web_execute_command` |
| POST | `/api/actions/start` | `action_lab_start_action` |
| POST | `/api/actions/stop` | `action_lab_stop_action` |
| POST | `/api/actions/reset` | `action_lab_reset_action` |
| GET | `/api/action-mission/status` | `action_mission_status_payload` |
| POST | `/api/action-mission/configure` | `configure_action_mission` |
| POST | `/api/action-mission/start` | `action_mission_start` |
| POST | `/api/action-mission/stop` | `action_mission_stop` |
| POST | `/api/action-mission/reset` | `action_mission_reset` |
| POST | `/api/action-mission/tick` | `action_mission_tick` |
| POST | `/api/action-mission/skip-current` | `action_mission_skip_current` |
| POST | `/api/manual-step-move` | `manual_step_move` |
| POST | `/api/field-heading/confirm` | `confirm_field_heading_manual` |
| GET | `/api/field-reference/status` | `field_reference_status` |
| POST | `/api/field-reference/mark-origin` | `field_reference_mark_origin` |
| POST | `/api/field-reference/mark-forward` | `field_reference_mark_forward` |
| POST | `/api/field-reference/use-current-yaw` | `field_reference_use_current_yaw` |
| POST | `/api/field-reference/set-manual-heading` | `field_reference_set_manual_heading` |
| POST | `/api/field-reference/confirm` | `field_reference_confirm` |
| POST | `/api/field-reference/reset` | `field_reference_reset` |
| POST | `/api/field-reference/freeze` | `field_reference_freeze` |
| POST | `/api/camera-recording/toggle` | `camera_recording_toggle` |
| POST | `/api/services/{svc}/restart` | `restart_external_service` |

### 3.2 `app/main.py` — 单一入口

```python
runner = SystemRunner(config, stop_event=stop_event)
runner.run()
```

### 3.3 `tests/test_web_ui.py` — FakeRunner 测试替身

`_FakeRunner` 实现了 11 个方法作为 SystemRunner 的 duck-type 替身，用于 Web UI 测试：
`web_status_snapshot`, `web_missions`, `web_execute_command`, `camera_recording_*`, `clear_localization_result`, `field_heading_status`, `confirm_field_heading_manual`，以及 config 重连/重启相关。

---

## 4. 依赖图

```
main.py ──► SystemRunner ──► ServiceManager
                               ├─ LinkManager
                               ├─ FusionManager
                               ├─ YoloCommandClient
                               ├─ RuntimeContextBuilder
                               ├─ FieldReferenceService
                               ├─ ActionRuntimeService
                               │    └─ ActionDispatcher
                               ├─ MissionRunner
                               ├─ MissionOrchestrator
                               ├─ StageRegistry
                               ├─ CommandShaper
                               ├─ FlightCommandExecutor
                               ├─ BlackboxRecorder
                               ├─ HealthMonitor
                               ├─ DebugRuntime
                               ├─ ControlRuntimeSwitches
                               └─ WebUiServer

web_ui/server.py ──► SystemRunner (25 endpoints)
web_ui/static/app.js ──► /api/* 端点 (间接)
```

---

## 5. 推荐拆分阶段

### 阶段 SR-1：提取 `FieldReferenceController`（最低风险）

**文件**：`app/field_reference_controller.py`
**提取方法**：9 个（E 区全部 + `_drone_snapshot` helper）

```python
class FieldReferenceController:
    field_reference_status()            # GET /api/field-reference/status
    field_reference_mark_origin()       # POST /api/field-reference/mark-origin
    field_reference_mark_forward()      # POST /api/field-reference/mark-forward
    field_reference_use_current_yaw()   # POST /api/field-reference/use-current-yaw
    field_reference_set_manual_heading() # POST /api/field-reference/set-manual-heading
    field_reference_confirm()           # POST /api/field-reference/confirm
    field_reference_reset()             # POST /api/field-reference/reset
    field_reference_freeze()            # POST /api/field-reference/freeze
    _drone_snapshot()
```

**依赖**：`FieldReferenceService`, `RuntimeContextBuilder`, `latest_snapshot`（通过属性注入）
**调用方**：`web_ui/server.py`（8 个端点），未在控制循环或 mission 链路中使用
**风险**：极低 — 这些方法是纯 Web API 层，不参与飞控实发链路
**已有测试**：`tests/test_field_reference.py`（63 个测试），`tests/test_web_ui.py`
**验证**：`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_field_reference.py tests/test_web_ui.py`

---

### 阶段 SR-2：提取 `WebStatusService`

**文件**：`app/web_status_service.py`
**提取方法**：

```python
class WebStatusService:
    web_status_snapshot()
    web_missions()
    _web_stage_modes()
    _web_stage_modes_for_mission()
    _active_mission_stage_selection()
    _action_lab_snapshot()
    _json_safe()
```

**依赖**：`RuntimeContextBuilder`, `ActionRuntimeService`, `MissionOrchestrator`, `ControlRuntimeSwitches`, `latest_snapshot`
**调用方**：`web_ui/server.py`（`/api/status`, `/api/missions`, `/api/events`）
**风险**：中 — `web_status_snapshot()` 是跨切面最多的方法，读取 9+ 个子系统
**已有测试**：`tests/test_web_ui.py`, `tests/test_action_lab_only_startup.py`
**验证**：`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_web_ui.py`

---

### 阶段 SR-3：提取 `CommandPipeline`

**文件**：`app/command_pipeline.py`
**提取方法**：

```python
class CommandPipeline:
    web_execute_command()
    _execute_yolo_command()
    _handle_mission_command()
    _set_stage_override()
```

**依赖**：`build_ui_command_handler`, `YoloCommandClient`, `ControlRuntimeSwitches`, `LinkManager`, `MissionRunner`
**调用方**：`web_ui/server.py`（`/api/commands/execute`, `/api/yolo/target/*`）
**风险**：中 — `web_execute_command()` 聚合了所有子命令 handler，`_handle_mission_command()` 深度调用 `_switch_mission` 和 `_reset_mission_runtime`
**已有测试**：`tests/test_ui_commands.py`, `tests/test_web_ui.py`
**验证**：`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_ui_commands.py tests/test_web_ui.py`

---

## 6. 不建议拆分的部分

| 区域 | 原因 |
|------|------|
| `__init__()` | God-object 构造函数，拆分需要先建立 DI 容器或工厂 |
| `_control_loop()` | 核心实时循环，紧密耦合所有传感器源和控制器 |
| `_reset_mission_runtime()` | 安全关键路径，跨 7+ 子系统一次 reset |
| `_reload_mission_stage_config()` | 配置广播，跨 8+ 对象 |
| `manual_step_move()` | 手动控制 + Action 停止 + MAVLink 发送，深度耦合 |

这些不适合当前阶段拆分；应先完成 SR-1/2/3 的提取，降低 SystemRunner 的代码量后再评估。

---

## 7. 每阶段验证命令

所有阶段执行：

```bash
python -m compileall app missions telemetry_link fusion yolo_app web_ui scripts
python scripts/validate_action_missions.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

阶段特有验证：

| 阶段 | 重点测试 |
|------|----------|
| SR-1 | `tests/test_field_reference.py` (63 tests), `tests/test_web_ui.py` |
| SR-2 | `tests/test_web_ui.py`, `tests/test_action_lab_only_startup.py` |
| SR-3 | `tests/test_ui_commands.py`, `tests/test_web_ui.py` |

---

## 8. 小结

- **85 个方法** → 建议先提取 **20 个**（SR-1 + SR-2 + SR-3），减少 ~350 行
- **Field Reference**（SR-1）是最安全的首选 — 9 个纯 Web API 方法，0 控制循环依赖
- **每阶段独立提交** + 独立验证，确保不引入回归
- 不追求完美拆分，优先边界清晰、可纯迁移的部分
