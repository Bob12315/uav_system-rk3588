# RK3588 运行手册

本项目仅面向 Linux ARM64 RK3588。`yolo_app` 使用 RKNN INT8 模型和
RK3588 NPU，不提供 x86、CUDA、PyTorch 或 GPU 推理路径。

## 1. 启动前确认

服务端口如下：

| 端口 | 服务 | 说明 |
| --- | --- | --- |
| `8080/tcp` | `app` | Web UI 页面与 API |
| `8081/tcp` | `yolo_app` | 标注后的 MJPEG 视频流 |
| `5005/udp` | `app` | 接收 YOLO 目标/场景数据 |
| `5006/udp` | `yolo_app` | 接收网页发出的目标锁定/切换命令 |

两端都应先保持以下安全配置：

```yaml
# config/app.yaml
ui:
  web_enabled: true
executor:
  send_commands: false
```

YOLO 输出端口需要匹配 app 输入端口：

```yaml
# yolo_app/config.yaml
udp_ip: "127.0.0.1"
udp_port: 5005
web_stream:
  enabled: true
  host: "0.0.0.0"
  port: 8081
```

启动后浏览器访问：

```text
http://<运行设备的局域网 IP>:8080/
```

只在 SITL 已检查控制方向，或实机已确认安全措施后，才在网页或配置中打开
自动发命令。

## 2. RK3588 实机运行

以下步骤适用于板端仓库位于 `/home/pi/uav_project`、代码分支为
`platform/rk3588` 的部署方式。

### 2.1 配置摄像头和模型

SSH 登录板端后进入项目：

```bash
ssh pi@<rk3588-ip>
cd ~/uav_project
git switch platform/rk3588
```

USB 摄像头建议使用不会随插拔序号变化的 `by-id` 路径：

```bash
v4l2-ctl --list-devices
ls -l /dev/v4l/by-id/
```

在 `yolo_app/config.yaml` 中配置板端模型和实际摄像头。例如：

```yaml
model_path: "../data/models/best-int8-rk3588.rknn"
source: /dev/v4l/by-id/<usb-camera>-video-index0
target_class: "bucket"
```

如果改用 CSI/板载摄像头，应先使用 Python/OpenCV 或 `v4l2-ctl` 确认该
节点能够读取实际画面，再写入 `source`。

### 2.2 首次安装 Web 依赖与用户服务

`app` 环境安装 Web UI 依赖；`yolo` 环境需要已安装 OpenCV、PyYAML、
NumPy 以及匹配模型的 `rknn-toolkit-lite2`：

```bash
cd ~/uav_project
~/miniconda3/envs/app/bin/python -m pip install -r requirements-control.txt
~/miniconda3/envs/yolo/bin/python -c "import cv2, yaml; from rknnlite.api import RKNNLite"
```

安装随登录用户运行的服务：

```bash
mkdir -p ~/.config/systemd/user
cp deploy/systemd/uav-app.service deploy/systemd/uav-yolo.service ~/.config/systemd/user/
systemctl --user daemon-reload
sudo loginctl enable-linger "$USER"
systemctl --user enable --now uav-app.service uav-yolo.service
```

模板的 `WorkingDirectory` 是 `%h/uav_project`。如果代码放在其他目录，
需要先修改 `~/.config/systemd/user/uav-*.service` 中的路径。

### 2.3 启动、停止和重启

同时管理 app 与 YOLO：

```bash
systemctl --user start uav-app.service uav-yolo.service
systemctl --user stop uav-app.service uav-yolo.service
systemctl --user restart uav-app.service uav-yolo.service
systemctl --user --no-pager --full status uav-app.service uav-yolo.service
```

只操作一个进程：

```bash
# Web UI、telemetry、mission 或控制代码变化时
systemctl --user restart uav-app.service

# YOLO、摄像头、模型或视频流代码变化时
systemctl --user restart uav-yolo.service
```

服务已经配置为开机后自动启动。需要临时关闭自动启动，或再次恢复时使用：

```bash
systemctl --user disable --now uav-app.service uav-yolo.service
systemctl --user enable --now uav-app.service uav-yolo.service
```

### 2.4 修改程序后加载新版本

