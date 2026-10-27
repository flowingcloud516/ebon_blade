# 外部核心与内部插件协作设计

状态：第一版建议，等待评审

最近更新：2026-10-27

> 代码归属以[外部与内部代码维护边界](external-internal-ownership.md)为准。本文主要描述内网Fork/Overlay、插件加载和Git同步方式；“内部不修改公共路径”是外部专属区的规则，不适用于被明确标记为内外协作区的具体插件集成文件。

## 1. 要解决的问题

项目需要同时满足：

- 总体框架、公共Connector、关键安全逻辑和通用Step由外部能力较强的模型持续维护，并同步到GitHub。
- 芯片代号、真实端点、文件名、命令、成功标志等敏感实现只能在内网维护。
- 内部模型不需要理解或修改整个框架，只在受约束接口内补齐具体实现。
- 外部核心更新后，内部同步不应反复产生Git冲突，也不能把敏感代码误推到GitHub。

仅把内部目录加入`.gitignore`不够可靠：内部开发一旦修改了公共文件，`git pull`仍会冲突；敏感文件也可能因误操作进入公共仓库历史。

## 2. 推荐结论：内部私有Fork/Overlay、公共基座与内部贡献分层

### 2.1 外部核心仓库

继续使用当前GitHub仓库`ebon_blade`，负责：

```text
ebon_blade-core/
├── src/ebon_blade/           # GUI、工作空间、运行编排
├── src/env_model/            # EnvironmentModel、Plan、Executor、公共Model骨架
├── src/basic_connector/      # SSH、Serial、BMC等公共Connector
├── src/plugin_api/           # 稳定插件契约与契约测试工具
├── tests/                    # 核心UT、Fake Plugin、兼容性测试
├── design/                   # 外部设计和接口设计
└── talk/external-discussion.md
```

### 2.2 内部私有仓库

内网仓库保存GitHub核心的完整历史和代码，同时叠加内部专属目录。它相当于GitHub仓库的私有Fork：

```text
ebon_blade-internal/                    # 内网Git仓库根目录
├── src/ebon_blade/                     # 原样同步的GitHub核心代码
├── src/env_model/                      # 原样同步
├── src/basic_connector/                # 原样同步
├── design/                             # 原样同步的公共设计
├── talk/                               # 原样同步的公共讨论
└── internal_extensions/                # 只在内网分支存在的保留目录
    └── company_plugin/                 # 独立Python插件包
        ├── pyproject.toml
        ├── src/company_ebon_plugin/
        │   ├── plugin.py
        │   ├── evb/
        │   │   ├── profiles/
        │   │   ├── adapters/
        │   │   ├── templates/
        │   │   └── readiness/
        │   └── dv/
        ├── tests/
        ├── design/
        ├── talk/internal-discussion.md
        ├── COMPATIBILITY.md
        └── INTERNAL_VALIDATION.md
```

内部checkout配置两个remote：

```text
origin    = 内网Git仓库，可fetch和push
upstream  = GitHub仓库，只允许fetch，禁止push
```

虽然代码处于同一棵内部工作树，核心和内部插件仍是两个Python包。开发机安装：

```text
pip install -e .
pip install -e ./internal_extensions/company_plugin
```

内部插件使用独立`pyproject.toml`，不能修改公共根目录的`pyproject.toml`。插件源码不得放进公共根目录的`src/`，否则构建核心wheel时可能被公共包发现规则意外打包。正式分发时分别构建core wheel和internal plugin wheel，在内网一起安装。

### 2.3 为什么这种Overlay冲突很小

Git只在双方修改相同路径和相同行时产生内容冲突。内网只新增或修改`internal_extensions/`，GitHub只修改公共路径，周期性合并通常是自动的：

```text
GitHub upstream/main ───────┐
                            ├─ merge到内网 main ── push origin/main
内网 internal_extensions/ ─┘
```

冲突控制的关键不是“更聪明地解决冲突”，而是通过插件API保证内网根本不需要修改公共路径。

## 3. 方案比较

