# Repo Trim Plan

> 生成日期：2026-07-02
> 分支：refactor/repo-trim-docs-tests-legacy
> 原则：只归档/标记/说明，不删除代码，不改行为。

本文档按四类整理仓库全部关键文件：**current（当前主线）**、**debug-only（调试工具）**、**legacy（旧架构残留）**、**archive（历史资料）**。

---

## 1. current — 当前主线文件

这些文件构成当前唯一可运行主线（Action Mission → ActionDispatcher → LinkManager → telemetry_link）。

### app/ — 启动、服务编排、Action runtime

| 文件 | 职责 |
| --- | --- |
| `app/main.py` | 入口 |
| `app/system_runner.py` | 主 orchestrator，编排全部服务 |
| `app/app_config.py` | 配置加载与验证 |
| `app/action_runtime.py` | Action 运行时服务 |
| `app/action_dispatcher.py` | Action → LinkManager 调度 |
| `app/runtime_context.py` | 运行时上下文（状态聚合） |
| `app/mission_orchestrator.py` | 当前 Action Mission 步骤编排；仍列为待审查命名/拆分项，但不得按 legacy 删除 |
| `app/service_manager.py` | 服务生命周期管理 |
| `app/field_reference.py` | Field Reference 核心逻辑 |
| `app/field_reference_controller.py` | Field Reference 控制器 |
| `app/field_reference_service.py` | Field Reference 服务 |
| `app/coordinate_transform.py` | 坐标变换 |
| `app/control_switches.py` | 发送门控开关 |
| `app/blackbox_recorder.py` | 黑匣子记录 |
| `app/health_monitor.py` | 健康监控 |
| `app/web_status_service.py` | Web UI 状态推送 |
| `app/ui_commands.py` | 终端命令处理（引用 command_dispatcher） |
| `app/command_pipeline.py` | 低风险命令管线（camera/YOLO/外部进程） |
| `app/completion_catalog.py` | 命令补全 |
| `app/yolo_command_client.py` | YOLO 命令客户端 |
| `app/dispatch/` | 分发子模块（flight_mode/local_position/servo/policy/normalizer） |

### missions/common/actions/ — Action 实现

| 文件 | 职责 |
| --- | --- |
| `missions/common/actions/base.py` | Action 基类 |
| `missions/common/actions/result.py` | ActionResult |
| `missions/common/actions/registry.py` | Action 注册表 |
| `missions/common/actions/runner.py` | ActionRunner |
| `missions/common/actions/takeoff.py` | 起飞 |
| `missions/common/actions/land.py` | 降落 |
| `missions/common/actions/goto_waypoint.py` | 航点移动 |
| `missions/common/actions/payload_release.py` | 投放（→ set_servo） |
| `missions/common/actions/target_lock.py` | 目标锁定 |
| `missions/common/actions/align_descend.py` | 对准下降 |
| `missions/common/actions/recon_scan.py` | 侦察扫描 |
| `missions/common/actions/recon_inspect_target.py` | 侦察检查 |
| `missions/common/actions/select_recon_targets.py` | 选择侦察目标 |
| `missions/common/actions/select_drop_targets.py` | 选择投放目标 |
| `missions/common/actions/survey_area.py` | 区域调查 |
| `missions/common/actions/single_view_localize.py` | 单视图定位 |
| `missions/common/actions/multi_view_localize.py` | 多视图定位 |
| `missions/common/actions/multi_photo_fusion.py` | 多照片融合 |
| `missions/common/actions/target_localization.py` | 目标定位 |
| `missions/common/actions/action_lab.py` | Action Lab 手动操作 |

### telemetry_link/ — MAVLink 通讯

| 文件 | 职责 |
| --- | --- |
| `telemetry_link/link_manager.py` | 链接管理（发送入口） |
| `telemetry_link/command_sender.py` | MAVLink 命令构造与发送 |
| `telemetry_link/telemetry_receiver.py` | 遥测接收 |
| `telemetry_link/telemetry_parser.py` | 遥测解析 |
| `telemetry_link/state_cache.py` | 状态缓存 |
| `telemetry_link/state_publisher.py` | 状态发布 |
| `telemetry_link/config.py` | 链接配置 |
| `telemetry_link/models.py` | 数据模型 |
| `telemetry_link/command_queue.py` | 命令队列 |
| `telemetry_link/mavlink_client.py` | MAVLink 客户端 |
| `telemetry_link/main.py` | telemetry_link 独立入口 |
| `telemetry_link/rate_controller.py` | 速率控制 |
| `telemetry_link/frames.py` | 帧定义 |
| `telemetry_link/utils.py` | 工具函数 |

