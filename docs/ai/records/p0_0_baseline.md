# P0-0 可观察行为与控制入口基线

> 历史快照：本页只记录 2026-08-12 重构前基线，所列复合 Action/权限已被当前原子
> Action + Mission subflow 替代；当前事实以 `docs/ai/architecture/current_architecture.md` 和
> execution policy 为准。

## 1. 记录范围

| 项目 | 值 |
| --- | --- |
| 记录日期 | 2026-08-12 |
| Git commit | `6ffe116eaedcf2148af28f59f88aaa1431506a1c` |
| 分支 | `agent/beginner-docs-guide` |
| Python | 3.12.3 |
| Node.js | 当前环境未安装 |
| 行为约束 | 本阶段只增加清单、记录和特征测试，不修改生产运行行为 |

记录时工作树已经包含维护者未提交的
`docs/beginner/04_rk3588_setup.md` 修改和未跟踪的本改造计划；P0-0 不覆盖这些内容。

## 2. Action 请求到 LinkManager 的当前路径

所有表内飞行请求的共同入口是：

```text
Action result
  → ActionRuntimeService.tick / MissionOrchestrator.tick
  → ActionDispatcher.dispatch_result
  → ActionDispatcher.dispatch_actions
  → SafetyGate + ACTION_DISPATCH_POLICY
  → type handler
  → LinkManager public method
  → CommandQueue / CommandSender
```

当前“本次运行授权”仍由可变的 `ActionDispatcher.send_actions` 表示，不是 P0-3 目标中的不可变
run authorization context。除 `yolo_lock_target` 外，表内请求同时要求 `send_actions=true` 和系统
`send_commands=true`。

| request type | policy 允许的 Action | 连续 | 当前双门控 | 最终接口 |
| --- | --- | --- | --- | --- |
| `local_position` | `goto_waypoint`, `survey_area`, `multi_view_localize`, `recon_scan`, `recon_inspect_target`, `drop_sequence`, `recon_sequence` | 否 | 两门都需要 | `LinkManager.goto_local_ned()`，兼容回退为 `local_position()` |
| `global_goto` | `goto_waypoint`, `multi_view_localize`, `gps_multi_view_localize`, `gps_drop_sequence`, `gps_recon_sequence`, `gps_recon_area_scan` | 否 | 两门都需要 | `LinkManager.global_goto()` |
| `flight_command` | `align_descend`, `recon_inspect_target`, `payload_release`, `recon_descend_observe`, `drop_sequence`, `recon_sequence`, `gps_drop_sequence`, `gps_recon_sequence`, `visual_land` | 是 | 两门都需要 | `send_body_velocity()` 或 `send_velocity_command()` |
| `body_velocity` | `align_descend`, `recon_inspect_target` | 是 | 两门都需要 | 与 `flight_command` 相同 |
| `set_servo` | `payload_release`, `drop_sequence`, `gps_drop_sequence` | 否 | 两门都需要 | `set_servo_output_pwm()`，兼容回退为 `set_servo()` |
| `set_mode` | `takeoff` | 否 | 两门都需要 | `set_mode()` |
| `arm` | `takeoff` | 否 | 两门都需要 | `arm()` |
| `takeoff` | `takeoff` | 否 | 两门都需要 | `takeoff()` |
| `land` | `land` | 否 | 两门都需要 | 先 clear continuous/navigation，再 `land()` |
| `condition_yaw` | `yaw_align`, `gps_multi_view_localize` | 否 | 两门都需要 | `condition_yaw()` |
| `change_speed` | `change_speed` | 否 | 两门都需要 | `change_speed()` |
| `clear_continuous_commands` | `drop_sequence`, `recon_sequence`, `recon_descend_observe`, `gps_drop_sequence`, `gps_recon_sequence`, `visual_land` | 清理类 | 两门都需要 | `stop_body_velocity_and_clear()` 或 `clear_continuous_commands()`；可同时 clear navigation |
| `yolo_lock_target` | `target_lock`, `recon_inspect_target`, `drop_sequence`, `recon_sequence`, `gps_target_lock`, `gps_drop_sequence`, `gps_recon_sequence`, `visual_land` | 否 | 只需要 `send_actions` | `YoloCommandClient.lock_target()`，不进入 LinkManager |

当前重要特征：

- 未知 request type 和 Action/request 非白名单组合由 dispatcher 拒绝；
- `flight_command`/`body_velocity` 是当前唯一 policy 标记的连续飞行请求；
- `once` 去重只在进程内使用 `dispatched_keys`，连续请求明确不使用 once；
- 当前 dispatcher 尚没有统一 TTL/deadman、有限值、安全包线或 telemetry freshness 裁决层；
- stop/reset/fail/切换主要依赖 `ActionRuntimeService.clear_navigation_queue()` 和各复合 Action
  产生的 `clear_continuous_commands(send_stop_first=true)`；
- payload 正式 Action 路径只使用 `set_servo`，但通用文本命令入口仍能直接调用 `set_servo`。

## 3. Web 状态修改入口