| 方案 | 问题 |
| --- | --- |
| 同仓库普通目录 | 内外修改共享索引，拉取容易冲突；敏感内容存在误推风险 |
| `.gitignore`内部目录 | 只能忽略未跟踪文件，不能阻止内部人员修改公共文件；也没有独立版本历史 |
| Git subtree | 内外历史仍需合并，使用复杂，冲突没有根本消失 |
| 公共仓库引用私有submodule | 可以隔离代码，但公共仓库会记录私有仓库地址和commit指针，更新流程也容易混乱 |
| 同级双checkout | 隔离最彻底，但不符合内网仓库需要保存完整GitHub代码的工作方式 |
| **内网私有Fork/Overlay + 独立插件包** | 内网保存完整代码；内部文件路径隔离；周期性merge冲突很少；当前推荐 |

不建议使用`merge=ours`或大范围自定义合并策略掩盖冲突；它可能静默丢失外部修复。正确做法是让内网相对`upstream/main`的差异只出现在保留目录。

## 4. 代码归属边界

| 能力 | 外部核心维护 | 内部插件维护 |
| --- | --- | --- |
| GUI、工作空间、执行编排 | 是 | 否 |
| `EnvironmentModel`、Plan/Phase/Step、Executor | 是 | 否 |
| SSH、Serial、BMC Connector | 是 | 否 |
| 版本缓存、SFTP下载、安全解压、FileZilla目录锁 | 是 | 否 |
| SSH等待、SFTP上传、expect/poll等通用Step | 是 | 否 |
| EVB四Phase骨架、取消与失败规则 | 是 | 否 |
| 插件发现、兼容性检查、脱敏和契约测试 | 是 | 否 |
| 真实芯片代号和串口角色 | 否 | 是 |
| 真实文件名和版本映射 | 否 | 是 |
| 启动脚本参数适配/Jinja模板 | 否 | 是 |
| 启动内部Action、命令和成功/失败标志 | 否 | 是 |
| 驱动/三方包安装及内部环境操作 | 否 | 是 |
| 最终Ready的敏感检查 | 只维护接口 | 是 |

内部插件不得替换`PlanExecutor`、Connector实现、目录安全检查或主流程；它只能在核心预留的扩展槽位提供实现。

## 5. 插件接口应当是“受约束填空”

### 5.1 顶层插件契约

核心包提供稳定SDK：

```python
class EbonBladePlugin(Protocol):
    def manifest(self) -> PluginManifest: ...
    def register(self, registry: PluginRegistry) -> None: ...
```

`PluginManifest`至少包含：

```text
plugin_id             例如 company.internal.lab
plugin_version        插件自身版本
api_version           使用的插件接口版本，例如 1
core_version_spec     兼容的核心版本范围
capabilities          提供evb_profile、dv_model等哪些能力
```

内部包只注册命名空间化能力，例如：

```text
company.internal.evb.<chip-profile>
company.internal.dv.<profile>
```

不得覆盖核心已有ID，也不得通过修改核心的全局`ADAPTERS`字典完成注册。

### 5.2 EVB插件不实现整个`EvbModel`

这里必须区分“逻辑插件”和“Git代码模块”。对用户而言EVB是一项完整能力，但代码由两层在运行时组合：

```text
逻辑EVB能力
├── Public EvbModel Base        外部/GitHub维护
│   ├── 四个Phase骨架
│   ├── 公共Step
│   ├── Connector调用
│   ├── 日志、超时、取消和安全规则
│   └── 敏感实现扩展槽
└── Internal EvbContribution   内网维护
    ├── 芯片与文件映射
    ├── 私有配置Action
    ├── 私有启动Action
    ├── 私有环境操作Action
    └── 私有Ready检查
```

因此外部和内部确实是在共同完善“同一个EVB插件”，但不会修改同一个Git文件。外部完善基座，内部完善Contribution；核心加载后把两者组合成一个注册给UI的`EvbModel`。

`EvbModel`及四Phase骨架保留在核心仓库。内部插件只实现：

