# Phase 3.5：Field Reference 迁移对照分析

> **基线**：`54156cc` — `feat: add field reference coordinate transform primitives`
> **full pytest**：767 passed
> **状态**：纯逻辑模块就绪，尚未接入 `runtime_context.py` 或 Action 链路

---

## 1. `runtime_context.py` 当前 Field Reference 字段

`RuntimeContextBuilder` 实例属性（`app/runtime_context.py:24-32`）：

| # | 属性 | 类型 | 说明 |
|---|------|------|------|
| 1 | `field_heading_yaw_rad` | `float \| None` | FIELD +Y 在 LOCAL_NED 中的 yaw，归一化到 `(-π, π]` |
| 2 | `field_heading_time` | `float \| None` | 确认时间戳 |
| 3 | `field_heading_confirmed` | `bool` | heading 是否已确认 |
| 4 | `field_heading_source` | `str` | 来源（`"manual"` / `"takeoff_auto"` 等） |
| 5 | `field_origin_local_x` | `float \| None` | LOCAL_NED 原点 north |
| 6 | `field_origin_local_y` | `float \| None` | LOCAL_NED 原点 east |
| 7 | `field_origin_local_z` | `float \| None` | LOCAL_NED 原点 down |
| 8 | `field_origin_time` | `float \| None` | 原点确认时间戳 |
| 9 | `field_origin_confirmed` | `bool` | 原点是否已确认 |

**关键方法**：

| 方法 | 行号 | 功能 |
|------|------|------|
| `field_transform_ready()` | 122-129 | heading + origin 都确认 + 都有值 → True |
| `field_transform()` | 131-139 | 返回 `{heading_yaw_rad, origin_local_x/y/z, confirmed, convention}` dict |
| `field_to_local_xy(fx, fy)` | 156-167 | FIELD → LOCAL_NED XY，公式：`local_dx = fy·cos - fx·sin`，`local_dy = fy·sin + fx·cos` |
| `local_to_field_xy(lx, ly)` | 141-154 | 逆变换 |
| `field_position_from_drone(drone)` | 169-185 | 把 drone 位置转为 field 位置 |
| `confirm_field_heading(yaw, drone, source)` | 187-225 | 同时确认 heading 和 origin，记录时间戳 |
| `build_action_context(snapshot)` | 38-120 | 把所有 field 状态注入 context dict |
| `_normalize_yaw(yaw)` | 267-268 | `atan2(sin, cos)` → `(-π, π]` |

**context dict 输出的 key**（由 `build_action_context` 生成）：

```text
field_heading_yaw_rad       (float | None)
field_heading_time           (float | None)
field_heading_confirmed      (bool)
field_heading_source         (str)
field_origin_local_x         (float | None)
field_origin_local_y         (float | None)
field_origin_local_z         (float | None)
field_origin_time            (float | None)
field_origin_confirmed       (bool)
field_transform              (dict: heading_yaw_rad, origin_local_x/y/z, confirmed, convention)
field_position               (dict: x, y, z, local_x/y/z, source, confirmed) — 仅当 local_position_valid
local_position               (dict: x, y, z) — 来自 drone
```

---

## 2. 新 `FieldReference` 字段清单

`app/field_reference.py` — `FieldReference` dataclass：

| # | 属性 | 类型 | 说明 |
|---|------|------|------|
| 1 | `is_confirmed` | `bool` | 已确认（合并了 `field_heading_confirmed` + `field_origin_confirmed`） |
| 2 | `is_frozen` | `bool` | 已冻结（新增，mission 执行期不可变） |
| 3 | `origin_source` | `str \| None` | `local_position` / `gps_marker` / `manual_gps_input` |
| 4 | `heading_source` | `str \| None` | `compass_yaw` / `gps_two_point` / `manual_angle` |
| 5 | `origin_local_n_m` | `float \| None` | LOCAL_NED 原点 north（对应旧 `field_origin_local_x`） |
| 6 | `origin_local_e_m` | `float \| None` | LOCAL_NED 原点 east（对应旧 `field_origin_local_y`） |
| 7 | `origin_lat` | `float \| None` | GPS A 点纬度（新增） |
| 8 | `origin_lon` | `float \| None` | GPS A 点经度（新增） |
| 9 | `forward_marker_lat` | `float \| None` | GPS B 点纬度（新增） |
| 10 | `forward_marker_lon` | `float \| None` | GPS B 点经度（新增） |
| 11 | `field_heading_yaw_rad` | `float \| None` | 归一化 yaw（与旧字段同名同语义） |
| 12 | `confirmed_at_s` | `float \| None` | 确认时间戳（合并了 `_heading_time` + `_origin_time`） |

