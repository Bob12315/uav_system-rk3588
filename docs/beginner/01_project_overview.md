# 01：认识这个项目

## 本章目标

读完后，你应该知道 RK3588、飞控、相机、Web UI 和 Action Mission 分别负责什么，
并理解为什么软件部署完成后还不能直接实飞。

预计时间：15～30 分钟。需要准备：只需浏览器和本仓库。

## 三个主要硬件角色

### 飞控

ArduPilot 飞控负责姿态稳定、电机输出、GPS/高度状态和底层飞行控制。RK3588 不替代
飞控，也不应该直接驱动电机。遥控器或地面站仍是紧急接管手段。

### RK3588

RK3588 运行两个主要软件进程：

- `yolo_app`：读取下视相机，使用 RKNNLite/NPU 检测和跟踪目标；
- `app`：接收感知与飞控状态，运行比赛任务并提供 Web UI。

### 下视相机和投放机构

下视相机为投放、侦察和视觉降落提供画面。投放机构由飞控 SERVO 输出控制，软件只允许
通过 `payload_release → set_servo` 请求投放。

## 数据和命令怎么流动

```text
相机画面
  → yolo_app / RKNN NPU
  → UDP 检测结果
  → app 运行时上下文
  → Action Mission
  → ActionDispatcher 双门控
  → LinkManager / MAVLink
  → ArduPilot
```

YOLO 不连接 MAVLink；Action 不直接调用飞控接口。这些边界用于减少感知或任务代码绕过
安全门控的可能性。

## 当前比赛场地

比赛使用 FIELD 坐标：

- `+Y`：从起飞点指向场地前方；
- `+X`：面向前方时的右侧；
- `altitude_m`：向上为正。

当前模板包含投放区和侦察区。正式任务前必须通过 Web UI 建立 Field Reference，确认、
同步并冻结场地原点和方向。

## 两类任务入口

- Action Lab：单独测试一个 Action，例如起飞、航点、识别或投放；
- Action Mission：按 JSON 模板连续运行多个 Action。

比赛完整流程使用 `rescue_2026_full_auto_v2`。其他模板主要用于分项验证或回归，不应
只根据名字直接实飞。

## 你暂时不需要掌握的内容

刚开始不需要修改 Action、MAVLink 消息或坐标公式。先完成硬件记录、软件部署、无桨
台架和 SITL。需要开发时再阅读 `docs/ai/README.md`。

## 完成检查表

- [ ] 我知道 RK3588 不直接驱动电机。
- [ ] 我知道 YOLO、Action 和 MAVLink 的边界。
- [ ] 我知道 Web UI 是正式操作入口。
- [ ] 我知道 SEND 默认必须关闭。
- [ ] 我知道软件启动成功不等于可以实飞。

下一章：[准备硬件](02_hardware_bom.md)。
