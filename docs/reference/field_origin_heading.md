# Field Reference：场地原点与方向

Field Reference 把比赛 FIELD 坐标映射到飞控 LOCAL_NED。它由原点、heading、来源、
确认状态和冻结状态组成。当前代码只有 yaw-based 第一版；本文同时定义后续 GPS
辅助设计，不代表 Phase 1 已实现这些能力。

## 来源

```text
origin_source:
  - local_position
  - gps_marker
  - manual_gps_input

heading_source:
  - compass_yaw
  - gps_two_point
  - manual_angle
```

- `local_position`：记录确认时的 LOCAL_NED 位置。
- `gps_marker`：从飞控有效 GPS 状态记录标记点。
- `manual_gps_input`：用户输入经纬度标记点。
- `compass_yaw`：确认时使用飞控 yaw。
- `gps_two_point`：用 GPS A→B 方位角定义 FIELD `+Y`。
- `manual_angle`：用户明确输入 FIELD `+Y` 的角度。

本机罗盘可能受电池和大电流干扰，因此 FIELD heading 不能只依赖
`compass_yaw`；它只是可选来源之一。

## GPS A/B 推荐方案

```text
GPS 点 A = 场地原点辅助标记
GPS 点 B = 场地正前方参考点
A → B 的方位角 = FIELD +Y heading
```

- 单个 GPS 点只能定义原点，不能定义方向。
- A-B 距离太短时不得确认。
- 建议最小距离至少 5 m，推荐 10 m 以上。
- 后续实现还必须校验 GPS fix 和精度；具体 EPH/HDOP 阈值需要实机讨论确认。
- GPS 辅助只负责场地大方向和大范围航点。
- 最终投放精定位仍依赖视觉对准和激光高度。

## 确认和冻结

1. 用户选择 origin source 和 heading source。
2. 系统校验所需位置、GPS、角度和最小基线。
3. 用户显式确认后才生成可用 Field Reference。
4. 未确认时必须拒绝实发 FIELD 航点。
5. Action Mission 开始后 Field Reference 冻结。
6. yaw 跳变、GPS Home 更新和 EKF Origin 更新不能自动改写已确认值。
7. 只有停止相关 mission 并由用户重新确认后才能替换；具体解冻时机待实现前裁决。

## 当前实现与后续边界

当前 `app/runtime_context.py` 保存 LOCAL_NED 原点、yaw heading 和确认状态，并提供
FIELD↔LOCAL_NED 转换；Web UI 提供“确认场地方向/原点”按钮。后续应把现有逻辑
迁移到 `FieldReference`、`CoordinateTransform` 和 `FieldReferenceService`，而不是
建立平行实现。转换公式见 [coordinate_frames.md](coordinate_frames.md)。
