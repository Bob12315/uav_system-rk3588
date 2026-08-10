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

当前主线：

```text
Web UI → Action Lab / Action Mission → ActionRuntimeService → ActionRunner
→ missions/common/actions/* → ActionDispatcher → LinkManager → telemetry_link
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
python -m compileall app missions telemetry_link fusion yolo_app web_ui scripts
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/current tests/integration
python scripts/validate_action_missions.py
```

主线测试说明见 `tests/README.md`。Git 历史中的设计计划和重构快照不是当前实现依据。