**关键方法**：

| 方法 | 功能 |
|------|------|
| `is_ready()` | `is_confirmed` + `origin_local_n_m` + `origin_local_e_m` + `field_heading_yaw_rad` 全 finite |
| `confirm()` | 校验所有必需字段后标记 `is_confirmed = True` |
| `confirm_with_warnings()` | 同上，返回 `(ok, warnings)` |
| `freeze()` | 冻结，阻止修改 |
| `reset()` | 清除全部字段回初始状态 |
| 各种 `set_*` | 有 frozen guard 的 setter |

`app/coordinate_transform.py` — 转换函数：

| 函数 | 功能 |
|------|------|
| `field_to_local_ned(fx, fy, alt, ref) → LocalNedPoint` | FIELD → LOCAL_NED 规范实现 |
| `local_ned_to_field(n, e, zd, ref) → FieldPoint` | 逆变换规范实现 |

---

## 3. 字段映射表

| 旧 `RuntimeContextBuilder` | 新 `FieldReference` | 差异 |
|---|---|---|
| `field_heading_yaw_rad` | `field_heading_yaw_rad` | 同名同语义 |
| `field_heading_time` | `confirmed_at_s` | 合并；旧有两个时间戳，新只有一个 |
| `field_heading_confirmed` | `is_confirmed` | 合并；旧有两个 bool，新只有一个 |
| `field_heading_source` | `heading_source` | 旧为任意 str（`"manual"`、`"takeoff_auto"`）；新为枚举值 |
| `field_origin_local_x` | `origin_local_n_m` | **命名变化**：`x`→`north_m`（语义一致，都是 LOCAL_NED north） |
| `field_origin_local_y` | `origin_local_e_m` | **命名变化**：`y`→`east_m` |
| `field_origin_local_z` | _(无)_ | 新模块不存 z；z 仅在转换时通过 `altitude_m` 参数传入 |
| `field_origin_time` | `confirmed_at_s` | 合并 |
| `field_origin_confirmed` | `is_confirmed` | 合并 |
| _(无)_ | `origin_source` | 新增 |
| _(无)_ | `is_frozen` | 新增 |
| _(无)_ | `origin_lat / origin_lon` | 新增 GPS A |
| _(无)_ | `forward_marker_lat / lon` | 新增 GPS B |
| `field_transform_ready()` | `is_ready()` | 等价的 readiness 检查 |
| `field_transform()` → dict | _(无直接等价)_ | 需在迁移时构造兼容 dict |
| `field_to_local_xy(fx, fy)` | `field_to_local_ned(fx, fy, alt, ref)` | 新接口增加 `altitude_m` 和 `reference` 参数 |
| `local_to_field_xy(lx, ly)` | `local_ned_to_field(n, e, zd, ref)` | 新接口增加 `z_down_m` 和 `reference` 参数 |
| `confirm_field_heading(yaw, drone, source)` | `FieldReferenceService` 方法 | 拆分：先设置 origin/heading，再 `confirm()` |
| `_normalize_yaw(yaw)` | `FieldReference._normalize_yaw(yaw)` | 实现一致，新版本修复了 `-π`→`π` 的边界 |

---

## 4. 当前 FIELD→LOCAL_NED 转换入口清单

### 4.1 重复实现 #1（Action 链路，最活跃）

**文件**：`missions/common/actions/goto_waypoint.py`，行 253-275
**方法**：`GotoWaypointAction._local_target(context)`
**公式**：
```python
cos_yaw = math.cos(field_heading_yaw_rad)
sin_yaw = math.sin(field_heading_yaw_rad)
dx_north = self.target_y * cos_yaw - self.target_x * sin_yaw
dy_east = self.target_y * sin_yaw + self.target_x * cos_yaw
return {"x": origin_x + dx_north, "y": origin_y + dy_east, "z": self.target_z}
```
**调用链**：`survey_area` → `multi_view_localize` → `recon_scan` → `recon_inspect_target` 全部通过 `_new_goto_action()` 委托到此处
**影响范围**：所有 `waypoint_mode="field"` 的航点飞行

