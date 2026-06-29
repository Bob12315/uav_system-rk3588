# 重构计划 (Refactor Plan)

> 基线 tag: `pre-refactor-20260629`
> 基线 commit: `5333135`
> 生成日期: 2026-06-29
> 分支: `codex/recon-inspect-target-stepwise`

---

## 1. 当前架构问题清单

### 1.1 双轨并存：旧 Mission/Stage 与 Action Mission

- `app/mission_runner.py` 依赖 `missions.base.Mission`、`missions.registry`，但这些模块已删除
- `app/stage_registry.py` 依赖 `missions.base_stage.MissionStage`，该模块已删除
- `app/system_runner.py` 在 `_control_loop` 中仍有旧 mission/stage 路径，运行时回退到 `action_lab_only` 模式
- 旧测试 12 个文件 (`test_approach_track.py`, `test_command_shaper.py`, `test_downward_align_descend.py` 等) import 失败
- **影响**: 代码路径分支复杂，维护两套接口，旧路径是死代码但未清理

### 1.2 `missions/common/actions/` 动作过多，缺少功能分组

当前 21 个 .py 文件全部平铺在 `missions/common/actions/`:

```
align_descend.py      894行  投掷对齐
multi_view_localize.py 527行  多视图定位
recon_scan.py         522行  侦察扫描
multi_photo_fusion.py 437行  多照片融合
takeoff.py            377行  起飞
action_lab.py         359行  Action Lab
target_lock.py        353行  目标锁定
select_drop_targets.py 349行  选择投掷目标
survey_area.py        344行  区域扫描
goto_waypoint.py      311行  航点飞行
recon_inspect_target.py 305行  侦察目标检查
single_view_localize.py 298行  单视图定位
payload_release.py    277行  载荷投掷
target_localization.py 216行  目标定位
land.py               204行  降落
select_recon_targets.py 187行  选择侦察目标
runner.py             129行  运行器
registry.py            46行  注册表
base.py                24行  基类
result.py              22行  结果
__init__.py            12行
```

**问题**: 导航、视觉、载荷、侦察四类动作混在一起，缺乏层次结构。

### 1.3 编排器边界不统一

三个模块职责重叠:

| 模块 | 行数 | 当前职责 |
|------|------|----------|
| `app/mission_runner.py` | 174 | 旧 mission/stage 调度 (已半废弃) |
| `app/mission_orchestrator.py` | 487 | Action Mission 编排 |
| `app/action_runtime.py` | 158 | Action 运行时服务 |

**问题**: `mission_runner` 和 `mission_orchestrator` 共存但一个已死，`action_runtime` 和 `mission_orchestrator` 边界模糊。

### 1.4 UI 命令分发重复

- `uav_ui/terminal_ui.py` (492行) 有独立的命令分发逻辑
- `web_ui/server.py` (454行) 也有独立的命令分发逻辑
- 两个 UI 通过不同的路径调用 `ActionDispatcher` / `SystemRunner`
- **问题**: 相同的命令语义在两处各自实现，不一致风险高

### 1.5 docs 新旧混杂

- `docs/ai/architecture.md` 描述的是旧 mission/stage 架构（`missions/common/control/` 路径已不存在）
- `docs/ai/development_rules.md` 描述的是旧 stage 开发流程
- `docs/mission/action_mission_rescue_2026.md` 描述的是新 Action Mission 架构
- 两份架构文档共存，新人容易混淆

### 1.6 大文件臃肿 (来自代码分析)

| 文件 | 行数 | 问题 |
|------|------|------|
| `web_ui/static/app.js` | 2,222 | 单文件零模块化 |
| `app/system_runner.py` | 1,768 | 上帝类，7+职责 |
| `app/app_config.py` | 1,015 | 20+配置类堆一个文件 |
| `app/action_dispatcher.py` | 831 | 所有派发类型混在一起 |
| `missions/common/actions/align_descend.py` | 894 | 单动作近千行 |

---

## 2. 推荐目标结构

