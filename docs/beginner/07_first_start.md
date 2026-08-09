# 07：第一次启动

## 本章目标

在拆桨、无载荷、SEND=OFF 的条件下启动 app 和 yolo，确认 Web UI、视频、检测和
telemetry 状态可见。本章不运行 Action。

预计时间：30～90 分钟。需要准备：已部署 RK3588、相机、飞控和同一局域网电脑。

## 1. 启动前确认

```bash
cd <仓库绝对路径>
git status --short
grep -n "send_commands" config/app.yaml
bash scripts/healthcheck/check_rk3588.sh
```

必须确认 `executor.send_commands: false`。健康检查中的相机、服务端口警告可以在服务
启动后复查，但配置安全检查不能失败。

## 2. 手动启动方式

先用两个终端观察日志：

```bash
# 终端 1
conda activate yolo
python -m yolo_app.main

# 终端 2
conda activate app
python -m app.main --connect-telemetry --send-commands false
```

或使用已安装服务：

```bash
systemctl --user restart uav-yolo.service uav-app.service
systemctl --user --no-pager --full status uav-yolo.service uav-app.service
```

## 3. 打开 Web UI

浏览器访问：

```text
http://<RK3588-IP>:8080/
```

第一次只观察：

- link 是否 connected，状态是否 stale；
- GPS、姿态、高度、LOCAL_NED 是否更新；
- YOLO 视频是否连续；
- 检测类别和框是否合理；
- SEND 是否明确为 OFF；
- Action Mission 是否尚未运行。

不要点击起飞、航点、模式、投放或 Mission Start。

## 4. 检查端口和 API

```bash
ss -lntu | grep -E ':(5005|5006|8080|8081)\b'
curl -fsS http://127.0.0.1:8080/api/status
timeout 5s curl -fsS http://127.0.0.1:8081/video/yolo.mjpeg \
  -o /tmp/yolo-check.mjpeg || true
test -s /tmp/yolo-check.mjpeg && echo "video stream has data"
```

端口含义：8080 是 Web/API，8081 是 MJPEG，5005 是 app 接收检测，5006 是 yolo 接收
目标选择命令。

## 5. 查看日志

```bash
journalctl --user -u uav-app.service -n 100 --no-pager
journalctl --user -u uav-yolo.service -n 100 --no-pager
```

重点关注模型加载失败、相机打不开、UDP 地址冲突、MAVLink heartbeat 超时、反复重启和
权限错误。

## 正确结果

两个进程稳定运行；Web UI 和视频流可打开；检测和飞控状态持续更新；系统 SEND 显示
关闭；没有任何飞行或舵机动作。

## 完成检查表

- [ ] 拆桨、无载荷、SEND=OFF。
- [ ] app/yolo 服务没有反复重启。
- [ ] Web UI 和 MJPEG 可以访问。
- [ ] YOLO scene 数据随画面变化。
- [ ] telemetry 状态更新，或已明确记录连接问题。
- [ ] 未启动任何 Action 或 Mission。

下一章：[无桨台架测试](08_bench_test.md)。
