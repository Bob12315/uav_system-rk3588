# Phase 0 基线快照

> 这是创建重构分支时的快照，不是最终架构完成状态。

- 分支：`refactor/field-reference-architecture`
- 基线 HEAD：`ec8e31e1d222dc21d72647054c75aeec6e592cdd`
- 分支创建后工作区：clean
- GitHub/Gitee：均已推送同名分支
- 当前主线：Action Mission → ActionRuntimeService → ActionRunner → Action →
  ActionDispatcher → LinkManager → telemetry_link
- 旧 MissionRunner/stage/control 主线：依赖缺失、deprecated，并由运行时 fallback
  进入 `action_lab_only`
- `uav_ui`：terminal/curses UI deprecated，但 app 仍导入 runtime switches、命令
  分发和 YOLO client，不能直接删除
- 模型：部署文件是 `data/models/cuadc-fp16.rknn`；`config/yolo.yaml` 仍指向不存在的
  `cuadc2026-fp16.rknn`，旧 YOLO 文档仍有 INT8 默认描述

## 大文件快照

`web_ui/static/app.js` 2222 行、`app/system_runner.py` 1768 行、
`app/app_config.py` 1015 行、`align_descend.py` 894 行、
`app/action_dispatcher.py` 831 行、`telemetry_link/link_manager.py` 755 行、
`telemetry_link/command_sender.py` 687 行、`uav_ui/terminal_ui.py` 492 行、
`app/mission_orchestrator.py` 487 行。Phase 1 不拆这些文件。

## 测试快照

- compileall：通过。
- Action Mission validator：2 个主模板通过。
- 全量 pytest：12 个旧 mission/stage/control 测试模块在收集阶段失败。
- 排除这 12 个模块后：653 passed，28 failed。
- 28 个失败主要涉及 multi-photo fusion、multi-view/survey 联动、target localization
  默认参数/符号及 telemetry 根配置预期。

这些失败属于 Phase 0 已知基线；Phase 1 不修改测试或业务行为。
