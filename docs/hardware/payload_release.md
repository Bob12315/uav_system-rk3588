# 投放机构与舵机

## 唯一软件链路

```text
payload_release Action
  → set_servo
  → LinkManager.set_servo_output_pwm
  → MAV_CMD_DO_SET_SERVO
```

这里的 channel 是飞控 **SERVO 输出编号**，不是遥控器 RC 输入通道。禁止 RC override、
旧 `release_payload` 或 Action 直接调用 pymavlink。

## 当前模板值

`rescue_2026_full_auto_v2.json` 当前写入：

| 载荷 | SERVO 输出 | release PWM | hold PWM | 软件偏移 |
| --- | ---: | ---: | ---: | --- |
| payload 1 | 8 | 1750 | 1250 | forward -0.06 m，right 0 m |
| payload 2 | 9 | 1815 | 1185 | forward +0.06 m，right 0 m |

这些只是当前软件模板值，不是硬件真值。安装新舵机、修改摇臂、维修机构或更换飞控后，
必须重新空载验证并更新模板。

## 硬件记录

| 项目 | payload 1 | payload 2 |
| --- | --- | --- |
| 舵机型号 | 待确认 | 待确认 |
| 允许电压 | 待确认 | 待确认 |
| 堵转电流 | 待确认 | 待确认 |
| 电源/BEC | 待确认 | 待确认 |
| 飞控 SERVO 输出 | 待确认 | 待确认 |
| 保持 PWM 实测 | 待确认 | 待确认 |
| 释放 PWM 实测 | 待确认 | 待确认 |
| 安全机械范围 | 待确认 | 待确认 |
| 模拟载荷测试 | 待确认 | 待确认 |

## 空载标定顺序

1. 拆桨、移除正式载荷；
2. 舵机先与机构脱开或处于不会堵转的位置；
3. 一次只连接一个舵机；
4. 由飞控/硬件负责人确认真实 SERVO 输出；
5. 从安全中位附近逐步确认方向和机械范围；
6. 确定 hold/release PWM，避免撞击机械极限；
7. 重新连接机构，使用无危险模拟载荷；
8. 分别验证 payload 1、payload 2 和顺序投放；
9. 检查动作时电源压降、发热和另一通道串扰；
10. 将最终值同步到所有正式模板和 profile。

不要把正式比赛模板当作舵机调试工具。发送 set_servo 是真实外部动作，即使没有起飞。

## 软件安全检查

- 系统 SEND 和 Action send_actions 双门控均应可见；
- SEND 关闭时不得调用飞控 SERVO 实发；
- once/key 防止同一请求重复派发；
- Mission 失败恢复不能跳回已释放载荷；
- payload_release 期间保持 zero velocity；
- telemetry 断线时不得继续或重放投放；
- 修改 channel/PWM 后运行模板 validator、SITL 和空载实机验证。

## 验收签字

- [ ] 两路输出均由第二人复核。
- [ ] 保持和释放位置不在堵转极限。
- [ ] 空载、模拟载荷、单路和顺序投放均有记录。
- [ ] 电源不会因舵机动作导致飞控/RK3588 重启。
- [ ] 模板与实际记录一致。
- [ ] 测试人：________ 复核人：________ 日期：________
