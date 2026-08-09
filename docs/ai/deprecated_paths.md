# Deprecated 路径清单

本清单用于阻止后续开发误恢复旧架构。`deprecated` 不等于都能立即删除。

| 项目 | 状态与原因 | 当前替代 | 现在可删除？/前置迁移 |
| --- | --- | --- | --- |
| terminal/curses UI | 已删除；Web UI 是正式入口 | `web_ui/` | 不得恢复独立 terminal 人工操作入口 |
| `MissionRunner` | 旧 mission 主线，依赖缺失；SystemRunner fallback 已清理 | `MissionOrchestrator` | 文件暂留历史参考；最终 legacy removal 时删除 |
| `StageRegistry` | 旧 stage 注册表，依赖缺失；SystemRunner fallback 已清理 | Action registry | 文件暂留历史参考；最终 legacy removal 时删除 |
| `CommandShaper` | 旧 stage 命令整形器，不在 Action 主线 | 待裁决的 Action-compatible safety pipeline | 不能用“删除测试”代替安全裁决，也不得恢复旧栈 |
| `FlightCommandExecutor` | 旧 stage 执行器，不在 Action 主线 | 当前为 `ActionDispatcher → LinkManager` | 待安全架构裁决后清理 |
| `missions/<mission>/mission.py` | deprecated 旧式任务插件 | `config/action_missions/*.json` | 不新增；旧引用清理后可删残留 |
| `missions/<mission>/stages/<stage>` | deprecated 旧式控制阶段 | `missions/common/actions/` | 不新增；旧引用清理后可删残留 |
| `missions.visual_tracking` | missing/deprecated | Action/Action Mission | 清理旧测试和配置说明后删除引用 |
| `missions.rescue_competition` | missing/deprecated | Action Mission 模板 | 清理旧测试和配置说明后删除引用 |
| `missions.common.control` | missing/deprecated | Action runtime + 待裁决安全管线 | 不恢复；先解决连续命令安全边界 |
| `release_payload` 接口 | disabled/错误投放抽象 | `payload_release` Action → `set_servo` | 清理旧 runner/文档引用后可删 |
| RC override 投放 | deprecated，通道语义和安全边界不合适 | `set_servo` | 可禁止；不得新增兼容路径 |
| INT8 默认部署路径 | 当前模型已废弃/未验证 | `data/models/cuadc2026-fp16.rknn` | 可清理默认描述；硬件仍可支持未来经验证的 INT8 |

旧测试的分类和删除必须在 Phase 2 单独完成，不能在文档阶段通过忽略测试掩盖。
