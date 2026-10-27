# Ebon Blade · 自动化测试客户端

Ebon Blade 是一个运行在 Windows 上的实验环境自动化客户端。它以本地工作空间保存环境档案和测试组合，在同一界面完成环境编排、初始化、进度查看与日志留存。

项目名取意于《魔兽世界》的黑锋骑士团（Knights of the Ebon Blade）：这支力量专门替巫妖王承担艰难、危险且不那么体面的任务。对本项目而言，Ebon Blade 代表把重复、耗时、易错的环境准备工作交给自动化工具，让测试人员把精力留给真正需要判断的事情。

> 当前版本：v0.2.0。GUI、工作空间和多环境编排框架已经可运行；真实 EVB、DV、服务器初始化仍需接入内部实现。

![Ebon Blade 客户端预览](design/images/client-preview.png)

## 当前能力

- 当前提供一个稳定的测试类型标识，显示名称可在侧栏通过“编辑”按钮按工作空间修改；保留后续多测试类型扩展位置。
- 本次任务可按数量组合环境，例如 `2 × EVB + 1 × 通用服务器`。
- 环境档案与本次组合分开保存，同一档案可跨任务复用。
- 支持创建和打开工作空间、保存本机路径、编辑环境详情。
- 初始化在后台运行，提供进度、日志、停止请求、配置快照和结果记录。
- 离线演示不会连接设备、复制固件或执行脚本，也不会伪装成真实初始化成功。
- Benchmark 与“执行测试”目前只保留入口，第一版聚焦环境初始化。

## 软件架构

Ebon Blade 采用单机桌面客户端架构。UI 不直接执行设备命令，而是把一次测试需要的环境组合交给运行编排层；编排层先完成全组合检查，再按顺序调用对应环境适配器。

```text
Qt 桌面界面
    │
    ├── 工作空间与环境组合 ── JSON 持久化、迁移、冲突检查
    │
    └── 初始化任务 ── 快照、日志、进度、停止和结果
                         │
                         └── Adapter 边界
                               ├── EVB 内部实现
                               ├── DV 内部实现
                               └── 通用服务器内部实现
```

Adapter 是公开 GUI 框架与内部设备操作之间的边界。SSH、串口、BMC、固件准备及真实成功条件由内部适配器实现，工作空间不能指定任意 Python 模块或命令。

详细设计见 [架构设计](design/architecture.md)，实施范围见 [实施计划](design/implementation-plan.md)。

## 文件组织

```text
ebon_blade/
├── src/ebon_blade/              主要软件源码
│   ├── __main__.py              程序入口
│   ├── ui.py                    Qt 主界面和配置弹窗
│   ├── models.py                工作空间、环境档案和组合模型
│   ├── storage.py               本地持久化与冲突保护
│   ├── runner.py                初始化任务编排、日志和结果
│   └── adapters.py              内部设备能力接口
├── design/                      产品与技术设计
│   ├── architecture.md          架构设计
│   ├── implementation-plan.md   实施计划
│   ├── requirements.md          原始需求
│   ├── internal-integration.md  内部设备接入索引
│   └── images/                  UI 草图、批注和当前预览
├── talk/                        与不同 AI 的讨论记录
│   ├── codex-discussion.md      本轮多轮讨论与决策
│   └── conversation-summary.md  会话归档说明
├── tests/                       核心逻辑与 Qt 离屏测试
├── tools/                       开发辅助脚本
├── HOW_TO_USE.md                使用、开发和内部接入指南
├── launch.bat                   Windows 快速启动脚本
├── pyproject.toml               Python 项目与桌面入口配置
└── requirements.txt             运行依赖
```

`talk` 专门用于保存人与不同 AI 的讨论、决策过程和需求演进，不与正式设计文档混放。新的讨论可以按 AI、主题或日期增加独立 Markdown 文件。

## 开始使用

安装与启动、工作空间操作、离线演示、开发环境、测试方法和 Adapter 接入说明统一放在 [HOW_TO_USE.md](HOW_TO_USE.md)。最短启动方式如下：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
launch.bat
```

当前源码也支持安装为开发包后运行 `ebon-blade` 命令。真实设备接入前，建议始终勾选“离线演示”。

## 文档入口

| 文档 | 用途 |
| --- | --- |
| [HOW_TO_USE.md](HOW_TO_USE.md) | 软件使用、开发、测试与 Adapter 接入 |
| [design/architecture.md](design/architecture.md) | 客户端架构、流程和安全边界 |
| [design/implementation-plan.md](design/implementation-plan.md) | 三块式实施计划和验收方式 |
| [design/internal-integration.md](design/internal-integration.md) | 私有设备动作需要补齐的信息 |
| [design/requirements.md](design/requirements.md) | 用户最初的需求记录 |
| [talk/codex-discussion.md](talk/codex-discussion.md) | 与 Codex 的结构化讨论记录 |
| [talk/conversation-summary.md](talk/conversation-summary.md) | 会话归档范围和补充记录 |

工作空间和运行日志属于本地运行数据，不应提交到代码仓库。环境配置只保存凭据引用，不应写入密码、密钥或其他敏感信息。
