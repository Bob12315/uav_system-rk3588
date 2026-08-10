# 04：RK3588 环境配置

## 本章目标

从空白 RK3588 开始准备 Linux、网络、相机和 NPU，再使用能够读取仓库、执行终端命令并
展示改动的 AI 编程助手，分阶段完成依赖安装、配置、服务部署和第一次只读启动。

预计时间：2 小时到半天，取决于网络、板卡镜像和 NPU 环境。需要准备：已完成组装的
RK3588、显示器或串口控制台、局域网、仓库地址、真实相机/MAVLink 信息。

> 本章只做软件部署和只读联调。保持拆桨、无正式载荷和
> `executor.send_commands: false`，不要运行 Action 或 Mission。

## 一、准备板卡系统

### 1. 确认架构和系统

登录板卡后运行：

```bash
uname -a
uname -m
cat /etc/os-release
```

项目只支持 Linux ARM64 RK3588，架构应为 `aarch64` 或 `arm64`。如果是 x86_64，不要
添加 CUDA、PyTorch 或模拟兼容路径。

### 2. 建立网络和 SSH

```bash
ip address
ip route
hostname -I
```

从管理电脑测试：

```bash
ssh <用户名>@<RK3588-IP>
```

比赛现场应使用固定或可重复找到的地址，并准备离线操作方案。不要把 Wi-Fi 密码、SSH
私钥或访问令牌写进仓库和 AI 提示词。

### 3. 检查时间、存储和内存

```bash
date
df -h
free -h
```

日志、录像、SITL 文件和 blackbox 应写入 `runtime/`。预留足够空间，按板卡厂商方法检查
温度和散热状态。

### 4. 检查相机

USB/V4L2 相机可先运行：

```bash
v4l2-ctl --list-devices
ls -l /dev/v4l/by-id/ 2>/dev/null || true
v4l2-ctl --device=<真实设备> --list-formats-ext
```

优先记录稳定的 `/dev/v4l/by-id/...`，不能假定 `/dev/video41` 在所有板卡上都存在。
CSI 或网络相机按对应厂商文档检查真实画面。

### 5. 确认 NPU 和 RKNNLite 来源

NPU driver、runtime 和 RKNNLite 必须与当前板卡镜像匹配。先记录：

- 板卡准确型号和系统镜像/BSP；
- 内核版本；
- NPU driver/runtime 版本；
- 厂商确认可用的 `rknn-toolkit-lite2` 来源和版本。

不能确认版本匹配时先停止，向板卡厂商或项目硬件负责人核对。部署后使用：

```bash
python -c "from rknnlite.api import RKNNLite; print(RKNNLite)"
```

### 6. 准备 Conda 和仓库

安装适用于 aarch64 的 Conda 发行版，然后检查：

```bash
conda --version
conda info --envs
git --version
```

本项目使用两个独立 Python 3.10 环境：`app` 和 `yolo`。把仓库放到固定路径，执行：

```bash
cd <仓库绝对路径>
git status --short --branch
```

不要在路径不明确时让 AI 假设 `~/uav_project/uav_system-rk3588` 一定存在。

## 二、让 AI 分阶段部署

### 为什么要分阶段

无人机部署同时涉及系统包、Python、NPU、相机、网络和飞控。一个超长“全部装好”任务
发生错误时很难定位，也容易让 AI 猜硬件。下面每个 Prompt 都有明确终点；确认结果后再
发送下一段。

AI 可以执行软件操作，但以下事情必须由人确认：

- 电压、极性和物理接线；
- 螺旋桨和载荷是否已移除；
- 飞控固件、校准和遥控器接管；
- 相机、串口、网口的真实设备；
- 是否进入 SITL 或实机测试阶段。

### 所有阶段的固定约束

每次开始新对话时先发送：

