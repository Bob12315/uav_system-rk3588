# Tests

## 目录结构

| 目录 | 用途 | 默认 pytest 目标 |
| --- | --- | --- |
| `tests/current/` | 当前主线单元测试（Action、runtime、dispatcher、fusion、yolo 等） | ✅ 是 |
| `tests/integration/` | 集成级测试（telemetry link 接口、Web UI、Action Lab 调度） | ✅ 是 |
| `tests/legacy/` | 旧架构/待审查模块测试 | ❌ 否 |

## 运行

```bash
# 主线测试（current + integration）
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/current tests/integration

# 包含 legacy 测试
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/

# 单个测试文件
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/current/test_takeoff_action.py
```

## legacy 测试说明

`tests/legacy/` 只用于不再服务当前运行路径的旧架构测试。当前 Action Mission 使用的
`app/mission_orchestrator.py` 测试属于 `tests/current/`，不得借分类排除。

| 测试文件 | 对应模块 | 状态 |
| --- | --- | --- |
| （当前无） | — | 已退役旧测试仍保留在下述失败基线文档中 |

## 历史基线

- 已退役的 12 个 import-failing 旧架构测试记录见 [LEGACY_TEST_RETIREMENT.md](LEGACY_TEST_RETIREMENT.md)
- Phase 2 主线失败基线见 [MAINLINE_FAILURE_BASELINE.md](MAINLINE_FAILURE_BASELINE.md)
- 重构基线快照见 [../docs/refactor/phase0_baseline.md](../docs/refactor/phase0_baseline.md)

不要通过忽略测试或隐藏旧失败来假装全绿。
