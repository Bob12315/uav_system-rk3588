# Web UI Split Plan

## 1. Scope

本计划只针对 `web_ui/static/app.js` 前端拆分（2293 行）。
WU-0 不修改生产代码——只读分析并形成可执行拆分计划。

---

## 2. Current Files

| File | Lines | Responsibility |
|------|-------|---------------|
| `web_ui/static/app.js` | 2293 | 单体前端脚本：全局状态、API调用、状态轮询/WebSocket、Dashboard渲染、场地图绘制、Action Lab、Action Mission、Field Heading/Reference、Config编辑、日志、手动控制、初始化和事件绑定 |
| `web_ui/static/index.html` | 484 | HTML 骨架：5个主页面(tab)、DOM id结构、视频面板、场地图canvas、Action控件、Mission编辑器、Flight Safety面板、Config/Logs面板、Manual Command面板 |
| `web_ui/static/style.css` | 829 | 全局样式：dashboard网格、视频面板、场地图、Action Lab布局、Action Mission时间线、Flight Safety控制、Config编辑器、响应式布局 |
| `web_ui/server.py` | 518 | FastAPI Web 服务器：所有 `/api/*` 路由、`/ws/status` WebSocket、Pydantic请求模型、config存储和审计日志 |
| `app/web_status_service.py` | 224 | 只读Web状态快照构建器：从SystemRunner提取，注入依赖，构建包含drone/link/gimbal/perception/controllers/action_lab/action_mission/field_heading/localization的状态快照 |
| `app/field_reference_controller.py` | 198 | Field Reference API控制器：GPS A-B标记、当前yaw、手动heading、confirm/reset/freeze操作，同步runtime context |
| `app/command_pipeline.py` | 143 | 低风险命令处理器：camera录制、YOLO目标命令、外部进程管理（restart yolo/app等服务） |

---

## 3. app.js Current Responsibility Blocks

All line numbers from local `nl -ba` / grep on branch `refactor/split-web-ui` HEAD `f498bd2`.

### 3.1 Globals / Constants / Presets (行 1–177)

| Block | Line range | Main functions/constants | Responsibility | Risk |
|-------|-----------|--------------------------|---------------|------|
| `$` helper | 1 | `const $ = id => document.getElementById(id)` | DOM 快捷访问 | Low |
| State variables | 2–19 | `state`, `completions`, `history`, `historyIndex`, `currentConfigPath`, `currentOriginal`, `missionCatalog`, `actionSpecs`, `selectedActionName`, `actionParamCache`, `latestActionLab`, `actionStatusJsonSelecting`, `currentActionMission`, `currentActionMissionSteps`, `lastActionMissionStatus`, `lastActionMissionResult`, `actionMissionAutoTickTimer`, `latestCameraRecording` | 全局可变状态，贯穿所有模块 | **High** — 拆分时需保持全局可访问 |
| Constants | 20–177 | `fallbackStageModes`, `ACTION_SAFETY_HINTS`, `ACTION_ZH_LABELS`, `DEFAULT_ACTION_MISSION_STEPS`, `actionMissionPresets`, `FIELD_DEFAULTS` | 不可变配置、标签映射、预设模板 | Low |

### 3.2 API / Network Layer (行 179–184, 191–198, 2064–2072)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `json()` helper | 179–184 | `async function json(url, options)` | 通用 fetch + JSON parse + error handling | **Low** — WU-1 首选抽取目标 |
| `execute()` | 191–199 | `async function execute(command, source)` | POST `/api/commands/execute` + audit 刷新 | Medium — 涉及 command pipeline |
| `startStatusUpdates()` | 2041–2072 | WebSocket `/ws/status` + fallback polling (`/api/status` 500ms) + Action timer (1000ms) + Field Reference polling (2000ms) | 主状态刷新入口 | **High** — 多模块耦合，暂不拆分 |

### 3.3 Generic Format Helpers (行 185–189, 247–269, 546–555, 824–826)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `stamp()` | 185–187 | 时间戳格式化 | 通用工具 | Low |
| `escapeHtml()` | 188–190 | HTML 转义 | 通用工具 | Low |
| `num()` / `degNum()` / `xyzText()` / `boolText()` | 247–260 | 数值格式化 | 通用工具 | Low |
| `actionDisplayName()` / `actionNameWithZh()` | 261–269 | Action 中文名映射 | 工具函数 | Low |
| `setOptionalText()` | 546–549 | 安全设 DOM textContent | DOM 工具 | Low |
| `renderSummaryRows()` | 550–556 | 摘要行渲染 | DOM 工具 | Low |
| `finiteNumber()` | 824–827 | 数值安全转换 | 工具函数 | Low |

### 3.4 DOM Rendering Helpers (行 234–245)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `setBadge()` | 234–237 | Badge 样式设置 | DOM 工具 | Low |
| `cards()` | 238–241 | 卡片网格渲染 | DOM 工具 | Low |
| `infoRows()` | 242–246 | 信息行渲染 | DOM 工具 | Low |

### 3.5 Camera Recording (行 200–224)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `renderCameraRecordingStatus()` | 200–213 | 渲染录制状态到DOM | UI 渲染 | Low |
| `refreshCameraRecordingStatus()` | 214–218 | GET `/api/camera-recording/status` | API 调用 | Low |
| `toggleCameraRecording()` | 219–225 | POST `/api/camera-recording/toggle` | API 调用 + UI | Low |

### 3.6 Localization Clear (行 226–233)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `clearLocalization()` | 226–233 | POST `/api/localization/clear` + 更新 `state.localization` + 重绘场地图 | API + State + UI | Medium — 涉及 state 和 renderFieldMap |

### 3.7 Manual Move / Manual Yaw (行 323–367)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `positiveStep()` | 323–330 | 输入验证 >0 | 工具 | Low |
| `commandNumber()` | 331–334 | 命令数值格式化 | 工具 | Low |
| `bodyOffsetToLocalOffset()` | 335–343 | BODY→LOCAL 偏移转换 | 坐标计算 | Medium |
| `executeManualMove()` | 345–361 | POST `/api/manual-step-move` + confirm 弹窗 | API + UI | **High** — 触发后端 stop/clear/hold |
| `executeManualYaw()` | 362–367 | yaw 命令执行 | API | Medium |

### 3.8 Control Button Highlighting (行 368–405)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `setButtonActive()` | 368–372 | 按钮 active 状态 | DOM 工具 | Low |
| `updateControlHighlights()` | 373–405 | 同步 SEND/MODE/ARM/Controller 按钮高亮 | UI 同步 | Medium |

### 3.9 Field Heading (Legacy) (行 406–461)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `renderFieldHeading()` | 406–441 | 渲染 legacy 场地方向面板 + hint 动态文本 | UI 渲染 | Medium |
| `confirmFieldHeading()` | 442–461 | POST `/api/field-heading/confirm` + confirm 弹窗 | API + UI | **High** — 影响 yaw/origin 确认 |

### 3.10 Field Reference (New Panel) (行 463–521)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `fetchFieldReferenceStatus()` | 463–468 | GET `/api/field-reference/status` | API 调用 | Low |
| `renderFieldReference()` | 469–491 | 渲染 Field Reference 面板（18个字段） | UI 渲染 | Medium |
| `frPost()` | 492–502 | 通用 FR POST 包装 + hint 显示 | API 调用 | Low |
| `frSetManualHeading()` | 503–517 | POST `/api/field-reference/set-manual-heading` | API 调用 | Low |
| `gpsText()` | 518–521 | GPS 坐标格式化 | 工具 | Low |

### 3.11 Mission Stage Selector (Legacy) (行 522–545)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `renderMissionSteps()` | 522–545 | Mission stage 选择器渲染 / 切换 | UI 渲染 | Medium — 依赖 missionCatalog, execute |

