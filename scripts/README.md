# Scripts

运维和开发辅助脚本。

## 目录

| 路径 | 用途 |
| --- | --- |
| `scripts/install/` | Python 环境和系统依赖安装 |
| `scripts/deploy/` | systemd 用户服务安装与启用 |
| `scripts/config/` | RK3588 实机/SITL 配置档案切换与保存 |
| `scripts/healthcheck/` | RK3588 板卡只读健康检查 |

## 顶层脚本

| 文件 | 用途 |
| --- | --- |
| `scripts/validate_action_missions.py` | Action Mission JSON 模板格式和参数校验 |
| `scripts/smoke_test_envs.sh` | app 和 yolo conda 环境冒烟测试 |
| `scripts/run_iris_gimbal_sitl.sh` | 启动 Iris + gimbal SITL 仿真 |

## 安装

```bash
conda create -n app python=3.10 -y && conda activate app
bash scripts/install/install_app_env.sh

conda create -n yolo python=3.10 -y && conda activate yolo
bash scripts/install/install_yolo_env.sh
```

完整说明见 [docs/user/install.md](../docs/user/install.md)。

## 部署

```bash
bash scripts/deploy/install_systemd_user_services.sh --dry-run
bash scripts/deploy/install_systemd_user_services.sh
bash scripts/deploy/install_systemd_user_services.sh --enable-now
```

## 配置档案切换

RK3588 实机和 SITL 使用不同的遥测和 YOLO 配置。通过 profile 脚本切换：

```bash
bash scripts/config/apply_rk3588_real.sh   # 实机配置
bash scripts/config/apply_rk3588_sitl.sh    # SITL 配置
```

调参后保存回档案：

```bash
bash scripts/config/save_rk3588_real.sh
bash scripts/config/save_rk3588_sitl.sh
```

两个 apply 脚本都要求 `config/app.yaml` 中 `executor.send_commands` 为 `false` 才允许切换。

## 健康检查

```bash
bash scripts/healthcheck/check_rk3588.sh
```

只读检查：NPU、摄像头、MAVLink 连接、conda 环境、磁盘空间等。

## 验证

```bash
python scripts/validate_action_missions.py
```
