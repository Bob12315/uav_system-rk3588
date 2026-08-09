# 比赛系统使用入口

本项目是面向 Linux ARM64 RK3588 的 2026 无人机救援比赛系统。正式操作入口是
Web UI；YOLO 使用 RK3588 NPU 和 RKNN FP16 模型，飞控通过 MAVLink/ArduPilot 连接。

如果你还没有完成硬件采购、组装、接线或环境部署，请先从
[新手完整搭建教程](../beginner/README.md) 开始；本目录主要面向已经完成安装的操作者。

## 常用位置

| 路径 | 用途 |
| --- | --- |
| `config/app.yaml` | app、Web UI、服务开关和系统 SEND |
| `config/telemetry.yaml` | 真机或 SITL 的 MAVLink 连接 |
| `config/yolo.yaml` | 模型、摄像头、UDP 和视频流 |
| `config/action_missions/*.json` | 完整比赛和分项任务模板 |
| `config/field_profiles/*.json` | 比赛场地和 SITL 场地配置 |
| `runtime/` | 日志、视频、SITL 和 blackbox 运行产物 |

旧 `missions/<name>/config.yaml` 和 terminal/curses UI 不再是正式任务入口。

## 第一次安装

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

先运行不连接感知、不连接飞控、不发送命令的 smoke test：

```bash
conda activate app
python -m app.main \
  --no-yolo-udp \
  --no-ui \
  --run-seconds 1 \
  --send-commands false \
  --blackbox-enabled false
```

默认安全项必须保持：

```yaml
executor:
  send_commands: false
```

## 切换实机和 SITL

```bash
# RK3588 实机配置
bash scripts/config/apply_rk3588_real.sh

# SITL 联调配置
bash scripts/config/apply_rk3588_sitl.sh
```

切换脚本会覆盖生效配置。执行前检查 `git status`，确认不会丢失现场调参结果。

## 手动启动

终端 1：

```bash
conda activate yolo
python -m yolo_app.main
```

终端 2：

```bash
conda activate app
python -m app.main --connect-telemetry --send-commands false
```

浏览器打开：

```text
http://<RK3588-IP>:8080/
```

## 比赛操作顺序

1. 核对 telemetry、相机、模型、SERVO 通道和 `SEND=OFF`；
2. 在 Competition Field Setup 输入 forward marker GPS；
3. 飞机静止在起飞点，完成 GPS 采样、finalize 和 freeze；
4. 选择 `rescue_2026_full_auto_v2` 或所需分项模板；
5. 检查任务步骤、高度、速度、失败恢复和投放参数；
6. 先以 SEND=OFF 运行完整流程；
7. 按 SITL、无载荷实机、断开投放、空载 SERVO、正式载荷的顺序验证。

系统 SEND 和 Action `send_actions` 必须同时开启才允许飞行动作实发。紧急情况应使用
遥控器或地面站接管，不能把停止 app 当作唯一急停方式。

## systemd 服务

```bash
bash scripts/deploy/install_systemd_user_services.sh --dry-run
bash scripts/deploy/install_systemd_user_services.sh --enable-now
sudo loginctl enable-linger "$USER"

systemctl --user --no-pager --full status uav-app.service uav-yolo.service
journalctl --user -u uav-app.service -f
journalctl --user -u uav-yolo.service -f
```

## 常见排查

```bash
# 板端只读检查
bash scripts/healthcheck/check_rk3588.sh

# Web UI
ss -ltnp | grep ':8080'
curl -fsS http://127.0.0.1:8080/api/status

# YOLO 视频流
ss -ltnp | grep ':8081'
curl -v http://127.0.0.1:8081/video/yolo.mjpeg

# YOLO 检测 UDP
ss -lunp | grep ':5005'
```

详细运行与现场更新说明见 [running.md](running.md)，SITL 见
[sitl_start.md](sitl_start.md)。实机发命令前必须阅读
[安全边界](../reference/safety.md) 和
[场地初始化](../reference/field_origin_heading.md)。