### 3.12 Action Mission Utilities (行 557–598, 646–652)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `dispatchFromActionLab()` | 557–563 | 从 actionLab 中提取 dispatch 信息 | 数据提取 | Low |
| `countDispatchItems()` | 564–568 | 计数 dispatch items | 工具 | Low |
| `actionMissionDetail()` | 569–571 | 提取 action_mission.detail | 数据提取 | Low |
| `actionMissionBlackboard()` | 572–575 | 提取 blackboard | 数据提取 | Low |
| `inferActionMissionStepStatus()` | 576–591 | 推断步骤状态 (pending/running/done/failed/skipped) | 业务逻辑 | Medium |
| `failurePolicyLabel()` | 592–598 | on_failed 策略标签 | 工具 | Low |
| `getPathValue()` | 646–652 | 路径取值 | 工具 | Low |

### 3.13 Action Mission Rendering (行 599–644, 654–695, 696–745, 1780–1813, 1815–1822, 1896–1902, 1926–1937)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `actionMissionStatusLabel()` | 599–608 | 状态中文映射 | 工具 | Low |
| `renderActionMissionTimeline()` | 609–635 | 时间线表格渲染 | UI 渲染 | Medium |
| `renderBlackboardKeys()` | 636–645 | 黑板键渲染 | UI 渲染 | Low |
| `summarizeDropScan()` | 654–661 | 投放区扫描摘要 | 业务逻辑 | Medium |
| `summarizeDropTargets()` | 662–672 | 投放目标摘要 | 业务逻辑 | Medium |
| `summarizeReconReport()` | 673–684 | 侦察报告摘要 | 业务逻辑 | Medium |
| `renderActionMissionSummary()` | 685–695 | 结果摘要渲染 | UI 渲染 | Medium |
| `updateActionMissionAutoTickButton()` | 696–703 | 自动推进按钮状态 | UI 同步 | Low |
| `stopActionMissionAutoTick()` | 704–710 | 清除 auto tick timer | 定时器管理 | Low |
| `renderActionMissionStatus()` | 711–745 | 完整 Mission 状态渲染（含 SEND 警告、skip 按钮、detail JSON） | UI 渲染 | **High** — 写 lastActionMissionStatus/Result |
| `parseActionMissionInput()` | 1780–1785 | JSON parse（数组或对象） | 数据解析 | Medium |
| `normalizeActionMissionSteps()` | 1786–1813 | 步骤校验与规范化 | 数据校验 | Medium |
| `parseActionMissionSteps()` | 1815–1822 | 解析 + 校验 + 错误提示 | 数据入口 | Medium |
| `setActionMissionEditorValue()` | 1896–1903 | 设编辑器值 + 规范化 + timeline预览 | UI | Medium |
| `validateActionMissionJson()` | 1926–1933 | 校验 JSON + timeline预览 | UI | Low |
| `formatActionMissionJson()` | 1934–1938 | 格式化 JSON | UI | Low |

### 3.14 Action Mission Control (行 1824–1895, 1904–1924, 1939–1982)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `refreshActionMission()` | 1824–1829 | GET `/api/action-mission/status` | API | Low |
| `configureActionMission()` | 1830–1842 | POST `/api/action-mission/configure` | API + State | Medium |
| `startActionMission()` | 1843–1853 | POST `/api/action-mission/start` + confirm | API + UI | **High** |
| `stopActionMission()` | 1854–1860 | POST `/api/action-mission/stop` + stop auto tick | API | **High** |
| `resetActionMission()` | 1861–1867 | POST `/api/action-mission/reset` + stop auto tick | API | **High** |
| `tickActionMission()` | 1868–1873 | POST `/api/action-mission/tick` | API | **High** |
| `skipCurrentActionMissionStep()` | 1874–1895 | POST `/api/action-mission/skip-current` + 详细 confirm 弹窗 | API + UI | **High** — 语义敏感 |
| `loadActionMissionTemplates()` | 1904–1916 | GET `/api/action-mission/templates` + 渲染列表 | API + UI | Low |
| `loadActionMissionTemplate()` | 1917–1925 | GET `/api/action-mission/template/{name}` + 覆盖确认 | API + UI | Medium |
| `copyText()` | 1939–1951 | 剪贴板复制（clipboard API + fallback） | 工具 | Low |
| `toggleActionMissionAutoTick()` | 1952–1971 | setInterval 500ms 自动 tick | 定时器 | **High** — 不要改周期 |
| `loadActionMissionPreset()` | 1972–1983 | 内置 preset 加载 + 覆盖确认 | UI | Low |

### 3.15 Dashboard Summaries (行 746–784)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `renderDashboardSummaries()` | 746–771 | Dashboard Action/Mission/Dispatch/Recon 摘要 | UI 渲染 | Medium |
| `renderReconInspection()` | 772–784 | 侦察识别结果渲染 | UI 渲染 | Low |

### 3.16 Field Map Model (行 785–977)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `pointList()` | 785–793 | 点列表提取 | 工具 | Low |
| `swapPoint` | 794 | x/y 交换 | 坐标变换 | **High** — 坐标语义 |
| `fieldMapView` | 794–807 | 地图视图状态 (center, scale, drag, pinch) | 全局状态 | **High** — 触控/缩放 |
| `worldToCanvas()` | 808–815 | 世界→画布坐标 | 坐标变换 | **High** |
| `canvasToWorld()` | 816–823 | 画布→世界坐标 | 坐标变换 | **High** |
| `actionLocalizationDetail()` | 828–848 | 从 Action Lab 提取定位数据 | 数据提取 | Medium |
| `actionLocalizationDrone()` | 849–856 | 提取定位中的无人机坐标 | 数据提取 | Medium |
| `actionLocalizationTargets()` | 857–880 | 提取定位目标 | 数据提取 | Medium |
| `niceGridStep()` | 881–890 | 网格步长计算 | 工具 | Low |
| `fieldMapModel()` | 891–978 | 构建完整场地图数据模型（areas, survey points, targets, drone, localization, recon inspection） | 数据模型 | **High** — 所有绘制依赖此函数 |

### 3.17 Field Map Drawing (行 979–1293)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `resizeFieldCanvas()` | 979–991 | Canvas DPI 适配 | Canvas 工具 | Low |
| `drawFieldLabel()` | 992–998 | 绘制文字标签 | Canvas 绘制 | Low |
| `drawArea()` | 999–1012 | 绘制矩形区域 | Canvas 绘制 | Low |
| `drawCoordinateTicks()` | 1013–1096 | 绘制坐标轴/网格/刻度 | Canvas 绘制 | Medium |
| `drawField()` | 1097–1105 | 场地图主体（清空+坐标+三个区域） | Canvas 绘制 | **High** |
| `drawSurveyPoints()` | 1106–1122 | 绘制投放/侦察扫描点 | Canvas 绘制 | Medium |
| `drawDrone()` | 1123–1140 | 绘制无人机位置 | Canvas 绘制 | **High** |
| `drawTargets()` | 1141–1163 | 绘制投放/侦察目标（含recce状态颜色） | Canvas 绘制 | **High** |
| `drawLocalizationTargets()` | 1164–1192 | 绘制定位目标（含selected标红） | Canvas 绘制 | **High** — selected标红不能变 |
| `drawReconInspectionTargets()` | 1193–1212 | 绘制侦察识别目标 | Canvas 绘制 | Medium |
| `drawSingleViewTargets()` | 1213–1263 | 绘制单视角定位目标（含连线、十字、置信度） | Canvas 绘制 | Medium |
| `drawTargetCoordinateList()` | 1264–1294 | 绘制右上角坐标列表 | Canvas 绘制 | Low |

### 3.18 Field Map Interactions (行 1295–1458)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `fitFieldMapToDefaults()` | 1295–1310 | 自动适配视口 | 视图控制 | Medium |
| `setupFieldMapInteractions()` | 1311–1458 | 滚轮缩放、Pointer Events 拖拽/双指缩放、zoom/reset/clear按钮 | 交互控制 | **High** — 触控/拖拽不能变 |

