# AI/开发者快速接管

本项目只面向 Linux ARM64 RK3588。修改前按顺序阅读：

1. 根目录 `README.md` 和 `AGENTS.md`；
2. [当前架构](current_architecture.md)；
3. [Action 契约](action_contracts.md)；
4. [废弃路径](deprecated_paths.md)；
5. [坐标系](../developer/coordinate_frames.md)；
6. [Field Reference](../developer/field_origin_heading.md)；
7. [安全边界](../developer/safety.md)；
8. [任务阅读清单](task_checklist.md)。

进行全项目架构整理时，追加阅读并严格按单任务执行
[全项目架构重构任务书](architecture_refactor_tasks.md)。

在 RK3588 实机上部署本项目时，还必须阅读
[RK3588 AI 部署规范](DEPLOY_RK3588.md)。

当前主线：

```text
Web UI → typed routers → WebServices → Action Mission → ActionRuntimeService
→ thin Actions → guidance → ActionDispatcher → ActionSafetyPipeline → VehicleCommandPort
→ telemetry_link
```

核心规则：

- 不恢复旧 mission/stage/control 栈；
- Action 不直接调用 pymavlink 或 `LinkManager`；
- Web UI 是唯一正式人工操作入口；
- RKNNLite + RK3588 NPU，实机模型为 `cuadc2026-fp16.rknn`；
- 不新增 x86、CUDA、PyTorch 或 GPU 推理路径；
- `executor.send_commands` 默认保持 false；
- 投放只走 `payload_release → set_servo`；
- 运行产物只进入 `runtime/`。

验证：

```bash
python -m compileall app application contracts execution field guidance missions observability telemetry_link fusion yolo_app web_ui scripts
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/unit tests/contracts tests/integration tests/sitl
python scripts/validate_action_missions.py
```

主线测试说明见 `tests/README.md`。Git 历史中的设计计划和重构快照不是当前实现依据。