```text
你正在协助部署 cuadc2026 多旋翼无人机侦察与救援项目。

必须遵守：
1. 始终保持 config/app.yaml 中 executor.send_commands=false。
2. 不得发送解锁、起飞、速度、航点、降落、模式切换或舵机命令。
3. 不得恢复旧 mission/stage/control 栈。
4. 不得添加 x86、CUDA、PyTorch 或 GPU 推理路径。
5. YOLO 只使用 RKNNLite、RK3588 NPU 和仓库中的 RKNN 模型。
6. 修改前先检查 git status，保留用户已有改动。
7. 不确定硬件端口、电压、设备节点、用户名或路径时必须询问，不能猜测。
8. 不得输出、提交或记录密码、SSH 私钥、访问令牌和 Wi-Fi 密码。
9. 每个阶段结束后报告执行内容、验证结果、未解决问题和下一步，不自动进入实飞阶段。
10. 先阅读仓库的 README.md、AGENTS.md 和相关安全文档，再执行任务。
```

### Prompt 0：只读环境检查

```text
现在只做只读环境检查，不安装软件、不修改文件、不启动服务。

请检查并报告：
- uname、CPU 架构、Linux 发行版和内核；
- 板卡是否看起来是 RK3588/aarch64；
- 磁盘、内存、系统时间；
- Conda 和已有 Python 环境；
- NPU driver/runtime 和 RKNNLite 的可见信息；
- v4l2/USB/CSI 相机设备；
- 网络地址、路由和当前监听端口；
- 仓库路径、Git 分支和 git status；
- data/models 下的 RKNN 模型；
- 当前 config/app.yaml 的 executor.send_commands 值。

不要显示秘密信息。最后给出“满足、缺失、需要人工确认”三类清单。
```

通过标准：确认 Linux ARM64/RK3588、仓库存在、SEND 为 false，并得到明确缺项列表。

### Prompt 1：阅读仓库并制定部署计划

```text
请阅读 README.md、AGENTS.md、docs/beginner/04_rk3588_setup.md、
docs/developer/safety.md、docs/ai/current_architecture.md、
docs/ai/deprecated_paths.md，以及 scripts/install 和
scripts/deploy 下本次会使用的脚本。

只制定部署计划，不执行安装。计划必须分为 app 环境、yolo 环境、硬件配置、
systemd、只观察联调五个阶段。指出每阶段会修改什么、验证命令、回滚方法和需要我确认的
硬件信息。确认所有方案保持 executor.send_commands=false。
```

通过标准：AI 的计划使用两个 Python 3.10 环境，没有提出 CUDA/PyTorch 或旧任务栈。

### Prompt 2：安装 app 环境

```text
只完成 app 环境，不安装 yolo、不改硬件配置、不启动 systemd 服务。

请先确认当前是 Linux aarch64/arm64，并确认将使用名为 app 的 Python 3.10 Conda 环境。
如果环境不存在，可以创建；激活后运行 scripts/install/install_app_env.sh。

安装完成后验证：
- python -m app.main --help
- python -m telemetry_link.main --help
- app 运行依赖导入
- config/app.yaml 仍为 executor.send_commands=false

如果需要 sudo 安装系统包，先说明将安装的包并等我确认。不要启动飞控连接或服务。
```

### Prompt 3：安装 yolo 环境

```text
只完成 yolo 环境和离线导入检查，不启动持续摄像头服务。

请确认将使用名为 yolo 的 Python 3.10 Conda 环境，检查板卡 NPU driver/runtime 与
rknn-toolkit-lite2 的来源是否明确。不能明确匹配版本时停止并告诉我需要哪个板卡资料。

激活环境后运行 scripts/install/install_yolo_env.sh，并验证：
- import cv2, numpy, yaml
- from rknnlite.api import RKNNLite
- data/models/cuadc2026-fp16.rknn 存在
- config/yolo.yaml 的 model_path 能解析到该文件

不要添加 PyTorch、CUDA、x86 或 GPU 后备路径，不要启动飞行动作。
```

### Prompt 4：根据真实硬件配置

先把尖括号内容替换成你的真实信息：

