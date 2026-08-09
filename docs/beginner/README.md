# 新手完整搭建教程

这套教程面向第一次搭建 RK3588 视觉无人机的读者。教程从硬件清单开始，依次经过
机械组装、接线、软件部署、无桨测试、SITL 和首次实飞。

## 阅读规则

- 按编号阅读，不要跳过供电检查、无桨测试或 SITL。
- 文档中的 **待确认** 不是推荐型号，必须用你的真实硬件信息替换。
- 每完成一章再进入下一章；“程序能启动”不等于“可以装桨实飞”。
- 所有软件部署阶段保持 `executor.send_commands: false`。
- 实机调试时必须准备遥控器或地面站接管。

## 学习路线

| 章节 | 内容 | 风险等级 |
| --- | --- | --- |
| [01](01_project_overview.md) | 认识系统和比赛流程 | 只读 |
| [02](02_hardware_bom.md) | 填写并确认硬件 BOM | 采购前 |
| [03](03_mechanical_assembly.md) | 机械安装和重心 | 低 |
| [04](04_wiring_and_power.md) | 接线、供电和断电检查 | 高 |
| [05](05_rk3588_preparation.md) | RK3588 系统、网络和 SSH | 低 |
| [06](06_ai_deployment.md) | 分阶段让 AI 部署环境 | 中 |
| [07](07_first_start.md) | 第一次启动和状态检查 | 中 |
| [08](08_bench_test.md) | 拆桨台架验证 | 高 |
| [09](09_sitl_test.md) | SITL 低速任务验证 | 中 |
| [10](10_field_setup.md) | 比赛 FIELD 坐标初始化 | 中 |
| [11](11_first_flight.md) | 无载荷首次实飞 | 极高 |
| [12](12_competition_runbook.md) | 比赛当天固定流程 | 极高 |
| [13](13_troubleshooting.md) | 分层排查故障 | 按问题 |

## 开始前准备一个装机记录

建议建立一个不包含密码的装机记录，至少保存：

- 每件硬件的准确型号、版本和照片；
- 电源输入/输出实测值；
- 飞控固件版本和参数备份；
- RK3588 系统、内核、NPU driver/runtime 版本；
- 相机稳定设备路径；
- MAVLink 连接方式、端口和波特率；
- 投放 SERVO 输出编号和空载 PWM 测试结果；
- 每次 SITL、台架和实飞的日期与结果。

不要在文档、Git 或发给 AI 的提示词中记录 Wi-Fi 密码、SSH 私钥、访问令牌等秘密。

## 教程与参考文档的区别

`docs/beginner/` 告诉你按什么顺序操作；`docs/hardware/` 保存接线和硬件参数表；
`docs/user/` 面向已经完成安装的操作者；`docs/reference/` 是坐标、安全和配置规范；
`docs/ai/` 面向维护代码的开发者和 AI。

下一章：[认识项目](01_project_overview.md)。
