# 文档索引

本目录只保留当前比赛系统仍在使用的教程、操作手册和权威规范。已完成的设计计划、
重构过程记录、仓库快照以及旧 mission/stage/terminal UI 文档已经删除，历史变化由 Git
提交记录追溯。

## 新手入口

| 文档 | 用途 |
| --- | --- |
| [../README.md](../README.md) | 项目介绍和完整学习路线 |
| [beginner/README.md](beginner/README.md) | 从采购、组装到比赛操作的连续教程 |
| [hardware/README.md](hardware/README.md) | BOM、接线、供电、相机、MAVLink 和投放记录 |

## 比赛与用户操作

| 文档 | 用途 |
| --- | --- |
| [mission/action_mission_rescue_2026.md](mission/action_mission_rescue_2026.md) | 当前完整比赛任务和分项模板 |
| [user/README.md](user/README.md) | 已完成安装后的用户入口 |
| [user/install.md](user/install.md) | RK3588 app/yolo 环境安装 |
| [user/running.md](user/running.md) | 服务、配置、更新和日志 |
| [user/sitl_start.md](user/sitl_start.md) | 当前 SITL/Gazebo 联调 |

## 架构与开发

| 文档 | 用途 |
| --- | --- |
| [ai/README.md](ai/README.md) | AI/开发者快速接管 |
| [ai/current_architecture.md](ai/current_architecture.md) | 当前唯一 Action 主线和模块边界 |
| [ai/action_contracts.md](ai/action_contracts.md) | Action、参数、速度和投放契约 |
| [ai/interfaces.md](ai/interfaces.md) | Action/runtime/telemetry 总体接口 |
| [ai/deprecated_paths.md](ai/deprecated_paths.md) | 禁止恢复的旧路径 |
| [ai/task_checklist.md](ai/task_checklist.md) | 按修改类型追加阅读和验证 |

## 权威参考

| 文档 | 用途 |
| --- | --- |
| [reference/configuration.md](reference/configuration.md) | 当前配置文件和 profile |
| [reference/coordinate_frames.md](reference/coordinate_frames.md) | 坐标系唯一规范源 |
| [reference/field_origin_heading.md](reference/field_origin_heading.md) | Field Reference schema v2/v3 |
| [reference/safety.md](reference/safety.md) | SEND、停止、断线和投放安全边界 |
| [reference/telemetry_link_interfaces.md](reference/telemetry_link_interfaces.md) | LinkManager 公开接口 |

当前实现冲突时，以根 `AGENTS.md`、
[current_architecture.md](ai/current_architecture.md)、实际代码和配置为准。不要根据 Git
历史中的旧文档恢复 mission/stage/control、CommandShaper 或 FlightCommandExecutor。