### 4.2 重复实现 #2（保留 helper，非当前生产路径）

**文件**：`app/runtime_context.py`，行 156-167
**方法**：`RuntimeContextBuilder.field_to_local_xy(fx, fy)`
**公式**：
```python
local_dx = fy * math.cos(yaw) - fx * math.sin(yaw)
local_dy = fy * math.sin(yaw) + fx * math.cos(yaw)
return (origin_x + local_dx, origin_y + local_dy)
```
**用途**：当前为保留的重复 helper。`field_position` 实际由
`local_to_field_xy()`（逆变换，见 4.3）通过 `field_position_from_drone()` 生成；
`field_transform` 只是状态元数据字典，不涉及坐标转换。
Phase 4A 仍可先收敛此方法，但不应将其误称为现有 `field_position` 生产路径。
**影响范围**：当前仅在测试中使用；非生产链路入口点。

### 4.3 重复实现 #3（context 富化，逆变换）

**文件**：`app/runtime_context.py`，行 141-154
**方法**：`RuntimeContextBuilder.local_to_field_xy(lx, ly)`
**公式**：
```python
dx = lx - ox; dy = ly - oy
return (-dx * sin(yaw) + dy * cos(yaw), dx * cos(yaw) + dy * sin(yaw))
```
**用途**：`field_position_from_drone()`、`_with_field_coordinates()` 中把 LOCAL_NED 位置/目标坐标转为 FIELD 坐标显示

### 4.4 规范实现 #4（新，FIELD→LOCAL_NED）

**文件**：`app/coordinate_transform.py`，行 43-91
**函数**：`field_to_local_ned(fx, fy, alt, ref) → LocalNedPoint`

### 4.5 规范实现 #5（新，逆变换）

**文件**：`app/coordinate_transform.py`，行 94-125
**函数**：`local_ned_to_field(n, e, zd, ref) → FieldPoint`

### 4.6 Web UI 前端转换

**文件**：`web_ui/static/app.js`，行 283-304
**函数**：`localPointToField()` / `pointForFieldMap()` — 在浏览器端做
LOCAL_NED→FIELD 转换用于地图/状态显示。`localPointToField()` 将 `local_x`/`local_y`
减去 origin 后通过逆旋转矩阵转为 `field_x`/`field_y`；`pointForFieldMap()` 优先使用
已有的 `field_x`/`field_y`，缺失时调用 `localPointToField()` 转换。
**说明**：此为前端显示转换，不是后端航点实发转换，暂不纳入 Phase 4A 后端迁移范围。

---

## 5. Field 链路全景

```
┌─────────────────────────────────────────────────────────────────────┐
│ Web UI (app.js)                                                     │
│  ├─ Field map canvas: FIELD coords → canvas pixels                  │
│  ├─ Confirm button → POST /api/field-heading/confirm                │
│  └─ Action Lab params: waypoint_mode="field" (default)              │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ HTTP / WebSocket
┌──────────────────────────────▼──────────────────────────────────────┐
│ app/system_runner.py                                                │
│  ├─ confirm_field_heading_manual() → RuntimeContextBuilder.confirm  │
│  ├─ field_heading_status() → Web UI state                           │
│  └─ _with_field_coordinates() → local_to_field_xy() for display    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│ app/runtime_context.py (RuntimeContextBuilder)                      │
│  ├─ field_heading_yaw_rad / field_origin_local_x/y/z               │
│  ├─ field_to_local_xy() ★ DUPLICATE #2                             │
│  ├─ local_to_field_xy()  ★ DUPLICATE #3                            │
│  └─ build_action_context() → context dict with field_* keys        │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ context dict
┌──────────────────────────────▼──────────────────────────────────────┐
│ missions/common/actions/goto_waypoint.py                            │
│  └─ _local_target() ★ DUPLICATE #1                                 │
│       (called by survey_area / multi_view_localize / recon_scan)   │
└──────────────────────────────┬──────────────────────────────────────┘
                               │ action dict (already LOCAL_NED)
┌──────────────────────────────▼──────────────────────────────────────┐
│ app/action_dispatcher.py                                            │
│  └─ _dispatch_local_position() → LinkManager → MAVLink             │
└─────────────────────────────────────────────────────────────────────┘
```

