# EVB Driver设计

> **文档定位**：EVB Driver具体实现权威设计。
>
> **主要作用**：定义制品准备、FileZilla安全、四Phase、Provider边界和最终Ready规则。
>
> **使用方式**：修改EVB公共流程或实现内部Provider前阅读；实施状态继续查看本目录实施计划。

状态：公共实现已完成，等待内部实现与真实环境验证

层级：具体实现设计

上层设计：[Environment Driver模块设计](../env_driver_design.md)

相关代码：`src/env_driver/evb/`

实施计划：[EVB Driver实施计划](evb_driver_implementation_plan.md)

跨模块设计：[版本目录设计](../../../design/artifact_version_design.md)

最后复核：2026-10-28

## 1. 第一阶段目标

`EvbDriver`负责把一套EVB从“已选择环境和版本”推进到“可以执行测试”。完整初始化包含四个Phase：

1. 备料：取得同一版本的固件、启动脚本、驱动和三方包。
2. 配置：准备FileZilla固件目录、工作空间文件和启动脚本配置。
3. 启动：通过内部适配层调用已有启动框架并等待各小步骤成功。
4. 环境上操作：EVB SSH就绪后上传驱动和三方包，完成内部操作。

四个Phase全部成功后，框架仍调用独立的`verify_ready()`。只有最终只读检查通过，环境才标记为Ready。

具体芯片代号、5个串口真实名称、制品真实文件名、启动参数映射、内部操作命令和成功标志不进入公共实现，由内部适配层补齐。

## 2. 已确认的三类目录

### 2.1 用户选择的工作空间

“工作空间”就是客户端主界面“01 工作空间”显示的目录，例如：

```text
F:/Codes/ebon_blade_tmp/
```

它是所有本地配置、版本缓存、启动准备文件和运行记录的共同根目录，不等同于单次运行日志目录。

```text
<workspace>/
├── workspace.json
├── versions/
│   └── <platform>/<version>/
│       ├── firmware.zip
│       ├── boot-script.zip
│       ├── driver.zip
│       └── third-party.zip
├── <内部适配层声明的启动脚本目录或文件>
├── <内部适配层声明的驱动压缩包目标>
├── <内部适配层声明的三方包目标>
└── runs/<run-id>/...
```

启动脚本、驱动和三方包在配置阶段准备到工作空间范围内。真实目标名由受信任适配层声明。平台只能替换适配层明确拥有的相对路径，绝不能清空工作空间根目录。

### 2.2 版本缓存

`<workspace>/versions/<platform>/<version>/`长期保存四个原始压缩包。本地目录存在时直接复用；不存在时通过Linux版本机的SSH/SFTP下载。

同一次环境组合中，不同EVB分别选择版本。若多个EVB选择相同`platform + version`，Run级备料协调器只执行一次远端下载；后续EVB复用同一本地缓存并把备料Step记为`SKIPPED/reused`。

### 2.3 FileZilla固定目录

FileZilla根目录是每台执行机的本机设置，位于工作空间之外。它不按版本建立子目录：

```text
<filezilla-root>/
└── 本次固件解压后的内容
```

每次EVB初始化都必须：

1. 对规范化后的FileZilla根目录取得跨任务独占锁。
2. 验证它不是盘符根目录、工作空间、工作空间父目录、用户目录或系统目录。
3. 清空目录内旧内容。
4. 直接从版本缓存中的`firmware.zip`解压到该目录。
5. 确保FileZilla目录中没有遗留的固件ZIP。

版本缓存中的原始固件ZIP始终保留。如果内部解压工具必须临时复制ZIP，只删除临时副本。

独占锁从清空目录前持有，至少持续到启动适配层明确报告设备不再读取固件。启动结果未知时不能立即让另一个任务覆盖目录；锁保持到本次运行结束或用户明确处置未知状态。

## 3. 配置归属

