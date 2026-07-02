# Legacy Mission/Stage Entrypoint Audit

审查日期：2026-07-02  
审查基线：`main@2d837e0e046ff5cc2603ba08ea6316cc2dce82a0`  
范围：仅 `app/mission_runner.py`、`app/stage_registry.py` 的引用与可达性；本次不移动、删除或修改运行代码。

## 结论

| 文件 | 当前运行代码是否引用 | 当前主线是否实际启用 | deprecated 依赖 | 推荐动作 |
| --- | --- | --- | --- | --- |
| `app/mission_runner.py` | 是。`app/system_runner.py` 在 legacy runtime 的联合 `try` 中尝试 import，并保留实例化、控制循环和旧 Web 命令兼容分支 | 否。模块因缺少 `missions.base` 无法 import；`SystemRunner` 设置 `MISSION_RUNTIME_AVAILABLE=False`，运行 Action-only fallback | `missions.base`；其所在联合导入还依赖缺失的 `missions.common.control`、`missions.registry` | **keep but mark deprecated** |
| `app/stage_registry.py` | 是。`app/system_runner.py` 在同一联合 `try` 中尝试 import，并保留 stage 创建、查找、reset 和配置更新兼容分支 | 否。模块因缺少 `missions.base_stage` 无法 import，且还直接依赖已缺失的 visual/rescue stages | `missions.base_stage`、`missions.visual_tracking.stages.*`、`missions.rescue_competition.stages.*` | **keep but mark deprecated** |

两者都不是当前 Action Mission 主线的一部分。当前主线仍是：

```text
Web UI → Action Mission → ActionRuntimeService → ActionRunner
→ missions/common/actions/* → ActionDispatcher → LinkManager → telemetry_link
```

不要把 `app/mission_runner.py` 与当前使用中的 `app/mission_orchestrator.py` 混为一谈；后者不得删除。

## 1. `app/mission_runner.py`

### import 与可达性

- `app/system_runner.py` 确实包含 `from app.mission_runner import MissionRunner`，所以不能描述为“只被 tests/legacy 或 docs/archive 引用”。
- 该 import 位于 legacy mission/control 栈的联合 `try` 中。
- 直接执行 import 的结果是 `ModuleNotFoundError: No module named 'missions.base'`。
- 联合 import 失败后，`SystemRunner` 将 `MISSION_RUNTIME_AVAILABLE` 设为 `False`，并把 `mission_runner`、`stage_registry`、旧 shaper/executor 设为 `None`。
- `load_app_config()` 同样因 legacy mission modules 缺失而设置 `mission_enabled=False`、`mission_name=action_lab_only`。
- 因此当前部署不会实例化 `MissionRunner`，旧 `_control_loop()` 和旧 mission Web 命令分支不可达；当前 Action Lab/Action Mission fallback 由 integration tests 覆盖。

### 其他引用

- 当前代码：`app/system_runner.py`、`app/web_status_service.py` 保留兼容字段和不可达分支。
- 当前文档：`app/README.md` 仍把它描述为 mission 调用/派发组件，需要在后续清理时修正。
- 历史/审计文档：`docs/refactor/*`、`docs/ai/deprecated_paths.md`、`docs/ai/repo_trim_plan.md`。
- 测试：旧专用测试已经记录在 `tests/LEGACY_TEST_RETIREMENT.md`，当前没有可运行的 `tests/legacy/test_mission_runner.py`。

## 2. `app/stage_registry.py`

### import 与可达性

- `app/system_runner.py` 确实包含 `from app.stage_registry import StageRegistry, copy_dataclass_values`，所以也不是“只被 tests/legacy 或 docs/archive 引用”。
- 直接执行 import 的结果是 `ModuleNotFoundError: No module named 'missions.base_stage'`。
- 文件还静态依赖已缺失的 `missions.visual_tracking.stages.*` 和 `missions.rescue_competition.stages.*`。
- 因为它和 `MissionRunner`、旧 control/registry 位于同一个联合 import gate，当前运行只会采用 `stage_registry=None` 的 Action-only fallback，不会创建或调用任何旧 stage controller。

### 其他引用

- 当前代码：`app/system_runner.py` 保留 stage get/reset/apply_configs 兼容分支；`app/app_config.py` 仍有对应 legacy config fallback。
- 当前文档：`app/README.md` 仍将其描述为 stage controller 注册组件。
- 历史/审计文档：`docs/refactor/*`、`docs/ai/rescue_competition_redesign_plan.md`、`docs/ai/deprecated_paths.md`、`docs/ai/repo_trim_plan.md`。
- 测试：旧 app config/stage 测试记录在 `tests/LEGACY_TEST_RETIREMENT.md`；当前 integration test 明确验证 legacy modules 缺失时的 Action-only fallback。

## 3. 推荐动作

本轮选择 **keep but mark deprecated**，不建议现在单独 move 或 delete：

1. 两个文件虽不可运行，但当前 `SystemRunner` 仍显式 import 并围绕它们保留成组兼容逻辑；只移动文件会改变 import error 的来源，只删除文件会留下更难理解的死分支。
2. 删除应作为后续独立小任务，目标是移除整个 legacy mission/stage/control fallback，而不是为了让旧 import 再次成功去恢复缺失模块。
3. 不得恢复 `missions.base`、`missions.base_stage`、`missions.visual_tracking`、`missions.rescue_competition`、`missions.common.control`、CommandShaper 或 FlightCommandExecutor。

若后续决定移动或删除，必须同步审查和修改：

- 代码：`app/system_runner.py` 的联合 import、`MISSION_RUNTIME_AVAILABLE` gate、旧 `_control_loop()`、mission/stage Web 命令及配置热更新分支。
- 代码：`app/app_config.py` 的 legacy mission/stage config imports、fallback config 和 `mission_enabled` 推导。
- 代码：`app/web_status_service.py` 的 legacy mission/stage 状态兼容分支。
- 文档：`app/README.md`、`docs/ai/deprecated_paths.md`、`docs/ai/repo_trim_plan.md`；历史 `docs/refactor/*` 保留但应继续标明非当前依据。
- 测试：保留并更新 `tests/integration/test_action_lab_only_startup.py`，确保移除 fallback 后 Action Mission、Web UI 和默认 SEND-off 行为不变；同步更新 `tests/LEGACY_TEST_RETIREMENT.md`。

## 4. 审查裁决

- 发现 current 代码引用：**是**，均来自 legacy compatibility/fallback 表面。
- 发现当前可运行依赖：**否**；两个模块都不能独立 import，也不会在当前主线实例化。
- 是否只被 `tests/legacy` 或 `docs/archive` 引用：**否**。
- 当前是否建议删除/移动：**否**；先保持原位并标记 deprecated。
- 后续方向：以一次可验证的 `SystemRunner` legacy fallback 清理替代零散删文件，且不得改变 Action Mission、发送门控或飞控行为。
