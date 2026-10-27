# 外部与内部代码维护边界

状态：第一版草案，等待评审

最近更新：2026-10-27

本文回答的不是“如何完全消除Git冲突”，而是：哪些代码应由外部长期维护，哪些由内部维护，哪些允许内外共同完善。目标是把不可避免的冲突限制在少量插件集成文件中。

## 1. 三类所有权

### A. 外部专属区

由外部维护。内网同步后直接使用，内部模型原则上不得修改。

这部分的共同特点是：通用、非敏感、实现难度高、错误会影响所有插件，或者需要长期保持行为一致。

### B. 内外协作区

主要是具体EnvModel、Benchmark或其他业务插件的“公共骨架与集成层”。外部先搭建结构和公共步骤，内部可能基于真实环境继续调整，因此允许内网分支保留少量修改。

这部分允许产生Git冲突，但要通过细文件、稳定接口和小提交把冲突范围控制住。能抽回外部的通用改进，应及时回到GitHub，避免长期积累内部补丁。

### C. 内部专属区

只在内网仓库维护，外部仓库没有对应文件。包含敏感信息、内部脚本、真实规则和真实验证。

## 2. 应当放在外部维护的内容

### 2.1 产品与运行框架

- GUI壳、工作空间创建/打开/保存和schema迁移。
- 插件发现、注册、启用/禁用和兼容性检查。
- Run编排、多环境顺序、依赖、状态汇总和结果模型。
- Plan、Phase、Step、Executor、Step状态和SideEffect语义。
- 超时、取消、失败传播、UNKNOWN处理和通用重试规则。
- 日志生命周期、目录结构、脱敏、诊断包和证据引用。
- 线程/异步执行、UI进度更新和程序退出清理。

### 2.2 公共工具

- SSH Connector及命令、expect、SFTP、跳板、重连和主机密钥策略。
- Serial Connector及共享连接、observe、expect、缓冲、重连和原始日志。
- BMC/Redfish公共能力。
- 本地进程Connector、文件传输、压缩包安全解压。
- 文件锁、目录安全、防止误删和原子文件替换。
- 版本缓存、远端下载和同版本备料去重。

### 2.3 公共Step和能力组件

- `WaitForSSHStep`、`SSHCommandStep`、`SFTPUploadStep`。
- `SerialExpectStep`、`PollUntilStep`。
- `EnsureLocalVersionStep`、`SafeExtractStep`。
- `FileZillaPrepareStep`和目录Lease。
- 通用模板渲染、配置校验和结果检查构件。
- 通用Collector及Collector健康检查。

### 2.4 插件SDK和测试基础设施

- `EnvironmentModel`、`BenchmarkModel`等抽象接口。
- 插件Manifest、API版本、Registry和Context。
- 配置schema、Action定义、结果类型和证据模型。
- Fake Connector、Fake Plugin、契约测试和测试夹具框架。
- 插件脚手架和内部模型可直接填写的模板。

### 2.5 安全和一致性规则

- 哪些路径允许删除、哪些凭据必须脱敏。
- 插件不能绕过Executor、不能假成功、不能动态加载工作空间代码。
- Step ID、日志层级、超时和取消的统一规则。
- 向前兼容、弃用和配置迁移机制。

## 3. 可以内外协同维护的内容

这一层按“具体插件”划分，例如EVB Model、某类服务器Model、某类Benchmark。

### 3.1 EnvModel协作内容

- 该环境有哪些Phase以及大致顺序。
- 哪些配置项需要在主界面展示，哪些在环境档案中维护。
- 公共Step与内部Step的插入位置。
- 插件如何组合公共Connector和公共Step。
- 插件最终对框架暴露哪些能力。
- 非敏感的错误分类和用户提示。
- 该插件特有但可以公开的通用逻辑。

以EVB为例，以下内容适合协作区：

- 备料、配置、启动、环境上操作四个Phase。
- FileZilla准备、SSH等待、两个SFTP上传等公共Step顺序。
- 内部启动Action和环境Action插入哪些位置。
- EVB档案、版本选择、本机设置如何进入本次配置快照。
- 最终`verify_ready()`接口的调用时机。