```python
class EvbProfileProvider(Protocol):
    def artifact_mapping(self) -> ArtifactMapping: ...
    def serial_role_mapping(self) -> SerialRoleMapping: ...
    def actions(self, phase: EvbPhase) -> tuple[EvbActionDefinition, ...]: ...
    async def execute_action(self, action_id, context) -> StepResult: ...
    async def verify_ready(self, context) -> ReadinessResult: ...
```

核心负责把`EvbActionDefinition`包装成普通Step，再交给`PlanExecutor`执行。内部模型不需要处理状态机、超时传播、日志生命周期或UI。

更准确的接口名建议使用`EvbContribution`，避免让人误解内部需要复制整个EVB插件：

```python
class EvbContribution(Protocol):
    def manifest(self) -> ContributionManifest: ...
    def profile_schema(self) -> ProfileSchema: ...
    def artifact_mapping(self, request) -> ArtifactMapping: ...
    def actions(self, slot: EvbExtensionSlot) -> tuple[EvbActionDefinition, ...]: ...
    async def execute_action(self, action_id, context) -> StepResult: ...
    async def verify_ready(self, context) -> ReadinessResult: ...
```

核心固定提供以下扩展槽：

| 扩展槽 | 核心已经负责 | 内部Contribution负责 |
| --- | --- | --- |
| `configure.private_actions` | FileZilla锁、清理、固件解压、工作空间准备、通用配置校验 | 启动脚本私有字段映射和额外配置Step |
| `start.private_actions` | Phase顺序、Step包装、超时/取消/结果传播 | 真实启动、烧录、复位、EVB-GE设置Action |
| `operate.private_actions` | SSH等待、两个SFTP上传、公共日志 | 驱动/三方包后的安装和环境操作 |
| `readiness.private_probe` | 调用时机、只读约束、结果模型 | 私有命令、Matcher和Ready证据 |
| `collectors.private` | LogSession生命周期和Connector所有权 | EVB SSH具体日志采集内容 |

Contribution只能向指定槽位追加Action，不能删除、替换或重排核心Step。核心Step ID使用`core.*`命名空间，内部Step ID使用`<plugin_id>.*`命名空间，避免双方同时新增Step时发生名字冲突。

如果内部Contribution未安装、版本不兼容或必需槽位为空，核心EVB Model在预检阶段明确显示“内部实现不可用”，不能返回模拟成功。

### 5.2.1 内外并行完善同一EVB能力的工作方式

外部可以继续修改：

```text
src/env_model/evb/model.py
src/env_model/evb/common_steps.py
src/plugin_api/evb.py
tests/fake_evb_contribution.py
```

内部同时只修改：

```text
internal_extensions/company_plugin/src/company_ebon_plugin/evb/**
```

合并GitHub更新时，文件路径不重叠，所以Git不会产生内容冲突。真正需要协调的只有插件API语义；它通过`api_version`、契约测试和兼容性错误显式处理，而不是在Git merge时临时人工猜测。

如果外部要把某个原本内部实现的Action提升为公共Step，采用两阶段迁移：

1. 核心先新增公共Step并保留原扩展槽兼容性，发布新的minor版本。
2. 内部升级并删除重复Action，契约测试确认没有重复Step ID或重复能力声明。
3. 至少经过一个兼容版本后，核心才允许收紧或删除旧槽位。

反过来，如果内部发现公共能力不足，应先提出脱敏后的扩展槽需求；外部增加通用接口后，内部再实现。不要在内部直接复制并修改`EvbModel`基座。

### 5.3 内部尽量组合公共Step

核心SDK提供可直接组合的构件，例如：

```text
SerialExpectAction
SSHCommandAction
SFTPUploadAction
PollUntilAction
RenderTrustedTemplateAction
ReadinessProbeAction
```

内部插件优先填写参数、命令、Matcher和超时，不重新实现SSH/SFTP/串口循环。只有公共构件无法表达的敏感逻辑，才编写内部Python Action。

### 5.4 只提供受控能力，不暴露整个框架

`PluginActionContext`只向插件提供：

- 只读的本次配置快照。
- 已解析的制品路径。
- 受控的SSH、Serial、SFTP能力接口。
- 当前Step的日志/证据入口。
- 取消信号和插件专属工作目录。