### 3.19 Field Map Render Entry (行 1459–1489)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `renderFieldMap()` | 1459–1489 | 场地图总渲染入口：setup interactions→resize→model→draw→legend | 总入口 | **High** |

### 3.20 renderStatus (行 1490–1578)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `renderStatus()` | 1490–1578 | 主状态渲染入口：所有badges、aircraftInfo、targetInfo、statusCards、commandCards、events、renderFieldMap、renderActionLabStatus、renderActionMissionStatus、renderDashboardSummaries | **耦合中心** | **Critical** — 暂不拆分 |

### 3.21 Detections / Video Click (行 1579–1614)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `renderDetections()` | 1579–1590 | 检测列表渲染 + 锁定按钮绑定 | UI 渲染 | Low |
| `clickVideo()` | 1591–1614 | 视频点击→检测命中→target lock | 交互逻辑 | Medium |

### 3.22 Audit Log / Missions (行 1615–1627)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `loadAudit()` | 1615–1620 | GET `/api/audit` + 渲染 + 更新 `history` | API + UI + State | Low |
| `loadMissions()` | 1621–1627 | GET `/api/missions` + 更新 `missionCatalog` + 渲染 `missionSelect` | API + State + UI | Low |

### 3.23 Action Lab (行 1628–1776)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `loadActionLab()` | 1628–1641 | GET `/api/actions/list` + 按钮渲染 + auto select | API + UI | Medium |
| `cacheSelectedActionParams()` | 1642–1645 | 缓存参数到 `actionParamCache` | State | Low |
| `selectAction()` | 1646–1670 | 选择 Action：缓存→设编辑器值→hints→高亮 | UI + State | Medium |
| `refreshActionStatus()` | 1671–1677 | GET `/api/actions/status` + renderActionLabStatus + renderFieldMap | API + UI | Medium |
| `renderActionLabStatus()` | 1678–1746 | 完整 Action Lab 状态渲染（gate、highlights、JSON） | UI 渲染 | **High** |
| `nodeInside()` | 1747–1751 | DOM 包含检测 | 工具 | Low |
| `actionStatusJsonHasSelection()` | 1752–1757 | 检测 JSON pre 文本选区 | 工具 | Low |
| `updateActionStatusJson()` | 1758–1769 | 更新 JSON pre（保留选区+滚动位置） | UI 工具 | Low |
| `parseActionParams()` | 1770–1779 | 解析 Action params JSON | 数据解析 | Medium |

### 3.24 Action Lab Control (行 1984–2035)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `selectedActionIsRunning()` | 1984–1987 | 判断选中 Action 是否运行中 | State 查询 | Low |
| `toggleActionLabRun()` | 1988–1994 | 切换运行/停止 | 控制入口 | Medium |
| `startActionLabAction()` | 1995–2022 | POST `/api/actions/start` + send_actions + confirm逻辑 | API + UI | **Critical** — send_actions语义 |
| `stopActionLabAction()` | 2023–2028 | POST `/api/actions/stop` | API | Medium |
| `resetActionLabAction()` | 2029–2035 | POST `/api/actions/reset` + cache params | API + State | Medium |

### 3.25 Config Files (行 2036–2132)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `loadConfigFiles()` | 2036–2040 | GET `/api/config/files` + 按钮渲染 | API + UI | Low |
| `openConfig()` | 2074–2088 | GET `/api/config/file` + 编辑器填充 + apply按钮文字 | API + UI + State | Medium |
| `localDiff()` | 2089–2092 | 本地差异预览 | 工具 | Low |
| `setupActionStatusJsonCopyGuard()` | 2093–2115 | Action JSON pre 选区保护 | 事件绑定 | Low |
| `saveConfig()` | 2116–2126 | PUT `/api/config/file` + confirm 弹窗 + diff | API + UI | **High** — 触发重启/重连 |
| `actionForPath()` | 2127–2132 | 路径→action 映射 (apply/reconnect/restart/save) | 业务逻辑 | **High** — 映射不能改 |

### 3.26 Init / Event Binding (行 2133–2293)

| Block | Line range | Main functions | Responsibility | Risk |
|-------|-----------|---------------|---------------|------|
| `init()` | 2133–2292 | 所有初始化：视频URL、事件绑定（~100行）、completions加载、5个并行数据加载、startStatusUpdates | 总入口 | **Critical** — 暂不拆分 |

---

## 4. Global State Inventory

| Variable | Line | Written by | Read by | WU-2 candidate | Must remain global |
|----------|------|-----------|---------|---------------|-------------------|
| `state` | 2 | `renderStatus()` L1491 | ~50+ functions | Yes | Yes (耦合中心) |
| `completions` | 3 | `init()` L2288 | `init()` (Tab/ArrowUp/Down) | Yes | Yes |
| `history` | 4 | `loadAudit()` L1617, `init()` L2166 | `init()` (ArrowUp/Down) | Yes | Yes |
| `historyIndex` | 5 | `init()` L2166,2176,2178 | `init()` (ArrowUp/Down) | Yes | Yes |
| `currentConfigPath` | 6 | `openConfig()` L2076 | `saveConfig()`, `restoreConfig`, `actionForPath()` | Yes | Yes |
| `currentOriginal` | 7 | `openConfig()` L2077, `saveConfig()` L2122 | `localDiff()`, `previewConfig` | Yes | Yes |
| `missionCatalog` | 8 | `loadMissions()` L1622 | `renderMissionSteps()` | Yes | Yes |
| `actionSpecs` | 9 | `loadActionLab()` L1630 | `selectAction()`, `loadActionLab()` | Yes | Yes |
| `selectedActionName` | 10 | `selectAction()` L1650 | `cacheSelectedActionParams()`, `selectAction()`, `startActionLabAction()`, `toggleActionLabRun()`, `selectedActionIsRunning()`, `renderActionLabStatus()`, `init()` | Yes | Yes |
| `actionParamCache` | 11 | `cacheSelectedActionParams()` L1644, `selectAction()` L1652 | `selectAction()`, `resetActionLabAction()` | Yes | Yes |
| `latestActionLab` | 12 | `renderActionLabStatus()` L1680, `renderStatus()` L1575 | `renderDashboardSummaries()`, `dispatchFromActionLab()`, `fieldMapModel()` 等 | Yes | Yes |
| `actionStatusJsonSelecting` | 13 | `setupActionStatusJsonCopyGuard()` | `updateActionStatusJson()` | Yes | Yes |
| `currentActionMission` | 14 | `configureActionMission()` L1833, `setActionMissionEditorValue()` L1899, `validateActionMissionJson()` L1929 | — (only write) | Yes | Yes |
| `currentActionMissionSteps` | 15 | `configureActionMission()` L1834, `setActionMissionEditorValue()` L1900, `validateActionMissionJson()` L1930 | `renderActionMissionStatus()` L742 | Yes | Yes |
| `lastActionMissionStatus` | 16 | `renderActionMissionStatus()` L715, `skipCurrentActionMissionStep()` L1891 | `skipCurrentActionMissionStep()`, `toggleActionMissionAutoTick()`, `copyText()`, `setActionMissionEditorValue()`, `validateActionMissionJson()` | Yes | Yes |
| `lastActionMissionResult` | 17 | `renderActionMissionStatus()` L717 | `copyText()` | Yes | Yes |
| `actionMissionAutoTickTimer` | 18 | `toggleActionMissionAutoTick()` L1957, `stopActionMissionAutoTick()` L706 | `stopActionMissionAutoTick()`, `toggleActionMissionAutoTick()`, `updateActionMissionAutoTickButton()` | Yes | Yes |
| `latestCameraRecording` | 19 | `renderCameraRecordingStatus()` L201 | `renderCameraRecordingStatus()` L202 | Yes | Yes |
| `fallbackStageModes` | 20 | — (const) | `renderMissionSteps()` L535 | No (constant) | No |
| `ACTION_SAFETY_HINTS` | 21 | — (const) | `selectAction()` L1666 | No (constant) | No |
| `ACTION_ZH_LABELS` | 30 | — (const) | `actionDisplayName()` L263 | No (constant) | No |
| `DEFAULT_ACTION_MISSION_STEPS` | 45 | — (const) | `loadActionMissionPreset()`, `init()` L2251 | No (constant) | No |
| `actionMissionPresets` | 72 | — (const) | `loadActionMissionPreset()` | No (constant) | No |
| `FIELD_DEFAULTS` | 160 | — (const) | `fieldMapModel()`, `fitFieldMapToDefaults()` | No (constant) | No |
| `fieldMapView` | 794 | `setupFieldMapInteractions()`, `fitFieldMapToDefaults()` | `worldToCanvas()`, `canvasToWorld()`, all draw functions | Yes | Yes (触控状态) |

