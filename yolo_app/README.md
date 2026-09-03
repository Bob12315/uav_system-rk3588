# RK3588 YOLO App

`yolo_app` 是板端视觉感知进程，只在 Linux ARM64 RK3588 上使用 RKNNLite/NPU。
它不连接飞控、不读取 MAVLink，也不生成飞行命令；检测和目标状态通过 UDP JSON
发送给 app。

## 当前模型策略

默认部署模型：

```text
data/models/cuadc2026-fp16.rknn
```

从 `config/yolo.yaml` 引用时，正确相对路径为：

```text
../data/models/cuadc2026-fp16.rknn
```

RK3588/RKNN 本身可以支持 INT8，但本项目当前 INT8 模型已废弃。除非重新完成量化
校准并验证类别、置信度和检测结果正常，否则不要切回 INT8 默认部署。

## 流程

```text
camera/video/stream
→ latest-frame capture
→ RKNNLite / RK3588 NPU
→ model-specific decode + NMS
→ short-lived track_id association
→ TargetManager
→ UDP target + scene
→ optional MJPEG annotation / raw recording
```

启用 `virtual_nadir.enabled` 后，检测输入改为：

```text
raw frame + FramePacket monotonic timestamp
→ localhost ATTITUDE history
→ quaternion SLERP
→ pure-rotation Virtual Nadir homography
→ valid-mask constrained stabilized frame
→ RKNN detector / tracker
```

`virtual_nadir.enabled` 是图像处理路径的模式开关：关闭时保持
`raw frame → YOLO → Web UI`，开启时使用
`IMU stabilized frame → YOLO → Web UI`。Web UI 始终显示 YOLO 实际处理坐标域中的
标注画面；`debug_compare` 仅改变板端本机 OpenCV 调试窗口。

Virtual Nadir V1 将虚拟相机固定为 `roll=0`、`pitch=0`、`yaw=yaw_ref`；
`yaw_ref` 在每个 telemetry/source session 首次获得有效姿态时锁定。它只补偿相机姿态，
不补偿无人机平移，也不执行 GPS 投影、地面交点、正射图或地图拼接。

姿态旁路由 `telemetry_link` 的 runtime active source 独占发布，YOLO 不连接 MAVLink。
视频帧和姿态都使用同一主机的 monotonic 时间域。当前帧时间代表 camera read/UDP decode
完成时间，不是真实曝光时间。

该路径 fail closed：姿态缺失、过期、采样频率不足、session/source 切换或重投影失败时，
当帧不执行推理并立即清除 tracker 历史和 target lock。重投影生成的 `valid_mask` 同时用于
屏蔽推理输入和拒绝跨入无真实像素区域的检测框。飞控侧启用姿态 UDP 后会显式请求至少
30 Hz 的 `ATTITUDE`；YOLO 使用配置的最低实际频率继续进行独立检查。

输入与输出张量布局必须以当前 FP16 RKNN 模型的实际导出结果为准，不要因为历史
INT8 文档假设而修改后处理。

## 模块

| 文件 | 职责 |
| --- | --- |
| `main.py` | 主循环和服务生命周期 |
| `config.py` | YAML/CLI 配置 |
| `video_source.py` | 相机、UDP/RTSP、视频输入 |
| `rknn_detector.py` | RKNNLite 推理和后处理 |
| `tracker_runner.py` | 短时 track_id 关联 |
| `target_manager.py` | 主目标选择、锁定和丢失管理 |
| `udp_publisher.py` | UDP JSON 输出 |
| `command_receiver.py` | Web UI 目标选择命令 |
| `mjpeg_stream.py` | 浏览器标注流 |
| `raw_frame_recorder.py` | 原始画面录像 |

## 环境

使用匹配板端 Runtime/Driver 的 `rknn-toolkit-lite2`。安装：

```bash
conda activate uav-rk3588-yolo
bash scripts/install/install_yolo_env.sh
```

禁止新增 x86、CUDA、PyTorch 或 GPU 推理路径。

## 运行

```bash
conda activate uav-rk3588-yolo
python -m yolo_app.main
```

显示、录像、视频源、UDP 目的地址和 Web stream 均由 `config/yolo.yaml` 管理。运行
录像属于产物，应写入 `runtime/`；当前 `recording_dir` 若配置为仓库外路径，需要在
后续配置清理阶段统一评审。

## UDP 输出

每帧发送包含 `target` 和 `scene` 的 JSON：

- `target`：当前主目标、tracking_state、误差和尺寸。
- `scene.detections`：当前全部检测。

协议字段变化必须同步更新 app receiver、fusion、Web UI 和测试。
