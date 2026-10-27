# 内外协作代码结构规划

状态：结构建议，等待评审

最近更新：2026-10-27

关联文档：[代码维护边界](external-internal-ownership.md) · [插件与Git同步](plugin-maintenance-design.md)

## 1. 规划目标

代码结构同时表达三件事：

1. 这是框架、公共工具，还是具体插件。
2. 这个文件由外部维护、内外协作，还是只在内部存在。
3. 内部插件可以依赖什么，不能绕过什么。

不追求一次性重构所有现有代码。先确定目标结构，再在实现EnvModel、Benchmark时逐步迁移。

## 2. GitHub核心仓库的建议结构

```text
ebon_blade/
├── pyproject.toml
├── src/
│   ├── ebon_blade/                 # 产品壳：GUI、工作空间、Run编排
│   │   ├── app/
│   │   ├── workspace/
│   │   ├── runtime/
│   │   └── plugin_loader/
│   │
│   ├── ebon_blade_sdk/             # 稳定插件契约，外部专属
│   │   ├── manifest.py
│   │   ├── registry.py
│   │   ├── context.py
│   │   ├── environment.py
│   │   ├── benchmark.py
│   │   ├── actions.py
│   │   └── results.py
│   │
│   ├── basic_connector/            # 公共连接器，外部专属
│   │   ├── ssh_connector/
│   │   ├── serial_connector/
│   │   ├── bmc_connector/
│   │   └── local_process_connector/
│   │
│   ├── common_steps/               # 跨插件复用Step，外部专属
│   │   ├── ssh.py
│   │   ├── serial.py
│   │   ├── transfer.py
│   │   ├── filesystem.py
│   │   ├── process.py
│   │   └── polling.py
│   │
│   ├── env_model/                  # 环境控制运行内核
│   │   ├── model.py
│   │   ├── executor.py
│   │   ├── plan.py
│   │   ├── steps.py
│   │   ├── logs.py
│   │   ├── service.py
│   │   ├── registry.py
│   │   ├── common_host/            # 具体环境插件
│   │   ├── evb/                    # 具体环境插件
│   │   └── dv/                     # 只保留公共壳/接口
│   │
│   └── benchmark_model/            # 未来Benchmark运行内核
│       ├── model.py
│       ├── executor.py
│       ├── plan.py
│       ├── results.py
│       ├── artifacts.py
│       └── plugins/
│
├── tests/
│   ├── core/
│   ├── connectors/
│   ├── common_steps/
│   ├── contracts/
│   ├── env_models/
│   ├── benchmarks/
│   └── fakes/
│
├── design/
├── talk/
└── CODE_OWNERSHIP.toml
```

当前已有的`src/ebon_blade`、`src/basic_connector`和`src/env_model`可以继续使用，不需要立即改包名。建议优先新增`ebon_blade_sdk`和`common_steps`，再逐步把现有代码移动到更清晰的子模块。

## 3. 顶层包各自负责什么

### `ebon_blade`

只负责产品层：窗口、工作空间、配置转换、插件加载、Run编排和结果展示。不放SSH命令、硬件动作或Benchmark算法。

### `ebon_blade_sdk`

只放内部插件允许依赖的稳定公开类型：Protocol、dataclass、Enum和注册接口。它不能依赖GUI，也尽量不依赖Connector具体实现。

内部插件优先这样导入：

```python
from ebon_blade_sdk import EvbContribution, ActionDefinition, StepResult
```

而不是导入：

```python
from env_model.executor import PlanExecutor
from basic_connector.ssh_connector.connector import ManagedSSHSession
```

后两者属于核心实现细节；应通过SDK中的受控Context能力提供给插件。

### `basic_connector`

只解决协议和稳定性，不包含EVB、服务器或Benchmark业务语义。

### `common_steps`

把Connector组合成可复用动作。例如SSH等待、SFTP上传、安全解压和轮询。具体插件优先组合这些Step，避免重复实现。

