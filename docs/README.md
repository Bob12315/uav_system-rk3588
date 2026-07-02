# 文档索引

## 当前权威入口

| 文档 | 用途 |
| --- | --- |
| [ai/README.md](ai/README.md) | AI/开发者接管入口 |
| [ai/current_architecture.md](ai/current_architecture.md) | 当前 Action 主线与架构裁决 |
| [ai/action_contracts.md](ai/action_contracts.md) | Action 边界和参数迁移方向 |
| [ai/deprecated_paths.md](ai/deprecated_paths.md) | 禁止恢复的旧路径与删除前置条件 |
| [reference/coordinate_frames.md](reference/coordinate_frames.md) | 坐标系唯一规范源 |
| [reference/field_origin_heading.md](reference/field_origin_heading.md) | Field Reference 与 GPS A/B 设计 |
| [reference/safety.md](reference/safety.md) | 当前发送链路与安全边界 |
| [refactor/phase0_baseline.md](refactor/phase0_baseline.md) | 重构分支基线快照 |
| [ai/repo_trim_plan.md](ai/repo_trim_plan.md) | 仓库文件裁剪分类（current/debug-only/legacy/archive） |

## 用户文档

| 文档 | 用途 |
| --- | --- |
| [user/README.md](user/README.md) | 用户入口 |
| [user/install.md](user/install.md) | RK3588 安装 |
| [user/running.md](user/running.md) | 运行和服务管理 |
| [user/sitl_start.md](user/sitl_start.md) | SITL 联调 |
| [user/rescue_competition_sitl.md](user/rescue_competition_sitl.md) | 历史比赛/SITL 资料；使用前核对 deprecated 清单 |

## AI 与参考文档

| 文档 | 用途 |
| --- | --- |
| [ai/architecture.md](ai/architecture.md) | 当前模块边界 |
| [ai/interfaces.md](ai/interfaces.md) | 当前 Action/runtime/telemetry 接口 |
| [ai/control_flow.md](ai/control_flow.md) | 当前数据和命令流 |
| [ai/development_rules.md](ai/development_rules.md) | 开发规则 |
| [ai/task_checklist.md](ai/task_checklist.md) | 按任务追加阅读 |
| [reference/configuration.md](reference/configuration.md) | 当前配置说明 |

**当前实现以根目录 `README.md`、`AGENTS.md` 和 `docs/ai/current_architecture.md` 为准。**

`archive/` 和 `docs/refactor/` 保存历史材料，不是当前实现依据。旧 mission/stage 文档若未标注更新，均按
[deprecated_paths.md](ai/deprecated_paths.md) 处理。`docs/ai/repo_trim_plan.md` 提供了全仓库文件的 current/debug-only/legacy/archive 分类。
