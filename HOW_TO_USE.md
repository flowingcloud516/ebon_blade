# Ebon Blade 使用与开发指南

本文面向两类读者：使用客户端准备测试环境的人，以及继续开发 GUI、工作空间或设备适配器的人。

## 一、安装与启动

### 环境要求

- Windows 10/11
- Python 3.10 或更新版本；当前验证版本为 Python 3.12
- 首版运行依赖为 PySide6 Essentials

在仓库根目录执行：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
launch.bat
```

`launch.bat` 会自动把 `src` 加入 Python 搜索路径。也可以按标准 Python 项目方式安装并启动：

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\ebon-blade.exe
```

启动时可直接指定工作空间和客户端偏好目录：

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m ebon_blade --workspace D:\LabWorkspaces\example
.\.venv\Scripts\python.exe -m ebon_blade --state-dir .local\state
```

## 二、使用客户端

1. 点击“新建”，选择一个空目录创建工作空间；已有工作空间使用“打开”。
2. 在“本次环境组合”中按数量添加环境，例如两行 EVB 和一行通用服务器。
3. 每一行先选环境类型，再选择已有环境档案；没有档案时点击“新建档案”。
4. 在“配置详情”中维护版本、连接信息、凭据引用和扩展参数。
5. 在“本机设置”中维护固件目录、FTP 目录、启动脚本和 Python 路径。
6. 首次验证时勾选“离线演示”，再点击“环境初始化”查看进度和日志。
7. 接入真实 Adapter 后取消“离线演示”，客户端会先检查本次组合需要的全部适配器，再开始设备操作。

离线演示不会连接设备、传输文件或运行脚本，结束后也不会把环境标记为真实就绪。当前“执行测试”按钮尚未接入。

### 工作空间内容

```text
用户选择的目录/
├── workspace.json          环境档案、本次组合和本机设置
├── .run.lock               初始化运行或设备状态未知时的保护记录
└── runs/<运行编号>/
    ├── snapshot.json       本次配置快照，敏感键经过脱敏
    ├── execution.log       完整执行日志
    └── result.json         各环境及整体执行结果
```

重新打开客户端只恢复配置，不代表设备仍处于上一次的就绪状态。若异常退出留下 `.run.lock`，应先确认没有设备动作仍在运行，再由内部人员处理；程序不会自动解锁并重试。

## 三、开发环境

安装依赖和当前项目：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
```

运行全部测试：

```powershell
$env:PYTHONPATH = "$PWD\src"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

生成最新 GUI 预览：

```powershell
.\.venv\Scripts\python.exe tools\render_preview.py
```

预览脚本只使用临时、虚构的工作空间数据，输出到 `design/images/client-preview.png`，不会连接真实环境。

### 源码职责

| 文件 | 职责 |
| --- | --- |
| `src/ebon_blade/models.py` | 环境档案、测试类型、本次组合和字段校验 |
| `src/ebon_blade/storage.py` | JSON 持久化、原子替换、配置冲突检测和脱敏 |
| `src/ebon_blade/ui.py` | 主窗口、配置弹窗和后台线程桥接 |
| `src/ebon_blade/runner.py` | 运行快照、日志、锁、组合编排和 Adapter 调度 |
| `src/ebon_blade/adapters.py` | 内部设备能力接口和注册表 |
| `src/ebon_blade/__main__.py` | GUI 启动及命令行参数 |
| `tests/` | 核心逻辑和 Qt 离屏集成测试 |

## 四、接入真实环境

内部实现一个带有 `initialize(environment, settings, emit, cancel)` 方法的对象，并注册到适配器表：

```python
from ebon_blade.adapters import ADAPTERS
from internal_adapters.evb import InternalEvbAdapter

ADAPTERS["EVB"] = InternalEvbAdapter()
```

内部实现不随当前仓库提供。接口返回 `AdapterResult`，包含 `ready`、`summary` 和 `action_state`。

- `environment` 和 `settings` 是启动任务时捕获的配置副本。
- `emit(progress, message)` 提交 0–100 的当前环境进度和已脱敏消息。
- `cancel` 是停止请求，不代表可以强制终止任何底层工具；实现应在安全点响应。
- 只有必要后置检查全部通过，且 `action_state == "completed"`，才能返回 `ready=True`。
- 抛出异常时设备动作状态按未知处理并保留 `.run.lock`，不能自动重发破坏现场。
- 工作空间不能动态导入模块或运行任意命令；Adapter 只能由受信任代码注册。

EVB、服务器和 DV 的具体输入、成功条件与异常场景见 [内部接入索引](design/internal-integration.md)。DV 的语义和实现由内部系统决定。

## 五、数据与并发边界

当前工作空间格式版本为 2。环境档案、测试类型、本次环境组合和本机设置保存在同一个 `workspace.json`，旧版单选配置在读取时迁移为目标列表。

保存采用临时文件与原子替换，并使用短期 `.save.lock` 和内容摘要避免多个窗口静默覆盖。初始化使用 `.run.lock` 阻止同一工作空间并行运行。不同工作空间或不同 PC 指向同一物理设备的全局占用管理尚未实现。

环境配置应保存凭据引用，不能保存密码或密钥。Adapter 仍有责任确保日志、异常和外部工具输出不泄露敏感信息。

## 六、当前未完成

- 真实 SSH、SFTP、串口、Telnet、Redfish/BMC 操作。
- 固件和安装包分发、内容校验及真实就绪检查。
- 跨工作空间、跨执行机的设备占用管理。
- 实际 Benchmark、测试执行、多测试类型管理和无人值守调度。
- 独立 EXE、安装器和自动升级。

自动测试通过只说明客户端框架符合当前约定，不代表真实设备已经验证通过。