### `env_model`

顶层文件是环境运行内核；`common_host/evb/dv`是具体环境插件。运行内核外部专属，具体插件目录允许按文件进一步划分所有权。

### `benchmark_model`

与`env_model`平行，不塞进EnvModel中。它负责Benchmark生命周期、执行、产物、指标和报告；具体Benchmark放在`plugins/`下。

## 4. 每个EnvModel插件的目录模板

以EVB为例：

```text
src/env_model/evb/
├── __init__.py
├── interfaces.py            # 外部专属：Contribution接口和扩展槽
├── types.py                 # 外部专属：配置、路径、Action定义
├── common_steps.py          # 外部专属：EVB可复用Step
├── model.py                 # 内外协作：EvbModel与四Phase集成
├── plan.py                  # 内外协作：公共Step顺序和内部Action插槽
├── schema.py                # 内外协作：EVB公开配置结构
├── fakes.py                 # 外部专属：Fake Contribution
├── DESIGN.md                # 外部主导：公共/脱敏设计
└── IMPLEMENTATION_PLAN.md   # 外部主导：公共实现和内网待办
```

所有真实命令和映射都不放在这里。若内部确实需要调整Phase、字段或插槽，只修改`model.py`、`plan.py`或`schema.py`这几个薄文件。

建议每个协作文件控制在容易完整评审的规模；公共Step实现继续放外部专属文件，避免协作文件逐渐变成大杂烩。

## 5. 每个Benchmark插件的目录模板

```text
src/benchmark_model/plugins/<benchmark_type>/
├── interfaces.py            # 外部专属：内部Contribution接口
├── types.py                 # 外部专属：参数与结果结构
├── common_steps.py          # 外部专属：公共执行/采集Step
├── model.py                 # 内外协作：生命周期集成
├── plan.py                  # 内外协作：公共步骤和内部插槽
├── schema.py                # 内外协作：可公开参数结构
├── fakes.py                 # 外部专属
└── DESIGN.md
```

Benchmark不要直接借用`EnvironmentModel`：

- EnvModel回答“环境是否已经准备好”。
- Benchmark回答“测试如何准备、运行、采集和产生结果”。
- Benchmark通过环境依赖引用Ready环境，不复制环境初始化逻辑。

## 6. 内网Overlay仓库的内部专属结构

内网仓库保留GitHub完整代码，并新增：

```text
internal_extensions/
└── company_plugin/
    ├── pyproject.toml
    ├── src/company_ebon_plugin/
    │   ├── plugin.py
    │   ├── env_models/
    │   │   ├── evb/
    │   │   │   ├── contribution.py
    │   │   │   ├── profile.py
    │   │   │   ├── artifact_mapping.py
    │   │   │   ├── configure_actions.py
    │   │   │   ├── startup_actions.py
    │   │   │   ├── operate_actions.py
    │   │   │   ├── readiness.py
    │   │   │   └── templates/
    │   │   └── dv/
    │   └── benchmarks/
    │       └── <benchmark_type>/
    │           ├── contribution.py
    │           ├── cases.py
    │           ├── commands.py
    │           ├── metrics.py
    │           └── thresholds.py
    ├── tests/
    │   ├── contract/
    │   ├── unit/
    │   └── live/
    ├── design/
    ├── talk/
    ├── COMPATIBILITY.md
    └── INTERNAL_VALIDATION.md
```

内部插件有自己的`pyproject.toml`。根目录核心包和内部插件包分别安装，避免修改公共根`pyproject.toml`。

## 7. 运行时依赖方向

依赖只能向下：

```text
GUI / Run Orchestrator
        ↓
EnvModel Core / Benchmark Core
        ↓
SDK接口 + Common Steps
        ↓
Basic Connectors

Internal Contribution
        ↓
SDK接口 + 允许的Common Steps
```

禁止：

