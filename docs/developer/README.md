# 开发者文档

本目录面向维护代码、任务模板和飞控接口的开发者。第一次搭建整机请从
[新手教程](../beginner/01_preface.md) 开始；AI 编程助手应先阅读
[AI 接管入口](../ai/README.md)。

## 阅读顺序

1. [比赛任务设计](action_mission_rescue_2026.md)
2. [配置说明](configuration.md)
3. [坐标系规范](coordinate_frames.md)
4. [场地原点与方向](field_origin_heading.md)
5. [安全边界](safety.md)
6. [Telemetry Link 接口](telemetry_link_interfaces.md)
7. [平台与环境支持](platform_support.md)

## 内容边界

- `developer/` 解释任务设计、配置、坐标、安全和底层接口；
- `ai/` 告诉 AI 修改仓库时必须遵守哪些架构约束；
- `beginner/` 按实际搭建顺序说明采购、组装、部署、仿真和实飞。

当前正式任务入口是 Web UI 和 Action Mission。开发者不得恢复旧
mission/stage/control 主线，也不得让 Action 绕过 `ActionDispatcher` 直接发送
MAVLink。