---

## 5. API Inventory

### 5.1 System / Status

| API | Method | Caller (line) | Purpose | Risk | Move target |
|-----|--------|--------------|---------|------|-------------|
| `/api/status` | GET | `startStatusUpdates()` L2044 | 状态轮询 fallback | Low | WU-1 `api_client.js` |
| `/ws/status` | WS | `startStatusUpdates()` L2065 | WebSocket 状态推送 | Low | WU-1 (WS wrapper) |
| `/api/audit?limit=100` | GET | `loadAudit()` L1616 | 审计日志 | Low | WU-1 |
| `/api/events` | GET | (route exists, not called from app.js) | 事件列表 | — | Not used |
| `/api/commands/completions` | GET | `init()` L2288 | 命令补全列表 | Low | WU-1 |
| `/api/commands/execute` | POST | `execute()` L193 | 执行命令 | Medium | WU-1 |

### 5.2 Missions

| API | Method | Caller (line) | Purpose | Risk | Move target |
|-----|--------|--------------|---------|------|-------------|
| `/api/missions` | GET | `loadMissions()` L1622 | Mission 目录 | Low | WU-1 |

### 5.3 Actions (Action Lab)

| API | Method | Caller (line) | Purpose | Risk | Move target |
|-----|--------|--------------|---------|------|-------------|
| `/api/actions/list` | GET | `loadActionLab()` L1629 | Action 规格列表 | Low | WU-1 |
| `/api/actions/status` | GET | `refreshActionStatus()` L1672 | Action 运行状态 | Low | WU-1 |
| `/api/actions/start` | POST | `startActionLabAction()` L2014 | 启动 Action | **High** — send_actions | WU-1 (不改语义) |
| `/api/actions/stop` | POST | `stopActionLabAction()` L2024 | 停止 Action | Medium | WU-1 |
| `/api/actions/reset` | POST | `resetActionLabAction()` L2031 | 重置 Action | Medium | WU-1 |

### 5.4 Action Mission

| API | Method | Caller (line) | Purpose | Risk | Move target |
|-----|--------|--------------|---------|------|-------------|
| `/api/action-mission/status` | GET | `refreshActionMission()` L1825 | Mission 状态 | Low | WU-1 |
| `/api/action-mission/templates` | GET | `loadActionMissionTemplates()` L1908 | 模板列表 | Low | WU-1 |
| `/api/action-mission/template/{name}` | GET | `loadActionMissionTemplate()` L1921 | 加载模板 | Low | WU-1 |
| `/api/action-mission/configure` | POST | `configureActionMission()` L1835 | 配置步骤 | Medium | WU-1 |
| `/api/action-mission/start` | POST | `startActionMission()` L1849 | 启动 | **High** | WU-1 |
| `/api/action-mission/stop` | POST | `stopActionMission()` L1856 | 停止 | **High** | WU-1 |
| `/api/action-mission/reset` | POST | `resetActionMission()` L1863 | 重置 | **High** | WU-1 |
| `/api/action-mission/tick` | POST | `tickActionMission()` L1869 | 推进 | **High** | WU-1 |
| `/api/action-mission/skip-current` | POST | `skipCurrentActionMissionStep()` L1886 | 跳过当前阶段 | **High** — 语义敏感 | WU-1 |

### 5.5 Field Heading / Field Reference

| API | Method | Caller (line) | Purpose | Risk | Move target |
|-----|--------|--------------|---------|------|-------------|
| `/api/field-heading/confirm` | POST | `confirmFieldHeading()` L455 | 确认场地方向 | Medium | WU-1 |
| `/api/field-reference/status` | GET | `fetchFieldReferenceStatus()` L465 | FR 状态 | Low | WU-1 |
| `/api/field-reference/mark-origin` | POST | `init()` L2157 (frPost) | 记录原点A | Low | WU-1 |
| `/api/field-reference/mark-forward` | POST | `init()` L2158 (frPost) | 记录前向点B | Low | WU-1 |
| `/api/field-reference/use-current-yaw` | POST | `init()` L2159 (frPost) | 使用当前 yaw | Low | WU-1 |
| `/api/field-reference/set-manual-heading` | POST | `frSetManualHeading()` L507 | 手动设 heading | Low | WU-1 |
| `/api/field-reference/confirm` | POST | `init()` L2161 (frPost) | 确认 FR | **High** — sync runtime | WU-1 |
| `/api/field-reference/reset` | POST | `init()` L2162 (frPost) | 重置 | Medium | WU-1 |
| `/api/field-reference/freeze` | POST | `init()` L2163 (frPost) | 冻结 | Low | WU-1 |

### 5.6 Manual / Localization / Camera / Config / Services

| API | Method | Caller (line) | Purpose | Risk | Move target |
|-----|--------|--------------|---------|------|-------------|
| `/api/manual-step-move` | POST | `executeManualMove()` L353 | 手动步进 | **High** | WU-1 |
| `/api/localization/clear` | POST | `clearLocalization()` L227 | 清空定位 | Medium | WU-1 |
| `/api/yolo/stream` | GET | `init()` L2134 | YOLO 视频流配置 | Low | WU-1 |
| `/api/camera-recording/status` | GET | `refreshCameraRecordingStatus()` L215 | 录制状态 | Low | WU-1 |
| `/api/camera-recording/toggle` | POST | `toggleCameraRecording()` L220 | 切换录制 | Low | WU-1 |
| `/api/config/files` | GET | `loadConfigFiles()` L2037 | 配置文件列表 | Low | WU-1 |
| `/api/config/file` | GET | `openConfig()` L2075 | 读取配置 | Medium | WU-1 |
| `/api/config/file` | PUT | `saveConfig()` L2119 | 保存配置 | **High** — 触发重启 | WU-1 |
| `/api/config/restore` | POST | `init()` L2237 (`restoreConfig`) | 恢复配置 | **High** — 触发重启 | WU-1 |
| `/api/services/telemetry/reconnect` | POST | `init()` L2240 | 重连通信 | **High** | WU-1 |
| `/api/services/yolo/restart` | POST | `init()` L2241 | 重启 YOLO | **High** | WU-1 |
| `/api/services/app/restart` | POST | `init()` L2242 | 重启 App | **High** | WU-1 |

N.B.: `/api/yolo/target/{action}` (server.py L437) exists in the backend but is **NOT** called by the current `app.js` — the frontend uses `execute("target lock ...")` through `/api/commands/execute` instead.

---

## 6. DOM Dependency Inventory

### 6.1 Dashboard

