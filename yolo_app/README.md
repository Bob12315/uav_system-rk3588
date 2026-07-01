# RK3588 YOLO App

`yolo_app` 是板端视觉感知进程，只在 Linux ARM64 RK3588 上使用 RKNNLite/NPU。
它不连接飞控、不读取 MAVLink，也不生成飞行命令；检测和目标状态通过 UDP JSON
发送给 app。

## 当前模型策略

默认部署模型：

```text
data/models/cuadc-fp16.rknn
```

从 `config/yolo.yaml` 引用时，正确相对路径为：

```text
../data/models/cuadc-fp16.rknn
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
conda activate yolo
bash scripts/install/install_yolo_env.sh
```

禁止新增 x86、CUDA、PyTorch 或 GPU 推理路径。

## 运行

```bash
conda activate yolo
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
