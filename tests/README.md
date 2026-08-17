# Test layout

| Directory | Scope |
|---|---|
| `unit/domain/` | Field, fusion, guidance, localization |
| `unit/mission/` | Action adapters and Mission engine |
| `unit/execution/` | authorization, double gates, deadman, stop/zero, queue cleanup, payload whitelist |
| `unit/adapters/` | Web, telemetry, YOLO, config and deployment adapters |
| `contracts/` | cross-producer schemas and architecture contracts |
| `integration/` | multi-component application paths |
| `sitl/` | marked simulated-flight acceptance |

Run the mainline with:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/unit tests/contracts tests/integration tests/sitl
```

SITL tests are isolated by directory; they never enable real-hardware SEND.
