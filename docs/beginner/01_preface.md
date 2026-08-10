# 01：前言

这套教程面向第一次接触 RK3588、MAVLink 或无人机视觉的新手。你不需要先看懂全部代码，
只需要按六章顺序完成准备、组装、部署、仿真和分级实飞。

> **安全提示：** 本项目会连接真实飞控和投放舵机。第一次部署和调试必须拆桨、移除
> 正式载荷，并保持 `config/app.yaml` 中 `executor.send_commands: false`。AI 可以帮助
> 安装软件，但不能替代供电检查、接线确认、飞控校准和现场安全判断。

## 项目要完成什么

当前项目面向 2026 多旋翼无人机侦察与救援比赛，完整任务包括：

```text
比赛场地初始化
  → 起飞
  → 投放区多视角识别与定位
  → 选择两个目标并依次投放
  → 侦察区识别危险标识
  → 生成侦察结果
  → 返回起飞点
  → 视觉辅助降落和 LAND 兜底
```

正式完整模板是
`config/action_missions/rescue_2026_full_auto_v2.json`。模板存在不代表已经通过实飞，
必须依次完成无桨台架、SITL 和无载荷实飞验证。

## 系统由什么组成

### 飞控

ArduPilot 飞控负责姿态稳定、电机输出、GPS/高度状态和底层飞行控制。RK3588 不替代
飞控，也不直接驱动电机。遥控器或地面站始终是实飞时的人工接管手段。

### RK3588

RK3588 运行两个主要进程：

- `yolo_app`：读取下视相机，使用 RKNNLite 和 NPU 检测、跟踪目标；
- `app`：接收感知与飞控状态，运行 Action Mission，并提供 Web UI。

### 下视相机与投放机构

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

YOLO 不连接 MAVLink，Action 也不直接调用飞控接口。正式人工操作入口只有 Web UI。

## 六章学习路线

| 顺序 | 教程 | 完成标志 |
| ---: | --- | --- |
| 1 | 本章：前言 | 理解系统组成、任务目标和安全边界 |
| 2 | [配置清单](02_hardware_bom.md) | 硬件、工具和软件准备完成，必需项均已确认 |
| 3 | [无人机组装](03_drone_assembly.md) | 机械、供电、接线和无桨上电检查完成 |
| 4 | [RK3588 环境配置](04_rk3588_setup.md) | app、YOLO、Web UI 和只读遥测运行正常 |
| 5 | [SITL 测试](05_sitl_test.md) | 仿真中完成分项及完整任务验证 |
| 6 | [实飞测试](06_flight_test.md) | 按台架、人工、无载荷、分项和完整任务逐级验收 |

## 必须理解的两个开关

系统默认配置必须保持：

```yaml
executor:
  send_commands: false
```

飞行动作实发至少同时需要：

1. 系统 SEND，即 `send_commands` 已由人工开启；
2. 当前 Action 的 `send_actions` 请求已开启。

连接飞控、打开网页、加载任务或初始化场地，都不等于允许发送飞行动作。新手在完成
SITL 前不应在实机上开启 SEND。

## FIELD 场地坐标

比赛使用 FIELD 坐标：

- `+Y`：从起飞点指向场地前方；
- `+X`：面向场地前方时的右侧；
- `altitude_m`：向上为正。

正式任务前要在 Web UI 建立并冻结 Field Reference。GPS Home、EKF Origin 和比赛
FIELD 原点不是同一个概念。

## 开始前检查

- [ ] 我知道 RK3588 不直接驱动电机。
- [ ] 我知道 Web UI 是正式操作入口。
- [ ] 我知道 SEND 默认必须关闭。
- [ ] 我知道 AI 不能替我确认电压、极性、引脚和实飞安全。
- [ ] 我会先完成 SITL，不会从“软件启动成功”直接跳到完整实飞。

下一章：[配置清单](02_hardware_bom.md)。
