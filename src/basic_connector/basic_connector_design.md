# Basic Connector模块设计

> **文档定位**：基础连接器模块设计入口。
>
> **主要作用**：定义所有Connector共同遵守的职责、稳定性和安全边界。
>
> **使用方式**：新增或修改任何Connector前先读本文，再进入对应具体Connector设计。

> **文档定位**：基础连接器模块设计入口。
>
> **主要作用**：定义所有Connector共同遵守的职责、稳定性和安全边界。
>
> **使用方式**：新增或修改任何Connector前先读本文，再进入对应具体Connector设计。

状态：当前有效

层级：模块设计

上层设计：[系统设计](../../design/system_design.md)

相关代码：`src/basic_connector/`

最后复核：2026-10-28

## 1. 职责

Basic Connector只解决连接、协议、数据传输和连接稳定性，不包含EVB、普通主机或Benchmark业务语义。

具体Driver通过`ControlContext`取得Connector或其窄能力接口；Connector不得反向导入Environment Driver。

## 2. 公共约束

- 长连接必须有明确的所有者和关闭时机；
- 保活、失联判断和重连次数必须有界；
- 修改性命令断线后不得自动重放；
- 超时、取消、认证失败和身份不匹配应分类返回；
- 日志和异常不得泄露密码、密钥和其他凭据；
- Live Test必须显式提供环境变量，没有设备配置时跳过。

## 3. 具体连接器

- [SSH Connector](ssh_connector/ssh_connector_design.md)
- [网络串口Connector](serial_connector/serial_connector_design.md)
- [BMC Connector](bmc_connector/bmc_connector_design.md)
- [File Transfer Connector](file_transfer_connector/file_transfer_connector_design.md)
- [Local Process Connector](local_process_connector/local_process_connector_design.md)

SSH和串口都提供连接复用和Expect能力，但第一阶段保持独立实现；只有重复模式稳定后才提取共享层。