**新模块（尚未接入）**：

```
app/field_reference.py          → FieldReference dataclass + 验证
app/coordinate_transform.py     → field_to_local_ned() / local_ned_to_field()
app/field_reference_service.py  → FieldReferenceService 封装
```

---

## 6. 必须保持兼容的地方

以下接口在迁移期间 **不能改变输出格式或语义**：

| 位置 | 兼容要求 |
|------|----------|
| `build_action_context()` 输出的 dict key | `field_heading_yaw_rad`、`field_heading_confirmed`、`field_heading_source`、`field_origin_local_x`、`field_origin_local_y`、`field_origin_local_z`、`field_origin_confirmed`、`field_transform`、`field_position` 的 key 名和结构不能变 |
| `field_transform` dict 结构 | `{heading_yaw_rad, origin_local_x, origin_local_y, origin_local_z, confirmed, convention}` 必须保持 |
| `field_position` dict 结构 | `{x, y, z, local_x, local_y, local_z, source, confirmed}` 必须保持 |
| `GotoWaypointAction._local_target()` 输出 | `{x, y, z}` 的 key 名、frame=1 的语义不变 |
| `confirm_field_heading()` 签名 | `(yaw_rad, drone, source) → bool` |
| Web UI `POST /api/field-heading/confirm` | 请求/响应格式不变 |
| `_with_field_coordinates()` | 输出对象附加 `field_x`/`field_y` 不变 |
| `action["field_origin_local_x"]` 等 dispatch detail | ActionDispatcher 日志和 detail 中使用的 key 名 |

**命名差异处理**：新旧之间有 `x`↔`north_m`、`y`↔`east_m` 命名差异。迁移期间可通过适配层（wrapper / property alias）保持 context dict 输出 key 不变，内部改用新模块。

---

## 7. 迁移阶段建议

### Phase 4A：runtime_context 内部切换到 CoordinateTransform（最小风险）

**目标**：让 `RuntimeContextBuilder.field_to_local_xy()` 和 `local_to_field_xy()` 内部调用 `coordinate_transform.field_to_local_ned()` / `local_ned_to_field()`，但对外输出完全不变。

**改动范围**：
- `app/runtime_context.py`：`field_to_local_xy()` 和 `local_to_field_xy()` 改为委托新模块
- 新增 `FieldReference` 实例作为 `RuntimeContextBuilder` 的内部状态持有者（或保持现有属性，仅复用转换函数）

**不改变**：
- context dict key 名不变
- `confirm_field_heading()` 签名不变
- Action 行为不变
- Web UI 不变

**风险**：低。对照测试已证明新旧公式数值一致。
**测试**：现有 `test_runtime_context.py`、`test_goto_waypoint_action.py` 全部通过即成功。

---

### Phase 4B：GotoWaypointAction 去除重复转换

**目标**：`GotoWaypointAction._local_target()` 改为调用 `coordinate_transform.field_to_local_ned()`。

**改动范围**：
- `missions/common/actions/goto_waypoint.py`：`_local_target()` 内部替换公式
- 可能需要从 context 构造 `FieldReference`（或接受 context 中的 `field_transform` dict 临时构造）

**不改变**：
- `_local_target()` 输出 `{x, y, z}` 不变
- Action 行为不变

**风险**：低-中。需要确保 `FieldReference` 从 context dict 正确重建。`x`/`y` vs `north_m`/`east_m` 命名需适配。
**测试**：`test_goto_waypoint_action.py` 全部通过。

---

### Phase 4C：扩展 Web UI Field Reference API

**目标**：Web UI 支持 `origin_source` / `heading_source` 枚举选择和 GPS A/B 输入。

