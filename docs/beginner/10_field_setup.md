# 10：比赛场地初始化

## 本章目标

在 Web UI 中建立比赛 FIELD 坐标，使任务能够把场地投放区、侦察区和返航点转换为
GLOBAL 航点。本章默认使用 schema v3 比赛现场流程。

预计时间：正式操作约数分钟，第一次学习建议 1～2 小时。需要准备：准确的 forward
marker GPS、开阔 GPS 环境和静止在起飞点的飞机。

## 先理解 A 和 B

- A：飞机在起飞点静止采样得到的动态 GPS 原点，对应 FIELD `(0, 0)`；
- B：位于场地 `+Y` 方向的 forward marker GPS；
- A→B 方位：本次比赛 FIELD `+Y` heading。

schema v3 生成 FIELD → GPS/GLOBAL 几何，不建立 LOCAL_NED 场地原点。不要把 GPS Home、
EKF Origin 和 FIELD 原点混为一谈。

## 1. 起飞前准备

- 飞机放在正式起飞点并保持静止；
- GPS fix、卫星数、EPH/EPV 满足 profile；
- forward marker 的经纬度已由人工确认；
- 使用 WGS84 表达，未把经纬度顺序写反；
- Web UI 可查看 telemetry；
- SEND 保持 OFF。

## 2. Competition Field Setup

在 Web UI 打开 `Competition Field Setup / 比赛场地初始化`：

1. 输入 forward marker 纬度和经度；
2. 启动 runtime sampling；
3. 保持飞机静止，等待采样窗口完成；
4. 查看 accepted/rejected/duplicate samples；
5. 检查水平离散度、A→B baseline、heading 和 warning；
6. 确认投放区、侦察区和扫描点地图预览；
7. 采样满足条件后等待系统自动 finalize、apply 和 freeze；
8. 确认状态为 confirmed、synced、frozen。

当前模板要求至少 20 个合格样本、12 秒采样窗口和不超过 1 m 的水平离散度。具体阈值
以 `config/field_profiles/competition_runtime_v3.json` 为准。

## 3. 拒绝继续的情况

- forward marker 不确定或疑似经纬度写反；
- GPS fix/卫星数/EPH/EPV 不满足阈值；
- 采样期间飞机被移动；
- 水平离散度超过阈值；
- A→B baseline 太短；
- 地图中投放区、侦察区方向与真实场地不一致；
- finalize 后未 confirmed/synced/frozen；
- 出现无法解释的 warning。

不要通过修改代码跳过 preflight。Reset 后排除原因并重新采样。

## 4. 固定场地和 SITL

预先测绘的固定场地可使用 schema v2 centerline profile，例如 `XSYU.json` 或
`sitl_centerline_lane.json`。该流程使用 anchor 和至少四个中心线点拟合 heading，并建立
LOCAL_NED 场地原点。两种 schema 的区别见
[Field Reference 规范](../reference/field_origin_heading.md)。

## 正确结果

Web UI 显示 Field Reference 已确认、同步并冻结；地图的起点、前向、投放区和侦察区与
真实场地一致；任务 preflight 不再报告 Field Reference 缺失。

## 完成检查表

- [ ] forward marker GPS 来源和经纬度顺序已复核。
- [ ] 采样期间飞机保持静止。
- [ ] GPS 质量、样本数、离散度和 baseline 合格。
- [ ] 地图方向和场地几何经过第二人复核。
- [ ] confirmed、synced、frozen 均为 true。
- [ ] SEND 仍为 OFF。

下一章：[第一次实飞](11_first_flight.md)。