```text
请根据下面已由人工确认的硬件信息配置仓库。修改前先展示计划和目标 diff：

- RK3588 板卡/系统：<准确型号和系统版本>
- 相机接口与稳定路径：<例如实际 /dev/v4l/by-id/...，不要猜>
- MAVLink 连接：<eth/udp/serial/tcp>
- MAVLink 监听/目标地址：<真实 IP 和端口>
- 如果是串口：<真实设备、波特率和电平已人工确认>
- 实机模型：data/models/cuadc2026-fp16.rknn
- Web UI 监听：<通常 0.0.0.0:8080>
- YOLO 视频流：<通常 0.0.0.0:8081>

只修改 config/yolo.yaml、config/telemetry.yaml 中与上述信息对应的字段。
保持 config/app.yaml 的 executor.send_commands=false，不修改 Action Mission 飞行参数，
不发送任何飞控或舵机命令。修改后运行 YAML 解析和只读 healthcheck，并展示最终 diff。
```

如果你没有真实设备路径或端口，返回硬件章节继续确认，不要让 AI试遍所有接口。

### Prompt 5：安装 systemd 服务

```text
请安装 app 和 yolo 的 systemd 用户服务，但先进行 dry-run。

步骤：
1. 检查 app/yolo 环境 Python 的实际绝对路径；
2. 检查 git status 和 executor.send_commands=false；
3. 运行 scripts/deploy/install_systemd_user_services.sh --dry-run；
4. 展示生成的 WorkingDirectory、ExecStart 和 Python 路径；
5. 如果路径正确，再安装服务；
6. 在我确认前不要使用 --enable-now；
7. 安装后报告 systemctl --user status，不发送飞行动作。

如果 Conda 不在默认 ~/anaconda3 路径，使用 APP_PYTHON 和 YOLO_PYTHON 显式指定。
```

确认 dry-run 后，可以让 AI 执行 `--enable-now`。此时仍应拆桨、无载荷、SEND=OFF。

### Prompt 6：只观察联调

```text
现在只做观察联调。确认螺旋桨和载荷已移除，executor.send_commands=false。

请启动或重启 uav-app.service 和 uav-yolo.service，然后只读检查：
- 两个服务状态和最近日志；
- 5005/udp、5006/udp、8080/tcp、8081/tcp；
- /api/status；
- YOLO MJPEG 是否有数据；
- telemetry heartbeat、GPS、姿态、local position 是否只读可见；
- YOLO target/scene 数据是否更新；
- scripts/healthcheck/check_rk3588.sh 输出。

禁止在 Web API、MAVLink、Action Lab 或 Mission 中发送任何动作。最后按“正常、警告、
失败”整理结果。
```

### Prompt 7：故障诊断

```text
请诊断当前部署问题，只做与故障相关的最小范围检查。先收集证据，不要直接重装环境、
覆盖配置或开启 SEND。

问题现象：<粘贴现象>
最近一次正常时间：<时间或未知>
最近改动：<改动或未知>

请按以下层次排查：电源/系统 → 文件和配置 → Python 环境 → systemd → 端口和网络 →
相机/NPU → YOLO UDP → telemetry → Web UI。读取相关日志，给出根因、证据和最小修复
方案。修改前展示 diff；修复后只运行无动作验证。
```

## 三、不使用 AI 时的安装命令

如果希望手动执行，先创建 app 环境：

```bash
conda create -n app python=3.10 -y
conda activate app
bash scripts/install/install_app_env.sh

python -m app.main --help
python -m telemetry_link.main --help
```

再创建 yolo 环境：

```bash
conda create -n yolo python=3.10 -y
conda activate yolo
bash scripts/install/install_yolo_env.sh

python -c "import cv2, numpy, yaml; from rknnlite.api import RKNNLite; print('ready')"
test -f data/models/cuadc2026-fp16.rknn
```

开发或运行测试时，在 `app` 环境额外安装：

```bash
python -m pip install -r requirements-dev.txt
```

## 四、第一次安全启动

### 启动前确认

