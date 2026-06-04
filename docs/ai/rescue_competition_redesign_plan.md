# Rescue Competition Redesign Plan

本文记录新版救援比赛 mission 的设计方案，用于后续生成程序。旧
`missions/rescue_competition/` 已废弃，新实现应围绕真实机体条件重建：

- 摄像头固定垂直向下，不使用云台控制。
- 载荷由飞控 RC 舵机通道投放，默认通道 8 和 9。
- 比赛全程不主动偏航，机头保持启动/解锁时方向。
- 长距离移动使用 `local_position` 航点动作。
- 目标上方微调用 `vx/vy/vz` 连续速度命令。
- 所有连续命令必须经过 `CommandShaper` 和 `FlightCommandExecutor`。
- 默认保持 `executor.send_commands: false`。

## 1. 设计目标

新版 mission 目标不是沿用旧状态机，而是实现一套更适合当前飞机的简洁流程：

```text
起飞
-> 投放区 5m 四点扫描建图
-> 规划两个投放圆筒
-> 3m 飞到目标上方
-> 边微调边慢降到 1m
-> 舵机投放
-> 回 3m 去第二个目标
-> 完成两次投放后进入侦察区
-> 侦察区 5m 四点扫描建图
-> 3m 飞到圆筒上方
-> 边微调边慢降到 2m
-> 悬停识别危险品标识
-> 确认 3 个标识后停止访问剩余圆筒
-> 返航、降落、结束
```

核心策略是“先扫描建图，再低空执行”，避免边飞边找导致重复目标和流程不可控。

## 2. 固定约定

### 2.1 坐标系

在解锁或 mission 正式开始时记录本地原点和机头方向：

```text
x: 启动/解锁时机头正前方
y: 启动/解锁时机头右侧
z: NED 坐标，向上为负
```

示例：

```text
z=-5.0 表示原点上方 5m
z=-3.0 表示原点上方 3m
z=-1.0 表示原点上方 1m
```

后续所有投放区、侦察区和返航航点都使用 mission 坐标，再通过
`missions.common.navigation.mission_to_local_position()` 转成飞控 local position。

### 2.2 控制方式

长距离移动：

```text
MissionAction(action_type="local_position")
```

微调下降：

```text
MissionStage -> FlightCommand(vx_cmd, vy_cmd, vz_cmd, yaw_rate_cmd=0)
```

禁止：

- stage 直接调用 MAVLink。
- stage 直接调用 `LinkManager`。
- mission 计算连续速度。
- mission 或 stage 主动输出偏航。

### 2.3 YOLO 使用方式

`yolo_app` 保持一个多类别 RKNN INT8 模型，不在比赛中切模型。YOLO 输出分两类：

```text
scene.detections: 全帧所有目标，用于扫描建图、危险品投票
current_target: 当前锁定目标，用于微调对准
```

短时 `track_id` 只用于当前画面锁定，不能作为全局圆筒编号。长期目标编号由 mission
根据估计地面坐标聚类生成。

## 3. 需要用户实测的参数

### 3.1 舵机

后续由用户实测并填写：

```yaml
payload_slots:
  - id: 1
    servo_channel: 8
    hold_pwm: 1100
    release_pwm: 1900
  - id: 2
    servo_channel: 9
    hold_pwm: 1100
    release_pwm: 1900
payload:
  release_wait_s: 1.0
```

需要确认：

- 通道 8、9 是否能通过 `set_servo` 正常动作。
- `hold_pwm` 是否能可靠保持。
- `release_pwm` 是否能可靠释放。
- 释放后多久水瓶一定脱离。

### 3.2 相机方向

现场标定两个符号：

```yaml
vision:
  image_x_sign: 1.0
  image_y_sign: 1.0
```

测试方法：

- 目标在画面右边时，估算地面位置应该是 `+y` 还是 `-y`。
- 目标在画面上边时，估算地面位置应该是 `+x` 还是 `-x`。

### 3.3 相机视场角

初始值：

```yaml
vision:
  fov_x_deg: 75.0
  fov_y_deg: 75.0
```

若 75 度是对角视场角，应实测水平和垂直视场角后更新。

### 3.4 YOLO 类别

建议训练一个多类别模型，至少包含：

```text
cylinder
hazard_* 或具体危险品标识类别
```

mission 配置只依赖类别名：

```yaml
vision:
  cylinder_classes:
    - cylinder
  hazard_classes:
    - flammable
    - toxic
    - corrosive
    - explosive
```

### 3.5 高度和速度

初始建议：

