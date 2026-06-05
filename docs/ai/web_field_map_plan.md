# Web Field Map Plan

本文记录 Web UI “场地态势图 / Field Map”功能设计。该功能用于在浏览器控制台中
显示比赛场地、无人机当前位置、扫描点、已估计目标点和侦察识别结果。本文只做设计，
后续实现时按本文拆分任务。

## 1. 目标

在 Web UI 控制台新增一个俯视场地图，帮助操作员实时理解比赛任务进展：

- 画出起降区、投放区、侦察区。
- 标出无人机当前位置和高度。
- 标出投放区、侦察区扫描点。
- 搜索到圆筒目标后，在地图上标出目标估计位置。
- 显示目标编号、`x/y` 数值、观测次数和置信度。
- 高亮当前正在处理的目标。
- 显示已投放、已访问和已确认危险品标识的状态。

第一版只做态势显示，不在地图上发控制命令，避免引入新的飞控操作入口。

## 2. 与新版 rescue mission 的关系

新版 `rescue_competition` mission 已经在 `MissionOutput.detail` 中输出：

```text
drop_scan_index
drop_estimate_count
drop_targets
drop_target_index
drop_count
recce_scan_index
recce_estimate_count
recce_targets
recce_target_index
recce_results
recce_report_path
payload_slots
```

其中 `drop_targets` / `recce_targets` 元素包含：

```json
{
  "target_id": 1,
  "x": 29.42,
  "y": -0.85,
  "seen_count": 4,
  "max_confidence": 0.82,
  "mean_target_size": 0.08,
  "sources": ["drop_p1", "drop_p2"],
  "visited": false
}
```

Web Field Map 第一版主要消费这些字段。后端需要把 mission detail 透出到
`/api/status` 和 WebSocket 状态流。

## 3. 后端设计

### 3.1 状态快照新增字段

在 `app/system_runner.py` 的 control loop 中，当前 `latest_snapshot` 包含：

```python
{
    "perception": asdict(perception),
    "scene": asdict(scene),
    "drone": asdict(drone),
    "gimbal": asdict(gimbal),
    "link": asdict(link) if link is not None else {},
    "health": {"hold_reason": health.hold_reason},
    "command": asdict(shaped),
}
```

建议新增：

```python
"mission_detail": mission.detail
```

这样前端可以通过 `/api/status` 获取：

```json
{
  "mission": "rescue_competition",
  "stage": "SURVEY_DROP_POINTS",
  "drone": {
    "local_position_valid": true,
    "local_x": 12.3,
    "local_y": -0.2,
    "local_z": -5.0,
    "relative_altitude": 5.0
  },
  "mission_detail": {
    "drop_targets": [],
    "drop_scan_index": 2
  }
}
```

### 3.2 必需字段：mission 原点和 mission 坐标

地图上的扫描点、投放目标和侦察目标都使用 mission 坐标，因此无人机也必须优先
使用 mission 坐标。不能直接把飞控 `local_x/local_y` 与 `drop_targets/recce_targets`
混画，否则当起飞点不等于 local origin，或 mission 坐标相对 local 坐标有 yaw 旋转时，
地图上的位置关系会错误。

rescue mission detail 应加入：

```json
{
  "mission_position": {"x": 12.3, "y": -0.2, "z": -5.0},
  "origin": {"local_x": 0.0, "local_y": 0.0, "local_z": 0.0, "yaw_rad": 0.0}
}
```

前端仅在 `mission_position` 暂无时，才用 `drone.local_x/local_y/local_z` 作为降级显示，
并在 legend 中标注 fallback 状态。

### 3.3 不新增控制接口

第一版后端不新增地图点击控制接口。地图只读，降低误操作风险。

## 4. 前端布局

在 `web_ui/static/index.html` 控制台页面新增一个 panel：

```html
<section class="field-map-row">
  <article class="panel field-map-panel">
    <div class="panel-title">场地态势图</div>
    <div class="field-map-wrap">
      <canvas id="fieldMap"></canvas>
      <div id="fieldMapOverlay" class="field-map-overlay"></div>
    </div>
    <div id="fieldMapLegend" class="field-map-legend"></div>
  </article>
</section>
```

建议位置：

```text
视频 + 目标列表
场地态势图
飞行安全控制 + Mission 控制
命令行
日志/系统输出
```

也就是放在 `.top-grid` 后，`.controls-grid` 前。

## 5. 地图范围和场地尺寸

第一版固定地图范围：

```text
x_min = -5m
x_max = 65m
y_min = -6m
y_max = 6m
```

比赛区域：

```text
起降区：x 约 0m 附近，宽 8m
投放区：中心 x=30m, y=0m，尺寸 8m x 5m
侦察区：中心 x=55m, y=0m，尺寸 8m x 5m
```

场地块建议：

```js
const FIELD = {
  bounds: {xMin: -5, xMax: 65, yMin: -6, yMax: 6},
  takeoff: {x: 0, y: 0, w: 8, h: 8},
  drop: {x: 30, y: 0, w: 8, h: 5},
  recce: {x: 55, y: 0, w: 8, h: 5},
};
```

后续增强可从 `missions/rescue_competition/config.yaml` 或 `/api/status.mission_detail`
中读取 route 和 survey points。

## 6. 坐标转换

世界坐标：

```text
x: 起飞/解锁时机头正前方
y: 起飞/解锁时机头右侧
```

canvas 坐标：

