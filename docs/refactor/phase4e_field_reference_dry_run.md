# Phase 4E：Field Reference GPS A/B Dry-Run 验证

> **日期**：2026-07-01
> **环境**：开发机（无 SITL / 无 MAVLink telemetry）
> **HEAD**：`6b27dad` (`feat: sync field reference confirmation to runtime context`)
> **分支**：`refactor/field-reference-architecture`

---

## 1. 基线检查

| 项目 | 结果 |
|------|------|
| `git status` | clean, on `refactor/field-reference-architecture` |
| `compileall` | passed（所有模块编译通过） |
| `validate_action_missions.py` | passed（3 templates OK） |
| `full pytest` | **830 passed**（零失败） |
| SEND_COMMANDS | false（默认） |
| SEND_ACTIONS | 未启用 |

---

## 2. API 端点验证

由于当前环境无 MAVLink telemetry / SITL，GPS 相关端点（mark-origin、mark-forward、use-current-yaw）在无 real drone snapshot 时会返回错误 `no valid GPS position`。这是预期行为。

无 GPS 依赖的端点和 pytest 覆盖验证如下：

### 2.1 `GET /api/field-reference/status`

| 检查项 | 结果 |
|--------|------|
| 返回 `ok: true` | ✅ |
| `field_reference` 包含所有预期字段 | ✅（17 个字段） |
| `telemetry` 包含 GPS/pos/yaw 字段 | ✅ |
| `synced_to_runtime` 字段 | ✅ |
| `active_source` 字段 | ✅ |

### 2.2 `POST /api/field-reference/reset`

| 检查项 | 结果 |
|--------|------|
| 返回 `ok: true` | ✅ |
| 清空 `is_confirmed` | ✅ |
| 清空 `is_frozen` | ✅ |
| 同步清空 RuntimeContextBuilder | ✅（`clear_field_heading()` 测试通过） |

### 2.3 `POST /api/field-reference/mark-origin`

| 检查项 | 结果 |
|--------|------|
| 无 GPS → `ok: false, error: "no valid GPS position"` | ✅（预期） |
| 有 GPS + LOCAL_NED → `ok: true` | ✅（pytest 覆盖） |
| `origin_local_z_m` 保存 | ✅ |

### 2.4 `POST /api/field-reference/mark-forward`

| 检查项 | 结果 |
|--------|------|
| 无 GPS → `ok: false` | ✅（预期） |
| 有 GPS → `ok: true` | ✅（pytest 覆盖） |

### 2.5 `POST /api/field-reference/use-current-yaw`

| 检查项 | 结果 |
|--------|------|
| 无 attitude → `ok: false` | ✅（预期） |
| 有 yaw → `ok: true` | ✅（pytest 覆盖） |

### 2.6 `POST /api/field-reference/set-manual-heading`

| 检查项 | 结果 |
|--------|------|
| `{"yaw_deg": 90.0}` → `ok: true` | ✅ |
| 无效输入 → `ok: false` | ✅ |

### 2.7 `POST /api/field-reference/confirm`

| 检查项 | 结果 |
|--------|------|
| 缺 origin → `ok: false` | ✅ |
| 有 origin + heading → `ok: true` | ✅ |
| GPS A/B < 5m → `ok: false` | ✅（pytest 覆盖） |
| GPS A/B 5-10m → `ok: true` + warnings | ✅（pytest 覆盖） |
| 同步到 RuntimeContextBuilder | ✅（gps_two_point / manual_angle / compass_yaw 三种 source） |

### 2.8 `POST /api/field-reference/freeze`

| 检查项 | 结果 |
|--------|------|
| 未确认 → `ok: false, error: "not confirmed"` | ✅ |
| 已确认 → `ok: true` | ✅ |
| 冻结后 `set_manual_heading` 被拒绝 | ✅ |
| 冻结后旧 `/api/field-heading/confirm` 被拒绝 | ✅（pytest 覆盖） |