```yaml
drop:
  survey_altitude_m: 5.0
  transit_altitude_m: 3.0
  release_altitude_m: 1.0

recce:
  survey_altitude_m: 5.0
  transit_altitude_m: 3.0
  identify_altitude_m: 2.0

align:
  max_vx_mps: 0.4
  max_vy_mps: 0.4
  descend_speed_mps: 0.2
  min_altitude_m: 0.8
```

需要实测：

- 5m 是否能稳定识别圆筒。
- 3m 是否能稳定重新锁定圆筒。
- 2m 是否能稳定识别危险品标识。
- 1m 投放是否安全且命中率更高。

## 4. 配置草案

新 `missions/rescue_competition/config.yaml` 建议结构：

```yaml
name: rescue_competition
initial_stage: PREPARE
auto_start: false
local_position_frame: 1
takeoff_altitude_m: 5.0
takeoff_altitude_tolerance_m: 0.5
land_complete_altitude_m: 0.3

route:
  home:
    x: 0.0
    y: 0.0
  drop_area_center:
    x: 30.0
    y: 0.0
  recce_area_center:
    x: 55.0
    y: 0.0

drop:
  required_payload_drops: 2
  survey_altitude_m: 5.0
  transit_altitude_m: 3.0
  release_altitude_m: 1.0
  survey_hold_s: 1.2
  target_count: 2
  survey_points:
    - {name: drop_p1, x: 28.0, y: -1.2}
    - {name: drop_p2, x: 28.0, y:  1.2}
    - {name: drop_p3, x: 32.0, y: -1.2}
    - {name: drop_p4, x: 32.0, y:  1.2}

payload:
  release_wait_s: 1.0
  return_hold_pwm_after_release: true

payload_slots:
  - id: 1
    servo_channel: 8
    hold_pwm: 1100
    release_pwm: 1900
    drop_center_x: 0.0
    drop_center_y: 0.0
  - id: 2
    servo_channel: 9
    hold_pwm: 1100
    release_pwm: 1900
    drop_center_x: 0.0
    drop_center_y: 0.0

recce:
  survey_altitude_m: 5.0
  transit_altitude_m: 3.0
  identify_altitude_m: 2.0
  survey_hold_s: 1.2
  capture_hold_s: 1.5
  visit_max_count: 5
  required_confirmed_count: 3
  output_dir: runtime/logs/recce
  image_dir: runtime/images/recce
  save_images: true
  survey_points:
    - {name: recce_p1, x: 53.0, y: -1.2}
    - {name: recce_p2, x: 53.0, y:  1.2}
    - {name: recce_p3, x: 57.0, y: -1.2}
    - {name: recce_p4, x: 57.0, y:  1.2}

vision:
  fov_x_deg: 75.0
  fov_y_deg: 75.0
  image_x_sign: 1.0
  image_y_sign: 1.0
  cylinder_classes: ["cylinder"]
  hazard_classes: ["flammable", "toxic", "corrosive", "explosive"]
  min_cylinder_confidence: 0.4
  min_hazard_confidence: 0.4
  cluster_radius_m: 0.8
  edge_margin_norm: 0.85
  lock_center_max_error: 0.65

align:
  max_ex_cam: 0.06
  max_ey_cam: 0.06
  hold_s: 0.5
  lost_timeout_s: 1.0
  max_vx_mps: 0.4
  max_vy_mps: 0.4
  descend_speed_mps: 0.2
  min_altitude_m: 0.8

shaper:
  max_vx: 0.4
  max_vy: 0.4
  max_vz: 0.25
  max_yaw_rate: 0.0
  max_gimbal_yaw_rate: 0.0
  max_gimbal_pitch_rate: 0.0
  max_vx_rate: 0.8
  max_vy_rate: 0.8
  max_vz_rate: 0.5
  max_yaw_rate_rate: 0.0
  smooth_to_zero_when_disabled: true
```

## 5. 位置估算

### 5.1 单帧估算

YOLO 输出检测框中心与图像大小：

```text
cx, cy, image_width, image_height
```

先计算归一化图像偏移：

```text
nx = (cx - image_width / 2) / (image_width / 2)
ny = (cy - image_height / 2) / (image_height / 2)
```

`nx` 和 `ny` 范围约为 `[-1, 1]`。

根据高度和视场角估计地面偏移：

```text
half_x_m = altitude_m * tan(fov_x_deg / 2)
half_y_m = altitude_m * tan(fov_y_deg / 2)

offset_right_m   = image_y_sign * nx * half_x_m
offset_forward_m = image_x_sign * ny * half_y_m
```

目标 mission 坐标：

