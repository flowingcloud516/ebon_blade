# 内部开发接手说明

## 代码结构

| 文件 | 职责 |
| --- | --- |
| frostmourne/models.py | 环境/工作空间模型与字段校验 |
| frostmourne/storage.py | JSON 持久化、原子替换、配置冲突检测、快照脱敏 |
| frostmourne/ui.py | 主窗口、环境与本机设置弹窗、后台线程桥接 |
| frostmourne/runner.py | 运行快照、日志、状态、演示、锁及适配器调度 |
| frostmourne/adapters.py | 内部实现接口与注册表 |
| frostmourne/__main__.py | GUI 启动与命令行参数 |
| tests/ | 核心逻辑及 Qt 离屏集成测试 |

默认不执行任何外部脚本，不连接任何主机。配置路径只是保存的信息。EVB 和服务器已提供常用输入字段；DV 使用基础字段与扩展 JSON，不假定内部语义。串口端点使用 JSON 名称/地址映射，角色在内部实现。

## Adapter 约定

内部创建实现 initialize(environment, settings, emit, cancel) 的对象，并在代码中注册：

```python
from frostmourne.adapters import ADAPTERS
from internal_adapters.evb import InternalEvbAdapter

ADAPTERS["EVB"] = InternalEvbAdapter()
```

以上是内部接入示意，internal_adapters 不随公开仓库提供。接口返回 AdapterResult，含 ready、summary 和 action_state。只有所有必要后置检查通过，且 action_state 为 completed，才能返回 ready=True。

- environment 是捕获的配置副本；settings 是本机配置副本，不从 UI 线程读取可变控件。
- emit(progress, message) 将 0–100 进度及经过脱敏的消息写入日志并发送至主线程。
- cancel 是线程安全的 Event。它表示停止请求，不表示强制杀进程；内部实现须在安全点响应。
- 抛出异常时设备动作按 unknown 处理，保留 .run.lock；别在未知情况下自动重发。
- 无法完成就绪检查时返回 ready=False，不能把命令结束当成初始化成功。
- 注册仅来自可信代码；workspace.json 不允许指定任意导入模块或执行命令。

身份核验、烧录、网络配置、安装、日志成功条件等见根目录 internal_integration.md。内部模型在公司环境中补齐，不能从示例猜测。

## 持久化与并发边界

格式版本为 1，当前将环境与设置放在单一 workspace.json，便于保存选择与配置的一致状态。对未知字段/版本拒绝加载而不自动覆盖；将来扩展字段必须增加迁移与兼容策略。

保存使用临时文件与原子替换，配合短期 .save.lock 和文件摘要发现过期编辑。此机制用于本地多个客户端，未验证网络文件系统语义。初始化使用 .run.lock 阻止同一空间同时运行；不同工作空间/PC 指向同一设备或同一 FTP 目录的全局互斥尚未实现，真实适配时必须纳入对应约束。

启动程序不会恢复运行中的设备动作。打开工作空间只恢复配置，ready 始终重新检查。真实执行返回 ready 后编辑配置也会使 UI 就绪状态失效。

日志按运行分目录保存，GUI 只保留最近 2000 行；完整日志留在磁盘。GUI 窗口在任务执行中拒绝退出，可请求停止后等待线程结束。真实设备适配如无法中止，应在界面持续报告真实状态。

## 当前未完成部分

- 真实 SSH、SFTP、Telnet、Redfish 连接及设备适配。
- 文件分发、固件内容校验、真实就绪条件与版本确认。
- 跨空间/跨 PC 环境占用管理、凭据库、中心配置同步。
- 实际 Benchmark、测试类型扩展、监控和分析。
- 独立 EXE 打包、安装器和自动升级。

不要把公开骨架的测试通过理解为设备验证通过。离线演示始终返回 demo_completed 且 ready=False。