外部可以先实现这些结构；内部接入真实流程后，如果发现Phase顺序、插槽位置或字段不足，可以在内网分支小范围修改。修改不敏感且具有通用价值时，再整理成脱敏补丁回到GitHub。

### 3.2 Benchmark协作内容

- `prepare -> run -> collect -> analyze -> report`等生命周期。
- 参数schema和UI呈现方式。
- 资源、环境依赖和前置检查。
- 通用命令/进程执行、进度、取消和产物收集。
- 指标结果的公共结构、单位和状态。
- Benchmark插件特有但不敏感的步骤顺序。

外部负责Benchmark执行框架和常用Step；内部可以继续调整某个具体Benchmark的流程编排。如果流程本身敏感，则协作区只保留空槽，真实顺序下沉到内部专属区。

### 3.3 协作区的文件应该“薄”

不要在一个`model.py`中同时放框架、公共步骤、真实命令和敏感Matcher。建议拆成：

```text
src/env_model/evb/
├── model.py              # 薄集成层，允许内外协作
├── plan.py               # Phase与公共Step拼装，允许内外协作
├── interfaces.py         # 外部主导，尽量稳定
├── common_steps.py       # 外部专属
├── types.py              # 外部专属
└── DESIGN.md             # 公共/脱敏设计，外部主导
```

内部真实实现放在：

```text
internal_extensions/company_plugin/
└── src/company_ebon_plugin/evb/
    ├── profile.py
    ├── artifact_mapping.py
    ├── configure_actions.py
    ├── startup_actions.py
    ├── operate_actions.py
    └── readiness.py
```

这样即使内部确实需要调整`model.py`或`plan.py`，冲突也只会出现在两三个薄文件，不会波及Connector、Executor和公共Step实现。

## 4. 应当只放在内部维护的内容

### 4.1 环境与硬件信息

- 真实芯片代号、板卡类型和环境编号规则。
- BMC/EVB/串口的真实角色与拓扑。
- MAC对应规则、内部地址和环境清单来源。
- 真实账号、密码、密钥和内网服务地址。

### 4.2 制品与启动信息

- 固件、启动脚本、驱动、三方包的真实文件名和内部目录。
- 真实启动源码、入口和依赖。
- Jinja模板、PN码映射和私有参数转换。
- 烧录、复位、网络配置的真实命令和调用方法。

### 4.3 判断与恢复规则

- 真实成功/失败字符串、正则、回调判断。
- 真实超时、正常耗时和设备异常特征。
- 最终Ready命令和验收阈值。
- 设备故障后的内部处理和人工操作。

### 4.4 Benchmark敏感内容

- 真实Benchmark名称、二进制和脚本。
- 用例集合、参数矩阵、数据集和许可证信息。
- 命令行、环境变量、机器拓扑和内部依赖。
- 性能阈值、评分公式、验收标准和分析规则。
- 真实结果、日志样本和问题数据。

### 4.5 内部文档与测试

- 内部插件设计、讨论记录和兼容性说明。
- 真实设备UT/IT、日志fixture和验证结果。
- 内部发布记录和已验证的core commit。

## 5. 判断一段代码放在哪里的规则

依次询问：

1. 是否包含敏感信息？是则内部。
2. 是否可以被两个以上EnvModel/Benchmark复用？是则优先外部。
3. 是否涉及连接稳定性、状态机、超时、取消、日志、安全或文件删除？是则外部。
4. 是否只是把真实命令、参数、文件名和Matcher填进已有能力？是则内部。
5. 是否是某个插件独有但不敏感的步骤编排？放协作区。
6. 内部是否正在重复实现外部已经提供的Connector或Step？如果是，应停止并提升为外部公共能力。

一句话原则：

> 外部维护“机制与安全”，内部维护“事实与策略”，具体插件的非敏感流程编排允许内外协作。

## 6. Git冲突控制方法

### 6.1 冲突允许出现，但只能出现在协作区

内网CI对相对`upstream/main`的差异分类：

