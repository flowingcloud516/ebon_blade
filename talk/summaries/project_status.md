# Ebon Blade项目状态

> **文档定位**：面向新AI和维护者的阶段摘要。
>
> **主要作用**：快速说明当前代码能力、有效设计入口和下一阶段工作。
>
> **使用方式**：接手项目时先用于建立上下文，再阅读链接的正式设计确认细节。

更新时间：2026-10-28

## 当前代码

- GUI、工作空间、多环境组合和离线演示可运行；
- SSH和网络串口Connector已有公共实现与UT；
- Environment Driver Core包含Registry、Service、Plan、Step、Executor、Context和日志生命周期；
- EVB Driver公共四Phase、制品缓存、FileZilla安全、串口日志、SSH时序和Fake Provider已实现；
- 92项测试通过，8项真实设备测试在没有环境配置时跳过。

## 当前设计入口

- [系统设计](../../design/system_design.md)
- [Environment Driver设计](../../src/env_driver/env_driver_design.md)
- [EVB Driver设计](../../src/env_driver/evb/evb_driver_design.md)
- [Basic Connector设计](../../src/basic_connector/basic_connector_design.md)
- [代码所有权](../../design/code_ownership.md)

## 下一阶段

- 完成文档与代码结构重构后的内网同步；
- 实现CommonHostDriver；
- 内网补齐EVB真实`*_internal.py`；
- 实现并验证BMC Connector；
- 接通GUI与`EnvironmentControlService`。

重构前基线Tag：`pre-env-driver-refactor-2026-10-28`。
