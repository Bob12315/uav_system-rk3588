# 05：准备 RK3588

## 本章目标

让 RK3588 具备稳定的 Linux、网络、SSH、时间、存储和 NPU 运行基础，为 AI 部署软件
做好准备。本章不连接飞行动作。

预计时间：1～3 小时。需要准备：RK3588、显示器或串口控制台、局域网和另一台电脑。

## 1. 确认系统架构

登录板卡后运行：

```bash
uname -a
uname -m
cat /etc/os-release
```

项目要求 Linux，架构应为 `aarch64` 或 `arm64`。如果是 x86_64，不要尝试添加 CUDA、
PyTorch 或模拟兼容路径。

## 2. 建立稳定网络和 SSH

确认板卡能获取固定或可重复找到的局域网地址：

```bash
ip address
ip route
hostname -I
```

从管理电脑测试：

```bash
ssh <用户名>@<RK3588-IP>
```

比赛现场应提前决定使用有线网络、固定路由器还是其他方案，并准备离线操作能力。不要把
Wi-Fi 密码或 SSH 私钥写进仓库和 AI 提示词。

## 3. 检查时间、存储和温度

```bash
date
df -h
free -h
```

日志、录像和 blackbox 会写入 `runtime/` 或配置的录像目录。预留足够空间，并避免系统
时间错误导致日志难以排序。温度查看方式随板卡 BSP 不同，应按板卡厂商说明确认。

## 4. 检查摄像头

USB/V4L2 相机可先检查：

```bash
v4l2-ctl --list-devices
ls -l /dev/v4l/by-id/ 2>/dev/null || true
```

优先记录稳定的 `/dev/v4l/by-id/...`，不要默认 `/dev/video41` 在所有板卡上都成立。
CSI 或网络相机按板卡/相机文档测试实际画面。

## 5. 检查 NPU 前置条件

RKNNLite、NPU driver 和 runtime 必须与当前板卡镜像匹配。具体安装方式取决于板卡 BSP，
不能仅凭仓库猜版本。记录：

- 板卡和系统镜像版本；
- 内核版本；
- NPU driver/runtime 版本；
- 已验证可用的 `rknn-toolkit-lite2` 来源和版本。

软件环境安装完成后会用以下导入检查验证：

```bash
python -c "from rknnlite.api import RKNNLite; print(RKNNLite)"
```

## 6. 准备 Conda

安装适用于 aarch64 的 Miniconda/Anaconda/Miniforge。安装方式以其官方文档为准。完成后：

```bash
conda --version
conda info --envs
```

本项目将创建两个 Python 3.10 环境：`app` 和 `yolo`，不要混成一个环境。

## 完成检查表

- [ ] 系统是 Linux aarch64/arm64。
- [ ] 可以从管理电脑稳定 SSH 登录。
- [ ] 日期、磁盘和内存状态正常。
- [ ] 已记录相机实际接口和设备路径。
- [ ] 已记录板卡 BSP、内核和 NPU 版本。
- [ ] Conda 可以正常使用。
- [ ] 当前仍未开启飞行动作。

下一章：[让 AI 部署软件](06_ai_deployment.md)。
