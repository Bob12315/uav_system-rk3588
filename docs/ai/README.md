# AI 快速接管

本项目只面向 Linux ARM64 RK3588。开始工作前按顺序阅读：

1. [current_architecture.md](current_architecture.md)
2. [action_contracts.md](action_contracts.md)
3. [deprecated_paths.md](deprecated_paths.md)
4. [../reference/coordinate_frames.md](../reference/coordinate_frames.md)
5. [../reference/field_origin_heading.md](../reference/field_origin_heading.md)
6. [../reference/safety.md](../reference/safety.md)
7. [task_checklist.md](task_checklist.md)
8. [repo_trim_plan.md](repo_trim_plan.md)

当前主线：

```text
Web UI → Action Lab / Action Mission → ActionRuntimeService → ActionRunner
→ missions/common/actions/* → ActionDispatcher → LinkManager → telemetry_link
```

不要恢复旧 mission/stage/control 栈。不要删除整个 `uav_ui/`，其共用工具尚未迁出。
不要让 Action 直接调用 MAVLink/LinkManager。不要使用 `release_payload` 或 RC override。

平台硬约束：

- RKNNLite + RK3588 NPU。
- 默认模型 `data/models/cuadc-fp16.rknn`。
- 不新增 x86、CUDA、PyTorch 或 GPU 推理路径。
- `executor.send_commands` 默认 false。
- 运行产物只进入 `runtime/`。

文件分类参考：[repo_trim_plan.md](repo_trim_plan.md)（current/debug-only/legacy/archive）
仓库盘点：[repo_file_inventory.txt](repo_file_inventory.txt)、[repo_loc_inventory.txt](repo_loc_inventory.txt)

验证：

```bash
python -m compileall app missions telemetry_link fusion yolo_app web_ui scripts
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/current tests/integration
python scripts/validate_action_missions.py
```

legacy 测试在 `tests/legacy/` 下，不作为主线 pytest 默认目标。
已知测试基线见 [../refactor/phase0_baseline.md](../refactor/phase0_baseline.md)。