| 配置层 | 内容 | 界面位置/保存方式 |
| --- | --- | --- |
| 本次EVB目标 | `platform + version` | 每个EVB环境行都有可见版本选择框，不藏进配置详情 |
| EVB环境档案 | PN码；BMC IP/掩码/网关；EVB-GE目标IP/掩码/网关；5个串口IP/端口；EVB SSH端口、用户名、密码 | “配置详情”；保存到工作空间，第一期允许SSH密码明文保存 |
| 执行机本机设置 | Linux版本机地址/账号；FileZilla根目录、用户名、密码；启动框架/运行时位置 | “本机设置”；FileZilla账号密码允许明文保存，Linux版本机密码仍按运行时输入策略处理 |
| 内部适配配置 | 芯片代号、串口真实角色、文件名、参数模板、内部Step、成功/失败标志、最终检查 | 受信任内部Python/Profile，不从工作空间动态加载代码 |

BMC IP是设备已经具备的连接地址，只传给启动脚本。EVB-GE IP是启动阶段写入设备的目标地址；启动Phase成功前，平台不得尝试连接该EVB SSH地址。

## 4. 总体流程

```mermaid
flowchart LR
    Logs[先启动日志会话<br/>5路串口持续采集]
    P0[Phase 0 备料<br/>缓存缺失时高耗时]
    P1[Phase 1 配置<br/>固件解压可能高耗时]
    P2[Phase 2 启动<br/>高耗时且可能有设备副作用]
    P3[Phase 3 环境上操作<br/>上传与内部操作可能高耗时]
    Ready[verify_ready<br/>独立只读检查]

    Logs --> P0 --> P1 --> P2 --> P3 --> Ready
    Logs -.持续到结束本次运行.-> Ready
```

耗时等级只用于第一轮评审，不是性能承诺：

- 短：通常小于10秒。
- 中：通常10秒～2分钟。
- 高：可能超过2分钟，或受文件大小、网络、烧录/启动状态影响明显。
- 未知：公共仓库无法估计，必须由内部实测补齐。

## 5. 初始化Plan与初步耗时判断

### 5.1 Plan外的日志启动

| 动作 | 耗时判断 | 初始上限 | 完成依据 |
| --- | --- | --- | --- |
| 创建日志目录 | 短 | 5秒 | 目录创建成功 |
| 并行连接5个串口只读Collector | 短；5秒内失败即认为不可连接 | 5秒 | 5路TCP连接均建立并开始Reader |
| 启动延迟EVB SSH Collector | 短 | 5秒 | 后台等待任务已启动；此时不连接尚未配置的EVB IP |

5路串口日志是EVB初始化的必需能力。任一必需Collector启动失败，应在操作设备前停止初始化，而不是只记一条警告继续执行。BMC SSH不创建持续日志Collector。

### 5.2 Phase 0：备料 `material`

| Step | 类型 | 耗时判断 | 建议总超时 | 成功依据 |
| --- | --- | --- | --- | --- |
| `0.1 artifacts.resolve` 解析每个EVB的`platform + version` | Check | 短 | 5秒 | 版本引用和工作空间路径合法 |
| `0.2 artifacts.ensure_local` 确保四类压缩包进入版本缓存 | Operation | 缓存命中为短；缓存缺失为**高** | 10分钟（总量不超过5GB） | SFTP递归下载结束，临时目录原子改名为最终版本目录 |
| `0.3 artifacts.require_bundle` 检查四类逻辑制品存在 | Check | 短 | 10秒 | 固件、启动脚本、驱动、三方包均被内部文件映射解析到 |

同一Run内第二个EVB使用相同版本时，`0.2`返回`SKIPPED`并注明复用了哪个缓存准备结果，不再次访问Linux版本机。

### 5.3 Phase 1：配置 `configure`

