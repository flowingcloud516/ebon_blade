# BMC Connector 内网验证计划

状态：等待内部资料和测试环境
最近更新：2026-10-24

## 1. 安全要求

- 本文件只记录脱敏结论，不提交真实IP、用户名、密码、Session Token、Authorization头、证书私钥或内部文档原文。
- 上电和强制下电只能在明确授权、允许中断的测试设备上进行。
- 每次危险动作前人工核对System ID、设备身份和当前PowerState。
- 强制下电与上电分开执行、分开记录，不自动串联。

## 2. 内部资料待补充

```text
脱敏设备型号/固件版本：
Redfish服务根特征：
目标System ID：
Session创建与注销说明：
TLS/证书要求：
Reset Action与允许值：
Task Monitor行为：
Bios资源和Attributes结构：
SSH查询状态命令及输出样本：
SSH上电命令及成功/失败样本：
SSH强制下电命令及成功/失败样本：
```

## 3. Redfish只读验证

- 创建Session，确认Token和Location的返回位置，随后成功注销。
- 验证证书链、自签名证书或内部CA的实际要求。
- 从服务根发现Systems集合，并按明确System ID选择目标。
- 核对目标身份和PowerState，禁止默认选择集合第一项。
- 读取Reset Action、AllowableValues/ActionInfo。
- 读取Bios资源全部Attributes，确认是否分页、含OEM字段或Pending/Settings引用。
- 检查日志与异常不包含密码、Token或Authorization头。

## 4. 电源动作验证

按“当前状态读取—显式动作—有界轮询—最终状态确认”的顺序测试：

- 已为On时调用上电，确认幂等且不重复发动作。
- 已为Off时调用强制下电，确认幂等且不重复发动作。
- Off到上电，记录动作响应、Task Monitor（如有）和到达On的耗时。
- On到强制下电，记录动作响应和到达Off的耗时。
- 动作提交前网络失败时，验证允许按配置回退SSH。
- 动作提交后响应丢失时，验证先查询状态且不跨后端重放。
- 状态长期不变化时，验证返回超时而非虚假成功。

## 5. SSH备用路径验证

- 使用现有SSH Connector建连并核验BMC身份。
- 验证受限Shell下查询、上电、强制下电命令及解析规则。
- 命令返回后再次查询状态，不以退出码或单条文本作为最终完成依据。
- 验证断线重连不自动重放电源动作。
- Redfish与SSH均可用时，比对同一设备状态表示的映射。

## 6. BIOS快照验证

- 快照包含全部当前Attributes、采集时间、目标身份和可获得的版本信息。
- 验证大规模Attributes不被截断，字符编码可正确保存。
- 确认敏感/OEM字段是否需要额外脱敏规则。
- Redfish不可用时明确标记失败，不使用SSH猜测补全。
- 快照只读，不发送PATCH，不安排重启。

## 7. 执行记录模板

```text
测试批次：
日期：
执行人：
代码提交/版本：
脱敏设备编号：
固件/Redfish版本：
System ID：
TLS策略结论：
通过项：
失败项：
各动作转换耗时：
脱敏证据位置：
建议修改：
```
