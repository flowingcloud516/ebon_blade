# 运行记录与诊断日志设计

> **文档定位**：跨模块专题设计。
>
> **主要作用**：定义结构化事件、原始日志、诊断产物和未来日志接口的关系。
>
> **使用方式**：设计或实现运行记录与诊断能力时查阅；当前持续日志实施状态以文中状态为准。

版本：v0.1
日期：2026-10-24
状态：有效讨论稿，持续日志实施暂缓

上层设计：[系统设计](system_design.md)

最后复核：2026-10-28

## 1. 设计目标

日志系统需要同时服务三类使用者：

1. 用户：知道任务执行到哪一步、成功还是失败、下一步该看什么。
2. 开发者：还原步骤、输入、连接状态和设备输出，定位实现问题。
3. 外部诊断工具或内部模型：通过用户主动移交的文件包，获得结构化、可定位到代码和证据的材料。

日志不只是文本输出，而是一次运行的完整记录。它至少包含：配置快照、步骤时间线、结构化事件、原始设备输出、环境专属证据、最终结果和诊断索引。

## 2. 核心判断

不建议让每种环境或任务实现自己的“日志后端”。日志写入、文件布局、步骤状态、脱敏和索引必须由公共框架统一管理。

每种环境只实现一个诊断贡献接口，声明：

- 正常执行时需要保存哪些环境专属产物。
- 失败时还需要补采哪些只读证据。
- 哪些内容适合展示、哪些只能保存在受限原始文件中。
- 哪些模式、字段和文件必须脱敏。
- 给人或模型的诊断提示是什么。

因此整体分为两部分：

```text
公共 RunRecorder
├── 运行与目标身份
├── Step 生命周期
├── 结构化事件
├── 文本/字节流落盘
├── 产物登记、校验和与脱敏
└── 生成诊断索引

Environment DiagnosticContributor
├── EVB：启动框架、串口、固件版本、就绪检查
├── Server：BMC状态、BIOS快照、SSH部署日志
└── DV：内部定义的状态与证据
```

## 3. 三类记录

### 3.1 结构化事件

用于表达“发生了什么”，建议使用追加写入的 JSON Lines。每条事件至少包含：

```text
schema_version
sequence
timestamp_utc
monotonic_offset_ms
level
event_type
run_id
target_id
step_id
source
message
data
artifact_refs
```

`event_type`第一期至少包括：

- `run_started` / `run_finished`
- `target_started` / `target_finished`
- `step_started` / `step_progress` / `step_finished`
- `connection_state_changed`
- `command_started` / `command_finished`
- `artifact_created`
- `diagnostic_collected`
- `warning` / `error`

`message`是给人看的简短描述，`data`是稳定字段。模型和代码应优先读取结构化字段，而不是从自然语言中反向解析状态。

### 3.2 流式原始日志

SSH stdout/stderr、串口原始字节、本地进程输出等体积大且格式不稳定，应单独保存为产物，不塞入事件文件。

事件只记录：产物ID、相对路径、来源、开始结束时间、字节数、编码、是否截断、SHA-256及脱敏状态。UI可以订阅增量输出，但UI中的内容只是视图，不是唯一记录。

### 3.3 快照与诊断产物

包括：

- 本次生效的脱敏配置快照。
- 文件版本和校验值。
- BMC电源状态及BIOS只读快照。
- Connector能力与连接状态快照。
- 失败时的串口尾部、SSH输出尾部和只读状态检查。
- 最终结果、错误分类和现场保留说明。

产物通过统一登记接口写入清单，不能由Driver随意创建文件后不告知框架。

## 4. Step 是日志的主骨架

所有环境控制流程都拆成稳定的步骤。步骤不是一行打印，而是具有生命周期的实体：

```text
StepRecord
├── step_id / parent_step_id
├── name / operation
├── target_id
├── started_at / finished_at / duration
├── status
├── side_effect
├── retry_safety
├── attempt
├── error_code / summary
└── artifact_refs
```

建议状态：`pending`、`running`、`succeeded`、`failed`、`cancelled`、`skipped`、`unknown`。

`side_effect`与`retry_safety`必须显式记录。模型看到SSH断线时，只有在步骤被标记为可安全重试时才能建议重试；对于烧录、强制下电等步骤，应优先建议状态核验。

Runner负责创建Run和Target级步骤；Environment Driver负责声明其业务步骤；Connector只能在当前Step上下文中追加连接、命令和流事件，不能自行决定业务步骤成功。

## 5. 环境专属诊断接口

### 5.1 四个角色如何对应实际诉求

