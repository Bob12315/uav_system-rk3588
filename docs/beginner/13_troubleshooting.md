# 13：故障排查

## 本章目标

按“电源和系统 → 服务 → 配置 → 接口 → 数据 → Action”的顺序定位问题，避免一遇到故障
就重装系统、覆盖配置或开启 SEND 试错。

## 排查前固定动作

1. 关闭 SEND，停止 Mission；
2. 实机拆桨、移除载荷；
3. 记录故障时间、现象、最近正常时间和最近改动；
4. `git status --short` 保存当前改动证据；
5. 不运行破坏性 Git 命令，不删除日志。

## 一键只读检查

```bash
bash scripts/healthcheck/check_rk3588.sh
systemctl --user --no-pager --full status uav-app.service uav-yolo.service
journalctl --user -u uav-app.service -n 150 --no-pager
journalctl --user -u uav-yolo.service -n 150 --no-pager
ss -lntu | grep -E ':(5005|5006|8080|8081|14550|15001)\b'
```

## 问题：Web UI 打不开

检查：

```bash
systemctl --user status uav-app.service
curl -v http://127.0.0.1:8080/api/status
ss -ltnp | grep ':8080'
```

如果本机可访问、其他电脑不可访问，检查 `web_host`、RK3588 IP、路由和防火墙。不要通过
开启 SEND 验证 Web 是否正常。

## 问题：没有 YOLO 画面

检查：

```bash
systemctl --user status uav-yolo.service
journalctl --user -u uav-yolo.service -n 150 --no-pager
v4l2-ctl --list-devices
ls -l /dev/v4l/by-id/ 2>/dev/null || true
curl -v http://127.0.0.1:8081/video/yolo.mjpeg
```

常见原因：相机设备号变化、权限、占用、错误分辨率/FourCC、NPU 初始化失败或模型路径错误。

## 问题：有画面但没有检测

确认实际加载的是实机模型 `cuadc2026-fp16.rknn`，检查类别表、阈值、光照、目标尺寸、
输入方向和模型/NPU 日志。不要用显示镜像或历史 INT8 参数“修复”检测。

## 问题：app 收不到 YOLO

```bash
ss -lunp | grep -E ':(5005|5006)\b'
grep -En "udp_(ip|port)|command_(ip|port)" config/yolo.yaml config/app.yaml
```

确认 yolo 输出 `5005/udp` 与 app 接收一致，且没有端口占用或容器/网络命名空间隔离。

## 问题：telemetry 不连接

检查 `config/telemetry.yaml` 的 data_source、active_source、connection_type、地址、端口或
串口。实机默认 profile 是 Ethernet UDP-in 15001，但最终值必须与真实飞控/网络模块一致。

串口还需检查设备权限、电平、TX/RX、GND 和波特率；网络需检查 IP、路由、端口方向和
飞控是否真正发送 heartbeat。

## 问题：Field Reference 无法完成

检查 forward marker 经纬度、GPS fix、卫星数、EPH/EPV、采样数量、水平离散度和 A→B
baseline。飞机必须在采样期间静止。不要修改代码跳过 confirmed/synced/frozen preflight。

## 问题：Action/Mission 不启动

先看 Web UI 和 app 日志中的 reason。常见原因：

- Field Reference 未确认、同步或冻结；
- telemetry stale/control not allowed；
- Action 参数或 blackboard 引用错误；
- 上一个 Action 未停止；
- 模板校验失败；
- SEND/send_actions 状态与期望不同。

离线检查：

```bash
python scripts/validate_action_missions.py
```

## 问题：舵机通道或方向不对

立即移除正式载荷并断开机械负载。核对飞控 SERVO 输出编号，而不是 RC 输入通道。使用
[投放机构记录表](../hardware/payload_release.md) 重新进行单路空载验证。不要通过 RC
override 或直接 pymavlink 绕过当前链路。

## 问题：服务反复重启

```bash
systemctl --user status uav-app.service uav-yolo.service
journalctl --user -u uav-app.service -b --no-pager
journalctl --user -u uav-yolo.service -b --no-pager
systemctl --user cat uav-app.service uav-yolo.service
```

检查 WorkingDirectory、Python 路径、环境依赖、模型/相机权限和端口占用。仓库移动或
Conda 路径变化后应重新运行 service 安装脚本。

## 什么时候停止自行排查

- 供电电压、极性或共地不确定；
- 出现过热、异味、冒烟、连接器变色；
- 飞控姿态方向或电机输出异常；
- 自动动作方向与预期不一致；
- 需要靠关闭安全检查才能继续；
- 无法确认某个动作是否会实发。

这时保持断电/SEND=OFF，保存日志和配置，请硬件负责人、飞手或项目维护者共同处理。
