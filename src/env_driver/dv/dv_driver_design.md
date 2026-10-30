# DV Driver设计

> **文档定位**：DV Driver具体实现权威设计。
>
> **主要作用**：定义DV的设备组成、连接角色、五个Phase、严格上下电顺序、内部Provider边界和Ready规则。
>
> **使用方式**：修改DV公共流程或实现内部Provider前必须阅读；敏感命令和Matcher只写入内网同目录的`dv_driver_design_internal.md`。

状态：公共Driver与扩展契约已实现，待内网Provider与真实环境验证

层级：具体实现设计

上层设计：[Environment Driver模块设计](../env_driver_design.md)

相关代码：`src/env_driver/dv/`

相关设计：

- [SSH Connector设计](../../basic_connector/ssh_connector/ssh_connector_design.md)
- [网络串口Connector设计](../../basic_connector/serial_connector/serial_connector_design.md)
- [BMC Connector设计](../../basic_connector/bmc_connector/bmc_connector_design.md)

最后复核：2026-10-30

## 1. 环境边界

DV由一台Linux服务器A和一台异构计算机B组成。两者有固定的电源顺序、网络初始化和访问拓扑，对上层是一个不可拆分的`DvDriver`，不建模为两个可独立选择的Environment Driver。

```text
Windows客户端
├─ BMC --------------------------> Linux服务器A电源
├─ Serial A ---------------------> 内部控制端点A
├─ Serial B ---------------------> 异构计算机B电源/网络配置/日志
└─ SSH --------------------------> Linux服务器A
       └─ SSH tunnel -------------> 异构计算机B
```

DV第一期不读取或修改BIOS。BMC在DV中只承担Linux服务器A的强制下电和上电。

## 2. 必需连接角色

| 稳定角色 | Connector | 数量 | 公共语义 |
| --- | --- | --- | --- |
| `linux_bmc` | BMC | 1 | Linux服务器A的强制下电和上电 |
| `serial_a` | Serial | 1 | 内部初始化可使用的控制端点，不持续采集日志 |
| `serial_b` | Serial | 1 | 异构计算机B上下电、网络配置及持续日志 |
| `linux_ssh` | SSH | 1 | Windows到Linux服务器A的直连SSH |
| `accelerator_ssh` | SSH | 1 | 通过`linux_ssh`跳转到异构计算机B的SSH |

`linux_ssh`和`accelerator_ssh`各有自己的IP、port、用户名、密码凭据和主机身份。不得假设两者凭据相同，也不得因B只能经A访问就跳过B的主机密钥校验。

## 3. 串口B日志与控制会话

串口服务器允许同一`IP + port`同时建立多个客户端，因此串口B使用两条独立连接：

```text
serial_b
├─ OBSERVE_ONLY Session   LogSession所有，从初始化前持续到结束本次运行
└─ CONTROL Session        ControlContext所有，初始化完成后关闭
```

日志连接只读，不发送回车或探测命令。控制连接的Matcher只检查本次命令发送后的新输出，不读取日志连接缓冲区。

串口B日志是必需能力。如果Collector在任何设备动作之前无法建立，则停止DV初始化。初始化失败不自动停止已启动日志，以便继续保留现场。

## 4. 固定初始化Plan

```text
Plan: dv.initialize
├─ Plan外：启动必需的serial_b日志Collector
├─ Phase 0 precheck
├─ Phase 1 power_cycle
├─ Phase 2 serial_prepare
├─ Phase 3 wait_ssh
├─ Phase 4 ssh_operate
└─ verify_ready
```

Plan结构在执行前确定。内部Provider可在`serial_prepare`和`ssh_operate`中声明多个受信任Step，但不得改写Phase顺序或用一个`execute_all()`吞掉全部过程。

### 4.1 `precheck`

- 校验5个必需连接角色、凭据引用和端口配置。
- 验证BMC目标身份与电源能力。
- 建立必需的串口控制连接，不提前执行上下电或网络配置。
- SSH只做静态配置检查；B尚未配置网络，不尝试建立`accelerator_ssh`。

### 4.2 `power_cycle`

以严格顺序执行四个`OperationStep`：

```text
1.1 power.linux.force_off
1.2 power.accelerator.force_off
1.3 power.accelerator.power_on
1.4 power.linux.power_on
```

每个Step每轮都必须下发动作；即使已经是Off或On，也不跳过。Linux电源动作通过BMC Connector的显式`ALWAYS`策略完成；异构计算机动作由内部Provider使用串口B完成。

四个动作不并行。前一个Step没有取得本次成功证据时，后续Step不执行。串口命令、间隔、Matcher和证据由内网设计补充。

### 4.3 `serial_prepare`

通过串口B为异构计算机B配置IP等网络参数。该阶段是`accelerator_ssh`可用的前置条件，不能跳过。

内部Provider依据`actions(DvPhase.SERIAL_PREPARE)`返回一个或多个Step。每个Step必须声明稳定ID、超时、副作用、成功/失败证据和取消策略。

### 4.4 `wait_ssh`

1. 有界轮询`linux_ssh`，完成TCP、SSH认证及最小只读命令。
2. 复用A的任务级长连接创建`accelerator_ssh`跳转会话，独立校验B的认证和主机密钥。
3. 对B执行内部定义的最小只读命令，确认该SSH不只是完成了握手。

A未就绪时不尝试B。

### 4.5 `ssh_operate`

