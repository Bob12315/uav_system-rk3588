# AI 快速接管

本目录专门用于 AI 和开发者快速理解、修改、验证和部署项目。项目仅面向
Linux ARM64 RK3588；YOLO 必须使用 RKNNLite 在 NPU 上推理。

## 先读什么

任何修改前依次阅读：

1. [architecture.md](architecture.md)
2. [interfaces.md](interfaces.md)
3. [control_flow.md](control_flow.md)
4. [development_rules.md](development_rules.md)
5. [../reference/safety.md](../reference/safety.md)

然后根据任务类型从 [task_checklist.md](task_checklist.md) 选择追加文件。

## 一句话边界

```text
yolo_app       只负责 RKNN NPU 感知与 UDP 输出
telemetry_link 只负责 MAVLink 状态和发送
fusion         只负责融合感知与遥测
missions       只负责任务流程和 stage controller
app            只负责编排服务与运行循环
uav_ui/web_ui  只负责人工交互
config         保存当前生效的系统配置
runtime        保存不提交 Git 的运行产物
```

任何连续控制命令必须经过：

```text
MissionStage -> FlightCommand -> CommandShaper
  -> FlightCommandExecutor -> LinkManager -> MAVLink
```

## 平台硬约束

- 不新增 x86、CUDA、PyTorch 或 GPU YOLO 推理路径。
- 部署模型固定在 `data/models/best-int8-rk3588.rknn`。
- Python 保持 `3.10` 兼容。
- `config/app.yaml` 中 `executor.send_commands` 默认必须为 `false`。
- 日志、SITL 状态、视频和 blackbox 数据只能进入 `runtime/`。

## 常用操作

检查工作区：

```bash
git status --short --branch
```

运行测试：

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

安全 smoke test：

```bash
python -m app.main \
  --no-yolo-udp \
  --no-ui \
  --run-seconds 1 \
  --send-commands false \
  --blackbox-enabled false
```

检查 CLI：

```bash
python -m app.main --help
python -m telemetry_link.main --help
python -m yolo_app.main --help
```

## 修改后最少说明

完成任务时说明：

```text
修改了哪些文件
影响哪个模块边界
是否影响 send_commands 或 MAVLink
运行了哪些测试
是否仍有未处理问题
```

