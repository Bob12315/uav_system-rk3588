# 09：SITL 仿真验证

## 本章目标

在 ArduPilot SITL 中验证 telemetry、坐标方向、Action、停止路径和比赛任务模板。SITL
通过后仍不能跳过无载荷实飞。

预计时间：半天以上。需要准备：运行 ArduPilot SITL 的电脑、RK3588 和局域网。

## 1. 保存现场配置

切换 profile 会覆盖当前生效配置。先检查并保存需要保留的实机调参：

```bash
git status --short
bash scripts/config/save_rk3588_real.sh
```

确认 `config/app.yaml` 中 `executor.send_commands: false`，再应用 SITL profile：

```bash
bash scripts/config/apply_rk3588_sitl.sh
```

SITL profile 默认接收 MAVLink UDP 14550，YOLO 视频源为 UDP 5600，模型为
`gazebo_dataset-fp16.rknn`。

## 2. 启动 SITL

仓库提供辅助脚本：

```bash
bash scripts/run_iris_gimbal_sitl.sh
```

SITL 的运行位置、依赖和视频桥接可能因电脑环境不同而变化，详细说明见
[SITL 启动文档](../user/sitl_start.md)。先确认仿真飞控本身可被地面站连接，再接入 RK3588。

## 3. 只观察连接

保持 SEND=OFF，启动 app/yolo，确认：

- telemetry data_source/active_source 是 sitl；
- heartbeat、GPS、姿态、LOCAL_NED 更新；
- 仿真视频和 YOLO scene 更新；
- Web UI 明确显示 SEND OFF；
- 没有任务自动启动。

## 4. 建立 SITL Field Reference

使用 `config/field_profiles/sitl_centerline_lane.json` 或当前 SITL 流程建立并冻结场地参考。
确认 Web 地图上 `+Y` 前方、`+X` 右方与仿真运动一致。

## 5. 从低风险 Action 开始

按风险逐步验证：

```text
只读/识别 Action
→ 场地坐标预览
→ 单个低速航点
→ stop/reset/skip
→ 起飞与降落分项
→ 投放请求（无真实机构）
→ 分项 Mission
→ 完整 rescue_2026_full_auto_v2
```

只有在确认仿真场地、速度、高度和遥控接管后，才在 SITL 中开启系统 SEND 和 Action
send_actions。一次只改变一个变量。

## 6. 必测失败路径

- Action 运行中点击 Stop；
- 连续 BODY_NED Action 丢失视觉目标；
- Mission 中断、Reset 和 Skip Current；
- telemetry 断线和恢复；
- yolo 停止和恢复；
- Field Reference 未确认或未冻结时启动 Mission；
- 投放步骤失败后的恢复路径；
- 限速阶段结束后速度恢复；
- 视觉降落失败后 LAND 兜底。

确认停止或失败不会恢复旧速度、旧位置目标或重复投放请求。

## 7. 保存结果

记录使用的 commit、profile、Mission 模板、参数、SITL 起点、每个失败注入结果和日志路径。
运行产物放在 `runtime/`，不要把临时 SITL 文件写进配置目录。

## 完成检查表

- [ ] SITL telemetry、视频和 YOLO 状态稳定。
- [ ] FIELD 方向和航点方向经过实际仿真运动验证。
- [ ] stop/reset/skip 和丢目标路径均停止旧命令。
- [ ] 投放步骤不会重复或绕过 dispatcher。
- [ ] 完整 v2 模板在保守参数下完成一次。
- [ ] SITL 的 SEND 开启没有被带回实机配置。

返回实机配置前再次确认 `executor.send_commands: false`：

```bash
bash scripts/config/apply_rk3588_real.sh
```

下一章：[比赛场地初始化](10_field_setup.md)。
