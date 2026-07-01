# Action 契约与坐标参数迁移方向

本文描述当前 Action 主线的边界和未来参数方向。Phase 1 不修改运行时 schema。

## Action 边界

- Action 位于 `missions/common/actions/`，由 `ActionRunner` 驱动。
- Action 可以读取 runtime context，并返回结构化 result 和 action request。
- Action 不直接调用 pymavlink，不直接连接 `telemetry_link.LinkManager`。
- `ActionRuntimeService` 把 result 交给 `ActionDispatcher`。
- `ActionDispatcher` 执行 SEND 双门控并调用 `LinkManager` 的公开接口。
- `config/action_missions/*.json` 只编排 Action，不包含 MAVLink message。

## 推荐坐标参数

FIELD 航点建议迁移为：

```json
{
  "frame": "FIELD",
  "field_x_m": 0.0,
  "field_y_m": 10.0,
  "altitude_m": 3.0
}
```

LOCAL_NED 建议使用 `local_n_m/local_e_m/z_down_m`；BODY_NED 速度建议使用
`vx_forward_mps/vy_right_mps/vz_down_mps`。完整符号约定见
[../reference/coordinate_frames.md](../reference/coordinate_frames.md)。

## 兼容现状

若干 Action 仍支持 `x/y/z/waypoint_mode/frame`。这些参数在迁移期保持兼容，但
语义模糊：新参数优先，旧参数最终应发出 deprecated 诊断。任何迁移必须同步更新
Action Lab 说明、Action Mission JSON、validator 和回归测试，不能一次性破坏模板。

FIELD 航点必须经过后续唯一 `CoordinateTransform`；未确认 Field Reference 时必须
拒绝实发。BODY_NED 速度不参与 FIELD 转换。

## 投放契约

投放主线只能是：

```text
payload_release Action → set_servo → MAV_CMD_DO_SET_SERVO
```

禁止 `release_payload()`、RC override 和 Action 内直接发送 MAVLink。舵机输出通道
不是遥控器 RC 输入通道。