**改动范围**：
- `web_ui/static/app.js`：新增 GPS 输入控件、source 选择器
- `web_ui/static/index.html`：新增 UI 元素
- `web_ui/server.py`：新增或扩展 API endpoint
- `app/system_runner.py`：接入 `FieldReferenceService`

**风险**：中。Web UI 改动需保持向后兼容，不能破坏现有 Field Heading 确认流程。
**测试**：`test_web_ui.py` + 手工测试。

---

### Phase 4D：接入 GPS A/B 辅助

**目标**：从飞控 GPS 状态读取实际经纬度，填入 `FieldReference`。

**改动范围**：
- 从 telemetry snapshot 提取 GPS 数据
- `FieldReferenceService.mark_gps_origin()` / `mark_gps_forward()` 接入真实数据
- 校验 GPS fix type、HDOP/EPH 阈值

**风险**：高。涉及飞行安全——错误的 GPS 标记会导致错误的 FIELD→LOCAL_NED 转换。必须在 SITL 中充分测试。
**测试**：需要 SITL 环境 + GPS 模拟。

---

## 8. 每阶段风险和测试

| 阶段 | 风险等级 | 关键风险 | 回滚方案 |
|------|----------|----------|----------|
| 4A | 低 | 数值精度偏差 | git revert |
| 4B | 低-中 | context → FieldReference 构造 bug | git revert |
| 4C | 中 | Web UI 兼容性断裂 | 保留旧 API，新增可选参数 |
| 4D | 高 | GPS 精度不足 / 错误标记导致飞行偏离 | feature flag + SITL 验证 |

---

## 9. 需要 Codex review 的高风险点

1. **context dict 兼容性断裂**（Phase 4A）：当 `RuntimeContextBuilder` 内部切换到 `FieldReference` 时，`build_action_context()` 输出的 `field_heading_source` 从任意 str 变为枚举值 — 下游 Action（如 `takeoff.py` 设置的 `"takeoff_auto"`）和 Web UI 可能依赖特定字符串。建议：保留字符串兼容，或先对齐所有设置方。

2. **`origin_local_x/y` → `north_m/east_m` 命名迁移**（Phase 4A/4B）：context dict 的 key（`field_origin_local_x`）和 `FieldReference` 的属性（`origin_local_n_m`）命名不同。迁移时需明确适配层位置：是在 `build_action_context()` 做映射，还是在 `FieldReference` 上加 property alias。

3. **`origin_local_z` 语义**（Phase 4A）：旧代码存储 `field_origin_local_z`，新模块不存 z。`field_to_local_ned()` 的 z 完全由 `altitude_m` 参数决定（`z_down = -altitude_m`）。这不影响 2D XY 转换，但如果任何下游依赖 `field_origin_local_z` 做高度偏移计算，需要在迁移前确认。

4. **`confirmed_at_s` 合并**（Phase 4A）：旧代码有两个独立时间戳（`field_heading_time` 和 `field_origin_time`），新代码只有一个 `confirmed_at_s`。`build_action_context()` 当前分别输出两个时间戳，合并后需决定是否仍输出两个（相同值）还是只输出一个。

5. **freeze 语义引入**（Phase 4B+）：当前代码没有 freeze 概念。如果 Phase 4B 引入 freeze（在 mission 开始时冻结），需确保不影响 takeoff 阶段的 `auto_confirm_field_heading` 流程。

6. **GPS fix 校验标准**（Phase 4D）：`MIN_GPS_BASELINE_M = 5m` 和 `RECOMMENDED_GPS_BASELINE_M = 10m` 是基于通用建议的值。实际部署前需根据场地和飞控 GPS 精度校准 EPH/HDOP 阈值。

---

## 10. 对照测试覆盖

`tests/test_coordinate_transform.py` 中已有：

- `test_matches_runtime_context_field_to_local_xy`（5 组参数化，yaw=0.5）
- 正向 heading=0、π/2、π 测试
- 往返测试（8 组参数化）
- 逆变换往返测试（4 组参数化）

建议追加（见 `tests/test_field_reference_runtime_context_parity.py`）：

- 更多 yaw 角度的 `field_to_local` 对照
- `local_to_field` 逆变换对照
- `z_down = -altitude_m` 一致性
- 未确认拒绝语义对照
