# Field Reference：场地原点与方向

唯一方案：**FieldProfile Centerline Only**

## 唯一方案

起飞点锚定 + 4 点以上中轴 GPS profile。

### 流程

1. 创建 FieldProfile JSON（schema v2），包含：
   - `anchor`：起飞点 GPS 锚点（lat/lon），field (0,0)
   - `centerline_points`：≥4 个 GPS 点沿场地中轴排列
   - `field_geometry`：lane/drop/recce 几何参数
   - `binding_policy`：绑定时 start error 和 centerline residual 的 warn/max 阈值

2. 起飞前通过 Web UI 或 API：
   - 选择 profile
   - 验证 profile（`/api/field-profiles/{id}/validate`）
   - 绑定当前位置（`/api/field-profiles/{id}/bind-current`）
   - 确认 freeze（`/api/field-reference/freeze`）

3. 绑定成功后：
   - `origin_local` = 当前 LOCAL_NED 位置（**不从 GPS 反算**）
   - `field_heading` = 中心线拟合 heading
   - `field_reference` confirmed + synced_to_runtime + frozen

运行时 GPS 采样只以有效样本数量为完成条件：达到 profile 的
`min_samples`（比赛 profile 为 20）即可确认，不要求固定采样时长。

4. Action Mission 启动前 preflight 强制检查：
   - `field_reference` confirmed
   - `synced_to_runtime` = true
   - `frozen` = true
   - 不满足则拒绝 mission start

## 关键设计规则

- **origin_local = 当前起飞点 LOCAL_NED**：GPS 不参与原点计算
- **current GPS 仅用于检查 start_error**（距离 anchor GPS 的偏差）
- **yaw/compass 不参与 FIELD heading 控制**：heading 完全来自 profile 中心线拟合
- **yaw_error 仅显示**：当前 yaw 与 field heading 的差值，纯诊断信息
- **中心线拟合**：anchor + centerline_points 的 ENU 坐标进行 PCA 直线拟合，方向从 anchor 指向远端

## 绑定规则

| 条件 | 结果 |
|---|---|
| `current_start_error_m ≤ warn_start_error_m` | OK |
| `warn < start_error ≤ max` | Warning, 但 ok=True |
| `start_error > max` | ok=False，拒绝 |
| `max_centerline_residual > max_centerline_residual_m` | ok=False，拒绝 |
| `warn < residual ≤ max` | Warning |

## 已删除的旧方案

以下旧方案入口已返回 410 Gone，不再可用：

- `/api/field-heading/confirm`
- `/api/field-reference/mark-origin`
- `/api/field-reference/mark-forward`
- `/api/field-reference/use-current-yaw`
- `/api/field-reference/set-manual-heading`
- `/api/field-reference/confirm`

旧 enum 值（`compass_yaw`、`gps_two_point`、`manual_angle` 等）保留为内部兼容但不可 API 操作。

## 保留的 API

- `/api/field-reference/status`
- `/api/field-reference/reset`
- `/api/field-reference/freeze`
- `/api/field-profiles`（列表）
- `/api/field-profiles/{profile_id}`（查看）
- `/api/field-profiles/{profile_id}/validate`（验证）
- `/api/field-profiles/{profile_id}/bind-current`（绑定，centerline-only）

## 坐标转换

FIELD ↔ LOCAL_NED 转换仍使用 `app/coordinate_transform.py`：
- `field_to_local_ned()` 和 `local_ned_to_field()` 保持不变
- 转换依赖 `FieldReference` 的 origin_local 和 field_heading_yaw_rad
- 未确认/未同步时拒绝实发 FIELD 航点

## 相关文件

- `app/field_profile.py` — FieldProfile 数据结构、验证、中心线拟合
- `app/field_profile_service.py` — 加载、验证、绑定逻辑
- `app/field_reference.py` — FieldReference 核心数据结构
- `app/field_reference_service.py` — FieldReference 生命周期服务
- `app/field_reference_controller.py` — HTTP API ↔ 后端桥接
- `app/coordinate_transform.py` — FIELD ↔ LOCAL_NED 数学
- `app/runtime_context.py` — RuntimeContextBuilder（内部同步桥）
