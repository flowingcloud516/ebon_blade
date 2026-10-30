# ADR-001：使用Environment Driver术语

> **文档定位**：已接受的架构决策记录。
>
> **主要作用**：解释从Environment Model改为Environment Driver的原因和职责边界。
>
> **使用方式**：修改环境控制命名或职责前查阅；除非新增ADR取代，否则本决定持续有效。

状态：已接受

日期：2026-10-28

## 决定

将`env_model`改名为`env_driver`，抽象类使用`EnvironmentDriver`，具体实现使用`EvbDriver`、`CommonHostDriver`和`DvDriver`。

## 原因

该对象不仅保存数据，还负责校验配置、声明依赖和日志、构建初始化Plan、验证最终Ready并收集失败上下文。`Driver`比`Model`更能表达“某类环境的生命周期控制实现”。

Driver不替代底层Connector，也不承担公共调度：`EnvironmentControlService`组织一次初始化，`PlanExecutor`执行Plan，Connector完成真实通信。每次初始化必须创建新的Driver实例，不能跨并发Run共享可变运行状态。
