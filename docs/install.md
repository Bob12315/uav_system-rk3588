# 安装说明

建议分两个环境：app 环境和 YOLO 环境。用户先自行安装适合 RK3588/aarch64 的 Miniconda/Anaconda 或 Miniforge，并自行创建两个 conda 环境；本项目脚本负责在已经激活的环境里安装对应依赖。

## app 环境

```bash
conda create -n app python=3.10 -y
conda activate app
bash scripts/install/install_app_env.sh
```

用途：

- `app`
- `missions`
- `fusion`
- `telemetry_link`
- `uav_ui`
- `tests`

脚本会先检查：

- 当前系统是 Linux。
- 当前架构是 RK3588 常见的 `aarch64/arm64`。
- 当前已经激活 conda 环境 `app`。
- 当前 Python 版本是 `3.10.x`。

脚本安装依赖时使用清华 conda/PyPI 镜像作为临时源，不修改用户全局 `.condarc` 或 pip 配置。`pymavlink` 通过 pip 镜像安装，其他 app 依赖优先通过 conda 安装。

验证：

```bash
cd ~/uav_project/uav_system-rk3588
python -m app.main --help
python -m telemetry_link.main --help
python -m pytest -q
```

## YOLO 环境

```bash
conda create -n yolo python=3.10 -y
conda activate yolo
bash scripts/install/install_yolo_env.sh
```

## 模型文件

仓库内已跟踪部署模型：

```text
data/models/best-int8-rk3588.rknn
```

`yolo_app/config.yaml` 使用相对于配置文件的路径：

```yaml
model_path: "../data/models/best-int8-rk3588.rknn"
```

模型为 Rockchip 优化的 INT8 RKNN 文件，输入为 RGB uint8 `(1, 640, 640, 3)`，固定使用
`NPU_CORE_0_1_2`。

## 可选依赖

如果要运行视频源、GStreamer 或特定相机，可能还需要系统包。具体取决于硬件和视频输入方式。

## 快速验证

控制环境：

```bash
conda activate app
cd ~/uav_project/uav_system-rk3588
python -m app.main --no-yolo-udp --run-seconds 1 --send-commands false
```

YOLO 环境：

```bash
conda activate yolo
cd ~/uav_project/uav_system-rk3588/yolo_app
DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0 \
DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus python main.py
```