```js
function worldToCanvas(x, y, rect) {
  const pad = 28;
  const usableW = rect.width - pad * 2;
  const usableH = rect.height - pad * 2;
  const sx = usableW / (FIELD.bounds.xMax - FIELD.bounds.xMin);
  const sy = usableH / (FIELD.bounds.yMax - FIELD.bounds.yMin);
  const scale = Math.min(sx, sy);
  const plotW = (FIELD.bounds.xMax - FIELD.bounds.xMin) * scale;
  const plotH = (FIELD.bounds.yMax - FIELD.bounds.yMin) * scale;
  const left = (rect.width - plotW) / 2;
  const top = (rect.height - plotH) / 2;
  const originX = left + (x - FIELD.bounds.xMin) * scale;
  const originY = top + (y - FIELD.bounds.yMin) * scale;
  return [originX, originY];
}
```

注意屏幕 `y` 向下。为了符合“右侧为 +y”的直觉，可以让 `+y` 显示在图下方，并在地图
角落标注：

```text
+x 前方
+y 右方
```

## 7. 地图元素

### 7.1 场地区域

绘制：

- 起降区：灰色边框。
- 投放区：蓝色半透明区域。
- 侦察区：黄色半透明区域。
- 中心线：`y=0` 虚线。
- 起飞线：按比赛说明可选绘制。

每块区域显示文字：

```text
起降区
投放区 8x5m
侦察区 8x5m
```

### 7.2 扫描点

从配置或固定默认点绘制：

投放区：

```text
D1 D2 D3 D4
```

侦察区：

```text
R1 R2 R3 R4
```

样式：

- 未到达：空心小圆。
- 当前扫描点：高亮外圈。
- 已扫描：实心小圆或带勾。

第一版如果不读取配置，可直接使用默认点：

```js
drop survey:  (28,-1.2), (28,1.2), (32,-1.2), (32,1.2)
recce survey: (53,-1.2), (53,1.2), (57,-1.2), (57,1.2)
```

### 7.3 无人机

用三角箭头表示：

```text
△ UAV
```

由于新版 mission 不主动偏航，箭头默认朝 `+x`。若后续要显示实际 yaw，可用
`drone.yaw - mission_detail.origin.yaw_rad` 旋转，但第一版不需要。

旁边显示：

```text
UAV
x=12.30
y=-0.20
z=5.00
```

无人机坐标优先级：

1. `state.mission_detail.mission_position`
2. fallback: `state.drone.local_x/local_y/local_z`

### 7.4 目标点

投放目标：

```text
D-T1
x=29.42 y=-0.85
seen=4 conf=0.82
```

侦察目标：

```text
R-T3
x=55.20 y=1.10
blank / confirmed
```

样式：

- 投放目标：蓝色圆点。
- 侦察目标：黄色圆点。
- 当前目标：白色或青色高亮描边。
- 已投放/已访问：灰色或带勾。
- confirmed 危险品：绿色。
- blank/uncertain：灰色。

### 7.5 轨迹

第一版不画历史轨迹。后续可在前端缓存最近 N 个无人机位置，画成淡色折线。

## 8. 状态摘要

地图右上角或 legend 显示：

```text
Stage: SURVEY_DROP_POINTS
Drop: 1/2
Drop targets: 2
Recce confirmed: 2/3
Current: D-T2
```

数据来源：

```js
const detail = state.mission_detail || {};
const dropCount = detail.drop_count || 0;
const dropTargets = detail.drop_targets || [];
const recceResults = detail.recce_results || [];
const confirmed = recceResults.filter(item => item.status === "confirmed").length;
```

## 9. 前端函数拆分

在 `web_ui/static/app.js` 中新增：

```js
function renderFieldMap(state) {}
function fieldMapModel(state) {}
function resizeFieldCanvas(canvas) {}
function worldToCanvas(x, y, bounds, rect) {}
function drawField(ctx, model) {}
function drawSurveyPoints(ctx, model) {}
function drawDrone(ctx, model) {}
function drawTargets(ctx, model) {}
function drawFieldLabel(ctx, text, x, y, options = {}) {}
```

在 `renderStatus(next)` 末尾调用：

```js
renderFieldMap(next);
```

## 10. CSS 设计

新增样式：

```css
.field-map-row {
  margin-top: 12px;
}
.field-map-wrap {
  position: relative;
  height: 360px;
  background: #08111a;
  border: 1px solid var(--line);
  border-radius: 5px;
}
#fieldMap {
  width: 100%;
  height: 100%;
  display: block;
}
.field-map-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 8px;
  color: var(--muted);
  font-family: Consolas, monospace;
  font-size: 12px;
}
```

避免将地图放入嵌套卡片，保持一个单独 panel。

## 11. 第一版实现清单

1. 后端 `latest_snapshot` 增加 `mission_detail`。
2. 可选：rescue mission detail 增加 `mission_position`。
3. HTML 新增 Field Map panel。
4. CSS 新增地图布局。
5. JS 新增 canvas 绘图函数。
6. 画固定场地、扫描点、无人机。
7. 画 `drop_targets`、`recce_targets`、`recce_results`。
8. 当前目标按 `drop_target_index` / `recce_target_index` 高亮。
9. legend 显示阶段和计数。
10. 添加基本前端 smoke：页面加载不报错；无数据时显示空场地。

## 12. 后续增强

后续可选：

- 鼠标悬停目标点显示详情。
- 点击目标点在右侧显示 target detail，但不发控制命令。
- 从 mission config 动态读取场地范围和扫描点。
- 绘制最近飞行轨迹。
- 显示 raw detections 临时估计点。
- 显示投放动作时间和 payload id。
- 保存地图截图到运行日志。

## 13. 安全边界

第一版 Field Map 必须只读：

- 不新增地图点击起飞/移动/投放功能。
- 不绕过 UI command handler。
- 不访问任意文件。
- 不改变 `send_commands` 默认值。
- 不影响 `CommandShaper` / `FlightCommandExecutor` 控制链路。

地图只是态势显示，控制仍通过现有 Mission 控制、命令行和安全按钮完成。