| Step | 类型 | 耗时判断 | 建议总超时 | 成功依据 |
| --- | --- | --- | --- | --- |
| `1.1 filezilla.acquire_lease` 取得固定目录独占锁 | Operation | 通常短；被占用时是等待 | 30秒 | 当前任务持有以规范化根目录为键的跨进程锁 |
| `1.2 filezilla.validate_root` 做删除前安全检查 | Check | 短 | 5秒 | 路径存在/可写且不属于禁止目标，并通过所有权标记检查 |
| `1.3 filezilla.clear_root` 清空旧固件内容 | Operation/Destructive | 中；旧文件很多时可能高 | 5分钟 | 目录为空，删除失败项为0 |
| `1.4 firmware.extract` 将固件解压到FileZilla根目录 | Operation | **高** | 5分钟 | 安全解压完成、目标内容存在、根目录无固件ZIP |
| `1.5 workspace.prepare_artifacts` 将启动脚本、驱动、三方包准备到工作空间 | Operation | 中（总量不超过5GB） | 5分钟 | 适配层声明的三个目标路径均准备完成 |
| `1.6 startup.extract` 解压启动脚本 | Operation | 中（脚本包不超过1GB） | 2分钟 | 入口及必需资源存在 |
| `1.7 startup.render_config` 写入网络、串口、FileZilla、PN码等配置 | Operation | 短 | 30秒 | 模板渲染成功且无未替换变量 |
| `1.8 startup.validate_effective_config` 校验最终传给脚本的配置快照 | Check | 短 | 30秒 | 地址、端点、路径和版本相互一致 |

ZIP解压必须拒绝绝对路径、`..`越界和不允许的链接项，避免压缩包写出目标目录。

### 5.4 Phase 2：启动 `start`

启动Phase由内部适配层提供一个或多个`startup.<action-id>` Step。每个Step都必须有独立标题、成功标志、失败标志、总超时和SideEffect，不允许用一个“执行整个GUI脚本”的黑盒Step吞掉所有过程。

| Step | 类型 | 耗时判断 | 建议总超时 | 成功依据 |
| --- | --- | --- | --- | --- |
| `2.n startup.<action-id>` 内部启动/烧录/复位/网络设置动作 | Provider Operation | **高或未知** | 默认60分钟，内部逐项覆盖 | 该Step自己的expect、回调或只读状态检查命中 |
| `2.last startup.confirm_complete` 快速复核启动框架完成且EVB-GE目标地址已经写入 | Check/Provider | 短 | 30秒 | 复核各`2.n`已经取得的本次成功证据，不能命中历史日志 |

等待过程优先使用串口新输出、适配层回调或只读轮询。只有没有可观察信号时才允许固定延时。启动动作默认不自动重试；连接断开或超时时若无法证明远端动作停止，结果为`UNKNOWN`。

启动成功后释放FileZilla独占锁。启动失败但动作已明确结束时可以释放；动作状态未知时锁保持到显式结束运行或人工处置。

### 5.5 Phase 3：环境上操作 `operate`

| Step | 类型 | 耗时判断 | 建议总超时 | 成功依据 |
| --- | --- | --- | --- | --- |
| `3.1 evb_ssh.wait_ready` 使用启动后生效的EVB IP等待SSH | Check/Poll | **高** | 20分钟 | TCP、SSH认证及内部最小就绪命令均成功 |
| `3.2 evb_ssh.collector_ready` 确认持续SSH日志Collector已接入 | Check | 短 | 15秒 | `3.1`确认SSH可用后，内部Collector报告开始采集本次连接日志 |
| `3.3 packages.upload_driver` SFTP上传驱动包 | Operation | 中（文件不超过5GB） | 10分钟 | 原子上传完成且远端大小与本地一致 |
| `3.4 packages.upload_third_party` SFTP上传三方包 | Operation | 中（文件不超过5GB） | 10分钟 | 原子上传完成且远端大小与本地一致 |
| `3.n environment.<action-id>` 执行内部环境操作 | Provider Operation | **高或未知** | 默认60分钟，内部逐项覆盖 | 每个内部Step自己的成功/失败标志和验证 |

EVB SSH Connector对象可以在Plan开始前构造，但`3.1`之前不得实际连接。驱动和三方包上传默认不自动重试；如内部能证明上传目标是纯临时文件，可在内部定义一次安全重试。

### 5.6 独立最终检查 `verify_ready()`

| 动作 | 耗时判断 | 建议总超时 | 成功依据 |
| --- | --- | --- | --- |
| 内部只读最终就绪检查 | 中；需要等待稳定时可能高 | 10分钟 | 内部适配器返回可追溯的ReadinessResult |

最终检查不得再次烧录、复位、上传或安装。具体命令和标志在内部实现，但结果必须带摘要和证据引用。

## 6. `EvbContributionProvider`边界

内部Provider解决不同芯片和不同版本启动源码的差异，公共EVB Driver只依赖窄协议：