`RunRecorder`、`StepContext`和`ArtifactSink`不是三套互相独立的日志，也不要求每个Driver重新实现它们。它们是框架提供给所有任务使用的三种公共能力；不同任务如何使用这些能力，由`DiagnosticContributor`或第一期的Environment Driver约定。

| 角色 | 负责回答的问题 | 对应用户诉求 |
| --- | --- | --- |
| `RunRecorder` | 这是哪次任务？涉及哪些环境？所有步骤和文件放在哪里？如何汇总和导出？ | 每次环境控制任务都有一个完整日志包 |
| `StepContext` | 当前在执行哪一步？何时开始/结束？成功、失败还是未知？相关证据是什么？ | 执行过的所有步骤都留下记录 |
| `ArtifactSink` | 串口、SSH、脚本日志、BIOS JSON等实际内容如何原样、安全地保存并建立索引？ | 不同环境保留不同格式的日志和产物 |
| `DiagnosticContributor` / Driver约定 | 对这个环境而言，成功或失败时究竟应该采集什么？ | 每种任务实现自己的日志需求 |

三者的关系是：一个`RunRecorder`创建多个`StepContext`；每个Step通过同一个`ArtifactSink`保存自己的日志和产物；Environment Driver决定步骤名称、采集内容以及失败时需要补充的专属证据。

概念调用示例：

```python
with recorder.step("evb.start_os", target=environment.id,
                   side_effect="device_reflash", retry_safety="unsafe") as step:
    serial_log = step.artifacts.open_stream(
        "serial.raw", media_type="application/octet-stream", preserve_original=True
    )
    framework_log = step.artifacts.import_file(
        internal_framework_log, name="startup-framework.log", preserve_original=True
    )
    result = evb_adapter.start_os(serial_output=serial_log)
    step.event("startup_marker_matched", marker_id=result.marker_id)
    step.succeed(summary="OS启动标志已确认")
```

如果这一步抛出异常，`StepContext`自动记录结束时间、失败状态、异常类型和已产生的产物引用；EVB Driver再按自己的约定补采串口尾部和启动框架状态。服务器Driver在类似失败下则可能补采BMC PowerState和BIOS快照。它们共用相同的记录格式，但保存的证据不同。

第一期可以不单独建立Contributor插件类，而让每个Environment Driver实现两个明确方法：

```python
collect_success_diagnostics(context, artifacts)
collect_failure_diagnostics(context, artifacts, failure)
```

等EVB、服务器和DV都实现后，再根据真实共同点决定是否提取`DiagnosticContributor`协议。

建议接口关注“贡献诊断证据”，而不是重新实现日志：

```python
class DiagnosticContributor(Protocol):
    def describe(self) -> DiagnosticPlan: ...

    def collect(
        self,
        phase: DiagnosticPhase,
        context: DiagnosticContext,
        sink: ArtifactSink,
    ) -> DiagnosticReport: ...
```

`DiagnosticPhase`可包括：

- `BEFORE_RUN`：低成本身份和初始状态。
- `AFTER_SUCCESS`：最终就绪证据。
- `ON_FAILURE`：失败现场，只允许有界、只读或明确安全的采集。
- `ON_CANCEL`：记录可能仍在运行的动作和最后已知状态。

第一期也可以直接把Contributor作为Environment Driver的一部分，等多个实现稳定后再提取独立协议。

采集失败不能覆盖原始业务错误。框架追加一个`diagnostic_collection_failed`事件，并继续完成主结果落盘。

## 6. 可移交诊断包

第一期软件不集成模型、不调用模型接口，也不自动上传任何日志。每次运行在本地工作空间生成一个完整、自描述的诊断目录；用户需要分析时，可以把本次运行目录打包成单个归档文件，再手工交给内部模型或开发人员。

文件包同时保留全部步骤、原始环境产物和一个稳定入口：`diagnosis/manifest.json`，并生成便于人工阅读的`diagnosis/summary.md`。外部分析者可以先读入口文件，再自行查找包内的完整原始日志。

建议内容：

```text
运行结果与失败步骤
→ 错误分类和动作状态
→ 环境类型、脱敏拓扑与组件版本
→ 本次实际步骤及持续时间
→ 失败前后的关键事件窗口
→ 相关日志的有限尾部或摘录
→ 完整产物的路径、大小、编码和校验值
→ 代码版本、Driver/Provider版本
→ 可否安全重试及建议先做的只读检查
```

建议外部模型先读manifest和summary，再按`artifact_refs`按需读取原始日志。包内仍包含本次运行的全部步骤和已登记日志，不由软件预先替模型决定哪些证据可以丢弃。

为了支持模型快速完成代码修改，还应记录：