### fusion/ — 感知融合

| 文件 | 职责 |
| --- | --- |
| `fusion/fusion_manager.py` | 融合管理器 |
| `fusion/rules.py` | 融合规则 |
| `fusion/models.py` | 融合数据模型 |

### yolo_app/ — RKNN 感知

| 文件 | 职责 |
| --- | --- |
| `yolo_app/rknn_detector.py` | RKNNLite NPU 推理 |
| `yolo_app/main.py` | YOLO 主循环 |
| `yolo_app/config.py` | YOLO 配置 |
| `yolo_app/video_source.py` | 视频源 |
| `yolo_app/target_manager.py` | 目标管理 |
| `yolo_app/tracker_runner.py` | 跟踪器 |
| `yolo_app/annotator.py` | 标注绘制 |
| `yolo_app/mjpeg_stream.py` | MJPEG 流 |
| `yolo_app/udp_publisher.py` | UDP 发布 |
| `yolo_app/command_receiver.py` | 命令接收 |
| `yolo_app/raw_frame_recorder.py` | 原始帧录制 |
| `yolo_app/models.py` | 检测数据模型 |
| `yolo_app/utils.py` | 工具函数 |

### web_ui/ — Web 控制台

| 文件 | 职责 |
| --- | --- |
| `web_ui/server.py` | HTTP/WS 服务端 |
| `web_ui/config_store.py` | 配置存储 |
| `web_ui/audit.py` | 审计日志 |
| `web_ui/static/` | 前端资源（JS/HTML/CSS） |

### config/ — 配置文件

| 文件 | 职责 |
| --- | --- |
| `config/app.yaml` | 应用配置 |
| `config/telemetry.yaml` | 遥测链接配置 |
| `config/yolo.yaml` | YOLO 配置 |
| `config/action_missions/*.json` | Action Mission 模板 |
| `config/profiles/` | RK3588 实机/SITL 配置档案 |

### docs/ — 当前文档

| 文件 | 职责 |
| --- | --- |
| `README.md` | 仓库总入口 |
| `AGENTS.md` | AI 开发入口 |
| `docs/README.md` | 文档索引 |
| `docs/ai/README.md` | AI 接管入口 |
| `docs/ai/current_architecture.md` | 当前架构裁决 |
| `docs/ai/action_contracts.md` | Action 契约 |
| `docs/ai/deprecated_paths.md` | 废弃路径清单 |
| `docs/ai/architecture.md` | 模块边界 |
| `docs/ai/interfaces.md` | 接口说明 |
| `docs/ai/control_flow.md` | 数据/命令流 |
| `docs/ai/development_rules.md` | 开发规则 |
| `docs/ai/task_checklist.md` | 任务阅读清单 |
| `docs/reference/*.md` | 参考规范（坐标系/安全/配置等） |
| `docs/user/*.md` | 用户文档 |
| `docs/mission/action_mission_rescue_2026.md` | 比赛任务说明 |

### scripts/ — 运维脚本

| 文件 | 职责 |
| --- | --- |
| `scripts/install/` | 环境安装 |
| `scripts/deploy/` | systemd 部署 |
| `scripts/config/` | 配置档案切换 |
| `scripts/healthcheck/` | 板卡健康检查 |
| `scripts/validate_action_missions.py` | Action Mission 模板验证 |
| `scripts/smoke_test_envs.sh` | 环境冒烟测试 |
| `scripts/run_iris_gimbal_sitl.sh` | SITL 启动 |

### tests/current/ — 主线测试

包含 Action Mission、Action runtime/dispatcher、telemetry、Web UI、YOLO、fusion、
Field Reference 等当前主线测试；`test_mission_orchestrator.py` 必须保留在默认目标中。

---

## 2. debug-only — 调试工具

这些文件**不是当前主线运行路径的一部分**，仅用于调试/开发辅助。不要删除但也不要依赖它们做行为决策。

| 文件 | 原因 | 备注 |
| --- | --- | --- |
| `fusion/debug_main.py` | 独立 fusion debug runner，需要 telemetry link 直连；不通过 Action 主线 | 保留供开发调试 |
| `app/debug_runtime.py` | 依赖 deprecated `missions.base` 和 `missions.common.control`；仅供旧 stage 调试 | 不再服务于当前主线 |
| `telemetry_link/command_dispatcher.py` | 终端文本命令 → LinkManager 分发；被 `app/ui_commands.py`、`app/command_pipeline.py`、`telemetry_link/main.py` 引用 | **不可删除**：`set_servo` 是 payload_release Action 的底层通道；但整体模块定位为 debug/终端入口，非 Web UI/Action 主线的标准入口 |
| `yolo_app/udp_gst_bridge_helper.py` | 独立 GStreamer UDP H264 桥接调试工具 | 保留供视频调试 |