如果代码在 GitHub 的 `platform/rk3588` 分支已经提交并推送，在板端执行：

```bash
cd ~/uav_project
git status --short --branch
git fetch github platform/rk3588
git merge --ff-only github/platform/rk3588
```

板端可能保留现场的 `yolo_app/config.yaml` 与 `.rknn` 模型文件。更新前应
确认 `git status`，不要用会丢失现场配置的强制覆盖命令。

普通 Python、HTML、JavaScript、CSS 或 YAML 配置修改不需要重新安装，
重启受影响服务即可：

```bash
# 修改了 app/、web_ui/、missions/、config/ 中 app/mission/telemetry 行为
systemctl --user restart uav-app.service

# 修改了 yolo_app/、YOLO 配置、摄像头 source 或模型路径
systemctl --user restart uav-yolo.service

# 不能确定修改影响哪一端时
systemctl --user restart uav-app.service uav-yolo.service
```

如果修改了依赖文件，更新后先安装依赖，再重启服务：

```bash
# requirements-control.txt 变化
~/miniconda3/envs/app/bin/python -m pip install -r requirements-control.txt

# RK3588 的 yolo 依赖变化时，只安装板端需要的包；
# rknn-toolkit-lite2 版本仍需与板端模型和驱动匹配
~/miniconda3/envs/yolo/bin/python -m pip install opencv-python pyyaml numpy
~/miniconda3/envs/yolo/bin/python -c "import cv2, yaml; from rknnlite.api import RKNNLite"

systemctl --user restart uav-app.service uav-yolo.service
```

如果修改了 `deploy/systemd/uav-app.service` 或
`deploy/systemd/uav-yolo.service`，需要重新覆盖用户服务文件并重新加载：

```bash
cd ~/uav_project
cp deploy/systemd/uav-app.service deploy/systemd/uav-yolo.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user restart uav-app.service uav-yolo.service
```

### 2.5 运行检查与日志

检查 Web 和视频流：

```bash
curl -fsS http://127.0.0.1:8080/api/status
timeout 5s curl -fsS http://127.0.0.1:8081/video/yolo.mjpeg -o /tmp/yolo-check.mjpeg || test -s /tmp/yolo-check.mjpeg
wc -c /tmp/yolo-check.mjpeg
```

从同一局域网笔记本打开：

```text
http://<rk3588-ip>:8080/
```

服务日志：

```bash
journalctl --user -u uav-app.service -f
journalctl --user -u uav-yolo.service -f
```

## 3. 参数修改与任务切换

Web UI 的参数页面可修改白名单中的 YAML 文件：

- `config/app.yaml`
- `config/telemetry.yaml`
- `yolo_app/config.yaml`
- `missions/*/config.yaml`

保存 mission 参数后，系统会先执行 `control send off`，再重载当前
mission 配置；保存 telemetry 参数后，使用页面中的“立即重连通信服务”
按钮。修改 app 或 YOLO 启动参数后，使用相应重启按钮应用配置。

## 4. 排查

Web UI 打不开：

```bash
ss -ltnp | grep ':8080'
curl -fsS http://127.0.0.1:8080/api/status
```

网页没有 YOLO 画面：

```bash
ss -ltnp | grep ':8081'
curl -v http://127.0.0.1:8081/video/yolo.mjpeg
```

同时检查 `yolo_app` 是否成功打开视频源。USB 摄像头拔插后，`/dev/videoX`
可能变化，应优先使用 `/dev/v4l/by-id/...` 路径。

app 收不到目标：

```bash
ss -lunp | grep ':5005'
```

检查 `config/app.yaml` 的 `runtime.yolo_udp_port` 与
`yolo_app/config.yaml` 的 `udp_port` 是否都为 `5005`。

YOLO 报 Python 依赖缺失：

```bash
python -c "import cv2, yaml; from rknnlite.api import RKNNLite; print('YOLO environment ready')"
```

如果这里失败，当前命令使用的不是完整 YOLO 环境，或还没有安装
`requirements-yolo.txt` 中的依赖。

停止服务或进程：

```bash
systemctl --user stop uav-app.service uav-yolo.service
```
