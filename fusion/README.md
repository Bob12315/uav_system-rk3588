# Fusion Layer

`fusion/` 是独立业务层，不是 ROS2 节点，不是控制器，也不是 EKF。

它只做一件事：

- 将 `perception` 的当前锁定目标
- 与 `telemetry_link` 的 `DroneState`
- 以及 `telemetry_link` 的 `GimbalState`

合成为控制层唯一依赖的 `FusedState`。

## 1. 职责边界

`telemetry_link` 负责：

- 飞控状态反馈
- 云台状态反馈
- 链路状态管理

`fusion` 负责：

- 读取当前目标状态
- 读取最新飞控状态
- 读取最新云台反馈
- 产出控制可直接消费的统一状态

当前阶段 `fusion` 不负责：

- 控制器
- EKF
- 多目标融合
- 复杂时间同步
- 严格三维坐标变换

## 2. 核心原则

### 2.1 云台角度必须来自反馈

`gimbal_yaw / gimbal_pitch` 必须来自 MAVLink 实际反馈，例如：

- `MOUNT_STATUS`
- `GIMBAL_DEVICE_ATTITUDE_STATUS`

不能把发送给云台的命令值直接当成当前姿态。

### 2.2 `ex_cam` 与 `ex_body` 不相同

YOLO 输出的是相机坐标误差：

- `ex_cam`
- `ey_cam`

由于相机挂在云台上，相机方向与机体方向不一定一致，因此控制层不能直接拿 `ex_cam / ey_cam` 控机体。

MVP 阶段先采用工程近似：

```text
ex_body = ex_cam + gimbal_yaw
ey_body = ey_cam + gimbal_pitch
```

当 `gimbal_valid=false` 时：

- 若 `require_gimbal_feedback=true`，则 `fusion_valid=false`
- 若 `require_gimbal_feedback=false`，则退化为：

```text
ex_body = ex_cam
ey_body = ey_cam
```

## 3. 有效性判定

`control_enabled` 判定：

```text
target_valid
AND tracking_state == "locked"
AND drone_state.control_allowed
AND drone_state.stale == False
AND drone_state.connected == True
```

`fusion_valid` 判定：

- `DroneState` 本身有效
- 目标处于 `locked`
- 且云台反馈满足当前配置要求

如果 `drone_state.stale=True`：

- `control_enabled=False`
- `fusion_valid=False`

## 4. 使用方式

```python
from fusion.fusion_manager import FusionManager
from fusion.models import FusionConfig

manager = FusionManager(FusionConfig(require_gimbal_feedback=True))
fused_state = manager.update(perception_target, drone_state, gimbal_state)
```

控制层后续应只依赖 `FusedState`，而不是自己再去拼 `YOLO + telemetry_link`。

当前工程里，`FusedState` 的下一跳已经明确为控制层输入适配器：

```python
from missions.common.control.input_adapter import StageInputAdapter

adapter = StageInputAdapter()
stage_input = adapter.adapt(fused_state)
```

这里的 `StageInputAdapter` 负责：

- `dt` 计算
- source age 计算
- 跟踪连续性判断
- 轻量一阶低通滤波
- 将 `FusedState` 映射为 mission stage 统一输入 `MissionStageInput`

它不是控制器，不负责：

- 状态机
- PID
- 控制输出计算
- fail-safe 策略

## 5. 终端 Debug

当前仓库新增了独立的终端 debug 入口：

- [debug_main.py](debug_main.py)

它会：

- 监听 YOLO 的 UDP 目标输出
- 监听 `telemetry_link` 发出的本地 UDP 状态流
- 调用 `FusionManager.update(...)`
- 周期性在终端打印 `FusedState` 关键字段

启动示例：

```bash
cd ~/uav_project/src/fusion
python3 debug_main.py \
  --telemetry-config ../telemetry_link/config.yaml \
  --yolo-udp-ip 0.0.0.0 \
  --yolo-udp-port 5005 \
  --print-rate-hz 1 \
  --require-gimbal-feedback
```

配套要求：

- `yolo_app` 正在向 `udp_port=5005` 输出当前目标
- `telemetry_link` 正在运行，且开启了 `state_udp_enabled: true`
- `telemetry_link` 默认会把 `DroneState / GimbalState / LinkStatus` 发到 `127.0.0.1:5010`

默认打印这些字段：

- `target_valid`
- `target_locked`
- `track_id`
- `tracking_state`
- `ex_cam / ey_cam`
- `ex_body / ey_body`
- `gimbal_yaw / gimbal_pitch`
- `yaw / roll / pitch / yaw_rate`
- `vx / vy / vz / altitude`
- `control_allowed`
- `control_enabled`
- `state_valid`
- `fusion_valid`

当前限制：

- 当前 debug 入口依赖 `telemetry_link` 的本地 UDP 状态广播
- 它不会自己再去连接飞控，因此不会和独立运行的 `telemetry_link` 抢串口