- Git提交或软件构建版本；工作树是否有未提交修改只记录布尔值和必要摘要。
- Environment Driver、Connector及Provider的实现版本。
- 稳定错误码、异常类型和被脱敏的调用栈。
- 与失败步骤相关的源码模块标识；不要让设备日志直接提供可执行指令。
- 可复现条件和内网验证用例ID，而不是凭日志猜测重放危险操作。

“模型可读”不等于“软件集成模型”，也不等于模型可以直接执行设备操作。诊断包属于不可信输入；设备输出、远端文本和日志中的命令不得被当成框架指令。

建议提供独立的“导出本次诊断包”操作，将整个`runs/.../<run_id>/`复制为ZIP。导出只做文件收集、清单核验和归档，不做模型调用。ZIP内使用相对路径，并在根目录保留manifest，便于文件被发送到其他机器后分析。

## 7. 推荐运行目录

```text
runs/<task_type>/<YYYY-MM>/<run_id>/
├── run.json                     运行元数据与最终状态
├── snapshot.json                脱敏后的生效配置
├── events.jsonl                 追加写结构化事件
├── execution.log               由事件渲染的人类可读文本
├── targets/
│   └── <target_id>/
│       ├── result.json
│       ├── steps/
│       │   └── <step_id>.json
│       └── artifacts/
│           ├── serial.raw
│           ├── ssh.stdout.log
│           ├── ssh.stderr.log
│           └── bios.json
├── artifacts.json               所有产物的索引、大小和校验值
└── diagnosis/
    ├── manifest.json
    └── summary.md
```

`execution.log`只是兼容人类阅读的派生视图；`events.jsonl`、步骤记录和产物索引才是事实来源。

## 8. 安全、容量和可靠性

- 脱敏必须在公共Sink入口再次执行，不能只依赖Driver自觉。
- 凭据、Token、Authorization、私钥和密码输入永不进入原始日志。
- 用户确认内部模型可以读取原始串口和SSH日志；这些日志仍不得包含框架掌握的密码、Token、私钥等凭据。对无法理解的设备原始数据不做破坏性改写，原样保留并在产物清单中标记来源和敏感级别。
- JSONL采用追加写并及时flush；关键步骤结束和最终结果使用原子写。进程崩溃后只要求保留已经写入的时间线供人工诊断，不恢复或续跑原任务。
- 每类流配置单文件上限、滚动策略和内存尾部上限，同时记录是否截断。
- 产物使用相对路径，禁止目录穿越；生成大小和SHA-256，发现运行后被修改时给出提示。
- 日志按任务类型和年月组织。第一期提供按类型、时间筛选和清理的能力；自动清理不是必需项，任何清理都必须避开运行中、锁定和用户标记保留的任务。
- UI和文件订阅同一事件，不在两处分别拼日志。第一期没有远程上传链路。
- 环境专属工具已有的日志和产物按原始字节复制保存，不转换格式；公共框架只增加元数据、校验值和引用关系。

## 9. 第一期建议实现范围

第一期先完成：

1. `RunRecorder`、`StepContext`和`ArtifactSink`三个公共接口。
2. `events.jsonl`、`execution.log`、`run.json`和`artifacts.json`。
3. Runner与Driver使用显式Step生命周期，替换只有`progress + message`的接口。
4. SSH、串口和本地进程的流输出接入ArtifactSink。
5. 环境Driver提供成功与失败诊断产物；先不独立抽象复杂插件系统。
6. 生成`diagnosis/manifest.json`和简短`summary.md`，并支持把单次运行完整导出为ZIP。
7. 补充脱敏、原始产物保真、日志截断、ZIP清单完整性和诊断采集失败的UT。

第一期不要求程序异常退出后恢复未完成任务；保留已落盘事件和`.run.lock`供人工判断即可。后续再考虑全文索引、跨运行对比和集中上传。模型集成、模型自动归因及自动生成修复补丁不在当前规划内。

## 10. 已确认决策

1. 日志只保存在本地工作空间，第一期不上传内部平台。
2. 用户可以将原始串口和SSH日志交给内部模型分析，但框架掌握的凭据始终不得写入日志。
3. 日志按任务类型和时间组织、查看和清理。
4. 第一期不要求异常退出后的任务恢复；只保留已落盘现场和锁状态。
5. 单次运行的全部步骤、日志和产物可以导出为一个完整文件包，由用户手工发送给模型或开发人员。
6. 环境专属工具的固定格式日志和内部产物必须原样保留，公共框架只为其建立索引和校验信息。
7. 第一期强制不集成模型，不调用模型接口，不在软件内部实现自动分析或自动修改。