```text
target_x = drone_mission_x + offset_forward_m
target_y = drone_mission_y + offset_right_m
```

注意：`image_x_sign` 和 `image_y_sign` 必须现场标定。

### 5.2 多帧融合

每个扫描点悬停时持续收集检测。每个检测转成：

```text
EstimatedObject(
  class_name,
  confidence,
  target_size,
  x,
  y,
  track_id,
  source_scan_point,
  timestamp
)
```

权重建议：

```text
weight = confidence * max(target_size, 0.001)
```

### 5.3 聚类去重

将所有圆筒估计按地面距离聚类：

```text
distance(candidate, cluster_center) <= cluster_radius_m
```

合并时更新：

```text
center_x = weighted_average(x)
center_y = weighted_average(y)
seen_count += 1
max_confidence = max(...)
mean_target_size = weighted_average(target_size)
```

投放区期望得到 3 个圆筒，选择其中 2 个。侦察区期望得到 5 个圆筒，最多访问 5 个。

## 6. 目标选择策略

### 6.1 投放目标选择

第一版以稳定为主，不追求识别 1/2/3 号筒：

```text
score = seen_count * 2.0
      + max_confidence
      + mean_target_size
      - edge_penalty
```

选择 score 最高且相互距离大于 `cluster_radius_m` 的 2 个圆筒。

若后续 YOLO 能识别筒号，可改为：

```text
优先 1 号筒，再 2 号筒，再 3 号筒
```

### 6.2 侦察目标选择

侦察区先找圆筒，不要求 5m 高度识别危险品标识。计划访问：

```text
按 seen_count / confidence / target_size 排序后的最多 5 个圆筒
```

到 2m 后识别危险品，确认 3 个危险品标识后停止访问剩余圆筒。

## 7. YOLO 锁定策略

### 7.1 建图阶段

不主动锁定目标，使用 `scene.detections` 里的全部圆筒。

### 7.2 执行阶段

飞机飞到某个估计目标上方后，从当前 `scene.detections` 选择需要锁定的圆筒：

1. 类别属于 `vision.cylinder_classes`。
2. 置信度不低于 `vision.min_cylinder_confidence`。
3. 目标估算地面位置离计划目标最近，或画面中心误差最小。
4. 中心误差不超过 `vision.lock_center_max_error`。

找到后发 mission action：

```text
yolo_lock_target(track_id)
```

对准下降完成或阶段失败后发：

```text
yolo_unlock_target
```

如果没有可锁定目标：

- 投放阶段：重新上升到 transit 高度，回当前目标附近重新搜索；超过次数则失败返航。
- 侦察阶段：标记该圆筒为 `blank_or_unvisited`，进入下一个圆筒。

## 8. 新 stage controller

只需要一个连续控制 stage：

```text
DOWNWARD_ALIGN_DESCEND
```

职责：

- 使用 `MissionStageInput.ex_cam / ey_cam` 做水平微调。
- 输出 `vx/vy/vz`。
- 不使用云台。
- 不输出偏航。
- 根据目标是否有效、是否锁定、视觉是否新鲜决定是否有效。
- 在对准误差较大时暂停下降，只做水平修正。
- 在对准误差满足条件时慢速下降。

输入配置：

```yaml
align:
  max_ex_cam: 0.06
  max_ey_cam: 0.06
  hold_s: 0.5
  lost_timeout_s: 1.0
  max_vx_mps: 0.4
  max_vy_mps: 0.4
  descend_speed_mps: 0.2
  min_altitude_m: 0.8
```

输出示意：

```text
vx_cmd = kp_forward * corrected_ey
vy_cmd = kp_right * corrected_ex
vz_cmd = descend_speed_mps when aligned else 0
yaw_rate_cmd = 0
enable_body = true
enable_approach = true
enable_gimbal = false
valid = true
```

`corrected_ex/ey` 需要扣除当前载荷或识别中心偏移：

```text
corrected_ex = ex_cam - target_center_x
corrected_ey = ey_cam - target_center_y
```

## 9. Mission 状态机

建议状态：

```text
PREPARE
ARM
TAKEOFF

GOTO_DROP_SURVEY
SURVEY_DROP_POINTS
PLAN_DROP_TARGETS
GOTO_DROP_TARGET
LOCK_DROP_TARGET
ALIGN_DESCEND_DROP
RELEASE_PAYLOAD
ASCEND_AFTER_DROP
NEXT_DROP_OR_RECCE

GOTO_RECCE_SURVEY
SURVEY_RECCE_POINTS
PLAN_RECCE_TARGETS
GOTO_RECCE_TARGET
LOCK_RECCE_TARGET
ALIGN_DESCEND_RECCE
CAPTURE_RECCE
ASCEND_AFTER_RECCE
NEXT_RECCE_OR_REPORT

REPORT_RECCE
RETURN_HOME
LAND
FINISH
FAILSAFE
```