```python
class EvbContributionProvider(Protocol):
    def validate(self, request: EvbRunRequest) -> ValidationReport: ...

    def actions(self, phase: EvbPhase) -> tuple[EvbActionDefinition, ...]: ...

    async def execute_action(
        self,
        action_id: str,
        context: EvbActionContext,
    ) -> StepResult: ...

    async def verify_ready(
        self,
        context: EvbActionContext,
    ) -> ReadinessResult: ...
```

`EvbActionDefinition`至少包含：

```text
action_id
title
phase（configure/start/operate）
side_effect
timeout
success/failure evidence description
cancellation policy
```

`EvbActionContext`向适配层提供：

- 不可变的本次配置快照。
- 四类制品的缓存路径。
- 用户选择的工作空间根目录。
- FileZilla根目录和已取得的Lease。
- 由框架管理的Connector访问能力。
- 当前Step日志/证据写入入口和取消信号。

适配层可以在同进程调用版本源码，也可以隔离到子进程；公共接口不绑定实现方式。但不得从工作空间动态导入任意Python插件，不得绕过PlanExecutor自行把所有阶段串成一个黑盒流程，也不得返回没有证据的“成功”。

## 7. `EvbDriver`公共函数

| 函数 | 第一阶段行为 |
| --- | --- |
| `definition()` | 声明EVB类型、5个串口日志角色和EVB SSH角色 |
| `validate_config()` | 校验档案、本次版本、本机设置和适配器是否齐全；汇总全部可发现问题 |
| `dependencies()` | 第一阶段返回空；以后组合环境再显式声明 |
| `create_log_collectors()` | 创建5个独立串口只读Collector和一个延迟EVB SSH Collector |
| `build_initialize_plan()` | 构造固定4个Phase，并把受信任适配层的小步骤包装为普通Step |
| `verify_ready()` | 委托内部适配器执行独立只读检查 |
| `collect_failure_context()` | 只读收集适配器状态、SSH尾部和Collector健康状态，不执行恢复动作 |

## 8. 日志与层级

建议运行目录：

```text
<workspace>/runs/<run-id>/
└── env/<evb-id>/
    ├── collectors/
    │   ├── serial_a.raw.log
    │   ├── serial_b.raw.log
    │   ├── serial_c.raw.log
    │   ├── serial_d.raw.log
    │   ├── serial_e.raw.log
    │   └── evb_ssh.log
    └── control/
        ├── effective-startup-config.json
        ├── adapter-events.jsonl
        └── step-results.jsonl
```

日志标签使用Plan原生层级，例如：

```text
[phase 1 configure][step 1.4 firmware.extract] started
[phase 1 configure][step 1.4 firmware.extract] succeeded elapsed=...
```

凭据即使允许明文保存在工作空间，也不得进入普通运行日志、异常文本、Provider事件或配置快照；快照必须脱敏。

## 9. 失败、取消和重试

- Phase内任一必需Step失败，停止后续Step。
- 下载、解压和上传使用临时目标，完成后再切换；半成品不能被当成成功结果。
- 只读轮询可以在Step超时内重复；会改变设备状态的动作默认不自动重放。
- 下载和本地解压可以安全响应取消并清理自己的临时文件。
- 启动/烧录动作取消时只停止后续调度；除非内部适配明确证明可安全终止，否则不强杀远端动作。
- FileZilla清空后失败，必须明确报告“当前目录未准备完成”，不能沿用旧Ready状态。
- 所有未知状态保留串口与SSH日志，不自动重烧、复位或再次启动。

## 10. 需要用户重点评审的耗时判断

当前判断为高耗时的步骤：

1. 缓存缺失时从Linux下载完整版本。
2. 固件解压到FileZilla根目录。
3. 内部启动/烧录/复位/网络设置步骤。
4. 等待EVB SSH就绪。
5. 内部环境操作及可能需要等待稳定的最终检查。

其中内部启动和环境操作无法在公共仓库中估算，需要内部按真实脚本拆分后逐项填写正常耗时和超时。文件准备与两个SFTP上传按正常中耗时、异常上限5～10分钟处理。其余建议超时仍需真实环境验证后调整。
