# ActionDispatcher 拆分分析计划

> **基线**：`e652ab3` — `merge: system runner low-risk split`
> **文件**：`app/action_dispatcher.py` ~831 行，23 个方法
> **数据来源**：完整代码审计 + dispatch_policy.py + safety_gate.py + action_runtime.py + 测试分析

---

## 1. 当前职责图

```
┌──────────────────────────────────────────────────────────────────┐
│                     ActionDispatcher                            │
│   dispatch_result() → dispatch_actions() → _dispatch_action()  │
├──────────────────────────────────────────────────────────────────┤
│ A. Gating & Policy         B. Per-Handler Dispatch              │
│   gate()                    │  _dispatch_set_servo (309)        │
│   SafetyGate.check()        │  _dispatch_set_mode  (366)        │
│   DispatchPolicy lookup     │  _dispatch_arm       (395)        │
│                             │  _dispatch_takeoff   (419)        │
│ C. Status & Lifecycle       │  _dispatch_land      (447)        │
│   payload()                 │  _dispatch_local_position (509)   │
│   reset_keys()              │  _dispatch_flight_command (598)   │
│   empty_dispatch()          │  _dispatch_yolo_lock_target (751) │
│                             │  _dispatch_confirm_field_heading  │
│ D. Shared State             │    (471)                          │
│   dispatched_keys           │                                   │
│   last_dispatch             │ E. Helpers                        │
│   last_servo_command        │  _format_log_float,               │
│   send_actions              │  _action_params,                  │
│                             │  _optional_float,                 │
│                             │  _body_velocity_to_local_ned      │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. 10 种 action_type 清单

| # | action_type | 门控 | LinkManager 调用 | allowed_actions |
|---|-------------|------|------------------|-----------------|
| 1 | `local_position` | SA+SC | `goto_local_ned` / `local_position` | goto_waypoint, survey_area, multi_view_localize, recon_scan, recon_inspect_target |
| 2 | `flight_command` | SA+SC | `send_body_velocity` / `send_velocity_command` | align_descend, recon_inspect_target, payload_release |
| 3 | `body_velocity` | SA+SC | (同 flight_command) | align_descend, recon_inspect_target |
| 4 | `set_servo` | SA+SC | `set_servo_output_pwm` / `set_servo` | payload_release |
| 5 | `set_mode` | SA+SC | `set_mode` | takeoff |
| 6 | `arm` | SA+SC | `arm` | takeoff |
| 7 | `takeoff` | SA+SC | `takeoff` | takeoff |
| 8 | `land` | SA+SC | `land` | land |
| 9 | `confirm_field_heading` | **无** | **无** | takeoff |
| 10 | `yolo_lock_target` | SA only | **无** | target_lock, recon_inspect_target |

> SA = requires_send_actions, SC = requires_send_commands

**注意**：`gimbal_angle`、`condition_yaw`、`disarm`、`global_goto`、`set_relay`、`release_payload` 共 6 种 action_type 由 `MissionRunner` 直接处理，不走 `ActionDispatcher`。它们在 `dispatch_policy.py` 中没有规则条目。

---

## 3. 关键派发路径

### 3.1 `local_position`

```
gate(action_type="local_position", ...)
  → SafetyGate.check(send_actions, send_commands, SA=True, SC=True)
  → 检查 action_name ∈ allowed_actions

_dispatch_local_position:
  → 提取 x, y, z, frame (=1 LOCAL_NED), yaw, priority
  → frame == LOCAL_NED:
      → link_manager.goto_local_ned(north_m, east_m, z_down_m, yaw_rad, priority) [优先]
      → 否则 link_manager.local_position(x, y, z, frame, yaw, priority)
  → 错误: missing_params / dispatch_not_available / yaw_not_supported
```

### 3.2 `body_velocity` / `flight_command`

```
gate(SA+SC, allowed_actions=align_descend/recon_inspect_target/payload_release)

_dispatch_flight_command:
  → 提取 vx, vy, vz, yaw_rate, yaw_hold_rad, velocity_yaw_rad
  → active=False → 所有速度归零
  → valid=False → skipped
  → yaw_hold_rad 存在:
      → _body_velocity_to_local_ned(vx, vy, yaw) 旋转到 LOCAL_NED
      → send_velocity_command(local_vx, local_vy, vz, frame=LOCAL_NED, yaw_rad)
  → 否则:
      → send_body_velocity(vx_forward, vy_right, vz_down) [优先]
      → send_velocity_command(vx, vy, vz, frame=BODY_NED)
```

### 3.3 `set_servo`

```
gate(SA+SC, allowed_actions=payload_release)

_dispatch_set_servo:
  → link_manager 为 None → error (telemetry_not_connected)
  → 提取 channel (servo_output/channel), pwm, priority
  → set_servo_output_pwm(servo_output, pwm) [优先]
  → set_servo(channel, pwm, priority)
  → 更新 last_servo_command
```

---

## 4. 安全门控详解

### 4.1 SafetyGate（`app/safety_gate.py，14 行`）

```python
class SafetyGate:
    @staticmethod
    def check(send_actions, send_commands, requires_send_actions, requires_send_commands):
        if requires_send_actions and not send_actions:
            return False, "dry_run_only"
        if requires_send_commands and not send_commands:
            return False, "send_commands_disabled"
        return True, "action_dispatch_enabled"
```

极简：两道独立开关。`confirm_field_heading` 两个都不需要，`yolo_lock_target` 只要求 `send_actions`。

### 4.2 DispatchPolicy（`app/dispatch_policy.py，67 行`）

```python
@dataclass
class DispatchRule:
    action_type: str
    allowed_actions: tuple[str, ...]
    requires_send_actions: bool
    requires_send_commands: bool
    continuous: bool = False
    once_respected: bool = True

