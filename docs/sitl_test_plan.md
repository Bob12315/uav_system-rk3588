# SITL 测试计划

本文按风险从低到高安排验证顺序。

## 1. 纯代码检查

```bash
python -m pytest -q
python -m app.main --no-yolo-udp --run-seconds 2 --send-commands false
python -m telemetry_link.main --help
```

通过标准：

- 测试通过。
- app 能自动退出。
- telemetry help 可显示。

## 2. telemetry only

启动 SITL 后运行：

```bash
python -m app.main --connect-telemetry --no-yolo-udp --send-commands false --run-seconds 5
```

观察：

- link connected。
- mode 正确。
- `control_allowed` 符合飞控模式。

## 3. YOLO + fusion dry-run

窗口 1：

```bash
conda activate yolo
cd ~/uav_project/uav_system-rk3588
python -m yolo_app.main
```

窗口 2：

```bash
conda activate app
cd ~/uav_project/uav_system-rk3588
python -m app.main --connect-telemetry --send-commands false
```

观察：

- target_valid。
- track_id。
- target_size。
- raw/shaped command。

## 4. gimbal dry-run

```bash
python -m app.main --connect-telemetry --force-mode APPROACH_TRACK --send-commands false
```

观察：

- `ex_cam -> gimbal_yaw_rate` 方向是否正确。
- `ey_cam -> gimbal_pitch_rate` 方向是否正确。

## 5. gimbal live

确认云台安全后：

```bash
python -m app.main --connect-telemetry --force-mode APPROACH_TRACK --send-commands true
```

建议先通过 debug/config 或 UI 关闭 body/approach，仅测云台。

## 6. body dry-run

打开 body/approach 但不发送：

```bash
python -m app.main --connect-telemetry --force-mode APPROACH_TRACK --send-commands false
```

观察：

- `ex_body -> vy`
- `gimbal_yaw -> yaw_rate`
- `target_size -> vx`

## 7. body low-speed live

先降低 `missions/<mission_name>/config.yaml`：

```yaml
shaper:
  max_vx: 0.3
  max_vy: 0.3
  max_yaw_rate: 0.3
```

再运行：

```bash
python -m app.main --connect-telemetry --force-mode APPROACH_TRACK --send-commands true
```

## 8. overhead 切换

调整 mission 阈值，让 SITL 中能触发 overhead：

```yaml
mission:
  overhead_entry_target_size_thresh: <测试值>
```

观察：

- `APPROACH_TRACK -> OVERHEAD_HOLD`
- overhead 中 `ex_cam -> vy`
- overhead 中 `ey_cam -> vx`
- 目标丢失或 size drop 后退出。

## 9. 回归检查

每次 SITL 后运行：

```bash
python -m pytest -q
```
