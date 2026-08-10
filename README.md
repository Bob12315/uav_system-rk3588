# cuadc2026 多旋翼无人机侦察与救援项目

这是一个面向 Linux ARM64 RK3588、ArduPilot 和下视相机的比赛专用无人机项目。
完成搭建后，系统可以通过网页操作，执行场地初始化、目标识别、双目标投放、危险标识
侦察、自动返回和视觉辅助降落。

这份 README 是新手入口。即使你第一次接触 RK3588、MAVLink 或无人机视觉，也可以按
下面的章节顺序完成搭建。每一步都包含“准备什么、怎么操作、正确结果和出错怎么办”。

> **重要安全提示：** 本项目会连接真实飞控和投放舵机。第一次部署、调试和检查必须
> 拆桨、移除载荷，并保持 `executor.send_commands: false`。AI 可以帮助安装软件，
> 但不能替代供电检查、接线确认、飞控校准和现场安全判断。

## 最终要完成什么

当前完整比赛任务使用
[`rescue_2026_full_auto_v2.json`](config/action_missions/rescue_2026_full_auto_v2.json)：

```text
比赛场地初始化
  → 起飞至 4.5 m
  → 投放区多视角识别与定位
  → 选择两个目标并依次投放
  → 前往侦察区识别危险标识
  → 生成侦察排名
  → 返回起飞点
  → 视觉辅助降落和 LAND 兜底
```

系统由三个主要部分组成：

```text
下视相机
  → RK3588：RKNN 目标检测、比赛任务、Web UI
  → MAVLink：飞控状态与控制请求
  → ArduPilot：姿态、位置、动力和舵机输出
```

更详细的内部架构见 [比赛任务说明](docs/developer/action_mission_rescue_2026.md)；新手不需要
先理解全部代码才能开始组装。

## 新手完整学习路线

请从上到下阅读，不建议跳过台架测试直接实飞。

| 顺序 | 教程 | 完成标志 |
| ---: | --- | --- |
| 1 | [前言](docs/beginner/01_preface.md) | 理解系统组成、比赛目标和安全边界 |
| 2 | [配置清单](docs/beginner/02_hardware_bom.md) | 填完 BOM，硬件、工具和软件资料准备完成 |
| 3 | [无人机组装](docs/beginner/03_drone_assembly.md) | 机械、接线、供电和无桨检查完成 |
| 4 | [RK3588 环境配置](docs/beginner/04_rk3588_setup.md) | app、YOLO、Web UI 和只读遥测正常 |
| 5 | [SITL 测试](docs/beginner/05_sitl_test.md) | 仿真中完成分项与完整任务验证 |
| 6 | [实飞测试](docs/beginner/06_flight_test.md) | 台架、无载荷、分项和完整任务逐级验收 |

## 购买硬件前先看

仓库能够证明软件接口和当前配置，但不能仅凭代码确定你的机架、电机、电池、飞控版本、
RK3588 板卡和相机实物型号。因此硬件文档把尚未确认的项目标为 **待确认**，不要照着
占位符购买。

核心硬件类别包括：

- 多旋翼机架、动力系统、电池和遥控器；
- 支持 ArduPilot 的飞控、GPS/罗盘；
- Linux ARM64 RK3588 板卡、散热和可靠供电；
- 下视相机及固定结构；
- RK3588 与飞控之间的 MAVLink 链路；
- 两路投放机构、舵机和独立验证过的 SERVO 输出；
- 必要的 DC-DC、电源分配、保险和线材。

完整 BOM 表见 [配置清单](docs/beginner/02_hardware_bom.md)，接线、供电、相机和投放机构
记录表已统一放入 [无人机组装](docs/beginner/03_drone_assembly.md)。填写时必须记录准确
型号、输入电压、接口、数量和实机验证状态。

## 可以让 AI 帮你部署

本项目建议使用能读取仓库并执行终端命令的 AI 编程助手完成软件环境部署。不要使用一句
“帮我全部装好并起飞”的提示词，而应分阶段执行：

```text
只读检查板卡
→ 阅读仓库和制定计划
→ 安装 app 环境
→ 安装 yolo 环境
→ 根据真实硬件修改配置
→ 安装 systemd 服务
→ 只观察联调
→ 根据日志排错
```

可以先把下面这段发给 AI：

```text
请帮助我部署当前仓库，但先只做只读检查，不要安装或修改任何文件。
请先阅读 README.md、AGENTS.md、docs/ai/current_architecture.md、
docs/developer/safety.md 和 docs/beginner/04_rk3588_setup.md。

必须遵守：
1. 始终保持 config/app.yaml 的 executor.send_commands=false。
2. 不得发送解锁、起飞、速度、航点、降落或舵机命令。
3. 不确定硬件端口、电压、设备节点时必须询问，不能猜测。
4. 修改前检查 git status，保留已有改动。
5. 先报告系统架构、RK3588/NPU、摄像头、网络、Conda 和仓库状态，
   再给出分阶段部署计划。
```

完整的可复制提示词见 [RK3588 环境配置](docs/beginner/04_rk3588_setup.md)。

## 当前软件约束

- 只支持 Linux ARM64 RK3588。
- YOLO 使用 `RKNNLite` 和 RK3588 NPU，不提供 x86、CUDA、PyTorch 或 GPU 推理路径。
- 实机模型是 `data/models/cuadc2026-fp16.rknn`。
- SITL profile 使用 `data/models/gazebo_dataset-fp16.rknn`。
- Web UI 是唯一正式人工操作入口，默认地址为 `http://<RK3588-IP>:8080/`。
- 当前任务通过 `config/action_missions/*.json` 编排，不使用旧 mission/stage/control 栈。
- Action 不直接发送 MAVLink；正式链路是 `ActionDispatcher → LinkManager`。

## 必须一直记住的安全开关

默认配置必须保持：

```yaml
executor:
  send_commands: false
```

飞行动作只有在系统 SEND 和 Action `send_actions` 两个开关同时开启时才可能实发。
连接 telemetry、打开网页、加载任务或初始化场地不等于允许飞行。

投放只能走：

```text
payload_release → set_servo → MAV_CMD_DO_SET_SERVO
```

禁止使用 RC override、旧 `release_payload` 接口或在 Action 中直接调用 pymavlink。
实机前完整阅读 [安全边界](docs/developer/safety.md)。

## 已经熟悉系统后

- [开发者文档入口](docs/developer/README.md)
- [比赛任务说明](docs/developer/action_mission_rescue_2026.md)
- [配置说明](docs/developer/configuration.md)
- [坐标系规范](docs/developer/coordinate_frames.md)
- [Field Reference](docs/developer/field_origin_heading.md)
- [开发者/AI 接管入口](docs/ai/README.md)
- [当前架构裁决](docs/ai/current_architecture.md)
- [完整文档索引](docs/README.md)

如果你正在第一次搭建，请从 [前言](docs/beginner/01_preface.md) 开始按六章继续。
