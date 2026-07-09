# Drop Two Targets V2 Aggressive Scoring Mission Design

## 文档目标

说明新版 `drop_two_targets_v2` 的比赛激进得分策略。

当前策略目标不是最保守安全，而是：

- 尽量完成比赛得分；
- 必须尽量清空两个载荷；
- 识别不到目标也要释放载荷；
- 不能因为识别失败导致任务卡死；
- 投放结束后必须进入返航/降落流程。

---

## 涉及的 Mission 文件位置

| 用途 | 路径 |
|------|------|
| 基础 mission | `config/action_missions/drop_two_targets_v2.json` |
| 完整流程投放段同步 | `config/action_missions/rescue_2026_full_auto_v2.json` |
| SITL profile — drop_two_targets_v2 | `config/profiles/rk3588-sitl/action_missions/drop_two_targets_v2.json` |
| SITL profile — rescue_2026_full_auto_v2 | `config/profiles/rk3588-sitl/action_missions/rescue_2026_full_auto_v2.json` |

---

## 新任务流程

```
1. takeoff_5m
2. resolve_first_scan_point：FIELD(-2.0, 31.25, 5.0) → GPS → LOCAL_NED
3. goto_first_scan_point：local_position 飞到四点扫描第一个点
4. yaw_align_before_scan：到第一个扫描点后做 yaw 对齐
5. drop_multi_view_scan：执行 2×2 四点扫描
6. resolve_drop_buckets：用 raw_estimates 的拍摄瞬间 pose 反算桶 GPS，再转 LOCAL_NED
7. select_drop_targets：选择最多 2 个目标，允许只找到 1 个
8. drop_sequence：飞到目标上方 3m，yaw 对齐，对准下降，释放载荷
9. resolve_home：home/origin GPS → LOCAL_NED
10. return_home：local_position 返航
11. yaw_align_before_land
12. land_home
```

---

## 坐标策略

三层坐标：

| 坐标层 | 用途 |
|--------|------|
| FIELD | 人写 mission / Web UI 场地图使用，+Y 场地前方，+X 场地右方 |
| GPS | 统一世界坐标，用于把任务点和视觉目标落到真实经纬度 |
| LOCAL_NED | 飞控执行坐标，实际发送 `local_position` |

### 固定航点链路

```
FIELD → GPS → LOCAL_NED → local_position
```

### 视觉桶链路

```
拍摄瞬间飞机 GPS + yaw + altitude + ex/ey
→ 桶 GPS
→ gps_to_local_ned()
→ 桶 local_x/local_y
→ local_position 飞到桶上方
```

### 明确禁止

- v2 比赛 mission 不使用 `target_frame: global`
- 不使用 `global_goto`
- 不使用扫描结束后的当前 GPS/yaw 统一反算所有 `raw_estimates`

---

## 四点扫描参数

### 扫描点坐标（FIELD 坐标系）

```json
[
  {"x": -2.0, "y": 31.25, "altitude_m": 5.0},
  {"x":  2.0, "y": 31.25, "altitude_m": 5.0},
  {"x":  2.0, "y": 33.75, "altitude_m": 5.0},
  {"x": -2.0, "y": 33.75, "altitude_m": 5.0}
]
```

### 推荐扫描参数

```json
{
  "capture_updates_per_waypoint": 6,
  "settle_updates_per_waypoint": 1,
  "max_updates_per_waypoint": 100,
  "tolerance_xy_m": 0.8,
  "tolerance_z_m": 0.6,
  "goto_min_hold_updates": 1,
  "min_confidence": 0.30,
  "camera": {
    "fov_x_deg": 51.3,
    "fov_y_deg": 39.6,
    "image_x_sign": 1.0,
    "image_y_sign": -1.0,
    "yaw_offset_deg": 0.0
  },
  "fusion": {
    "cluster_radius_m": 1.0,
    "outlier_radius_m": 1.0,
    "min_cluster_size": 2,
    "max_cluster_radius_m": 1.2,
    "center_weight_power": 2.0,
    "max_abs_ex": 0.75,
    "max_abs_ey": 0.75,
    "max_objects": 3
  }
}
```

### FOV 说明

FOV 当前按实测 5m 高度视场 4.8m × 3.6m 设置为 51.3 / 39.6。
如果后续确认图像横向对应 3.6m，需要对调为 39.6 / 51.3。
`yaw_offset_deg` 默认 0.0，后续实飞标定。

---

## 目标选择策略

```
target_count = 2
allow_fewer = true

最多选择 2 个目标
如果识别到 2 个或更多目标：选前 2 个（按得分排序）
如果只识别到 1 个目标：仍继续任务
如果识别到 0 个目标：仍继续任务，进入原地释放策略
```

不再要求必须识别 2 个或 3 个目标。

---

## 投放策略 — 比赛激进策略

```
识别到 2 个目标：
  两个载荷分别投两个目标

只识别到 1 个目标：
  两个载荷都投到这个目标

识别到 0 个目标：
  在当前位置原地释放两个载荷

align_descend 超过 30 秒：
  立即释放当前 payload
  不要先爬升再投
  不要让任务卡住

第一个目标失败：
  仍继续尝试释放后续 payload
  最终目标是清空载荷

投放流程结束：
  无论成功几个，都进入返航/降落
```

---

## drop_sequence 需要新增/调整的能力

### 现有能力

| 参数 | 说明 |
|------|------|
| `release_all_payloads_if_only_one_target` | 只有一个目标时释放全部载荷 |
| `fallback_release_when_last_target_failed` | 最后一个目标失败时 fallback 释放 |
| `continue_after_any_failure` | 任何失败后继续 |
| `align_descend_max_updates` | align_descend 超时限制 |

### 需要新增