---

## 3. legacy — 旧架构残留

这些文件引用了已废弃的 mission/stage/control 栈（`missions.base`、`missions.visual_tracking`、`missions.rescue_competition`、`missions.common.control`），不在当前 Action Mission 主线中。**不要删除，不要移动**，留给后续 Codex 审查决定清理策略。

| 文件 | 状态 | 依赖的废弃模块 | 当前引用方 |
| --- | --- | --- | --- |
| `app/mission_runner.py` | **deprecated，暂留历史参考** | `missions.base` (Mission, MissionAction, MissionContext, MissionOutput) | SystemRunner fallback 已清理；最终 legacy removal 时删除 |
| `app/stage_registry.py` | **deprecated，暂留历史参考** | `missions.base_stage`、`missions.visual_tracking.stages`、`missions.rescue_competition.stages` | SystemRunner fallback 已清理；最终 legacy removal 时删除 |
| `app/mission_orchestrator.py` | **待 Codex 审查（当前依赖，不是 legacy 删除候选）** | 自身不含废弃 import；`MissionOrchestrator`、`MissionActionStep` 和 `MissionBlackboard` 被当前 Action Mission、SystemRunner 与 Web UI 使用 | `app/system_runner.py`、`web_ui/server.py` 及当前 Action Mission 测试 |

### 额外 legacy 说明

- `uav_ui/` 目录（如存在）：deprecated terminal UI；仍有共用工具未迁出，不能删除
- `missions/` 下除 `missions/common/actions/` 以外的旧 mission/stage/control 模块：已废弃，不要恢复
- `action调试.md`（根目录）：历史调试笔记

---

## 4. archive — 历史资料

这些文档是已完成或仅用于追溯的设计计划。**开发和运行时不要把这里的内容当作当前操作手册。**

| 文件 | 类型 | 说明 |
| --- | --- | --- |
| `docs/archive/web_ui_implementation_plan.md` | 历史设计 | Web UI 实现计划（已完成） |
| `docs/ai/rescue_competition_redesign_plan.md` | 历史设计 | 救援比赛重构计划（参考用） |
| `docs/ai/web_field_map_plan.md` | 历史设计 | Web Field Map 计划（参考用） |
| `docs/refactor/action_dispatcher_split_plan.md` | 重构记录 | ActionDispatcher 拆分 |
| `docs/refactor/phase0_baseline.md` | 重构基线 | Phase 0 快照 |
| `docs/refactor/phase3_5_field_reference_migration.md` | 重构记录 | Field Reference 迁移 |
| `docs/refactor/phase4e_field_reference_dry_run.md` | 重构记录 | Field Reference 干跑 |
| `docs/refactor/system_runner_split_plan.md` | 重构记录 | SystemRunner 拆分 |
| `docs/refactor/web_ui_split_plan.md` | 重构记录 | Web UI 拆分 |
| `docs/user/rescue_competition_sitl.md` | 历史资料 | 比赛 SITL 资料（使用前核对 deprecated 清单） |

---

## 5. 不在此次范围内的文件

以下目录/文件按任务要求**不移动、不删除、不改动**：

- `data/models/` — 模型文件（cuadc-fp16.rknn 等）
- `runtime/` — 运行时产物目录（.gitignore 管理）
- `deploy/` — 部署配置（如有）
- `.reasonix/` — 工具配置
- `reasonix.toml` — 工具配置
- `requirements-*.txt` — 依赖声明

---

## 6. 后续行动建议

1. `app/mission_runner.py`、`app/stage_registry.py` 已审查并从 SystemRunner 解绑；最终 legacy removal 时删除。`app/mission_orchestrator.py` 作为当前 Action Mission 依赖仅评估命名或拆分，不得直接删除
2. 评估是否将 `MissionActionStep` 和 `MissionBlackboard` 从 `mission_orchestrator.py` 迁出到独立模块
3. 继续审查 `app/app_config.py`、`app/web_status_service.py` 中剩余的 legacy config/status 兼容表面
4. 评估是否需要为 `command_dispatcher.py` 设计正式的 Action-compatible 替代方案（当前安全架构缺口）
