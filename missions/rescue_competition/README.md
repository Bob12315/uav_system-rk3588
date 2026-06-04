# Rescue Competition Mission

新版 `rescue_competition` 面向固定下视相机和无偏航比赛流程：

- 摄像头固定垂直向下，不控制云台。
- 起飞/解锁时记录机头方向，后续 mission 坐标 `x` 为机头前方，`y` 为右方。
- 长距离移动使用 `local_position`。
- 目标上方微调用 `DOWNWARD_ALIGN_DESCEND` 输出 `vx/vy/vz`。
- 全程 `yaw_rate_cmd=0`，`shaper.max_yaw_rate=0`。
- 两个载荷默认通过舵机通道 8 和 9 投放。

## Flow

```text
PREPARE
-> ARM
-> TAKEOFF
-> GOTO_DROP_SURVEY
-> SURVEY_DROP_POINTS
-> PLAN_DROP_TARGETS
-> GOTO_DROP_TARGET
-> LOCK_DROP_TARGET
-> ALIGN_DESCEND_DROP
-> RELEASE_PAYLOAD
-> ASCEND_AFTER_DROP
-> NEXT_DROP_OR_RECCE
-> GOTO_RECCE_SURVEY
-> SURVEY_RECCE_POINTS
-> PLAN_RECCE_TARGETS
-> GOTO_RECCE_TARGET
-> LOCK_RECCE_TARGET
-> ALIGN_DESCEND_RECCE
-> CAPTURE_RECCE
-> ASCEND_AFTER_RECCE
-> NEXT_RECCE_OR_REPORT
-> REPORT_RECCE
-> RETURN_HOME
-> LAND
-> FINISH
```

投放阶段先在 5m 四点扫描建图，规划两个圆筒，3m 转场到目标上方，边微调边下降到
1m 后触发舵机。未完成两次投放时不会进入侦察区。

侦察阶段先在 5m 四点扫描建图，规划最多 5 个圆筒，3m 转场到目标上方，边微调边
下降到 2m 后统计危险品标识。确认 3 个危险品标识后停止访问剩余圆筒。

## Files

```text
mission.py                         mission 状态机和 YAML 配置装配
geometry.py                        图像偏移到地面位置估算
survey.py                          圆筒估计、聚类去重和目标选择
recce_report.py                    侦察结果 JSON 输出
stages/downward_align_descend/     固定下视微调下降 stage
config.yaml                        默认比赛参数
```

更详细的实现计划见：

```text
docs/ai/rescue_competition_redesign_plan.md
```

## Parameters To Measure

实机前需要测并写入 `config.yaml`：

- 通道 8/9 的 `hold_pwm`、`release_pwm` 和 `payload.release_wait_s`。
- 图像右/上方向对应的 `vision.image_y_sign` / `vision.image_x_sign`。
- 实际相机水平/垂直视场角 `vision.fov_x_deg` / `vision.fov_y_deg`。
- 5m 圆筒识别阈值、2m 危险品识别阈值和投票阈值。
- 1m 投放高度、2m 识别高度、微调最大速度和下降速度。