- **Badges**: `sourceBadge`, `linkBadge`, `sendBadge`, `armBadge`, `modeBadge`, `batteryBadge`, `altitudeBadge`, `actionBadge`, `missionBadge`
- **Target summary**: `targetInfo` (infoRows), `targetCurrent`, `detections`, `frameId`, `detCount`
- **Aircraft info**: `aircraftInfo` (infoRows)
- **Status cards**: `statusCards` (cards), `commandCards` (cards)
- **Events**: `events`
- **Legacy mission**: `missionSwitch`, `missionSelect`, `stageOverride`, `missionSteps`, `missionName`, `missionStage`, `stageController`, `holdReason`

### 6.2 Video

- **Video**: `video`, `videoOffline`, `hitCanvas`, `videoHint`
- **Recording**: `cameraRecordToggle`, `cameraRecordStatus`

### 6.3 Field Map

- **Canvas**: `fieldMap`, `fieldMapEmpty`
- **Controls**: `fieldMapZoomIn`, `fieldMapZoomOut`, `fieldMapReset`, `clearLocalization`
- **Legend**: `fieldMapLegend`
- **Interaction**: canvas `data-map-ready`, pointer events via `setupFieldMapInteractions()`

### 6.4 Action Lab (actionsPage)

- **Buttons**: `actionButtons` (dynamically generated), `actionDryRunStart`, `actionDispatchStart`, `actionStop`, `actionReset`, `actionRefresh`, `actionRunToggle`
- **Params**: `actionParams`, `actionParamHint`
- **Safety**: `actionSafetyHint`
- **Status**: `actionState`, `actionSelected`, `actionRunningAction`, `actionRunning`, `actionReason`, `actionDone`, `actionFailed`, `actionDryRun`
- **Gate**: `actionGateRequested`, `actionGateEffective`, `actionGateSystemSend`, `actionGateDryRun`, `actionGateSentCount`, `actionGateSkippedCount`, `actionGateErrorCount`, `actionGateNote`
- **Highlights**: `actionHighlights`, `actionSwitchHint`
- **JSON**: `actionStatusJson`

### 6.5 Action Mission (actionMissionPage)

- **Templates**: `actionMissionTemplateList`, `[data-action-mission-template]`, `actionMissionLoadCustom`, `actionMissionValidate`, `actionMissionPresets` (`[data-action-mission-preset]`)
- **Controls**: `actionMissionConfigure`, `actionMissionStart`, `actionMissionTick`, `actionMissionSkipCurrent`, `actionMissionAutoTick`, `actionMissionStop`, `actionMissionReset`, `actionMissionRefresh`
- **Status**: `actionMissionSystemSend`, `actionMissionEnabled`, `actionMissionRunning`, `actionMissionDone`, `actionMissionFailed`, `actionMissionIndex`, `actionMissionCurrent`, `actionMissionReason`, `actionMissionSendWarning`
- **Timeline**: `actionMissionTimeline`
- **Blackboard**: `actionMissionBlackboardKeys`
- **Results**: `actionMissionResults`
- **Editor**: `actionMissionSteps`, `actionMissionFormatJson`, `actionMissionCopyJson`, `actionMissionCopyStatus`, `actionMissionCopyResult`, `actionMissionDetail`

### 6.6 Flight Safety (flightSafetyPage)

- **Flight controls**: `takeoffAltitude`, `takeoffButton`, `sendToggle`, `sendToggleState`
- **Mode/arm buttons**: `[data-command]`, `[data-mode]`, `[data-arm-state]`, `[data-source]`
- **Field Heading**: `fieldHeadingStatus`, `fieldHeadingCurrentYaw`, `fieldHeadingPreArmYaw`, `fieldHeadingConfirmedYaw`, `fieldHeadingDelta`, `fieldHeadingOrigin`, `fieldHeadingCurrentField`, `fieldHeadingConfirmed`, `fieldHeadingSource`, `fieldHeadingTime`, `fieldHeadingAttitudeValid`, `confirmFieldHeading`, `fieldHeadingHint`
- **Field Reference**: `frConfirmed`, `frFrozen`, `frOriginSource`, `frHeadingSource`, `frHeadingDeg`, `frOriginLocal`, `frOriginGps`, `frForwardGps`, `frDistance`, `frWarnings`, `frGpsFix`, `frGpsEphEpv`, `frGpsValid`, `frHasLocal`, `frActiveSource`, `frSynced`, `frMarkOrigin`, `frMarkForward`, `frUseCurrentYaw`, `frManualHeadingDeg`, `frSetManualHeading`, `frConfirm`, `frReset`, `frFreeze`, `frHint`
- **Payload Release**: `payloadReleaseSelect`, `payloadReleaseRun`
- **Controller switches**: `[data-controller-row]` (gimbal/body/approach/all)
- **Manual move**: `moveStep`, `yawStep`, `[data-manual-move]`, `[data-manual-yaw]`
- **Flight Command**: `flightCommandInput`, `flightSendCommand`, `flightCompletionHint`

### 6.7 Config / Logs (configLogsPage)

- **Config files**: `configFiles`
- **Editor**: `editingPath`, `yamlEditor`, `previewConfig`, `saveConfig`, `applyConfig`, `restoreConfig`, `configDiff`, `configStatus`
- **Services**: `reconnectTelemetry`, `restartYolo`, `restartApp`
- **Audit log**: `auditLog`
- **CLI**: `commandInput`, `sendCommand`, `completionHint`

---

## 7. Polling and Status Refresh

### 7.1 Primary: WebSocket `/ws/status`

- Established in `startStatusUpdates()` L2065
- On `message` → calls `renderStatus(JSON.parse(event.data))` directly
- On `open` → starts Action timer (1000ms) + Field Reference polling (2000ms)
- On `error` / `close` → fallback to polling

### 7.2 Fallback: HTTP `/api/status` Polling

- `startFallback()` L2057–2063
- Immediate poll + setInterval 500ms
- Also starts Action timer + FR polling

### 7.3 Action Status Timer

- `setInterval(refreshActionStatus, 1000)` — L2049
- `refreshActionStatus()` (L1671–1677) calls `renderActionLabStatus()` then `renderFieldMap(state)`, forming the Action Lab status refresh → field map redraw coupling

### 7.4 Field Reference Polling

- `setInterval(fetchFieldReferenceStatus, 2000)` — L2055
- Only updates FR panel, does NOT call `renderFieldMap`

### 7.5 Action Mission Auto Tick

- `setInterval(tickActionMission, 500)` — L1957
- Only ticks if `lastActionMissionStatus.running` is true
- Stops on done/failed

### 7.6 Refresh Coupling Summary

| Poll/Source | Period | Calls renderFieldMap | Writes completionHint | Notes |
|-------------|--------|---------------------|-----------------------|-------|
| WebSocket msg | push | Yes (via `renderStatus`) | No | Primary path |
| `/api/status` fallback | 500ms | Yes (via `renderStatus`) | On error only | Fallback |
| Action status | 1000ms | Yes (via `refreshActionStatus`) | On error only | Always active |
| Field Reference | 2000ms | No | No | Always active |
| Mission auto tick | 500ms | No (indirect via status push) | On error only | Only when running |

---

## 8. Field Heading / Field Reference Analysis

### 8.1 Field Heading (Legacy)

**DOM**: `fieldHeadingStatus` (div with 10 field rows), `confirmFieldHeading`, `fieldHeadingHint`

**Functions**:
- `renderFieldHeading(next)` L406–441 — fills all fieldHeading DOM elements from `state.field_heading`
- `confirmFieldHeading()` L442–461 — POST `/api/field-heading/confirm`

**Behavior**:
- Reads `state.field_heading` (populated by `renderStatus` → `state = next`)
- Confirm button validates `attitude_valid`, then shows confirm dialog, then POSTs
- On success, updates `state.field_heading` from response and re-renders
- Hint dynamically shows: attitude invalid → local position invalid → unconfirmed → confirmed with delta
- **Does NOT send MAVLink** — backend only records internal yaw and LOCAL_NED origin

**Risk**: Confirm popup text must not change; delta coloring thresholds (≤2° ok, ≤8° warning, >8° danger) must not change.

