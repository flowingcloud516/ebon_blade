# Ebon Blade项目路线

> **文档定位**：跨模块实施路线与状态摘要。
>
> **主要作用**：记录已经完成的阶段、当前工作和后续优先级。
>
> **使用方式**：安排下一阶段任务时查阅；具体实现细节进入对应模块或具体实现设计。

状态：当前有效

最后复核：2026-10-28

## 1. 已完成

- GUI、工作空间和多环境组合第一版；
- SSH Connector及公共UT；
- 网络串口Connector及公共UT；
- Environment Driver公共执行框架的前身实现；
- EVB四Phase公共实现、Fake Provider和公共UT；
- 简单SFTP版本目录与工作空间本地缓存设计。

## 2. 2026-10-28结构整改（已完成）

- 已将`env_model`统一为`env_driver`，公共框架进入`env_driver/core/`；
- 已明确`EnvironmentDriver`、Service、Plan、Step和Connector术语；
- 已把模块设计和具体实现设计放回对应源码目录；
- 已确定内部补充使用同目录`*_internal.py`与`*_internal.md`；
- 已清理失效的SDK、`internal_extensions`和旧插件包方案；
- 已按日期拆分讨论记录，并建立AI阅读入口。

## 3. 下一阶段

- 完成CommonHostDriver公共实现；
- 在内网补齐EVB真实制品映射、动作、Matcher和Ready判断；
- 完成BMC Connector实现与真实环境验证；
- 接通GUI后台任务与EnvironmentControlService；
- 根据实际复用情况提取`common_steps`，不提前制造空抽象。

## 4. 后续阶段

- 设计DV Driver；
- 设计Benchmark Driver；
- 重新评估持续日志和可移交诊断包；
- 根据真实规模决定是否需要独立SDK或独立插件发布。