当前 `create_app()` 没有认证、授权或 CSRF/Origin 校验。`config/app.yaml` 当前默认监听
`0.0.0.0:8080`。以下是全部状态修改形态的 HTTP 入口：

| 入口 | 当前副作用/去向 | 是否经过 ActionDispatcher |
| --- | --- | --- |
| `POST /api/commands/execute` | 自由文本进入 `SystemRunner.web_execute_command()` 和 `ui_commands`/`dispatch_text_command()` | 多数命令否 |
| `POST /api/actions/start` | 启动 Action，可设置 `send_actions` 并立即 tick | 是 |
| `POST /api/actions/stop` | stop + 原子 BODY_NED stop/clear + navigation clear + hold | 停止路径直接使用 LinkManager |
| `POST /api/actions/reset` | reset + 同上清理 | 停止路径直接使用 LinkManager |
| `POST /api/action-mission/configure` | 替换内存中的 Action Mission steps | 不发送 |
| `POST /api/action-mission/start` | 启动已配置 Mission | 后续 tick 是 |
| `POST /api/action-mission/stop` | 停止 Mission 和 Action、清队列并 hold | 停止路径直接使用 LinkManager |
| `POST /api/action-mission/reset` | 重置 Mission/Action、清队列并 hold | 停止路径直接使用 LinkManager |
| `POST /api/action-mission/tick` | 人工推动一次 Mission，可能产生飞行请求 | 是 |
| `POST /api/action-mission/skip-current` | 跳过当前步骤，stop/clear 后开始下一步 | 后续请求是 |
| `POST /api/manual-step-move` | 直接计算并调用 `LinkManager.local_position()` | 否 |
| `POST /api/field-reference/reset` | 重置 Field Reference | 不发送 |
| `POST /api/field-reference/freeze` | 冻结 Field Reference | 不发送 |
| `POST /api/field-profiles/{profile_id}/runtime-sampling/start` | 开始 v3 runtime sampling | 不发送 |
| `POST /api/field-reference/runtime-sampling/start` | 创建现场 v3 profile 并开始采样 | 不发送 |
| `POST /api/field-reference/runtime-sampling/finalize` | finalize/apply/freeze binding | 不发送 |
| `POST /api/field-reference/runtime-sampling/cancel` | 取消采样 | 不发送 |
| `POST /api/localization/clear` | 清理定位结果 | 不发送 |
| `POST /api/camera-recording/toggle` | 启停录像 | 不发送飞行命令 |
| `POST /api/yolo/target/{action}` | 通过文本命令控制 YOLO target lock/next/prev/unlock | 不进入 LinkManager |
| `PUT /api/config/file` | 写受允许配置；`action` 可触发 reconnect/restart | 否 |
| `POST /api/config/restore` | 恢复配置；`action` 可触发 reconnect/restart | 否 |
| `POST /api/services/telemetry/reconnect` | 强制 SEND OFF 后重建 telemetry | 否 |
| `POST /api/services/{service}/restart` | 重启 `app` 或 `yolo`；app restart 前强制 SEND OFF | 否 |

下列 POST 路由当前固定返回 410，不产生状态修改：
`/api/field-heading/confirm`、`/api/field-reference/mark-origin`、
`/api/field-reference/mark-forward`、`/api/field-reference/use-current-yaw`、
`/api/field-reference/set-manual-heading`、`/api/field-reference/confirm`。

WebSocket `/ws/status` 当前只推送状态，但也没有认证；P0-1 需要把它纳入认证、断开和重连测试。

## 4. 通用文本命令和程序化旁路

`POST /api/commands/execute` 可到达下列命令根，且不是 Action 请求：

- source/发送门/旧 controller 状态：`switch_source`、`control send`、`controller`；
- 飞行和导航：`mode`、`arm`、`disarm`、`takeoff`、`land`、`condition_yaw`、
  `change_speed`、`set_home`、`global_goto`、`local_pos`、`reposition`、`body_vel`、
  `yaw_rate`、`stop`；
- 执行机构/云台：`set_servo`、`set_relay`、`set_roi_location`、`roi_none`、
  `gimbal_manager_configure`、`gimbal`、`gimbal_rate`；
- telemetry 管理：`set_message_interval`；
- YOLO/旧任务控制：`target`、`mission`、`task`、`stage`、`pid`。

`release_payload` 文本命令当前固定拒绝，但 `set_servo` 文本命令仍可直接排队。连续人工命令会先关闭
系统自动 SEND 并清 continuous queue，随后仍直接把人工命令排入 LinkManager；因此关闭自动发送门并不等价于
阻止该文本命令自身发送。

除 Web 路由外，以下 Python 入口也能改变状态：

- `SystemRunner.web_execute_command()` → `build_ui_command_handler()` →
  `telemetry_link.command_dispatcher.dispatch_text_command()`；
- `SystemRunner.manual_step_move()` → `LinkManager.local_position()`；
- `SystemRunner.action_lab_*()` / `action_mission_*()`；
- `SystemRunner.reconnect_telemetry_from_saved_config()`；
- `SystemRunner.restart_external_service()`；
- `LinkManager` 的公开发送方法本身。它们是 telemetry 边界 API，不应从 Action 或 YOLO 直接调用。