### 8.2 Field Reference (New Panel)

**DOM**: `fieldReferenceStatus` (div with 16 field rows), `fr*` buttons (7 buttons + 1 input)

**Functions**:
- `fetchFieldReferenceStatus()` L463–468 — GET `/api/field-reference/status`
- `renderFieldReference(data)` L469–491 — fills all `fr*` DOM elements
- `frPost(url)` L492–502 — generic POST wrapper, updates `frHint`
- `frSetManualHeading()` L503–517 — POST `/api/field-reference/set-manual-heading`
- `gpsText(lat, lon)` L518–521 — GPS formatting

**Behavior**:
- Polled every 2000ms independently
- 操作只改后端状态，不发送 MAVLink
- Confirm (`frPost("/api/field-reference/confirm")`) syncs to runtime context
- UI depends on `fr*` DOM ids exclusively (separate from legacy field heading)

**Key distinctions from legacy**:
- FR uses GPS A-B pair or current yaw or manual heading
- Legacy uses pre-arm yaw / manual confirm
- Both coexist — `active_source` shows which is in effect
- FR confirm calls `builder.confirm_field_reference()` which overwrites `field_heading_confirmed` / origin data

**Risk**: Cannot change coordinate conversion semantics. The `localPointToField()` function (L283–298) uses `next.field_transform` which is the FR-confirmed transform.

---

## 9. Field Map Analysis

### 9.1 State

- `fieldMapView` L794–807: `centerX`, `centerY`, `scale`, `minScale`(4), `maxScale`(120), `isDragging`, drag/pinch state
- `FIELD_DEFAULTS` L160–177: bounds, areas, survey points
- `state` (passed as `next` to `renderFieldMap`)

### 9.2 Coordinate System

- `worldToCanvas(x, y, rect, view)` L808–815: world coords → canvas coords
  - World origin at canvas center, x axis points left (因为 `originX - Number(x) * view.scale`)
  - y axis is standard: `originY - Number(y) * view.scale` (higher y → up on screen → y decreases)
- `canvasToWorld(screenX, screenY, rect, view)` L816–823: inverse
- Note `swapPoint` L794: swaps x,y (vertical ↔ horizontal for display convenience; data has x=东, y=北, but display maps x→horizontal)

### 9.3 Drawing Pipeline

`renderFieldMap(next)` L1459–1489 → `fieldMapModel(next)` → all `draw*` functions in order:
1. `drawField(ctx, model)` — axes, grid, areas (takeoff/drop/recce)
2. `drawSurveyPoints(ctx, model)` — scan points
3. `drawTargets(ctx, model)` — drop/recce targets
4. `drawLocalizationTargets(ctx, model)` — localized objects with selected (red) highlight
5. `drawReconInspectionTargets(ctx, model)` — recon inspection results
6. `drawSingleViewTargets(ctx, model)` — single-view localization
7. `drawDrone(ctx, model)` — drone position
8. `drawTargetCoordinateList(ctx, model)` — coordinate table overlay

### 9.4 Interactions

- Mouse wheel zoom (L1316–1331)
- Pointer events for drag (single finger) and pinch zoom (two fingers) (L1362–1438)
- Zoom in/out/reset buttons (L1441–1452)
- Clear localization button (L1453–1457)

### 9.5 Risks

- **地图方向、坐标轴**：x 在画布上向左，y 在画布上向上 — 不能变
- **缩放范围**：minScale=4, maxScale=120 — 不能变
- **触控拖拽**：pointer events with setPointerCapture — 不能变
- **selected drop target 标红**：`isSelectedDropTarget()` L309–321 → `drawLocalizationTargets()` L1172–1173 红色填充 — 不能变
- **坐标显示**：localization / single view / recon inspection 坐标显示格式不能变
- **坐标变换**：`localPointToField()` / `pointForFieldMap()` / `swapPoint` — 不能改变转换语义

---

## 10. Action Lab Analysis

### 10.1 Core Flow

1. `loadActionLab()` L1628: GET `/api/actions/list` → populate `actionSpecs`
2. `selectAction(name)` L1646: cache params → set editor → show hints
3. `startActionLabAction(sendActions)` L1995:
   - `sendActions=false` → Dry Run (no confirm dialog)
   - `sendActions=true` → Shows confirm dialog:
     > "这会请求 Action 实发。如果系统 SEND=OFF，飞控命令仍不会发送。如果系统 SEND=ON，local_position/body_velocity/set_servo 会实际发送..."
   - POST `/api/actions/start` with `{name, params, send_actions}`
4. `stopActionLabAction()` L2023: POST `/api/actions/stop`
5. `resetActionLabAction()` L2029: POST `/api/actions/reset` + cache params

### 10.2 Send_actions Semantics

```
send_actions = false → dry_run_only = true → 后端不发送飞控命令
send_actions = true → dry_run_only = false → 后端请求实际发送（仍受 System SEND 门控）
```

### 10.3 Gate Display (renderActionLabStatus L1678–1746)

- `actionGateRequested`: `send_actions_requested`
- `actionGateEffective`: `send_actions_effective`
- `actionGateSystemSend`: `state.controllers.send_commands`
- `actionGateDryRun`: `dry_run_only`
- `actionGateSentCount/SkippedCount/ErrorCount`: from dispatch

### 10.4 Key Risks

- **不要改变 send_actions 语义**
- **不要改变 send_commands 语义** (System SEND 是独立的系统级门)
- **不要改变 dry_run_only 显示语义**
- **不要改变 `startActionLabAction` 的确认弹窗语义** (sendActions=true 时必须弹窗)
- **不要改 ActionDispatcher**
- **不要改后端 API**
- `refreshActionStatus()` 在 L1675 行调用 `renderFieldMap(state)`，形成 Action Lab 状态刷新与场地图刷新的耦合；`renderActionLabStatus()` 本身只负责渲染 Action Lab UI，不直接调用场地图

---

## 11. Action Mission Analysis

### 11.1 Core Flow

1. **Configure**: `configureActionMission()` L1830 → parse → normalize → POST `/api/action-mission/configure`
2. **Start**: `startActionMission()` L1843 → confirm dialog → POST `/api/action-mission/start`
3. **Tick**: `tickActionMission()` L1868 → POST `/api/action-mission/tick` — executes next step's Action
4. **Skip**: `skipCurrentActionMissionStep()` L1874 → detailed confirm dialog showing current index/action → POST `/api/action-mission/skip-current`
5. **Stop/Reset**: stop auto tick → POST stop/reset

### 11.2 Auto Tick

- `toggleActionMissionAutoTick()` L1952: setInterval 500ms
- Only ticks when `lastActionMissionStatus.running`
- Stops on error, done, or failed

### 11.3 Key Data

- `DEFAULT_ACTION_MISSION_STEPS` L45–71: default goto→release template
- `actionMissionPresets` L72–159: 5 built-in presets (dry_goto, payload_release_test, goto_payload_release, survey_area_dry, target_lock_test)
- Templates loaded from server: 3 named templates (drop_two_targets_v1, rescue_2026_full_auto, recon_inspect_5_targets_stepwise_v1)

### 11.4 Skip-current Behavioral Notes

From the confirm dialog (L1878–1884):
> "该操作会停止当前 Action，清理连续控制/LOCAL_POSITION，并尝试保持当前位置，然后进入下一阶段。不会清空 blackboard。"

### 11.5 Key Risks

- **不要改 mission JSON 格式** (steps array, each step has name/params/save_as/label/on_failed)
- **不要改 template payload**
- **不要改 tick/skip/current_index 语义**
- **不要改 auto tick 周期** (500ms)
- **不要改 skip-current 对后端 stop/clear/hold 的行为**
- `lastActionMissionStatus` / `lastActionMissionResult` 全局状态写入必须保持

---

## 12. Config / Logs / Services Analysis

