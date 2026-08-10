# 05：SITL 测试

## 本章目标

在 ArduPilot SITL 中验证 telemetry、坐标方向、Action、停止路径和比赛任务模板。SITL
通过后仍不能跳过无载荷实飞。

预计时间：半天以上。需要准备：运行 ArduPilot SITL 的电脑、RK3588 和局域网。

## 1. 理解测试拓扑

推荐让电脑运行 Gazebo 和 ArduPilot SITL，让 RK3588 继续运行与实机相同的 app、
RKNNLite 和 Web UI：

```text
电脑：Gazebo 相机 + ArduPilot SITL
  ├─ H264/UDP 5600 → RK3588 yolo_app
  └─ MAVLink/UDP 14550 → RK3588 app

RK3588：YOLO + Action Mission + Web UI
```

先记录实际地址，不要照抄示例：

| 角色 | 实际 IP |
| --- | --- |
| Gazebo/SITL 电脑 | 待填写 |
| RK3588 | 待填写 |

电脑需要安装并验证 ArduPilot SITL、Gazebo、`ardupilot_gazebo`、GStreamer 和对应世界。
这些依赖因电脑系统不同而变化，不属于 RK3588 板端安装脚本的职责。

## 2. 保存现场配置

切换 profile 会覆盖当前生效配置。先检查并保存需要保留的实机调参：

```bash
git status --short
bash scripts/config/save_rk3588_real.sh
```

确认 `config/app.yaml` 中 `executor.send_commands: false`，再应用 SITL profile：

```bash
bash scripts/config/apply_rk3588_sitl.sh
```

SITL profile 默认接收 MAVLink UDP 14550，YOLO 视频源为 UDP 5600，模型为
`gazebo_dataset-fp16.rknn`。

## 3. 启动 Gazebo 和 SITL

仓库提供辅助脚本：

```bash
bash scripts/run_iris_gimbal_sitl.sh
```

也可以在电脑上分别启动各组件。下面路径按你的实际安装位置修改：

```bash
# 终端 1：Gazebo
cd <ardupilot_gazebo工作区>/worlds
gz sim -v4 -r iris_runway.sdf

# 终端 2：ArduPilot SITL，把 MAVLink 发给 RK3588
cd <ardupilot源码目录>
./Tools/autotest/sim_vehicle.py -D -v ArduCopter -f JSON \
  --add-param-file=<ardupilot_gazebo工作区>/config/gazebo-iris-gimbal.parm \
  --console --out=udp:<RK3588-IP>:14550
```

打开 Gazebo 相机流：

```bash
gz topic \
  -t /world/iris_runway/model/iris_with_gimbal/model/gimbal/link/pitch_link/sensor/camera/image/enable_streaming \
  -m gz.msgs.Boolean -p "data: 1"
```

若 Gazebo 默认把 H264/RTP 发到电脑 `127.0.0.1:5600`，可在电脑转发到 RK3588：

```bash
gst-launch-1.0 -v \
  udpsrc port=5600 caps="application/x-rtp,media=video,encoding-name=H264,payload=96" \
  ! rtph264depay \
  ! h264parse \
  ! rtph264pay config-interval=1 pt=96 \
  ! udpsink host=<RK3588-IP> port=5600
```

先确认仿真飞控可以被地面站连接、电脑到 RK3588 网络可达，再启动板端软件。

## 4. 启动 RK3588

应用 SITL profile 后可使用 systemd：

```bash
systemctl --user restart uav-yolo.service uav-app.service
systemctl --user --no-pager --full status uav-yolo.service uav-app.service
```

或手动启动：

```bash
# 终端 1
conda activate yolo
python -m yolo_app.main --source 5600

# 终端 2
conda activate app
python -m app.main --connect-telemetry --send-commands false
```

浏览器访问 `http://<RK3588-IP>:8080/`，视频流是
`http://<RK3588-IP>:8081/video/yolo.mjpeg`。

## 5. 只观察连接

保持 SEND=OFF，启动 app/yolo，确认：

- telemetry data_source/active_source 是 sitl；
- heartbeat、GPS、姿态、LOCAL_NED 更新；
- 仿真视频和 YOLO scene 更新；
- Web UI 明确显示 SEND OFF；
- 没有任务自动启动。

## 6. 建立 SITL Field Reference

使用 `config/field_profiles/sitl_centerline_lane.json` 或当前 SITL 流程建立并冻结场地参考。
确认 Web 地图上 `+Y` 前方、`+X` 右方与仿真运动一致。

## 7. 从低风险 Action 开始

按风险逐步验证：

```text
只读/识别 Action
→ 场地坐标预览
→ 单个低速航点
→ stop/reset/skip
→ 起飞与降落分项
→ 投放请求（无真实机构）
→ 分项 Mission
→ 完整 rescue_2026_full_auto_v2
```

只有在确认仿真场地、速度、高度和遥控接管后，才在 SITL 中开启系统 SEND 和 Action
send_actions。一次只改变一个变量。

## 8. 必测失败路径

- Action 运行中点击 Stop；
- 连续 BODY_NED Action 丢失视觉目标；
- Mission 中断、Reset 和 Skip Current；
- telemetry 断线和恢复；
- yolo 停止和恢复；
- Field Reference 未确认或未冻结时启动 Mission；
- 投放步骤失败后的恢复路径；
- 限速阶段结束后速度恢复；
- 视觉降落失败后 LAND 兜底。

确认停止或失败不会恢复旧速度、旧位置目标或重复投放请求。

## 9. 常见问题

### 收不到 MAVLink

- 确认 SITL 的 `--out` 指向 RK3588，而不是电脑本机；
- 确认防火墙允许 UDP 14550；
- 确认板端 `config/telemetry.yaml` 使用 SITL/UDP-in；
- 使用 `ss -lunp` 和获准的抓包工具确认数据方向；
- 检查 heartbeat 时不需要打开 SEND。

### 没有仿真视频

- 确认 Gazebo 相机传感器已经启用；
- 确认电脑本地 UDP 5600 有 RTP 数据；
- 确认 GStreamer 的目标是 RK3588 实际 IP；
- 确认板端 UDP 5600 没有被其他进程占用；
- 检查 `uav-yolo.service` 日志中的解码和模型加载错误。

### 仿真目标没有检测结果

SITL profile 使用 `data/models/gazebo_dataset-fp16.rknn`，不能误用实机场景模型。确认
模型、类别表、光照、相机方向和 Gazebo 目标素材与当前数据集一致。

### 飞行方向与地图相反

立即停止任务，核对 FIELD `+Y`、`+X`、SITL 起始朝向和 profile。不能通过临时交换
x/y 或修改符号来掩盖问题。

## 10. 保存结果

记录使用的 commit、profile、Mission 模板、参数、SITL 起点、每个失败注入结果和日志路径。
运行产物放在 `runtime/`，不要把临时 SITL 文件写进配置目录。

## SITL 验收清单

- [ ] SITL telemetry、视频和 YOLO 状态稳定。
- [ ] FIELD 方向和航点方向经过实际仿真运动验证。
- [ ] stop/reset/skip 和丢目标路径均停止旧命令。
- [ ] 投放步骤不会重复或绕过 dispatcher。
- [ ] 完整 v2 模板在保守参数下完成一次。
- [ ] SITL 的 SEND 开启没有被带回实机配置。

返回实机配置前再次确认 `executor.send_commands: false`：

```bash
bash scripts/config/apply_rk3588_real.sh
```

下一章：[实飞测试](06_flight_test.md)。