```
uav_system-rk3588/
├── actions/
│   ├── nav/                    # 导航类动作
│   │   ├── __init__.py
│   │   ├── takeoff.py
│   │   ├── land.py
│   │   ├── goto_waypoint.py
│   │   └── survey_area.py
│   ├── vision/                 # 视觉类动作
│   │   ├── __init__.py
│   │   ├── single_view_localize.py
│   │   ├── multi_view_localize.py
│   │   ├── multi_photo_fusion.py
│   │   ├── target_localization.py
│   │   └── target_lock.py
│   ├── payload/                # 载荷类动作
│   │   ├── __init__.py
│   │   ├── payload_release.py
│   │   ├── select_drop_targets.py
│   │   └── align_descend/
│   │       ├── __init__.py
│   │       ├── align_descend.py
│   │       ├── gain_scheduler.py
│   │       └── offset_compensator.py
│   ├── recon/                  # 侦察类动作
│   │   ├── __init__.py
│   │   ├── recon_scan.py
│   │   ├── recon_inspect_target.py
│   │   └── select_recon_targets.py
│   ├── __init__.py
│   ├── base.py                 # Action 基类
│   ├── result.py               # ActionResult
│   ├── registry.py             # Action 注册
│   └── runner.py               # Action runner
│
├── app/
│   ├── runtime/                # 运行时
│   │   ├── __init__.py
│   │   ├── action_runtime.py   # ActionRuntimeService
│   │   ├── blackbox_recorder.py
│   │   ├── runtime_context.py
│   │   └── safety_gate.py
│   ├── orchestration/          # 编排
│   │   ├── __init__.py
│   │   ├── orchestrator.py     # MissionOrchestrator (从 mission_orchestrator 改名)
│   │   ├── blackboard.py       # MissionBlackboard
│   │   └── dispatch_policy.py
│   ├── dispatch/               # 派发
│   │   ├── __init__.py
│   │   └── action_dispatcher.py
│   ├── config/                 # 配置加载
│   │   ├── __init__.py
│   │   └── app_config.py       # 拆分出 models
│   ├── __init__.py
│   ├── main.py
│   ├── system_runner.py        # 拆分出 heading_controller, web_status_builder
│   ├── service_manager.py
│   ├── health_monitor.py
│   └── debug_runtime.py
│
├── ui/
│   ├── common_commands/        # 统一命令分发层
│   │   ├── __init__.py
│   │   └── command_router.py
│   ├── terminal/               # 终端 UI (原 uav_ui)
│   │   ├── __init__.py
│   │   └── terminal_ui.py
│   └── web/                    # Web UI (原 web_ui)
│       ├── __init__.py
│       ├── server.py
│       └── static/
│
├── docs/
│   ├── ai/                     # AI/开发者文档 (更新为新架构)
│   ├── user/                   # 用户文档
│   ├── reference/              # 参考文档
│   ├── mission/                # 任务文档
│   └── archive/                # 归档旧文档
│       ├── old_architecture.md
│       └── old_development_rules.md
│
├── telemetry_link/             # 保持不变
├── fusion/                     # 保持不变
├── yolo_app/                   # 保持不变
├── config/                     # 保持不变
├── tests/                      # 同步重组
│   ├── actions/
│   │   ├── nav/
│   │   ├── vision/
│   │   ├── payload/
│   │   └── recon/
│   ├── app/
│   └── archive/                # 归档旧测试
├── scripts/                    # 保持不变
├── runtime/                    # 保持不变
├── data/                       # 保持不变
└── missions/                   # 删除或仅保留兼容 alias
```

---

## 3. 分阶段重构顺序

### Phase 0: 冻结基线 ✅ 已完成

- [x] 提交基线 commit `5333135`
- [x] 打 tag `pre-refactor-20260629`
- [x] 推送到 GitHub + Gitee

### Phase 1: 整理 docs (预计 0.5h)

**目标**: 消除新旧架构文档混杂，不改业务代码

1. 将 `docs/ai/architecture.md` 归档为 `docs/archive/old_architecture.md`
2. 将 `docs/ai/development_rules.md` 归档为 `docs/archive/old_development_rules.md`
3. 基于当前 Action Mission 架构重写 `docs/ai/architecture.md`
4. 基于当前 Action Mission 开发规则重写 `docs/ai/development_rules.md`
5. 更新 `docs/ai/interfaces.md` 反映新接口
6. 更新 `docs/ai/README.md` 导航

**验证**:
```bash
git diff --stat docs/
git log --oneline -3
```

### Phase 2: 重组 actions 目录 (预计 1-2h)

**目标**: 给 actions 分目录，保持 import 兼容

1. 创建 `actions/nav/`, `actions/vision/`, `actions/payload/`, `actions/recon/`
2. 移动对应 .py 文件到子目录
3. 在每个子目录添加 `__init__.py` 做 re-export
4. 保持 `missions/common/actions/` 作为兼容层:
   ```python
   # missions/common/actions/__init__.py
   from actions.nav.takeoff import TakeoffAction
   from actions.vision.multi_view_localize import MultiViewLocalizeAction
   # ... 保持旧 import 路径可用
   ```
5. 更新 `actions/registry.py` 中的 import 路径

**验证**:
```bash
python -m compileall actions missions
python scripts/validate_action_missions.py
python -m app.main --no-yolo-udp --run-seconds 1 --send-commands false
```