ACTION_DISPATCH_POLICY = (
    DispatchRule("local_position",        (...), True,  True),
    DispatchRule("flight_command",        (...), True,  True,  continuous=True, once_respected=False),
    DispatchRule("body_velocity",         (...), True,  True,  continuous=True, once_respected=False),
    DispatchRule("set_servo",             (...), True,  True),
    DispatchRule("set_mode",              (...), True,  True),
    DispatchRule("arm",                   (...), True,  True),
    DispatchRule("takeoff",               (...), True,  True),
    DispatchRule("confirm_field_heading", (...), False, False),
    DispatchRule("land",                  (...), True,  True),
    DispatchRule("yolo_lock_target",      (...), True,  False),
)
```

---

## 5. "Latest Only" / 队列清理 / stop_control

这些机制不在 ActionDispatcher 内部，而在 `ActionRuntimeService` 中：

### 5.1 `once` key 去重（`dispatch_actions，207-213 行`）

- 大部分 action_type 尊重 `once=True`：同一 key 第二次派发时被 `once_already_dispatched` 跳过
- `flight_command` / `body_velocity` 设置 `once_respected=False`：每次 tick 都可派发

### 5.2 `clear_navigation_queue`（`action_runtime.py，111-151 行`）

start/stop/reset 时调用：
1. `clear_continuous_commands()` — 清理连续速度指令
2. `clear_pending_local_position_actions()` — 清理航点队列
3. `stop_body_velocity()` — 发送零速度
4. `hold_current_local_position()` — 保持当前位置（stop/reset 时）

### 5.3 `reset_keys()`（`action_dispatcher.py，828-831 行`）

start/reset 时清空 `dispatched_keys`、`last_dispatch`、`last_servo_command`。

---

## 6. 推荐拆分阶段

### AD-1：提取 SafetyGate + DispatchPolicy（最低风险）

**文件**：`app/dispatch/`（保持 `app/dispatch_policy.py` 和 `app/safety_gate.py` 独立，或合并为 `app/dispatch/gate.py`）

纯逻辑提取，零副作用。SafetyGate 只有 14 行，DispatchPolicy 是纯数据 dataclass。两者都不依赖 LinkManager、telemetry、MAVLink。

**风险**：极低
**测试**：`test_action_lab_dispatch.py` 中所有 dry_run / send_commands 门控测试必须通过

---

### AD-2：提取 per-handler 到独立模块

**文件**：
- `app/dispatch/local_position_handler.py`（`_dispatch_local_position`，~80 行）
- `app/dispatch/body_velocity_handler.py`（`_dispatch_flight_command` + `_body_velocity_to_local_ned`，~140 行）
- `app/dispatch/servo_handler.py`（`_dispatch_set_servo`，~60 行）
- `app/dispatch/flight_mode_handler.py`（`_dispatch_set_mode` + `_dispatch_arm` + `_dispatch_takeoff` + `_dispatch_land`，~120 行）

每个 handler 是纯函数或简单类，接收 `(action_dict, link_manager, ...)` 返回 `dict(status=...)`。

**风险**：低-中。handler 内部调用 `link_manager.*` 方法，但这些调用在提取前后完全一致。
**测试**：`test_action_lab_dispatch.py` + `test_action_dispatcher_takeoff_land.py`

---

### AD-3：提取 DispatchPipeline 协调层

**文件**：`app/dispatch/dispatcher.py`

将 `dispatch_result()`、`dispatch_actions()`、`gate()`、`payload()`、`reset_keys()` 提取为协调层，负责：
- 门控判断
- once key 去重
- 错误/跳过聚合
- 状态 payload 构建

**风险**：中。`dispatch_actions` 的 once/latest 逻辑跨 handler 共享状态（`dispatched_keys`），需要仔细处理。
**测试**：full `test_action_lab_dispatch.py`（1460+ 行）必须全部通过

---

## 7. 不建议拆分的区域

| 区域 | 原因 |
|------|------|
| `dispatch_actions` 中的 `once` 去重逻辑 | 跨所有 handler 的共享状态，需要用共享的 `dispatched_keys` set |
| `_dispatch_flight_command` 中的 `body_velocity` / `flight_command` 双入口 | 两个 action_type 共享同一 handler，拆分会引入重复 |
| `ActionRuntimeService` 中的 `clear_navigation_queue()` | 不属于 ActionDispatcher，是独立的协调层 |

---

## 8. 实飞风险点

| 风险 | 等级 | 缓解 |
|------|------|------|
| `goto_local_ned` vs `local_position` fallback | 中 | T4 语义包装器优于旧方法，但 fallback 必须保留 |
| `send_body_velocity` vs `send_velocity_command` fallback | 中 | 同上 |
| `once_respected=False` 导致 `body_velocity` 连续派发 | 高 | 若拆错会导致 BODY_NED 命令无限累积 |
| `clear_navigation_queue` 在 stop/reset 时的 hold_current 语义 | 高 | 若遗漏会导致无人机失去位置保持 |
| `confirm_field_heading` 绕过双门控 | 低 | 设计如此，不可改变 |

---

## 9. 测试策略

| 阶段 | 重点测试 |
|------|----------|
| AD-1 | `test_action_lab_dispatch.py`（门控部分），`test_action_dispatcher_takeoff_land.py` |
| AD-2 | 全部 `test_action_lab_dispatch.py`（1460 行），全部 `test_action_dispatcher_takeoff_land.py`（292 行） |
| AD-3 | 同上 + manual smoke test（板端实飞 dry-run） |

全套验证：
```bash
python -m compileall app missions telemetry_link fusion yolo_app web_ui scripts
python scripts/validate_action_missions.py
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```