| 路径类型 | 内部修改策略 |
| --- | --- |
| 外部专属区 | CI报错，原则上禁止 |
| 内外协作区 | 允许，但必须人工评审和运行插件契约测试 |
| 内部专属区 | 允许，正常内部开发 |

可以在公共仓库增加`CODE_OWNERSHIP.toml`或类似清单：

```toml
[external_only]
paths = [
  "src/basic_connector/**",
  "src/env_model/executor.py",
  "src/env_model/steps.py",
  "src/plugin_api/**",
]

[collaborative]
paths = [
  "src/env_model/*/model.py",
  "src/env_model/*/plan.py",
  "src/benchmark_plugins/**",
]

[internal_only]
paths = ["internal_extensions/**"]
```

具体清单应按代码落地后调整，不能仅依赖文件名通配符猜测职责。

### 6.2 降低协作区冲突的编码规则

- 协作文件保持短小，避免大文件。
- 不在内部对协作文件做全文件格式化或无关重命名。
- 一个提交只完成一个插件修改，避免混入公共框架修改。
- 内部新增步骤优先放到新文件，再在薄集成文件中增加一两行注册。
- 开启`git rerere`记录重复冲突的处理结果，但不能用它掩盖语义变化。
- 同步GitHub后先运行契约测试，再解决真实设备问题。
- 非敏感协作改进尽快回流GitHub，减少内网长期差异。

### 6.3 为每个插件维护“冲突预算”

建议记录：

```text
插件名
内部相对upstream修改了哪些协作文件
为何不能放到internal_extensions
是否可以脱敏回流外部
预计何时消除该差异
```

目标不是协作区零差异，而是让长期差异保持可解释、可测试和数量有限。

## 7. 设计文档如何分

每个模块或插件可以有三类文档，但不要复制全文：

```text
公共 DESIGN.md
    外部维护；描述职责、接口、公共流程、安全和扩展槽

公共 IMPLEMENTATION_PLAN.md
    外部主导；列出公共实现和内网待办

内部 INTERNAL_DESIGN.md / INTERNAL_VALIDATION.md
    内部维护；只补真实映射、命令、Matcher、耗时和验证
```

内部发现公共设计需要调整时，可以先在内网协作分支修改公共`DESIGN.md`；如果内容不敏感，应随后回流GitHub。敏感说明永远写在内部文档，不要长期混进公共设计后再依赖人工删除。

讨论文件建议：

- `talk/codex-discussion.md`继续保存外部可公开的需求与设计历史。
- `internal_extensions/.../talk/internal-discussion.md`保存敏感问答。
- 同一个问题如果既有公共部分又有敏感部分，公共文件只写结论和接口，内部文件写真实值。

## 8. 对当前EVB和未来Benchmark的应用

### EVB

- 外部专属：Connector、PlanExecutor、通用Step、版本缓存、解压、FileZilla安全、日志框架。
- 协作区：四Phase、公共Step顺序、插件字段和扩展槽。
- 内部专属：芯片、文件映射、启动/环境Action、Matcher和Ready检查。

### Benchmark

- 外部专属：Benchmark执行器、资源与环境检查、进程管理、取消、结果与产物模型。
- 协作区：某类Benchmark的生命周期、参数schema和非敏感流程。
- 内部专属：真实程序、用例、数据、参数、阈值、评分和分析规则。

## 9. 推荐实施顺序

1. 先建立`CODE_OWNERSHIP.toml`，明确当前代码的三类路径。
2. 把SSH/Serial/Executor等核心标为外部专属。
3. 将EVB目录拆成公共能力文件与薄集成文件。
4. 建立`internal_extensions/company_plugin`保存敏感实现。
5. 为EnvModel和未来Benchmark定义统一插件Manifest与契约测试。
6. 内网CI检查外部专属区、协作区和内部专属区的差异。
7. 用一次真实GitHub同步演练验证冲突是否只发生在协作区。

## 10. 需要确认

1. 是否接受“外部专属、内外协作、内部专属”三类所有权，而不是追求所有插件文件零冲突？
2. 协作区修改是否要求内部人工评审后才能合入内网`main`？
3. 非敏感的内部改进是否允许整理后回流GitHub，从而逐步减少内网差异？
