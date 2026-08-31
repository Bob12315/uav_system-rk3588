# 文档索引

`docs/` 只按读者分为三个一级目录：新手、开发者和 AI。历史设计计划、重构快照和旧
mission/stage/terminal UI 文档通过 Git 历史追溯，不再与当前教程混放。

## 新手

按顺序阅读 [beginner/01_preface.md](beginner/01_preface.md) 到
[beginner/06_flight_test.md](beginner/06_flight_test.md)：

1. [前言](beginner/01_preface.md)
2. [配置清单（含完整 BOM 表）](beginner/02_hardware_bom.md)
3. [RK3588 环境配置](beginner/04_rk3588_setup.md)
4. [SITL 测试](beginner/05_sitl_test.md)
5. [实飞测试](beginner/06_flight_test.md)

## 开发者

[developer/README.md](developer/README.md) 汇总比赛任务、配置、坐标系、Field Reference、
安全边界和 Telemetry Link 接口。

## AI

[ai/README.md](ai/README.md) 是 AI 文档总入口，并把当前程序说明、改造计划、证据记录和执行指南
分开导航。

当前实现发生冲突时，以根目录 `AGENTS.md`、
[ai/architecture/current_architecture.md](ai/architecture/current_architecture.md)、实际代码和配置为准。