| 参数 | 说明 |
|------|------|
| `release_all_payloads_if_no_valid_targets` | 无有效目标时原地释放全部载荷 |

### 新增参数预期行为

```
如果 valid_targets 为空：
  不 goto
  不 target_lock
  不 align_descend
  在当前位置按 payload 顺序直接释放两个载荷
  released_count = payload_count
  reason = no_target_release_all_in_place
  然后继续 return_home
```

当前代码中 `DropSequenceAction.start()` 的 `init` 阶段已经处理 `valid_targets` 为空的情况，但只是标记 done 且 `released_count=0`，**不释放载荷**。新增 `release_all_payloads_if_no_valid_targets` 参数后，当该参数为 true 且 `valid_targets` 为空时，应走原地释放路径。

---

## 推荐 drop_sequence 参数

```json
{
  "targets": "$drop_targets.target_slots",
  "max_payloads": 2,
  "max_target_candidates": 3,
  "approach_altitude_m": 3.0,
  "finish_altitude_m": 1.5,
  "climb_after_drop_m": 3.5,
  "goto_max_updates": 100,
  "target_lock_max_updates": 40,
  "align_descend_max_updates": 300,
  "climb_max_updates": 80,
  "fallback_release_when_last_target_failed": true,
  "release_all_payloads_if_only_one_target": true,
  "release_all_payloads_if_no_valid_targets": true,
  "continue_after_any_failure": true
}
```

### 参数说明

| 参数 | 值 | 说明 |
|------|-----|------|
| `approach_altitude_m` | 3.0 | 飞到目标上方 3m（当前为 2.5m，3m 更安全） |
| `align_descend_max_updates` | 300 | `expected_dt_s=0.1` 时约 30 秒。30 秒后直接释放当前 payload，不等待重新爬升 |
| `goto_max_updates` | 100 | goto 超时 |
| `target_lock_max_updates` | 40 | 目标锁定超时 |
| `climb_max_updates` | 80 | 爬升超时 |

---

## 失败策略表

| 阶段 | 失败策略 |
|------|----------|
| takeoff 失败 | land / abort |
| goto_first_scan_point 失败 | 继续 multi_view_scan |
| yaw_align_before_scan 失败 | 继续扫描 |
| multi_view_scan 失败但有 raw_estimates | 继续 resolve/select/drop |
| multi_view_scan 无目标 | 继续进入 no-target 原地释放 |
| resolve_drop_buckets 失败 | 继续进入 no-target 原地释放 |
| select_drop_targets 失败 | 继续进入 no-target 原地释放 |
| 只找到 1 个目标 | 两个载荷都投同一个目标 |
| 0 个目标 | 原地释放两个载荷 |
| goto target 失败 | 如果配置允许 fallback，则释放当前 payload 或继续下一个 payload |
| align_descend 超过 30s | 立即释放当前 payload |
| release 失败 | 继续后续 payload / 返航 |
| return_home 失败 | 直接 land |
| land 失败 | 继续 land，不进入其他动作 |

---

## 涉及 on_failed 调整的动作

以下是需要从当前 `jump_to: return_home` / `jump_to: land_home` 调整为更激进策略的动作及其目标 on_failed 行为：

| 动作 | 当前 on_failed | 新 on_failed | 理由 |
|------|---------------|-------------|------|
| `resolve_drop_center` | `jump_to: land_home` | `continue` 或 `jump_to: return_home` | 解析中心点失败不应直接降落，可以尝试继续 |
| `goto_drop_scan_center` | `jump_to: return_home` | `continue`（直接进入扫描） | 已经在扫描点附近，goto 失败仍可尝试扫描 |
| `resolve_drop_buckets` | `jump_to: return_home` | `continue`（进入原地释放） | 反算失败不应返航，应原地释放载荷 |
| `select_drop_targets` | `jump_to: return_home` | `continue`（进入原地释放） | 选择失败不应返航，应原地释放载荷 |
| `return_home` | `jump_to: land_home` | `continue` | 返航失败直接尝试降落 |

---

## 后续代码改动清单

### Mission JSON（需同步修改 4 个文件）

```
config/action_missions/drop_two_targets_v2.json
config/action_missions/rescue_2026_full_auto_v2.json
config/profiles/rk3588-sitl/action_missions/drop_two_targets_v2.json
config/profiles/rk3588-sitl/action_missions/rescue_2026_full_auto_v2.json
```

### Python 代码

```
missions/common/actions/drop_sequence.py
```

### 测试

```
tests/current/test_drop_sequence_action.py
tests/current/test_action_mission_templates.py
```

---

## 验证计划

后续改代码时必须跑：

### 编译检查

```bash
python3 -m compileall app missions telemetry_link web_ui
```

### 验证脚本

```bash
python3 scripts/validate_action_missions.py
```

### 测试

```bash
PYTHONPATH=. pytest tests/current/test_drop_sequence_action.py \
       tests/current/test_action_mission_templates.py \
       tests/current/test_multi_view_localize_action.py \
       tests/current/test_resolve_gps_targets_action.py
```

### 安全 grep（确保 v2 mission 中没有残留 global target_frame）

```bash
grep -R '"target_frame": "global"' -n config/action_missions/*v2*.json config/profiles/rk3588-sitl/action_missions/*v2*.json
```

### SITL profile diff（确保 profile 与 base 一致）

```bash
diff -u config/action_missions/drop_two_targets_v2.json \
  config/profiles/rk3588-sitl/action_missions/drop_two_targets_v2.json

diff -u config/action_missions/rescue_2026_full_auto_v2.json \
  config/profiles/rk3588-sitl/action_missions/rescue_2026_full_auto_v2.json
```

---

## 提交要求

本轮只创建文档，不改 mission JSON，不改 Python 代码。

commit message：

```
document aggressive drop mission strategy
```
