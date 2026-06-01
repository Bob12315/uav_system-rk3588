# 用户使用说明

这是一个仅面向 Linux ARM64 RK3588 的无人机视觉任务程序。YOLO 使用 RK3588
NPU 和仓库中的 RKNN INT8 模型。运行状态、日志、SITL 文件和生成视频统一写入
`runtime/`。

## 目录里最常用的东西

| 路径 | 用途 |
| --- | --- |
| `config/app.yaml` | app、Web UI、任务选择和安全出口 |
| `config/telemetry.yaml` | 真机或 SITL 的 MAVLink 连接 |
| `config/yolo.yaml` | 模型、摄像头、UDP 和视频流 |
| `missions/<name>/config.yaml` | 任务参数和控制参数 |
| `runtime/` | 日志、视频和 SITL 运行产物 |

## 第一次安装

先创建两个独立环境：

```bash
conda create -n app python=3.10 -y
conda activate app
bash scripts/install/install_app_env.sh

conda create -n yolo python=3.10 -y
conda activate yolo
bash scripts/install/install_yolo_env.sh
```

完整说明见 [install.md](install.md)。

## 安全试运行

先运行 app，不启动 YOLO，不发送控制命令：

```bash
conda activate app
cd ~/uav_project/uav_system-rk3588
python -m app.main \
  --no-yolo-udp \
  --no-ui \
  --run-seconds 1 \
  --send-commands false \
  --blackbox-enabled false
```

运行单元测试：

```bash
python -m pip install -r requirements-dev.txt
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

## 切换真机和 SITL

程序直接读取并提交到 Git 的生效配置位于 `config/`。切换前必须保持
`config/app.yaml` 中：

```yaml
executor:
  send_commands: false
```

切换到 RK3588 真机配置：

```bash
bash scripts/config/apply_rk3588_real.sh
```

切换到 PC 仿真联调配置：

```bash
bash scripts/config/apply_rk3588_sitl.sh
```

## 手动启动

窗口 1 启动 YOLO：

```bash
conda activate yolo
cd ~/uav_project/uav_system-rk3588
python -m yolo_app.main
```

窗口 2 启动 app，连接 telemetry 但保持只观察：

```bash
conda activate app
cd ~/uav_project/uav_system-rk3588
python -m app.main --connect-telemetry --send-commands false
```

浏览器打开：

```text
http://<RK3588-IP>:8080/
```

## 使用 systemd 服务

首次安装用户服务：

```bash
bash scripts/deploy/install_systemd_user_services.sh --dry-run
bash scripts/deploy/install_systemd_user_services.sh --enable-now
sudo loginctl enable-linger "$USER"
```

常用操作：

```bash
systemctl --user restart uav-app.service uav-yolo.service
systemctl --user --no-pager --full status uav-app.service uav-yolo.service
journalctl --user -u uav-app.service -f
journalctl --user -u uav-yolo.service -f
```

## 修改任务参数

视觉跟踪参数位于：

```text
missions/visual_tracking/config.yaml
```

修改后可以在 UI 输入：

```text
pid reload
```

它会刷新 input adapter、健康监控阈值、stage controller 和 command shaper，
并重置控制器历史状态。配置文件本身不会被 UI 自动改写。

## 常见排查

板端只读检查：

```bash
bash scripts/healthcheck/check_rk3588.sh
```

Web UI 打不开：

```bash
ss -ltnp | grep ':8080'
curl -fsS http://127.0.0.1:8080/api/status
```

没有 YOLO 画面：

```bash
ss -ltnp | grep ':8081'
curl -v http://127.0.0.1:8081/video/yolo.mjpeg
```

app 收不到 YOLO 结果：

```bash
ss -lunp | grep ':5005'
```

详细运行和排查手册见 [running.md](running.md)。实机发命令前必须阅读
[../reference/safety.md](../reference/safety.md)。