### 12.1 Config Flow

1. `loadConfigFiles()` L2036: GET `/api/config/files` → button list
2. `openConfig(path)` L2074: GET `/api/config/file?path=` → fill editor
3. `saveConfig(action)` L2116: PUT `/api/config/file` with `{content, action}`
4. `restoreConfig` L2234–2239: POST `/api/config/restore` → re-open

### 12.2 Action Mapping

`actionForPath()` L2127–2132:
```
missions/* → "apply"
config/telemetry.yaml → "reconnect"
config/yolo.yaml → "restart"
config/app.yaml → "restart"
other → "save"
```

### 12.3 Service Operations

- `reconnectTelemetry` L2240: POST `/api/services/telemetry/reconnect` — confirm required
- `restartYolo` L2241: POST `/api/services/yolo/restart` — confirm required
- `restartApp` L2242: POST `/api/services/app/restart` — confirm required with special warning

### 12.4 Key Risks

- **保存 config/app.yaml、config/yolo.yaml、config/telemetry.yaml 可能触发重启/重连** — confirm 弹窗文本不能改
- **不能改变 `actionForPath` 映射**
- **不能改变 confirm 弹窗**（applyConfig 文本动态显示当前操作）

---

## 12b. Video Panel Analysis

### Data Flow

1. **YOLO stream URL**: `init()` L2134 calls `json("/api/yolo/stream")` → returns `{port: 8081, path: "/video/yolo.mjpeg"}` → constructs `http://<host>:<port>/video/yolo.mjpeg`
2. **Video element**: `<img id="video">` in `index.html` L37, src set by `init()`
3. **Offline overlay**: `<div id="videoOffline">` L39, shown when video fails to load
4. **Hit canvas**: `<canvas id="hitCanvas">` L38, overlays video for click detection
5. **Recording**: `cameraRecordToggle` / `cameraRecordStatus` (L42–43)

### Video Load / Error Handling (L2136–2141)

```
$("video").onload  → hide videoOffline overlay
$("video").onerror → show videoOffline overlay, retry after 1500ms with ?retry=<timestamp>
```

The 1.5-second retry with cache-busting timestamp is intentional and must not change.

### Click Target Lock (L1591–1614)

`clickVideo(event)`:
1. Reads `state.scene.image_width/height`
2. Computes display coordinates accounting for aspect-ratio letterboxing
3. Maps click position to image coordinates
4. Tests `scene.detections` bounding boxes for hit (inclusive: `x >= d.x1 && x <= d.x2`)
5. Sorts hits by area (smallest first) → locks smallest matching target
6. Falls back to `$("completionHint")` message if no hit

### Camera Recording (L200–224)

- `renderCameraRecordingStatus(payload)` L200: updates `cameraRecordToggle` text ("开始录制"/"停止录制") + `cameraRecordStatus` text
- `refreshCameraRecordingStatus()` L214: GET `/api/camera-recording/status`
- `toggleCameraRecording()` L219: POST `/api/camera-recording/toggle`
- `latestCameraRecording` (L19): global state `{recording, path, message}`
- Recording status refreshed once on init (L2290) and toggled via button (L2215–2220)

### Video Panel Risks

- Video element `onload`/`onerror` handlers set in `init()` — must remain attached
- `hitCanvas.onclick = clickVideo` set in `init()` L2142 — must remain attached
- 1.5s retry timer with `Date.now()` cache busting must not change
- `clickVideo` depends on `state.scene` (set by `renderStatus`) — must keep coupling
- Recording toggle uses `/api/camera-recording/toggle` — URL/payload must not change

### Video Panel Verification (if split in future)

1. 视频正常加载时 overlay 不显示
2. 视频断开时 overlay 显示
3. onerror 后 1.5 秒重试仍存在
4. 点击视频画面仍能触发目标锁定/命令路径
5. recording status 能刷新
6. recording toggle 按钮行为不变

---

## 13. Proposed Split Targets

建议目标文件（WU-1 不全拆，分期执行）：

```
web_ui/static/js/api_client.js      — WU-1: 所有 API fetch 调用
web_ui/static/js/app_state.js       — WU-2: 全局状态变量
web_ui/static/js/format_utils.js    — WU-2: 纯格式化/工具函数
web_ui/static/js/dom_utils.js       — WU-2: DOM 渲染辅助
web_ui/static/js/status_dashboard.js— 暂不拆: renderStatus 耦合中心
web_ui/static/js/video_panel.js     — 暂不拆: 轻量
web_ui/static/js/field_reference.js — WU-3A: Field Heading/Reference
web_ui/static/js/field_map.js       — 暂不拆: 坐标复杂
web_ui/static/js/action_lab.js      — WU-3B: Action Lab
web_ui/static/js/action_mission.js  — 暂不拆: 依赖 Action Lab
web_ui/static/js/config_panel.js    — 暂不拆
web_ui/static/js/log_panel.js       — 暂不拆
web_ui/static/js/manual_controls.js — 暂不拆: manual-step-move 语义敏感
web_ui/static/js/main.js            — 最终: init() + 事件绑定
```

---

## 14. Recommended Phases

### WU-1: Extract `api_client.js`

只抽 API 调用包装。低风险。

建议导出一个全局对象：

```js
window.UavApi = {
  request: json,               // generic fetch
  getStatus,
  executeCommand,
  getAudit,
  getMissions,
  listActions,
  getActionStatus,
  startAction,
  stopAction,
  resetAction,
  getActionMissionStatus,
  getActionMissionTemplates,
  getActionMissionTemplate,
  configureActionMission,
  startActionMission,
  stopActionMission,
  resetActionMission,
  tickActionMission,
  skipCurrentActionMission,
  getFieldHeadingStatus,       // same as getStatus; field_heading is in status snapshot
  confirmFieldHeading,
  getFieldReferenceStatus,
  markFieldReferenceOrigin,
  markFieldReferenceForward,
  useCurrentYawForFieldReference,
  setManualFieldHeading,
  confirmFieldReference,
  resetFieldReference,
  freezeFieldReference,
  getConfigFiles,
  getConfigFile,
  saveConfigFile,
  restoreConfigFile,
  getYoloStreamConfig,
  getCameraRecordingStatus,
  toggleCameraRecording,
  clearLocalization,
  manualStepMove,
  reconnectTelemetry,
  restartYolo,
  restartApp,
  getCommandCompletions,
};
```

WU-1 限制（只允许抽 API wrapper，不允许改变行为语义）：
- 不改 API URL
- 不改 HTTP method
- 不改 request body
- 不改 response handling 语义
- 不改轮询频率
- 不改按钮行为
- 不改 app.js 主流程
- `index.html` 只允许增加 `<script src="/static/js/api_client.js">` 引用

WU-1 明确不改：
1. WebSocket / fallback polling 频率
2. `/ws/status` 建连、失败、fallback 逻辑
3. `/api/status` 响应处理语义
4. Field Reference 坐标转换语义
5. Field Reference confirm / freeze / reset 行为
6. Field Heading legacy confirm 行为
7. Action Mission JSON 格式
8. Action Mission configure/start/stop/reset/tick/skip-current 语义
9. Action Lab send_actions / send_commands / dry_run 显示和请求语义
10. 任何后端 API URL、method、request body、response field

