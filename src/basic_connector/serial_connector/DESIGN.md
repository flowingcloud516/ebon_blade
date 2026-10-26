# 网络串口 Connector 设计

状态：讨论中
最近更新：2026-10-24

## 1. 使用场景

实验环境通过串口服务器暴露网络端点，通常使用 IP + Port，并以 Telnet 或近似 Telnet 的方式连接。连接后主要进行：

- 持续接收启动日志或设备输出。
- 写入命令和换行。
- 等待立即返回或延迟返回的结果。
- 对长时间操作匹配预期字符串、正则或受信任判断函数。

串口端点属于共享实验资源，同一物理串口通常不能被多个任务同时控制。Connector 必须支持独占占用和明确释放。

## 2. 与 SSH 的共同点和差异

可以共用增量输出缓冲、Matcher、总超时、输出空闲超时、expect、取消、日志回调、脱敏和有限输出尾部。

| SSH | 网络串口 |
| --- | --- |
| 每条命令可创建独立 Channel | 所有命令和异步输出共享同一字节流 |
| 通常有退出码和 stderr | 通常没有退出码，只有输出、提示符或状态检查 |
| SSH 协议提供认证和 keepalive | 串口服务器可能只有 TCP/Telnet，保活依设备而定 |
| 输出容易归属到对应 Channel | 启动日志、回显和命令响应可能混杂 |

因此建议抽取共享的 `StreamExpectEngine`，但不把两个 Connector 合并：

```text
SSH Connector ──────┐
                    ├── StreamExpectEngine
Serial Connector ──┘
```

共享引擎只负责“收到文本后是否匹配、是否超时、保留多少输出”，不负责连接、发送命令、Telnet协商或设备身份。

## 3. 协议技术选型

Python标准库`telnetlib`已在Python 3.13移除，项目不能依赖它。

### 方案A：telnetlib3

- 支持asyncio，与SSH Connector事件循环模型一致。
- 实现Telnet IAC和选项协商。
- 适合遵循标准Telnet协议的串口服务器。
- 增加第三方运行依赖。

### 方案B：asyncio原始TCP Stream

- 使用`asyncio.open_connection(IP, port)`，依赖最少。
- 适合透明TCP转发、没有Telnet协商的串口服务器。
- 如果服务端发送IAC协商字节，则需要Telnet解析，不能当普通串口数据。

定义统一Transport协议，并保留两个后端位置：

```text
SerialConnector
├── RawTcpTransport
└── TelnetTransport（telnetlib3）
```

第一期**优先实现RawTcpTransport**，不新增第三方依赖。TelnetTransport仅保留扩展位置。内部验证需要检查连接初始字节中是否存在Telnet IAC协商；如果Raw TCP无法正确处理，再评估telnetlib3。人工使用Xshell的Telnet模式可以连接，并不能单独证明服务端一定进行完整Telnet协商。

### telnetlib3与最小Telnet协商子集的差异

| 方案 | 实现内容 | 优点 | 风险与成本 |
| --- | --- | --- | --- |
| telnetlib3 | 成熟库处理IAC、DO/DON'T、WILL/WON'T、子协商、转义及asyncio读写 | 协议覆盖完整，兼容性和维护性更好 | 增加第三方依赖；需验证编码和协商行为 |
| 最小协商子集 | 项目自行识别IAC并响应少量常见选项，同时过滤控制字节 | 不增加依赖；固定设备可能够用 | 容易遗漏IAC转义、子协商、终端类型、窗口和回显；设备变化后维护风险高 |

最小实现不只是删除`0xFF`。Telnet用IAC作为控制前缀，数据中的IAC需要转义，选项还可能包含子协商。错误处理可能吞掉真实串口字节、污染日志，或让服务端持续等待协商。

阶段性建议：第一版只实现RawTcpTransport；内网没有IAC且行为正常就不引入Telnet库；若发现完整或多样协商，优先使用telnetlib3。只有确认全部目标设备只使用固定、极小的协商集合时，才考虑自研最小子集。

## 4. 顶层连接模型

建议采用任务级长连接：

```text
一次环境初始化任务
└── SerialSession（一个IP:Port长连接）
    ├── 后台Reader：持续收集所有字节
    ├── 命令1：写入并等待expect
    ├── 命令2：写入并等待expect
    └── 日志观察：只等待expect，不写命令
```

串口没有“一条命令一个Channel”。同一Session上的命令默认串行执行；后台Reader始终唯一，不能让多个调用方同时读取socket。

一个端点同一时间只能有一个命令事务，但可以存在多个只读观察器。观察器不能消费或删除其他事务需要的输出。

第一期提供两种逻辑模式：

- `CONTROL`：允许写命令并等待expect，同一Session内写操作严格串行。
- `OBSERVE_ONLY`：只读取并匹配日志，不发送命令，适合持续捕捉启动输出。

如果串口服务器只允许一个TCP客户端，只读观察器应挂接到已有CONTROL Session的后台Reader；如果允许多连接，才可创建独立只读Session。此能力需要内网验证。

