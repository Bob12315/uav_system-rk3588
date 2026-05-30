# RK3588 YOLO App

本目录是无人机项目的板端视觉感知进程，仅支持 RK3588 NPU 上的 RKNN INT8 模型。
它不连接飞控，也不生成控制命令；目标状态通过 UDP JSON 交给上层系统。

## 流程

```text
/dev/video41 (MJPG 640x480)
-> latest-frame capture
-> RKNNLite / NPU_CORE_0_1_2
-> 9-output score_sum + DFL + NMS postprocess
-> short-lived track_id association
-> TargetManager
-> UDP JSON + fullscreen annotation
```

## 模型

默认模型路径：

```text
~/rk3588_yolo/rknn_model_zoo/examples/yolo11/model/best-int8-rk3588.rknn
```

模型约定：

- 类别：`Target`、`bucket`、`class_2`
- 输入：RGB `uint8`，形状固定为 `(1, 640, 640, 3)`
- NPU：`RKNNLite.NPU_CORE_0_1_2`
- 输出：三个尺度、每尺度 `position / class_scores / score_sum`，共 9 个张量

`rknn_detector.py` 先用各分支的 `score_sum` 筛选位置，再执行 DFL 解码、letterbox
坐标还原和 NMS。该路径不使用普通单输出 YOLO 的后处理。

## 模块

```text
yolo_app/
  main.py                 主循环、显示和 FPS 日志
  config.yaml             RK3588 板端默认配置
  config.py               配置与命令行覆盖
  video_source.py         相机、UDP/RTSP/视频输入
  rknn_detector.py        RKNN 推理和后处理
  tracker_runner.py       检测结果短时 ID 关联
  target_manager.py       主目标锁定、切换、丢失管理
  annotator.py            全屏画面标注
  udp_publisher.py        UDP JSON 输出
  command_receiver.py     目标选择命令输入
```

## 环境

板端已验证环境：

- Ubuntu 22.04.4 LTS, aarch64, RK3588 / NanoPC-T6
- Python `3.10.20`
- `rknn-toolkit-lite2==2.3.2`
- RKNN Runtime `2.3.2`
- RKNN Driver `0.9.8`

`yolo` conda 环境至少需要：

```bash
pip install rknn-toolkit-lite2==2.3.2 opencv-python pyyaml numpy
```

## 屏幕运行

默认配置已设置模型、`/dev/video41`、MJPG `640x480@30`、最新帧采集和全屏显示。
从板载 GNOME 桌面会话启动：

```bash
cd ~/uav_project/uav_system-rk3588/yolo_app
DISPLAY=:0 \
XDG_RUNTIME_DIR=/run/user/1000 \
WAYLAND_DISPLAY=wayland-0 \
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
conda run --no-capture-output -n yolo python -u main.py
```

无窗口性能测试：

```bash
conda run --no-capture-output -n yolo python -u main.py \
  --show false --command-enabled false
```

日志每 60 帧报告一次管线 FPS、摄像到输出的延迟以及当前检测数量。

## 配置要点

- `model_path`：RKNN INT8 模型路径
- `source`：默认板端相机 `/dev/video41`
- `conf_thres` / `iou_thres`：检测与 NMS 阈值
- `class_names`：模型类别顺序
- `selection_mode` / `target_class`：自动选择主目标策略
- `udp_ip` / `udp_port`：向控制进程发布的目的地址
- `fullscreen`：板载屏幕全屏显示
- `latest_frame`：丢弃已积压相机帧以控制延迟

## UDP 输出

每帧发送一个包含 `target` 和 `scene` 的 JSON 包：

- `target`：当前锁定主目标及 `tracking_state`、误差和尺寸
- `scene.detections`：当前所有检测结果

`track_id` 是 RKNN 检测结果的跨帧关联标识，供目标锁定与切换业务使用。