插件不直接持有GUI、不自行创建全局连接、不清空任意目录，也不绕过核心日志与脱敏规则。

## 6. 插件发现方式

使用Python标准的package entry point，不扫描工作空间、不按路径动态导入：

内部包`pyproject.toml`：

```toml
[project.entry-points."ebon_blade.plugins"]
company_internal = "ebon_blade_internal.plugin:get_plugin"
```

核心启动时通过`importlib.metadata.entry_points()`发现已安装插件：

```text
发现插件
→ 读取Manifest
→ 检查api_version和core_version_spec
→ 通过契约检查后注册
→ 缺失或不兼容则标记“内部适配器不可用”，绝不假成功
```

Entry point解决的是安装与发现，不是安全沙箱。内部插件仍是受信任代码，与核心运行在同一进程。若以后内部依赖冲突或崩溃风险明显，再增加子进程Plugin Host；第一期不需要先做RPC系统。

## 7. Git与发布流程

### 7.1 内网仓库首次建立

首次从GitHub建立内网仓库时：

```text
1. clone GitHub仓库
2. 将原GitHub remote改名为upstream
3. 新增内网Git为origin
4. 从upstream/main建立内网main并推送到origin
5. 在internal_extensions/company_plugin中创建内部插件包
6. 后续内部提交只修改internal_extensions及明确允许的内网辅助目录
```

内部checkout必须设置：

```text
remote.pushDefault = origin
upstream的push URL设为无效地址
core.hooksPath指向内部版本化Git hooks
```

内部`pre-push` hook应拒绝任何目标为`upstream`的push。更可靠的措施是内部机器不配置GitHub写权限，只保留读取权限。

### 7.2 外部核心发布

1. 在公共设计文档中修改框架或接口。
2. 增加/更新Fake Plugin和契约测试。
3. 保持兼容时发布minor/patch；破坏兼容时提升插件API主版本。
4. 在GitHub创建tag，例如`core-v0.3.0`，构建wheel。
5. 输出`PLUGIN_API_CHANGELOG.md`和迁移说明。

### 7.3 内部同步

内部仓库不能对GitHub执行普通`git pull`后再强推，而应显式合并两个remote：

```text
git checkout main
git fetch upstream --tags
git merge --no-ff upstream/main
运行核心UT和内部plugin_check
git push origin main
```

推荐使用merge而不是把长期内部main反复rebase到upstream：merge保留每次同步边界，不需要改写已经推到内网的敏感提交历史。

每次同步按以下步骤执行：

1. 确认内网工作树干净，内部修改已经提交到`origin`。
2. fetch GitHub的`upstream/main`和tag。
3. 合并`upstream/main`到内网`main`。
4. 如果发生公共路径冲突，先停止并检查是否有人违反了“内部不修改核心”的边界。
5. 安装/更新核心和`internal_extensions/company_plugin`两个包。
6. 运行公共UT、插件契约测试和必要的内部离线测试。
7. 测试通过后把合并结果push到内网`origin/main`。
8. 真实设备验证通过后，记录core commit、plugin version和验证结果。

内部人员不得直接在核心checkout中长期修补代码。发现核心缺陷时，使用脱敏Fake复现并在公共仓库修复；随后发布新核心版本，再让内部插件升级。

### 7.4 自动检查“内部只改保留目录”

内网CI比较当前内网main相对GitHub基线的差异：

```text
git diff --name-only upstream/main...HEAD
```

正常情况下，输出只能包含：

```text
internal_extensions/**
internal_tools/**        # 可选：内网安装/同步脚本和Git hooks
```

出现`src/env_model/`、`src/basic_connector/`、`src/ebon_blade/`或公共`design/`修改时，CI失败。若确有核心修改需求，必须先在外部仓库完成并从`upstream`重新合入，不能把它作为长期内部补丁。

### 7.5 版本规则

建议同时维护两个版本：

```text
core version        产品实现版本，例如0.3.0
plugin api version  稳定接口代数，例如1
```