### 9.1 PREPARE

等待：

- mission start。
- telemetry 有效。
- local position 有效。

不请求云台动作。

### 9.2 ARM

通过 `MissionAction("arm")` 请求解锁。解锁成功后记录 mission 原点和初始 yaw。

### 9.3 TAKEOFF

请求起飞到 `takeoff_altitude_m`，达到高度后进入投放扫描。

### 9.4 GOTO_DROP_SURVEY

飞到第一个投放扫描点，使用高度 `drop.survey_altitude_m`。

### 9.5 SURVEY_DROP_POINTS

逐个扫描点执行：

```text
local_position 到点
稳定后悬停 survey_hold_s
收集 scene.detections
估算圆筒地面位置
进入下一个扫描点
```

全部扫描点完成后进入 `PLAN_DROP_TARGETS`。

### 9.6 PLAN_DROP_TARGETS

聚类所有圆筒估计，选择 2 个投放目标。若目标少于 2：

- 可降低高度重扫一次，作为后续增强。
- 第一版建议进入 `FAILSAFE` 或 `RETURN_HOME`，禁止带载荷进入侦察区。

### 9.7 GOTO_DROP_TARGET

以 `drop.transit_altitude_m` 飞到目标估计位置上方。

### 9.8 LOCK_DROP_TARGET

从当前画面选择与计划目标匹配的圆筒并发送 `yolo_lock_target(track_id)`。锁定成功后进入
`ALIGN_DESCEND_DROP`。

### 9.9 ALIGN_DESCEND_DROP

启用 `DOWNWARD_ALIGN_DESCEND`，边微调边下降到 `drop.release_altitude_m`。达到高度且对准保持完成后进入投放。

若目标丢失超过 `align.lost_timeout_s`：

- 先停止下降。
- 尝试重新锁定当前目标。
- 多次失败则上升到 transit 高度并跳过该目标或返航。

### 9.10 RELEASE_PAYLOAD

按 payload 顺序发 `set_servo`：

```text
第 1 次: channel 8
第 2 次: channel 9
```

等待 `payload.release_wait_s`，可选发送 `hold_pwm` 回位。投放完成后记录：

```text
payload_id
target_id
target_x
target_y
release_timestamp
```

### 9.11 ASCEND_AFTER_DROP

上升到 `drop.transit_altitude_m`。完成后进入 `NEXT_DROP_OR_RECCE`。

### 9.12 NEXT_DROP_OR_RECCE

如果投放次数达到 `drop.required_payload_drops`：

```text
进入 GOTO_RECCE_SURVEY
```

否则：

```text
进入 GOTO_DROP_TARGET
```

硬门禁：

```text
未完成两次投放，绝不进入侦察区
```

### 9.13 GOTO_RECCE_SURVEY

飞到第一个侦察扫描点，高度 `recce.survey_altitude_m`。

### 9.14 SURVEY_RECCE_POINTS

和投放扫描类似，但只用于估计侦察圆筒位置。5m 高度不强制识别危险品标识。

### 9.15 PLAN_RECCE_TARGETS

聚类侦察圆筒，计划最多访问 `recce.visit_max_count` 个。若不足 5 个，访问已有目标。

### 9.16 GOTO_RECCE_TARGET

以 `recce.transit_altitude_m` 飞到圆筒上方。

### 9.17 LOCK_RECCE_TARGET

锁定当前圆筒，准备低空识别。

### 9.18 ALIGN_DESCEND_RECCE

边微调边下降到 `recce.identify_altitude_m`。

### 9.19 CAPTURE_RECCE

悬停 `recce.capture_hold_s`，从 `scene.detections` 收集危险品类别投票。

确认逻辑：

```text
同一圆筒内 hazard 类别出现次数 >= vote_min_count
且置信度累计 >= vote_min_confidence_sum
则 status=confirmed
否则 status=blank 或 uncertain
```

由于规则是正确 +100，错误 -100，空白 0，默认应偏保守：

```text
uncertain 不应自动填写为 confirmed
```

### 9.20 NEXT_RECCE_OR_REPORT

如果已确认 3 个危险品标识：

```text
进入 REPORT_RECCE
```

否则访问下一个圆筒。若圆筒访问完，也进入 `REPORT_RECCE`。

