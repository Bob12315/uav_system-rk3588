# SITL + Gazebo + RK3588（UDP）

cd uav_project/uav_system-rk3588/
./scripts/run_iris_gimbal_sitl.sh

PC 跑仿真；RK3588 收 MAVLink（UDP 14550）和视频（UDP 5600）。以下 IP 按现场修改。

| 角色 | 示例 IP |
| --- | --- |
| PC | `10.31.18.107` |
| RK3588 | `10.31.18.109` |

## PC

### 1. Gazebo

```bash
cd ~/gz_ws/src/ardupilot_gazebo/worlds
gz sim -v4 -r iris_runway.sdf
```

### 2. SITL（MAVLink 发到板子）

```bash
cd ~/ardupilot
./Tools/autotest/sim_vehicle.py -D -v ArduCopter -f JSON \
  --add-param-file=$HOME/gz_ws/src/ardupilot_gazebo/config/gazebo-iris-gimbal.parm \
  --console --out=udp:10.31.18.108:14550
```

### 3. 打开 Gazebo 相机流

```bash
gz topic -t /world/iris_runway/model/iris_with_gimbal/model/gimbal/link/pitch_link/sensor/camera/image/enable_streaming \
  -m gz.msgs.Boolean -p "data: 1"
```

### 4. 本机 5600 转发到板子（不改 Gazebo SDF）

Gazebo 默认发到 `127.0.0.1:5600`，PC 上执行：

```bash
gst-launch-1.0 -v \
  udpsrc port=5600 caps="application/x-rtp,media=video,encoding-name=H264,payload=96" \
  ! rtph264depay \
  ! h264parse \
  ! rtph264pay config-interval=1 pt=96 \
  ! udpsink host=10.31.18.108 port=5600
```

## RK3588

### 配置要点

`config/telemetry.yaml`（sitl）：

```yaml
connection_type: udp
udp_mode: udpin
udp_host: 0.0.0.0
udp_port: 14550
```

`config/yolo.yaml`：

```yaml
model_path: "../data/models/best-int8-rk3588.rknn"
source: 5600
udp_ip: "127.0.0.1"
udp_port: 5005
```

在 RK3588 板端应用 SITL 配置：

```bash
bash scripts/config/apply_rk3588_sitl.sh
systemctl --user restart uav-yolo.service uav-app.service
```

### 手动启动

```bash
conda activate yolo
cd ~/uav_project/uav_system-rk3588
python3 -m yolo_app.main --source 5600

conda activate app
cd ~/uav_project/uav_system-rk3588
python3 -m app.main --connect-telemetry --send-commands false
```

或 systemd：

```bash
systemctl --user restart uav-yolo.service uav-app.service
```

### Web UI

```text
http://10.31.18.109:8080/
http://10.31.18.109:8081/video/yolo.mjpeg
```

## 附：USB 摄像头 / 本机预览

```bash
ffplay -f v4l2 -input_format yuyv422 -video_size 640x480 -framerate 30 /dev/video0
ffplay -fflags nobuffer -flags low_delay -framedrop -sync ext /dev/video0
```