```bash
cd <仓库绝对路径>
git status --short
grep -n "send_commands" config/app.yaml
bash scripts/healthcheck/check_rk3588.sh
```

必须看到 `executor.send_commands: false`。然后使用两个终端：

```bash
# 终端 1
conda activate yolo
python -m yolo_app.main

# 终端 2
conda activate app
python -m app.main --connect-telemetry --send-commands false
```

若已安装用户服务：

```bash
systemctl --user restart uav-yolo.service uav-app.service
systemctl --user --no-pager --full status uav-yolo.service uav-app.service
```

浏览器访问 `http://<RK3588-IP>:8080/`，第一次只观察：

- Web UI 明确显示 SEND OFF；
- link、GPS、姿态、高度和 LOCAL_NED 状态是否更新；
- YOLO 视频、检测类别和检测框是否合理；
- app/yolo 没有反复重启；
- Action Mission 尚未运行。

禁止点击起飞、航点、模式、投放或 Mission Start。

### 端口与日志

```bash
ss -lntu | grep -E ':(5005|5006|8080|8081)\b'
curl -fsS http://127.0.0.1:8080/api/status
journalctl --user -u uav-app.service -n 100 --no-pager
journalctl --user -u uav-yolo.service -n 100 --no-pager
```

| 端口 | 用途 |
| --- | --- |
| `8080/tcp` | Web UI 和 API |
| `8081/tcp` | YOLO MJPEG 视频 |
| `5005/udp` | app 接收检测结果 |
| `5006/udp` | yolo 接收目标选择命令 |

## 五、常见部署问题

### Web UI 打不开

```bash
systemctl --user status uav-app.service
curl -v http://127.0.0.1:8080/api/status
ss -ltnp | grep ':8080'
```

本机可访问而管理电脑不可访问时，检查监听地址、RK3588 IP、路由和防火墙。

### 没有 YOLO 画面或检测

```bash
systemctl --user status uav-yolo.service
journalctl --user -u uav-yolo.service -n 150 --no-pager
v4l2-ctl --list-devices
curl -v http://127.0.0.1:8081/video/yolo.mjpeg
```

检查相机路径、权限、占用、分辨率、FourCC、NPU 初始化和模型路径。实机模型应为
`data/models/cuadc2026-fp16.rknn`，不要切回历史 INT8 模型。

### app 收不到 YOLO

```bash
ss -lunp | grep -E ':(5005|5006)\b'
grep -En "udp_(ip|port)|command_(ip|port)" config/yolo.yaml config/app.yaml
```

### telemetry 不连接

检查 `config/telemetry.yaml` 的数据源、连接类型、地址、端口或串口。串口还要核对设备
权限、电平、TX/RX、GND 和波特率；网络还要核对 IP、路由、UDP 方向和 heartbeat。
检查连接不需要开启 SEND。

### 服务反复重启

```bash
systemctl --user cat uav-app.service uav-yolo.service
journalctl --user -u uav-app.service -b --no-pager
journalctl --user -u uav-yolo.service -b --no-pager
```

重点检查 `WorkingDirectory`、Python 绝对路径、依赖、模型/相机权限和端口占用。仓库或
Conda 路径改变后重新运行服务安装脚本。

## 环境配置验收

- [ ] app 和 yolo 是两个独立 Python 3.10 环境。
- [ ] RKNNLite 导入成功，模型路径存在。
- [ ] 相机路径来自真实设备检查，不是猜测。
- [ ] telemetry 连接参数来自真实硬件记录。
- [ ] systemd 服务使用正确的仓库和 Python 绝对路径。
- [ ] Web UI、视频流和健康检查可用。
- [ ] `executor.send_commands` 仍为 false。
- [ ] Git diff 中没有秘密、未知硬件猜测或旧架构文件。
- [ ] Web UI、视频流、YOLO 和 telemetry 只读状态可以观察。
- [ ] 没有启动任何 Action 或 Mission。

下一章：[SITL 测试](05_sitl_test.md)。
