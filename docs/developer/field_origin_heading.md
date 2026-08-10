# Field Reference：比赛场地原点与方向

本文面向维护 Field Profile、场地绑定和相关 Web 流程的开发者。

FIELD 是比赛任务使用的场地坐标系：`+Y` 指向场地前方，`+X` 指向场地右方。
FIELD 原点和 heading 必须由用户显式建立；任务执行期间二者冻结，yaw、罗盘、GPS
Home 或 EKF Origin 变化不得自动改写它们。

当前代码支持两类 Field Profile。比赛现场操作以 schema v3 runtime binding 为主；
schema v2 centerline profile 用于预先测绘的固定场地和 SITL。

## Schema v3：比赛现场初始化

模板：

```text
config/field_profiles/competition_runtime_v3.json
```

Web UI 的 `Competition Field Setup` 使用以下流程：

1. 用户输入位于场地 `+Y` 方向上的 forward marker GPS；
2. 系统加载 `competition_runtime_v3` 模板并创建本次运行 profile；
3. 飞机静止在起飞点，系统按 profile 要求采集当前 GPS 样本；
4. 通过 GPS 质量、样本数量、时间窗口和水平离散度检查；
5. 使用合格样本的中位位置作为运行时 GPS 原点 A；
6. heading 取动态原点 A 指向 forward marker B 的方位；
7. 动态 GPS 原点 A 作为本次 FIELD `(0, 0)` 的 GPS origin；
8. 根据 profile 生成投放区、侦察区和扫描航点的 GLOBAL 运行时几何；
9. 采样窗口和质量条件满足后，系统自动 finalize、apply 并 freeze，同时同步到
   RuntimeContext；操作者只负责启动、观察或取消采样。

schema v3 不建立 LOCAL_NED 场地原点，因此 `is_ready_for_field_to_local=false`；它只为
FIELD → GPS/GLOBAL 航点提供已确认的 origin 和 heading。需要 LOCAL_NED FIELD 转换时
应使用完成 local origin 绑定的 schema v2 流程。

当前模板的主要约束包括：

- 至少采集 20 个合格样本；
- 采样窗口 12 秒；
- 最大水平离散度 1 m；
- forward marker baseline 必须满足模板阈值；
- GPS fix、卫星数、EPH、EPV 必须满足 profile。

`competition_runtime_v3.json` 是 `template_only`，其中 placeholder GPS 不能直接作为
正式场地数据使用。forward marker 必须由现场操作者输入。

## Schema v2：预采集中心线场地

示例和现有 profile：

```text
config/field_profiles/XSYU.json
config/field_profiles/sitl_centerline_lane.json
config/field_profiles/example_centerline_lane.json
```

schema v2 profile 包含：

- `anchor`：预先测得的起飞点 GPS，对应 FIELD `(0, 0)`；
- `centerline_points`：至少 4 个沿场地中轴排列的 GPS 点；
- `field_geometry`：投放区、侦察区和航道几何；
- `binding_policy`：起点误差和中心线拟合残差阈值。

绑定时：

1. 验证 profile；
2. 使用当前 GPS 检查与 anchor 的 start error；
3. 使用 anchor 和中心线点 PCA 拟合 FIELD `+Y` heading；
4. `origin_local` 取当前 LOCAL_NED 位置，不从 GPS 反算；
5. 用户确认并 freeze。

中心线 residual 或 start error 超过最大阈值时必须拒绝绑定；处于 warn 与 max 之间时
允许继续但必须向操作者显示 warning。

## 任务启动前置条件

使用 FIELD 或由 FIELD 派生 GPS 航点的 Action Mission 启动前必须检查：

- Field Reference 已 confirmed；
- 已同步到 RuntimeContext；
- 已 frozen；
- profile 和运行时几何有效；
- 对需要 GPS 派生航点的任务，运行时 origin/heading 和 GPS 质量满足对应 preflight。

任一条件不满足都必须拒绝 mission start。加载模板、查看地图、采样和配置本身不得发送
飞行动作。

## 坐标转换

FIELD ↔ LOCAL_NED 的唯一实现源是 `app/coordinate_transform.py`：

```text
field_to_local_ned()
local_ned_to_field()
```

schema v3 根据动态 GPS origin 和 heading 生成 GLOBAL 航点，不把 GPS 原点伪装成
LOCAL_NED 原点。Action 不得复制坐标公式，也不得根据 Web UI 像素位置推断飞控坐标。

高度统一使用 `altitude_m` 向上为正，转换到 LOCAL_NED 时：

```text
z_down_m = -altitude_m
```

## API

当前保留的主要入口：

- `/api/field-reference/status`
- `/api/field-reference/reset`
- `/api/field-reference/freeze`
- `/api/field-profiles`
- `/api/field-profiles/{profile_id}`
- `/api/field-profiles/{profile_id}/validate`
- `/api/field-profiles/{profile_id}/bind-current`（schema v2）
- `/api/field-profiles/{profile_id}/runtime-sampling/start`（schema v3）
- `/api/field-reference/runtime-sampling/finalize`（兼容/恢复入口；主 Web 流程自动完成）
- `/api/field-reference/runtime-sampling/cancel`
- `/api/field-reference/runtime-sampling/start`（Web 比赛现场快捷入口）

以下旧式手动 heading/origin API 已返回 410 Gone，不得恢复为正式流程：

- `/api/field-heading/confirm`
- `/api/field-reference/mark-origin`
- `/api/field-reference/mark-forward`
- `/api/field-reference/use-current-yaw`
- `/api/field-reference/set-manual-heading`
- `/api/field-reference/confirm`

## 相关实现

- `app/field_profile.py` — schema v2/v3 数据结构与验证
- `app/runtime_field_binding.py` — schema v3 GPS 采样和 binding candidate
- `app/runtime_binding_orchestrator.py` — schema v3 生命周期与应用
- `app/runtime_field_geometry.py` — 比赛运行时场地几何
- `app/field_profile_service.py` — profile 加载、验证和 schema v2 绑定
- `app/field_reference.py` — Field Reference 核心数据结构
- `app/field_reference_service.py` — Field Reference 生命周期
- `app/field_reference_controller.py` — HTTP API 与后端桥接
- `app/coordinate_transform.py` — FIELD ↔ LOCAL_NED 唯一数学实现
- `app/runtime_context.py` — Action runtime context 同步桥