### 9.21 REPORT_RECCE

写出结果到 `runtime/logs/recce`。建议 JSON 字段：

```json
{
  "timestamp": 0.0,
  "items": [
    {
      "target_id": 1,
      "x": 0.0,
      "y": 0.0,
      "hazard_class": "flammable",
      "confidence_sum": 1.4,
      "vote_count": 4,
      "status": "confirmed"
    }
  ]
}
```

可选保存识别截图到 `runtime/images/recce`。

### 9.22 RETURN_HOME / LAND / FINISH

以安全高度返航到 home 上方，然后请求 `land`。相对高度低于 `land_complete_altitude_m` 后进入 `FINISH`。

## 10. 文件结构建议

```text
missions/rescue_competition/
  __init__.py
  config.yaml
  mission.py
  geometry.py
  survey.py
  recce_report.py
  stages/
    __init__.py
    downward_align_descend/
      __init__.py
      config.py
      mode.py
```

职责：

- `mission.py`: 状态机、动作生成、配置加载。
- `geometry.py`: 图像到地面估算、视场角计算。
- `survey.py`: 检测缓存、圆筒聚类、目标评分。
- `recce_report.py`: 侦察投票结果和输出文件。
- `stages/downward_align_descend/mode.py`: 微调下降 stage controller。

## 11. app 集成点

需要检查并更新：

- `missions/registry.py`: 注册 `rescue_competition`。
- `app/stage_registry.py`: 注册 `DOWNWARD_ALIGN_DESCEND`。
- `app/app_config.py`: 加载新 mission stage 配置。
- `tests/`: 更新旧 rescue 测试。
- `docs/ai/architecture.md` 和 `docs/ai/control_flow.md`: 若阶段命名或职责改变，需要更新说明。

不应修改：

- `telemetry_link/command_sender.py`，除非现有 `set_servo` 或 `local_position` 有明确缺陷。
- `yolo_app` 推理链路，除非需要新增截图保存或模型动态切换；当前设计不需要。

## 12. 测试计划

### 12.1 单元测试

新增或更新：

```text
tests/test_rescue_competition_config.py
tests/test_rescue_competition_geometry.py
tests/test_rescue_competition_survey.py
tests/test_rescue_competition_mission.py
tests/test_downward_align_descend.py
```

覆盖：

- YAML bool 严格解析。
- 高度参数和最小高度保护。
- 图像偏移到地面位置估算。
- 多点检测聚类去重。
- 投放区选择两个目标。
- 侦察区确认 3 个标识后停止。
- 未完成两次投放禁止进入侦察区。
- 舵机 action 的通道和 PWM 来自配置。
- stage 输出 yaw 始终为 0。

### 12.2 dry-run

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
python -m app.main --no-yolo-udp --run-seconds 1 --send-commands false
```

### 12.3 SITL

先验证：

- local_position 航点阶段切换。
- mission start / reset。
- `send_commands=false` 时 action 不发送。
- `send_commands=true` 只在 SITL 中使用。

### 12.4 实机低风险测试顺序

1. 不装桨或安全固定机体，测试通道 8/9 舵机 PWM。
2. 不挂水瓶，测试投放动作时序。
3. 5m 悬停拍圆筒，验证相机方向符号。
4. 5m 四点扫描，验证位置估计和聚类。
5. 3m 飞到估计目标上方，验证重新锁定。
6. 3m 到 2m 微调下降，验证危险品识别。
7. 3m 到 1m 微调下降，不投放，验证安全。
8. 挂水瓶低速投放一次。
9. 完整投放区流程。
10. 完整侦察区流程。

## 13. 实现顺序

建议按以下顺序编码：

1. 新建目录和配置 dataclass。
2. 实现 `geometry.py`。
3. 实现 `survey.py` 聚类和目标选择。
4. 实现 `DOWNWARD_ALIGN_DESCEND` stage。
5. 实现 mission 的 PREPARE/ARM/TAKEOFF/RETURN_HOME/LAND 基础流程。
6. 实现投放区扫描和规划。
7. 实现投放目标锁定、微调下降和舵机投放。
8. 实现侦察区扫描和规划。
9. 实现低空识别投票和报告输出。
10. 接入 registry、stage registry 和配置加载。
11. 更新测试。
12. 更新文档。

## 14. 当前不做的事情

第一版不实现：

- 比赛中动态切换 YOLO 模型。
- 识别 1/2/3 号投放筒并按分数最优选择。
- 云台控制。
- 主动偏航。
- 复杂连续横扫。
- 没找到目标时冒险进入侦察区。

这些可作为后续增强。