### Phase 3: 统一 Action Mission 为主线 (预计 2-3h)

**目标**: 删除旧 mission/stage 死代码，统一编排器

1. 删除 `app/mission_runner.py`（旧 mission 调度）
2. 删除 `app/stage_registry.py`（旧 stage 注册）
3. 删除 `missions/common/control/`（已不存在，清理残留引用）
4. 从 `app/system_runner.py` 移除旧 `_control_loop` 路径，只保留 `_action_lab_only_loop`
5. 重命名 `_action_lab_only_loop` → `_main_loop`
6. 将 `app/mission_orchestrator.py` 移到 `app/orchestration/orchestrator.py`
7. 将 `app/action_runtime.py` 移到 `app/runtime/action_runtime.py`
8. 归档旧测试文件:
   ```bash
   mkdir -p tests/archive
   git mv tests/test_approach_track.py tests/archive/
   git mv tests/test_command_shaper.py tests/archive/
   git mv tests/test_downward_align_descend.py tests/archive/
   git mv tests/test_executor.py tests/archive/
   git mv tests/test_input_adapter.py tests/archive/
   git mv tests/test_mission_navigation.py tests/archive/
   git mv tests/test_mission_registry.py tests/archive/
   git mv tests/test_mission_runner.py tests/archive/
   git mv tests/test_overhead_hold.py tests/archive/
   git mv tests/test_visual_tracking_mission.py tests/archive/
   git mv tests/test_debug_runtime.py tests/archive/  # 依赖旧模块
   ```
9. `tests/test_app_config.py` 修复或归档（依赖 `StageRegistry`）

**验证**:
```bash
python -m compileall app actions
python scripts/validate_action_missions.py
python -m app.main --no-yolo-udp --run-seconds 1 --send-commands false
# 确认不再出现 "mission modules unavailable" 警告
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q  # 期望: 12 ERROR → 0 ERROR
```

### Phase 4: 整理 UI 命令分发 (预计 1-2h)

**目标**: 统一 uav_ui 和 web_ui 的命令分发

1. 创建 `ui/common_commands/command_router.py`
2. 将 `uav_ui/ui_commands.py` 和 `web_ui/server.py` 中共有的命令分发逻辑提取到 `command_router`
3. 保持 `uav_ui/` 和 `web_ui/` 作为前端，只调用 `command_router`
4. 重命名目录 (可选):
   - `uav_ui/` → `ui/terminal/`
   - `web_ui/` → `ui/web/`

**验证**:
```bash
python -m compileall ui
python -m app.main --no-yolo-udp --run-seconds 1 --send-commands false
# 手动验证 web UI 可访问 http://0.0.0.0:8080
```

### Phase 5: 删除确认无用的旧代码 (预计 0.5h)

**目标**: 最终清理，删除所有仅用于 import 兼容的 shim

1. 删除 `missions/common/actions/` 兼容 shim（如果所有 import 已迁移到 `actions/`）
2. 删除 `missions/` 目录（如果不为空则只删除旧文件）
3. 最终全量验证

**验证**:
```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
python scripts/validate_action_missions.py
python -m app.main --no-yolo-udp --run-seconds 1 --send-commands false
python -m compileall app actions ui telemetry_link fusion yolo_app scripts
```

---

## 4. 每个 Phase 的完整验证命令

| Phase | pytest | validate | dry-run | SITL SEND=ON | 真机 SEND=OFF | 真机 SEND=ON |
|-------|--------|----------|---------|-------------|--------------|-------------|
| 0 | ✅ (12E, expected) | ✅ | ✅ | ⬜ | ⬜ | ⬜ |
| 1 | — | — | — | — | — | — |
| 2 | ✅ (same) | ✅ | ✅ | ⬜ | ⬜ | ⬜ |
| 3 | ✅ (expect 0E) | ✅ | ✅ | ⬜ | ⬜ | ⬜ |
| 4 | ✅ | ✅ | ✅ | ⬜ | ⬜ | ⬜ |
| 5 | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## 5. 风险与注意事项

1. **不要擅自合并到 main** — 当前分支 `codex/recon-inspect-target-stepwise` 是重构工作分支
2. **Phase 3 是最危险的阶段** — 删除旧代码前确保 SITL 验证通过
3. **真机验证**在每个 Phase 后可选，但 Phase 5 前必须完成真机 SEND=OFF + SEND=ON
4. **web_ui/static/app.js** 的拆分 (2,222行) 建议作为独立的 Phase 6，不在本次重构范围内
5. **不要修改 YOLO 为 x86/CUDA/PyTorch 路径**
6. **不要恢复旧 `missions/common/control/`**
7. **config/app.yaml 保持 `executor.send_commands: false` 默认**
