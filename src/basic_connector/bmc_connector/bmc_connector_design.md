# BMC Connector 设计

> **文档定位**：BMC Connector具体实现设计。
>
> **主要作用**：定义Redfish与SSH后端、电源动作和BIOS只读快照边界。
>
> **使用方式**：实现或调整BMC能力前阅读，并使用验证计划确认真实设备差异。

状态：公共语义层已实现，真实Redfish与厂商SSH后端待内网实现和验证

层级：具体实现设计

上层设计：[Basic Connector模块设计](../basic_connector_design.md)

相关代码：`src/basic_connector/bmc_connector/`

最后复核：2026-10-30

## 1. 目标

BMC Connector为Environment Driver提供统一的带外管理能力，第一阶段只关注：

1. 查询机器当前电源状态。
2. 强制下电。
3. 上电。
4. 读取全部BIOS配置并作为运行日志留档。

第一期不实现正常下电、重启、Power Cycle、BIOS修改或BIOS生效流程。强制下电和上电必须是两个显式且相互独立的步骤，Connector不自动串联。

BMC存在SSH和Redfish两种控制路径。Connector对上层暴露稳定语义，不让具体Driver拼接Redfish URI或直接执行厂商命令。

## 2. 分层结构

```text
Environment Driver
        ↓
BmcConnector（统一语义）
├── RedfishBackend
│   ├── Power control
│   ├── Power state
│   └── BIOS snapshot（只读）
└── BmcSshBackend（HTTPS失效时的电源能力备用路径）
    └── 复用SSH Connector及受信任命令Profile
```

Redfish应优先使用服务根和资源链接发现实际URI，不能假定所有设备都使用`/Systems/1`。SSH后端不得从工作空间加载任意命令；具体命令必须由受信任的厂商Profile或内部实现提供。

## 3. 统一能力接口

建议将不同电源语义定义为不同方法，而不是模糊的`set_power(state)`：

```text
get_power_state()
power_on(issue_policy=IF_NEEDED)
force_off(issue_policy=IF_NEEDED)
read_all_bios_config()
```

第一阶段只实现以上四个接口。其中强制下电和上电是两个独立动作、独立步骤、独立结果，不能合并成一个自动动作。

返回结果至少包含：

```text
PowerOperationResult
├── requested_action
├── previous_state
├── final_state
├── status
├── backend
├── action_accepted
├── verified
├── started_at / finished_at
└── diagnostic_summary
```

## 4. 电源动作语义

Redfish标准将动作请求和最终状态分开：HTTP请求被接受，不代表机器已经完成上下电。因此流程必须是：

```text
读取当前状态
→ 检查目标设备与支持动作
→ 提交明确动作
→ 轮询PowerState
→ 达到目标状态或超时
→ 返回验证结果
```

建议映射：

| 统一动作 | Redfish ResetType候选 | 目标状态 |
| --- | --- | --- |
| `power_on` | `On`，必要时按设备能力使用`ForceOn` | `On` |
| `force_off` | `ForceOff` | `Off` |

实际调用前读取`ResetType@Redfish.AllowableValues`或ActionInfo。设备不支持时明确返回`unsupported`，不静默换成更危险的动作。

### 4.1 幂等与重复调用

- `IssuePolicy.IF_NEEDED`是默认安全策略。已经为`On`时调用`power_on`，或已经为`Off`时调用`force_off`，返回成功且`changed=False`，不重复下发。
- `IssuePolicy.ALWAYS`表示上层明确要求本轮仍提交动作，即使操作前已是目标状态。该策略主要用于DV等把“本轮确实发送了上/下电”定义为流程证据的`OperationStep`。
- `ALWAYS`不表示无限重试，也不允许Connector在请求结果不明时自动再发一次。
- 后端拒绝对当前状态重复发送动作时，返回明确失败或`unsupported`，不伪造成功。
- 请求过程中断线或超时，但无法确认BMC是否已经接受动作时，结果为`unknown`；恢复连接后先查询PowerState。

## 5. Redfish Backend

### 5.1 发现和能力检查

1. 访问`/redfish/v1/`服务根。
2. 跟随`Systems`集合链接选择目标ComputerSystem。
3. 读取PowerState、Actions和允许的ResetType。
4. 找到Bios资源、`@Redfish.Settings`目标和AttributeRegistry。
5. 记录Redfish版本、设备标识和能力快照。

目标系统选择不能简单取集合第一项。环境档案需要保存目标System ID或可核验的设备身份；多System BMC必须明确选择。

### 5.2 HTTP与认证

需要配置：

- HTTPS地址和端口。
- 用户名与密码凭据引用。
- 连接、读取和整体操作超时。
- TLS证书验证策略。
- Basic认证或Redfish Session认证。