- Connector反向导入EnvModel或Benchmark。
- SDK导入GUI或具体插件。
- 内部Contribution导入GUI、Executor私有函数或Connector内部Backend。
- Benchmark直接修改环境状态；需要环境操作时通过明确EnvModel能力完成。
- 工作空间路径动态加载Python代码。

可以通过契约测试或import-linter规则检查这些依赖方向。

## 8. 注册与组合

核心加载顺序：

```text
加载内置公共插件
→ 发现已安装的内部插件entry point
→ 检查Manifest/API版本
→ 注册Env Contribution和Benchmark Contribution
→ 将公共Model与Contribution组合
→ 向GUI公布最终可用能力
```

内部插件缺失时：

- GUI仍可启动。
- 对应EVB/DV/Benchmark显示“内部实现未安装或不兼容”。
- 不返回模拟成功。

## 9. 测试结构

### 外部仓库

- Core UT：Executor、日志、工作空间、版本和安全规则。
- Connector UT与可选live test。
- Common Step UT。
- 每类插件用Fake Contribution做完整流程测试。
- Plugin contract test，供内部包复用。

### 内部Overlay

- Contract：是否满足SDK、Action ID、超时和证据要求。
- Unit：模板、映射、Matcher和命令生成。
- Live：真实串口、SSH、设备和Benchmark。
- Compatibility：对当前允许的core tag运行。

内部live test不能成为GitHub公共CI的依赖。

## 10. 所有权清单

建议在GitHub仓库增加`CODE_OWNERSHIP.toml`，而不是只靠口头约定：

```toml
[external_only]
paths = [
  "src/ebon_blade_sdk/**",
  "src/basic_connector/**",
  "src/common_steps/**",
  "src/env_model/executor.py",
  "src/env_model/steps.py",
  "src/env_model/logs.py",
  "src/benchmark_model/executor.py",
]

[collaborative]
paths = [
  "src/env_model/*/model.py",
  "src/env_model/*/plan.py",
  "src/env_model/*/schema.py",
  "src/benchmark_model/plugins/*/model.py",
  "src/benchmark_model/plugins/*/plan.py",
  "src/benchmark_model/plugins/*/schema.py",
]

[internal_only]
paths = [
  "internal_extensions/**",
  "internal_tools/**",
]
```

内网CI读取该文件并分类`upstream/main...HEAD`差异。这个清单应逐文件调整，不要一次用过宽通配符把整个插件目录标成协作区。

## 11. 从当前代码逐步迁移

建议顺序：

1. 不打断正在进行的EVB实现，先按现有包结构完成可测试公共部分。
2. 为EVB补齐`interfaces.py/types.py/common_steps.py/model.py/plan.py`边界。
3. 新增`ebon_blade_sdk`，先放Manifest、Contribution和结果接口。
4. 把通用EVB步骤逐渐提升到`common_steps`或EVB的`common_steps.py`。
5. 增加entry point插件加载，不再依赖手工修改全局`ADAPTERS`。
6. 创建`internal_extensions/company_plugin`模板并完成一次Fake安装。
7. 增加`CODE_OWNERSHIP.toml`和内网差异检查。
8. 开始Benchmark设计时直接使用新模板，不再重复旧式全局字典。
9. 最后再考虑是否移动现有文件和细分`ebon_blade/app/workspace/runtime`；避免纯目录重构干扰功能开发。

## 12. 推荐的日常开发方式

### 外部开发

- 可以修改外部专属区和协作区。
- 修改SDK时必须更新Fake插件、契约测试和变更说明。
- 不能接触内部真实实现。

### 内部开发

- 主要修改`internal_extensions/`。
- 确有需要时修改协作区的薄文件。
- 不修改外部专属区；发现缺口时提出脱敏需求。
- 每次同步upstream后先解决协作区冲突，再运行契约测试。

### 回流外部

- 内部在协作区完成的非敏感通用改进，整理成不含内部值的补丁回流GitHub。
- 回流后，下一次upstream同步删除内网重复补丁。
- 敏感实现永远不回流。
