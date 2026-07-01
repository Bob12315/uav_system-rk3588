# 当前开发规则

## 通用

- Python 3.10 兼容；配置 YAML 严格解析 bool 并转 dataclass。
- 只支持 Linux ARM64 RK3588、RKNNLite 和 NPU。
- 默认模型 `data/models/cuadc-fp16.rknn`。
- `executor.send_commands` 默认 false。
- 运行产物只进入 `runtime/`。
- 不恢复 deprecated mission/stage/control 栈。
- 不直接删除 `uav_ui/`；先迁出 app 共用组件。

## 修改 Action

主要修改 `missions/common/actions/`、对应测试和必要的 Action Mission JSON。
Action 返回结构化 result/request，不直接调用 LinkManager/pymavlink。坐标参数遵守
[action_contracts.md](action_contracts.md)。模板改动必须运行 validator。

## 修改 Action Mission

主要修改 `app/mission_orchestrator.py`、`config/action_missions/*.json` 和编排测试。
不在 orchestrator 中计算控制律或构造 MAVLink。

## 修改派发或 telemetry

ActionDispatcher 负责路由和双门控；LinkManager/CommandSender 负责通讯。连续命令
改动属于高风险，必须保留 stop/zero、队列清理、断线停止和 SEND 门控，并单独评审。
不得用恢复旧 Executor 作为快捷修复。

## 修改坐标和 Field Reference

先读坐标唯一规范和 Field Reference 设计。复用 `runtime_context.py` 现有逻辑并逐步
迁移到唯一 CoordinateTransform，不建立平行转换。字段语义变化必须覆盖 0/90/180°、
正反变换、未确认拒绝、GPS 短基线和冻结测试。

## 修改 UI

Web UI 是正式入口。UI 经 API/SystemRunner 进入业务层，不直接访问 pymavlink。
Field Reference 的记录/确认/清除操作本身不得产生飞行动作。

## 修改 YOLO

只改 `yolo_app/`、`config/yolo.yaml` 和协议相关文档/测试。保持 RKNNLite/NPU，禁止
x86/CUDA/PyTorch 路径；YOLO 不连接 MAVLink。

## 投放

唯一链路：`payload_release` Action → `set_servo`。禁止 `release_payload`、RC
override 和直接 pymavlink。

## 验证

```bash
python -m compileall app missions telemetry_link fusion yolo_app web_ui scripts
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
python scripts/validate_action_missions.py
```

已有失败必须如实记录，不能通过永久 ignore 或恢复旧架构掩盖。