密码、Session Token和Authorization头不得进入日志、异常、快照或repr。Session结束后应主动注销。

### 5.3 异步任务

Redfish动作可能返回同步成功，也可能返回`202 Accepted`和Task Monitor。Connector需要统一处理：

- 跟踪Task URI。
- 有界轮询任务状态。
- 处理Retry-After。
- 任务完成后仍检查实际PowerState。
- 轮询期间短暂不可访问时，按有界重试处理，不能直接报告动作成功。

## 6. SSH Backend

BMC SSH可能不是标准Linux Shell，不能直接复用“普通主机命令成功=退出码0”的全部假设。建议复用SSH Connector的连接生命周期，但增加受信任`BmcSshProfile`：

```text
BmcSshProfile
├── query_power_state command + parser
├── power_on command + success matcher
├── force_off command + success matcher
└── identity command + parser
```

SSH路径只作为Redfish HTTPS不可用时的电源能力备用后端。连接、保活、主机密钥和重连复用现有SSH Connector；具体命令由内部受信任Profile提供。命令返回成功后仍需重新查询实际电源状态。SSH第一期不承担BIOS快照。

## 7. BIOS全量只读快照

第一期不实现BIOS修改。`read_all_bios_config()`流程为：

```text
定位目标ComputerSystem
→ 跟随Bios资源链接
→ 读取当前全部Attributes
→ 尽可能记录AttributeRegistry标识和Pending/Settings引用
→ 脱敏并生成不可变快照
→ 将快照位置和摘要加入运行记录
```

结果包含目标身份、采集时间、Redfish/固件版本（若可得）、全部当前Attributes和采集状态。若Redfish不可用，BIOS快照明确失败或标记不可用，不自动使用SSH猜测替代。快照过程不发送PATCH，也不安排重启。

## 8. 后端选择与回退

建议每个环境档案明确配置首选后端和允许的回退：

```text
preferred_backend: redfish
allowed_fallbacks: [ssh]
system_id: 由环境档案显式提供
```

回退必须按动作决定：

- 查询操作可以安全切换后端后重试。
- Redfish在提交动作前因服务不可达而明确失败时，可以按配置切换到SSH；身份不匹配、证书校验失败或认证失败不得用回退掩盖。
- 电源动作请求已发出但结果未知时，不得立即换后端再次发送；先查询状态。
- BIOS快照不回退到SSH。
- 实际使用的后端和回退原因写入运行记录。

## 9. 状态、错误与安全

至少区分：

- 网络不可达、TLS失败、认证失败。
- Redfish服务发现失败。
- 目标System身份不匹配。
- 动作不支持。
- 请求被拒绝。
- 请求已接受但状态未变化。
- 状态转换超时。
- BIOS读取失败或快照不完整。
- BMC连接中断且动作状态未知。

强制下电是破坏性动作。Connector只执行显式`force_off()`，不自动执行后续上电。上层运行记录必须标记调用来源、目标环境、实际后端和最终验证状态。

## 10. 当前实现边界与内网输入

公开仓库已经实现后端无关的`BmcConnector`、电源状态/动作值对象、默认幂等策略、
`ALWAYS`策略、有界状态轮询、动作结果不明时禁止重放，以及BIOS快照委托接口。公共单元测试
使用Fake Backend验证这些语义。

公开仓库不在缺少内部Redfish文档和真实设备信息时猜测设备后端。内部开发前需补齐并验证：

- 服务根、Systems集合和System ID的实际形态。
- Session创建、Token头和注销行为。
- TLS/证书要求。
- Reset动作URI、允许值、同步或Task Monitor行为。
- PowerState状态集合与转换耗时。
- Bios资源及Attributes的实际返回结构。
- BMC SSH的受信任查询、上电和强制下电命令及输出样本。

公共验证步骤记录在同目录的[BMC Connector验证计划](bmc_connector_validation.md)。含敏感细节的
实现差异和结果分别写入内网相邻的`bmc_connector_design_internal.md`与
`bmc_connector_validation_internal.md`，不得提交真实地址、账号、密码、Token或内部文档原文。

## 11. 已确认决策

- Redfish为首选，HTTPS服务失效时允许SSH作为电源能力备用路径。
- 第一期电源动作只有上电和强制下电，并保留状态查询。
- 不做正常下电、重启或Power Cycle。
- BIOS只读取全量配置用于日志留档，不做修改。
- Redfish使用Session Token。
- 环境档案能够提供明确System ID。
- BMC SSH复用现有SSH Connector，内部后续提供具体命令。
- TLS策略和Redfish设备细节作为内网验证项。
- 真实Redfish与厂商SSH Backend等待内部文档和设备资料后再实现；公共语义层不依赖这些资料。