## 5. 输出缓冲与命令边界

- 后台Reader持续读取，不因当前没有命令而停止。
- 使用有限大小的环形内存缓冲区，完整原始日志写入运行目录。
- 每个命令记录开始时的缓冲区序号，只匹配此后的新输出，避免旧日志误命中expect。
- 可按设备规则忽略命令回显。
- 行尾可配置为`\r`、`\n`或`\r\n`。
- 编码和无法解码字节的处理可配置，同时保留原始字节日志。

## 6. 命令与expect模型

建议复用SSH的Matcher和超时语义，但串口没有退出码：

```text
SerialCommandRequest
├── command / raw_bytes
├── line_ending
├── expected matchers
├── failure matchers
├── total_timeout
├── idle_timeout
├── completion_policy
├── side_effect
└── redact_patterns
```

| 策略 | 成功条件 |
| --- | --- |
| `EXPECT_REQUIRED` | 指定成功Matcher命中 |
| `PROMPT_REQUIRED` | 设备提示符重新出现 |
| `QUIET_AFTER_EXPECT` | expect命中，随后指定时间内无新输出 |
| `WRITE_ONLY` | 数据成功写入；不代表设备执行成功 |

长时间命令默认必须提供成功Matcher、失败Matcher或提示符规则，不能只等待固定秒数后假定成功。

## 7. 共享与资源占用

用户确认理论上同一时间只允许一个人控制，但第一期暂不在Connector处理跨任务或跨PC冲突。资源所有权和抢占策略留给顶层环境框架。

Connector自身仍保证：

- 同一个SerialSession内只有一个写命令事务。
- 多个只读观察器可以订阅同一个后台Reader。
- Session关闭时释放自身socket和等待者。
- 发现连接被服务器拒绝或输出被其他会话明显干扰时，返回诊断错误，但不实现分布式锁。

## 8. 保活、断线与重连

Telnet/透明串口没有统一可靠的应用层保活：

- 启用TCP keepalive，并通过内部网络验证参数。
- 建连后CONTROL Session发送一次可配置回车，并等待连接探测expect，用于确认进入目标串口。
- 长命令执行期间不周期性发送回车，避免干扰命令。
- 空闲时也不默认周期性发送字符；Adapter可显式调用`probe()`。
- 只有内部确认安全时，才使用Telnet NOP/AYT或设备专用探测。
- EOF、写入失败或TCP错误表示断线。

重连后终端上下文可能变化：

1. 创建全新TCP/Telnet连接。
2. 重新完成登录或提示符同步。
3. 清空当前命令匹配窗口，但保留运行日志。
4. 不自动重放断线时正在执行的命令。
5. 通过提示符、只读命令或Adapter专用检查重新确定设备状态。

重连完成后CONTROL Session默认再次执行“回车 + 探测expect”。OBSERVE_ONLY模式绝不发送回车，其连接成功只能表示TCP已建立；是否为正确串口需要通过后续日志Matcher或顶层环境身份检查确认。

## 9. 并发和线程边界

- 一个SerialSession、Reader和Writer属于同一asyncio event loop。
- UI和Adapter通过异步接口或线程安全事件桥接，不直接读写socket。
- 命令事务使用asyncio Lock串行化。
- 日志回调不能阻塞Reader。
- Session关闭时取消Reader、唤醒expect等待者并释放端点锁。

## 10. 第一阶段建议范围

1. Transport协议及Raw TCP/Telnet后端选择。
2. 任务级长连接；资源占用由顶层框架处理。
3. 唯一后台Reader、环形缓冲和原始日志。
4. 命令写入、可配置行尾和Matcher。
5. 总超时、空闲超时、取消和断线状态。
6. 字符串、正则和受信任判断函数。
7. 重连后提示符同步，但不自动重放命令。
8. Fake Transport单元测试和可选内网串口服务器测试。

暂不做跨PC全局锁、多人同时写一个串口、任意脚本插件和未知破坏性操作的自动恢复。

## 11. 已确认决定

1. IP:Port连接后直接进入设备串口，没有用户名或密码认证。
2. CONTROL模式建连和重连后发送一次回车，通过配置的expect确认串口可用。
3. 同一时间理论上只允许一个控制方，但冲突管理留给顶层框架。
4. 第一阶段提供只读日志观察能力。
5. 每条命令配置自己的成功/失败expect，不假设统一提示符。
6. 优先实现RawTcpTransport，尽量不增加第三方依赖。
7. 行尾类型、Raw TCP兼容性、TCP keepalive和多连接行为进入内部验证清单。

## 12. 实施决定与后续触发条件

1. 现在不抽取共享`StreamExpectEngine`。SSH和串口分别实现，即使暂时存在代码重复；真实验证后再重构。
2. 第一版只实现RawTcpTransport。
3. 内网验证若未发现IAC协商，不增加Telnet依赖。
4. 若发现完整Telnet协商，默认建议引入telnetlib3；是否改为最小自研子集，在取得实际协商字节样本后再决定。