- Core patch：修复实现，不改变插件接口。
- Core minor：增加向后兼容能力。
- Plugin API major：删除/修改字段或改变语义；至少提供一个版本的弃用期。

启动时必须显示已加载的核心版本、插件版本和API版本，问题日志中也记录这些版本，但不记录敏感配置。

## 8. 文档和讨论文件的分法

### 8.1 公共仓库

```text
design/architecture.md
design/plugin-maintenance-design.md
src/env_model/DESIGN.md
src/env_model/evb/DESIGN.md
src/basic_connector/ssh_connector/DESIGN.md
src/basic_connector/serial_connector/DESIGN.md
src/plugin_api/DESIGN.md
talk/external-discussion.md
```

公共设计描述职责、接口、生命周期、安全规则和通用Step，不记录真实芯片、地址、文件名、命令和成功字符串。

### 8.2 内部Overlay目录

```text
internal_extensions/company_plugin/design/evb-plugin-design.md
internal_extensions/company_plugin/design/dv-plugin-design.md
internal_extensions/company_plugin/talk/internal-discussion.md
internal_extensions/company_plugin/INTERNAL_VALIDATION.md
internal_extensions/company_plugin/COMPATIBILITY.md
```

内部文档只描述插件如何实现公共接口，并在首页固定记录：

```text
tested_core_version
plugin_api_version
plugin_version
```

同一份文档不要在两个仓库各复制一份。公共设计是契约来源，内部设计通过版本号和链接引用它；内部只记录实现差异，避免两边文本逐渐不一致。

## 9. 面向内部模型的开发护栏

为了让能力较弱的内部模型也能稳定工作，内部仓库提供：

1. 一个可复制的最小EVB插件模板。
2. 每个扩展点只暴露少量必填函数和类型。
3. 公共Action构件和示例，不让内部重复写连接循环。
4. `python -m ebon_blade.plugin_check`一键契约检查。
5. Fake Connector与脱敏输出样例。
6. CI禁止内部包导入GUI、Executor私有模块或Connector内部实现。
7. CI检查插件ID命名空间、API版本、动作ID、超时、SideEffect和成功证据。
8. 内部模型的文件权限和任务说明只允许修改`internal_extensions/`；禁止自动修改公共核心路径。

## 10. 从当前项目迁移的顺序

1. 在当前公共仓库新增`plugin_api`，先稳定Manifest、Registry和EVB Profile接口。
2. 将当前`src/ebon_blade/adapters.py`的手工全局字典替换为“内置Fake + entry point发现”。
3. 保留`EvbModel`、公共Step和所有Connector在核心仓库。
4. 在内网Overlay仓库的`internal_extensions/company_plugin/`建立独立插件包和模板，只放敏感Profile/Adapter。
5. 核心测试使用Fake Plugin，确保没有内部插件也能运行GUI但明确显示真实适配不可用。
6. 内部插件安装后运行同一套契约测试，再运行内网设备验证。
7. 核心发布第一个带插件API的tag，内网Overlay仓库合并该tag对应commit并记录兼容版本。
8. 从此不再把内部实现复制回公共仓库。

## 11. 第一阶段不做

- 不做在线插件市场或远程下载插件。
- 不允许工作空间加载任意Python文件。
- 不做第三方不可信插件沙箱。
- 不一开始拆成大量独立仓库；先保持一个核心仓库和一个内部插件仓库。
- 不让每个Connector成为单独Git仓库；它们在核心仓库内分别维护`DESIGN.md`和测试即可。

## 12. 待确认决策

1. 内部执行机是否允许从同一工作树安装根目录核心包和`internal_extensions/company_plugin`插件包？
2. 内部是否需要同时维护多个核心版本，还是所有执行机可以按一个经过验证的core tag统一升级？
3. 内网CI能否访问GitHub的只读`upstream`，以自动检查内部差异只落在保留目录？
4. `talk/codex-discussion.md`目前包含完整历史。建议保留为公共历史；从下一阶段开始，外部讨论仍写公共文件，内部敏感讨论只写`internal_extensions/company_plugin/talk/internal-discussion.md`，是否接受？