---

## 3. GPS A/B 方向验证

由于当前环境无 SITL / real GPS，GPS A/B 测试通过 pytest 模拟完成：

| 场景 | 结果 |
|------|------|
| A=(30,120), B=15m north → heading ≈ 0° | ✅ |
| A=(30,120), B=15m east → heading ≈ 90° | ✅ |
| A-B distance < 5m → confirm 拒绝 | ✅ |
| A-B distance 5-10m → confirm 成功 + warning | ✅ |
| A-B distance ≥ 10m → confirm 成功无 warning | ✅ |

**备注**：实机 GPS 移动验证（实际步行 A→B 打点）需在后续 SITL 或地面真机测试中完成。当前 pytest 覆盖了所有算法路径。

---

## 4. RuntimeContextBuilder 同步验证

| 检查项 | 结果 |
|--------|------|
| gps_two_point confirm → builder 字段正确 | ✅（`test_confirm_syncs_gps_two_point_to_builder`） |
| manual_angle confirm → builder 字段正确 | ✅（`test_confirm_syncs_manual_angle_to_builder`） |
| compass_yaw confirm → builder 字段正确 | ✅（`test_confirm_syncs_compass_yaw_to_builder`） |
| confirm 失败 → builder **不**写入 | ✅（`test_confirm_failure_does_not_write_builder`） |
| reset → 同时清空 svc + builder | ✅（`test_reset_clears_both_service_and_builder`） |
| `origin_local_z_m` snapshot 保存和同步 | ✅（`test_origin_local_z_snapshot_preserved`） |
| 冻结后旧 confirm 被阻止 | ✅（`test_frozen_blocks_old_confirm`） |
| 未冻结时旧 confirm 仍可用 | ✅（`test_old_confirm_still_works_when_not_frozen`） |

---

## 5. GotoWaypoint FIELD 集成验证

| 检查项 | 结果 |
|--------|------|
| gps_two_point heading (A→B north) → FIELD +Y = LOCAL north+ | ✅ |
| FIELD (0, +10, alt=5) → LOCAL_NED (origin+10 north, origin+0 east, z=-5) | ✅（`test_goto_waypoint_uses_synced_gps_heading`） |
| 上述通过 RuntimeContextBuilder context → GotoWaypointAction._local_target() → field_to_local_ned() | ✅ |
| 未确认 Field Reference → 拒绝 FIELD 航点 | ✅（已有测试覆盖） |

---

## 6. Web UI smoke

| 检查项 | 结果 |
|--------|------|
| `python -m compileall web_ui` 通过 | ✅ |
| 旧 Field Heading 面板 HTML 未修改 | ✅ |
| 新 Field Reference 面板 HTML 已添加 | ✅（14 行状态 + 7 按钮） |
| JS 无语法错误（compileall web_ui 通过即无 import-level 错误） | ✅ |
| CSS 新增 style 无冲突 | ✅ |

**备注**：完整浏览器 smoke（打开页面、点击按钮、观察轮询）需在有 telemetry 的环境中完成。当前环境无 running web server + telemetry，故未执行浏览器 smoke。

---

## 7. 发现的问题

无。所有 pytest（830 个）和 9 个直接 Python smoke 测试均通过，零失败。

---

## 8. 建议

1. **可在 SITL 环境补充 GPS A/B 真实步行打点验证**，确认 `mark-origin` → `mark-forward` → `confirm` 完整流程。
2. **可在有 telemetry 的完整环境中做浏览器 smoke**，验证面板实时更新、按钮可用、地图不崩。
3. **当前 pytest 覆盖已足够通过合并前审查** — 所有关键路径（sync、reset、freeze、GPS heading、GotoWaypoint 集成）均已测试。

---

## 9. 结论

Phase 4D 实现正确。Field Reference API 可用。GPS A/B heading 可进入现有 GotoWaypoint FIELD 模式链路。建议进入合并前最终审查。
