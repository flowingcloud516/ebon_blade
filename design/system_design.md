# Ebon Blade系统设计

> **文档定位**：系统级权威设计入口。
>
> **主要作用**：定义产品范围、顶层模块、依赖方向和内外协作边界。
>
> **使用方式**：进行跨模块设计或结构调整前必须阅读，并通过本文链接进入对应模块设计。

状态：当前有效

层级：系统级设计

最后复核：2026-10-28

Ebon Blade是运行在Windows上的实验环境自动化客户端。它以工作空间保存环境档案和一次测试需要的环境组合，负责环境准备、执行入口、进度展示和运行结果留存。

## 1. 第一期范围

第一期优先解决重复、耗时且容易出错的环境准备工作：

- 工作空间与环境档案管理；
- 多环境组合与初始化顺序；
- SSH、网络串口、BMC等基础连接；
- 普通主机、EVB和后续DV的环境Driver；
- 初始化过程中的取消、超时、失败传播和必要日志；
- 为未来Benchmark Driver保留清晰入口。

Benchmark执行、完整运行诊断系统和无人值守调度不属于当前第一优先级。

## 2. 顶层模块

```text
Qt桌面界面与工作空间
          │
          ▼
EnvironmentControlService
          │ 选择
          ▼
EnvironmentDriver
          │ 生成
          ▼
Plan → Phase → Step
          │ 使用
          ▼
SSH / Serial / BMC Connector
```

- `src/ebon_blade/`：GUI、工作空间和产品级任务入口。
- `src/env_driver/`：环境生命周期、计划和具体环境Driver。
- `src/basic_connector/`：SSH、串口、BMC等通信能力。
- `src/common_steps/`：未来跨多个Driver复用的公共步骤。
- `src/benchmark_driver/`：未来具体测试内容的执行框架，当前不提前建立空实现。

## 3. 依赖方向

依赖只能从产品层指向环境控制层，再指向连接器：

```text
ebon_blade
    ↓
env_driver / future benchmark_driver
    ↓
common_steps
    ↓
basic_connector
```

Connector不得反向导入Environment Driver；具体Driver不得绕过公共Executor自行复制调度逻辑；工作空间不得指定任意Python模块或命令。

## 4. 内外协作方式

外部仓库维护系统框架、安全规则、Connector、公共步骤和具体Driver的公开部分。内部实现直接放在对应具体Driver目录，通过`*_internal.py`增加真实映射、命令、Matcher和就绪判断。必要的少量共同调整集中在具体Driver的`driver.py`和`plan.py`。

详细规则见[代码所有权](code_ownership.md)。本项目当前不建立独立SDK，也不建立`internal_extensions`插件包；只有未来出现独立发布或第三方兼容需求时才重新评估。

## 5. 设计导航

- [UI设计](../src/ebon_blade/ui_design.md)
- [Basic Connector设计](../src/basic_connector/basic_connector_design.md)
- [Environment Driver设计](../src/env_driver/env_driver_design.md)
- [日志设计](logging_design.md)
- [二进制版本设计](artifact_version_design.md)
- [项目路线](project_roadmap.md)
- [文档维护规则](document_rules.md)

具体实现设计继续由模块设计通过相对路径向下链接。