内部Provider依据`actions(DvPhase.SSH_OPERATE)`返回多个业务Step。普通命令使用`ManagedSSHSession.run()`；文本问答或菜单使用客户端的`InteractiveSSHSession`，不要求B安装`expect`。

交互形式是文本提示、输入后回车，不是全屏curses/TUI。第一期支持可选PTY，但不实现ANSI虚拟屏幕。多个业务Step复用同一交互进程：

```text
ManagedSSHSession（所有底层Channel）
└─ InteractiveSSHSession
   └─ DvExecutionState.interactive（跨Step引用）
```

首个交互Step打开进程，后续Step复用，末个Step正常退出。中途失败时，`ManagedSSHSession.close()`和`ControlContext.close()`兜底回收。如果存在等价的稳定CLI、配置文件或API，内网实现优先选择非交互路径。

## 5. `DvContributionProvider`边界

公共Driver不包含真实命令、菜单文本、IP规则、Matcher或最终业务检查。内网代码实现：

```python
class DvContributionProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    def validate(self, request: DvRunRequest) -> ValidationReport: ...

    def actions(self, phase: DvPhase) -> tuple[DvActionDefinition, ...]: ...

    async def execute_power_action(
        self,
        action: DvPowerAction,
        context: DvActionContext,
    ) -> StepResult: ...

    async def probe_ssh(
        self,
        endpoint: DvSshEndpoint,
        context: DvActionContext,
    ) -> StepResult: ...

    async def execute_action(
        self,
        action_id: str,
        context: DvActionContext,
    ) -> StepResult: ...

    async def verify_ready(self, context: DvActionContext) -> ReadinessResult: ...
```

`DvPhase`第一期只允许`SERIAL_PREPARE`和`SSH_OPERATE`。`DvActionDefinition`至少包含`action_id`、`title`、`phase`、`side_effect`、`timeout`、`success_evidence`、`failure_evidence`和`cancellation_policy`。

`DvActionContext`可提供不可变配置快照、`ControlContext`、取消信号、证据写入位置和任务级`DvExecutionState`。Provider不得绕过Connector操作原始Socket或AsyncSSH对象，也不得从工作空间动态导入任意Python代码。

## 6. 最终Ready规则

Plan内全部Step成功后，`verify_ready()`独立验证：

1. Linux服务器A SSH可连接，且最小只读命令成功。
2. 经A跳转的异构计算机B SSH可连接，且最小只读命令成功。
3. 内部Provider的环境专属只读Ready检查成功。

最终检查不得重新上下电、重新配置网络或重放交互操作。

## 7. 失败、取消和重试

- 串口B必需日志Collector启动失败时，在任何设备动作前停止。
- 电源、网络配置和交互操作默认不自动重放。
- 操作已发送但未取得完成证据时返回`unknown`，停止后续修改性Step。
- A SSH断开时，B的跳转会话及交互Channel全部失效。可重建底层SSH，但不自动恢复或重放交互上下文。
- `collect_failure_context()`只允许收集有界的BMC状态、串口日志尾部、SSH状态和交互Transcript尾部，不执行修复。

## 8. 初步耗时分类

| 阶段/操作 | 判断 | 建议初始上限 | 主要不确定性 |
| --- | --- | --- | --- |
| 启动串口B日志 | 短 | 10秒 | 串口服务器可达性 |
| `precheck` | 短 | 30秒 | BMC/串口建连和身份检查 |
| `power_cycle` | **高** | 10分钟 | 电源转换、启动间隔和串口证据 |
| `serial_prepare` | 中或未知 | 10分钟 | 内部网络配置步骤 |
| 等待A SSH | **高** | 20分钟 | Linux启动时间 |
| 等待B跳转SSH | 中或高 | 10分钟 | B网络、SSH服务和跳转链路 |
| `ssh_operate` | **高或未知** | 内部每Step指定，默认60分钟 | 交互流程和远端处理时间 |
| `verify_ready` | 中 | 10分钟 | 内部稳定性检查 |

上述为待内网实测的第一版预算，不是性能承诺。内网设计必须为每个内部Step记录正常耗时、总超时、空闲超时和成功/失败证据。

## 9. 内网待补全清单

内网仓库在同目录创建`dv_driver_design_internal.md`，至少补充：

- 串口A/B真实角色与设备身份。
- 异构计算机上下电命令、行结束符、Matcher和时间间隔。
- 串口B网络配置的小Step、参数、超时和验证方式。
- A和B的最小SSH就绪命令。
- B上普通SSH命令与交互进程的状态机、提示文本、敏感输入和脱敏规则。
- 是否存在等价的非交互CLI/配置文件/API。
- 环境专属Ready检查、成功证据和真机耗时。

真实IP、端口、用户名、密码、命令、内部设备名和输出样本不得进入本公共文档或GitHub。

## 10. 公共实现状态与内网后续

已完成的公共能力：

1. SSH Connector已增加行式`InteractiveSSHSession`及清理、超时、取消、增量Matcher和Transcript边界测试。
2. BMC Connector已增加显式`ALWAYS`动作策略，并保留默认`IF_NEEDED`幂等策略。
3. DV已实现固定五阶段Plan、Provider Registry、必需串口B日志、严格电源顺序、A到B跳转SSH和最终Ready检查。
4. 公共单元测试覆盖固定顺序、必需日志启动失败、动作结果不明、跳转SSH及最终Ready失败。

内网下一步是实现`DvContributionProvider`，并按
[DV Driver验证清单](dv_driver_validation.md)执行可选Live Test。没有真实设备时不得将Fake或公共单元测试描述为Live Test成功。