WU-1 验证：
```bash
python -m compileall app web_ui
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

手动验证 checklist (10 items):
1. Web UI 能打开
2. `/api/status` 正常
3. `/ws/status` 正常或 fallback 正常
4. Dashboard 刷新
5. Action Lab list/status/start dry-run/stop/reset 正常
6. Action Mission 配置/校验/状态刷新正常
7. Field Reference status/按钮响应正常
8. 视频 URL 正常
9. Config 文件列表和打开正常
10. 浏览器 console 无新增错误

### WU-2: Extract `app_state.js` + `format_utils.js` + `dom_utils.js`

只抽纯状态和无副作用工具。

可抽：
- `app_state.js`: 所有顶层 `let`/`const` 状态变量 + `fieldMapView` + 常量
- `format_utils.js`: `stamp`, `escapeHtml`, `num`, `degNum`, `xyzText`, `boolText`, `actionDisplayName`, `actionNameWithZh`, `finiteNumber`, `gpsText`, `commandNumber`
- `dom_utils.js`: `$`, `setBadge`, `cards`, `infoRows`, `setOptionalText`, `renderSummaryRows`

WU-2 禁止：
- 不抽 Action Lab start/stop
- 不抽 Field Map 坐标换算
- 不抽 Field Reference confirm
- 不抽 status polling
- 不改 init event binding

WU-2 如果抽 `app_state.js` / `format_utils.js` / `dom_utils.js`，必须额外验证：
1. Field Map 缩放按钮正常
2. Field Map 鼠标拖拽正常
3. Field Map 触控拖拽正常
4. target / localization / single-view / recon 标记仍正常显示
5. selected drop target 标红逻辑不变
6. Action Mission preset 下拉可用
7. Action Mission template 加载可用
8. Action Mission JSON format/copy/parse 不变
9. Config panel 打开文件、编辑、保存确认弹窗不变
10. 浏览器 console 无新增错误

### WU-3A: Extract `field_reference.js` (建议优先)

可包含：
- `renderFieldHeading` (L406–441)
- `confirmFieldHeading` (L442–461)
- `fetchFieldReferenceStatus` (L463–468)
- `renderFieldReference` (L469–491)
- `frPost` (L492–502)
- `frSetManualHeading` (L503–517)
- `gpsText` (L518–521)
- `init()` 中的 FR 按钮绑定 (L2157–2163)

WU-3A 禁止：
- 不改坐标转换
- 不改 confirm 弹窗文本含义
- 不改 Field Reference API
- 不改 runtime sync 语义

### WU-3B: Extract `action_lab.js` (后续)

可包含：
- `loadActionLab`, `selectAction`, `cacheSelectedActionParams`
- `parseActionParams`, `refreshActionStatus`, `renderActionLabStatus`
- `startActionLabAction`, `toggleActionLabRun`, `stopActionLabAction`, `resetActionLabAction`
- `selectedActionIsRunning`, `setupActionStatusJsonCopyGuard`
- `nodeInside`, `actionStatusJsonHasSelection`, `updateActionStatusJson`

WU-3B 风险更高（send_actions / send_commands / dry-run 提示），建议在 Field Reference 之后。

---

## 15. Do Not Split Yet

明确写入：
- **暂不拆 `field_map.js`** — 直到 api_client/app_state/field_reference 或 action_lab 稳定。坐标变换、canvas 绘制、触控交互耦合紧密。
- **暂不拆 `status_dashboard.js`** — `renderStatus` 当前是多个模块的耦合中心（1490–1578行，调用 renderFieldMap/renderActionLabStatus/renderActionMissionStatus/renderDashboardSummaries）。
- **暂不拆 `action_mission.js`** — 直到 Action Lab 拆分完成。两者共享 `latestActionLab`、`dispatchFromActionLab` 等。
- **暂不拆 `manual_controls.js`** — `manual-step-move` 触发后端 stop/clear/hold 行为，虽然前端只是按钮，但语义敏感。

---

## 15b. Cross-Phase No-Touch Areas

整个 WU-1 / WU-2 / WU-3 全阶段都不允许触碰以下区域：

```text
body_velocity / flight_command
stop_control
latest-only queue
clear pending
连续速度命令
telemetry_link
ActionDispatcher
后端 API
Mission JSON
飞控链路
MAVLink send path
SafetyGate / DispatchPolicy
CommandPipeline 后端语义
```

Web UI 拆分只搬前端组织结构，不改变任何实发链路、安全门、队列、stop、连续速度或 Mission 语义。

---

## 16. Verification Matrix

| Phase | Files changed | Automated validation | Manual validation | Main rollback |
|-------|--------------|---------------------|-------------------|---------------|
| WU-0 | `docs/refactor/web_ui_split_plan.md` (new) | `git diff --stat` — 1 file only | N/A | Delete `docs/refactor/web_ui_split_plan.md` |
| WU-1 | `web_ui/static/js/api_client.js` (new), `web_ui/static/app.js` (modify API calls), `web_ui/static/index.html` (add script) | `python -m compileall app web_ui`, `pytest -q` | 10-item checklist (see §14) | Remove api_client.js script tag, restore app.js json() calls |
| WU-2 | `web_ui/static/js/app_state.js`, `format_utils.js`, `dom_utils.js` (new), `app.js` (modify), `index.html` (add scripts) | `python -m compileall app web_ui`, `pytest -q` | Dashboard 刷新正常，浏览器 console 无错误 | Restore app.js top-level state and helpers |
| WU-3A | `web_ui/static/js/field_reference.js` (new), `app.js` (modify), `index.html` (add script) | `python -m compileall app web_ui`, `pytest -q` | Field Heading/Reference 按钮和状态正常 | Restore field_reference functions to app.js |
| WU-3B | `web_ui/static/js/action_lab.js` (new), `app.js` (modify), `index.html` (add script) | `python -m compileall app web_ui`, `pytest -q` | Action Lab dry-run/dispatch/stop/reset/status 正常 | Restore action_lab functions to app.js |

---

## 17. Rollback Strategy

```text
WU-0: 删除 docs/refactor/web_ui_split_plan.md 即可回滚。
WU-1: 删除 index.html 中 api_client.js script 引用，恢复 app.js 中 json()/API 调用。
WU-2: 删除新文件 script 引用，恢复 app.js 顶层状态和 helper 函数定义。
WU-3: 删除新文件 script 引用，恢复对应 domain functions 到 app.js。
每阶段必须保持小 diff，禁止大批量格式化 app.js。
```

---

## 18. WU-0 Verification

Run:

```bash
git status --short
git diff --stat
git diff --check
git diff --name-only
```

Expected: only `docs/refactor/web_ui_split_plan.md` changed. No production code modified.

Optional lightweight check:

```bash
python -m compileall app web_ui
```

---

## 19. High-Risk Couplings Discovered

1. **`renderStatus()` (L1490–1578) is the coupling hub** — 它调用 `renderFieldMap`, `renderActionLabStatus`, `renderActionMissionStatus`, `renderDashboardSummaries`。任何拆分都需要保持这个调用链。

2. **`state` global** — 被 ~50+ 函数读取。`renderStatus()` 是主状态快照 `state` 的主要写入点 (`state = next` L1491)；`clearLocalization()` 在 L229 行也会写 `state.localization = {}`。其他局部缓存 (`latestActionLab`, `lastActionMissionStatus`, `lastActionMissionResult` 等) 也有独立写入路径。拆分 `app_state.js` 时不能假设所有状态都只从 `renderStatus()` 进入，必须保持 `window.state` 或等效全局。

3. **`refreshActionStatus` → `renderFieldMap`** — `refreshActionStatus()` 拉取 Action 状态后调用 `renderActionLabStatus()` 和 `renderFieldMap(state)` (L1674–1675)，形成 Action Lab 状态刷新与场地图刷新的耦合。拆 `action_lab.js` 时需保持此耦合。

4. **`fieldMapModel` (L891–978)** — 聚合了 10+ 个数据源（mission_detail, drone, localization, action_lab, drop_targets, recon_inspection 等），是场地图绘制的唯一数据入口。

5. **Action Mission → `lastActionMissionStatus/Result`** — 这些全局状态被多个函数读写，包括 auto tick timer、skip-current、copy 按钮等。

6. **Config save → service restart** — `actionForPath()` 映射直接影响 `applyConfig` 按钮文字和后端行为，拆分 config_panel.js 时必须保持此映射。
