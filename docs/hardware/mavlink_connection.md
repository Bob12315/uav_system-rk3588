# RK3588 与飞控的 MAVLink 连接

## 软件当前默认值

实机 profile `config/profiles/rk3588-real/telemetry.yaml` 当前使用：

```yaml
data_source: real
active_source: real
real:
  connection_type: eth
  eth_mode: udpin
  eth_host: "0.0.0.0"
  eth_port: 15001
```

这表示软件监听 UDP 15001，并不自动证明你的飞控或网络模块已经向该地址发送 MAVLink。

## 方案 A：Ethernet/UDP

记录飞控或网络模块 IP、RK3588 IP、UDP 方向、端口和中间网络设备。验证顺序：

1. 两端物理链路和 IP 可见；
2. RK3588 路由正确；
3. 端口有数据包；
4. app 日志收到 MAVLink heartbeat；
5. Web UI 的 link、GPS、姿态更新；
6. 断线后 stale/control_allowed 正确变化。

只读网络检查可使用 `ip address`、`ip route`、`ss` 和经批准的抓包工具。不要为了检查
heartbeat 开启 SEND。

## 方案 B：UART

UART 必须确认：

- 两端逻辑电平；
- TX/RX 交叉和信号 GND；
- 飞控串口协议和波特率；
- RK3588 设备路径与用户权限；
- 插头中电源针脚是否应该断开。

对应配置示意仅用于字段说明：

```yaml
real:
  connection_type: serial
  serial_port: /dev/<真实设备>
  baudrate: <真实波特率>
```

不得直接复制占位符。不要把未知电源针脚连接到 RK3588。

## 双数据源

配置支持 real、sitl 和 dual，但新手部署先只使用明确的一种数据源。切换或重连后系统
SEND 应保持关闭，确认 active_source 后再继续。

## 验收记录

| 项目 | 结果 |
| --- | --- |
| 物理连接 | 待确认 |
| IP/串口/波特率 | 待确认 |
| heartbeat | 待确认 |
| GPS/姿态/LOCAL_NED | 待确认 |
| 断线 stale | 待确认 |
| 恢复后无旧命令重放 | 待确认 |
| 测试日期/人员 | 待确认 |