## 5. 连续命令失效行为特征

| 场景 | 当前行为 | 固化测试 |
| --- | --- | --- |
| Action stop/reset | `stop_body_velocity_and_clear()`，再 clear LOCAL/GLOBAL navigation；可 hold current | `tests/unit/execution/test_action_runtime.py` |
| stop 成功发送 | zero STOP 带 `clear_after_send=true`，成功发送后按对象身份清 queue | `tests/integration/test_telemetry_link.py` |
| stop 发送失败 | STOP 留在 queue 中等待后续机会 | `tests/integration/test_telemetry_link.py` |
| telemetry disconnected | `CommandSender` 清 control/gimbal rate，并逐个丢弃 pending action | `test_command_sender_disconnected_drops_continuous_and_pending_action` |
| heartbeat/RX stale | monitor 标记 reconnect，停止 workers，并清 control/gimbal/actions | `test_stale_link_monitor_clears_continuous_and_pending_commands` |
| source 切换 | 清所有 source 的 control/gimbal rate；SystemRunner 路径先强制 SEND OFF | `test_switch_active_source_clears_all_continuous_queues` |
| 丢失目标/控制不允许 | 复合 Action 不继续输出旧 `flight_command`，改发 `send_stop_first=true` 清理请求 | `test_align_target_invalid_emits_zero_and_clear`, `test_align_control_allowed_false_emits_zero_and_clear` |
| Action 切换 | start 新 Action 前先 stop/clear navigation，再 stop 旧 Action并启动新 Action | `test_switch_running_action_stops_old_action_and_clears_navigation` |
| Mission 阶段切换 | orchestrator 调用 runtime clear；align→payload 特例 clear 后保留 persistent STOP 并 hold | `tests/unit/mission/test_mission_orchestrator.py` |

当前缺口：没有独立于 Action tick 的统一 continuous watchdog/deadman；这属于 P0-2，而不是 P0-0
可以改变的行为。

## 6. 基线命令和结果

### 6.1 编译

```bash
python -m compileall app missions telemetry_link fusion yolo_app web_ui scripts
```

结果：通过，exit 0。

### 6.2 主线 pytest 原始入口

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/unit tests/contracts tests/integration tests/sitl
```

结果：collection 中止，4 个环境缺失错误：`httpx`、`fastapi`、`uvicorn` 未安装。分类为
**环境缺失**，不删除或忽略对应测试。

为了继续暴露其余基线，只在命令行临时 `--ignore` 上述 4 个无法收集的 Web 测试文件；未修改
pytest 配置或仓库忽略列表。结果：`1792 passed, 1 skipped, 6 failed`。

| 失败 | 分类 | 当前处置 |
| --- | --- | --- |
| `test_drop_descent_tune.py` 2 项 | 测试/配置漂移 | 模板当前为 timeout 1.0、approach altitude 3.5；P0-0 不猜测应改哪一侧 |
| `test_field_profile_runtime_ui.py` 3 项 | 环境缺失 | Node.js 未安装 |
| `test_telemetry_link_interfaces.py::test_send_body_velocity_can_hold_yaw` | 代码接口/测试契约不一致 | `LinkManager.send_body_velocity()` 当前不接受 `yaw_rad`；留待独立缺陷处理 |

P0-0 新增/扩展的定向特征测试：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/unit/execution/test_action_runtime.py \
  tests/integration/test_telemetry_link.py
```

结果：`42 passed`。

新增特征测试后再次运行同一“可收集部分”命令，结果为
`1795 passed, 1 skipped, 6 failed`；失败集合与上述基线完全相同，没有新增失败。

### 6.3 Action Mission validator

```bash
python scripts/validate_action_missions.py
```

结果：通过；6 个模板全部 validated。

### 6.4 配置解析

实际 parser/loader 读取 `config/app.yaml`、`config/telemetry.yaml`、`config/yolo.yaml`：

```text
app_yaml=ok executor.send_commands=false
telemetry=ok data_source=real active_source=real
yolo=ok model_path=.../data/models/cuadc2026-fp16.rknn
```

### 6.5 Node

```bash
node --test tests/js/*.js
```

结果：无法运行，`node: command not found`。分类为环境缺失。

## 7. runtime 和测试临时文件规则

- `.gitignore` 忽略 `runtime/*`，仅允许跟踪 `runtime/.gitkeep`；
- 当前 `git ls-files runtime` 只有 `runtime/.gitkeep`；
- 测试应使用 pytest `tmp_path`/临时目录，不把 fixtures、日志、录像、SITL 或 blackbox 写入
  `config/`；
- 本轮编译和测试后，`runtime/` 没有新增未跟踪文件，工作树只出现维护者原改动和 P0-0 文档/测试改动。

## 8. 后续门禁

- P0-1 在 D-06/D-07（凭据来源、安全事件接收地址、是否多操作者/角色）形成书面决策前不能宣称完成；
- P0-2 可以先实现 fail-closed 数据结构，但 watchdog 和实机默认值受 D-01～D-05 阻塞；
- P0-3 必须等待 P0-2 safety pipeline 成为全部 Action 实发请求的必经路径。
