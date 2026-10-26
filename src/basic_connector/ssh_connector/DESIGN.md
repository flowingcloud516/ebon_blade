# SSH Connector 设计

状态：接口收敛中
最近更新：2026-10-24

## 1. 目标与第一期范围

SSH Connector 为环境 Adapter 提供统一的 Linux OpenSSH 操作能力。环境 Adapter 不直接依赖 AsyncSSH、OpenSSH CLI 或其他具体实现。

第一期范围：

- 使用用户名和密码连接标准 Linux OpenSSH 服务。
- 执行短命令和最长约 10 分钟的长命令。
- 持续采集 stdout、stderr，并支持匹配预期输出。
- 支持本地 PC 与第一跳主机 A 之间的文件上传和下载。
- 支持从 A 二次 SSH 登录 B，并在 B 上执行命令。
- 需要向 B 传文件时，明确执行 PC → A → B 两段传输。
- 使用 AsyncSSH 进行技术验证，通过故障实验后再确认正式选型。

第一期暂不包含：

- 私钥认证。
- BMC、交换机或其他非标准 SSH 服务。
- 全局永久连接池。
- 对状态不明的有副作用命令自动重试。

## 2. 分层边界

```text
Environment Adapter
    ↓ 只使用项目定义的协议
SSHConnector
    ├── command execution
    ├── output observation / expect
    ├── SFTP transfer
    └── second-hop session and staged transfer
        ↓
AsyncSSH backend（第一候选）
```

SSH Connector 负责连接、认证、Channel、输出、超时、取消和传输；它不决定某条环境初始化命令应何时执行，也不判断整套 EVB 或服务器是否最终就绪。

## 3. 顶层连接架构

第一期以**任务级长连接、操作级短 Channel**为主模型：

```text
一次环境初始化或测试任务
└── SSH ManagedSession（长生命周期）
    ├── Command Channel 1（短命令，结束后关闭）
    ├── Command Channel 2（长命令，结束或满足策略后关闭）
    ├── SFTP Session（按传输创建，完成后关闭）
    └── Tunnel to B
        └── B ManagedSession
            └── Command Channel（每条命令独立）
```

这是一种混合模型：

- **长连接**指 SSH Transport/Connection 在一次环境任务中复用，避免每条命令都重新进行 TCP、SSH 握手和密码认证。
- **Channel**是 SSH 连接内部的一条逻辑数据流。执行命令、打开交互 Shell、启动 SFTP 或建立隧道，都会使用各自的 Channel。
- 一条 SSH Connection 可以同时或依次承载多个 Channel；关闭某个命令 Channel 不等于关闭整个 SSH Connection。
- 默认每条命令打开独立 Channel，完成后关闭；后续命令继续复用底层长连接。
- 只有确实依赖 Shell 上下文的操作，才创建连续交互的 Shell Channel。普通命令不得为了“长连接”而共用一个交互 Shell。

### 3.1 长连接作用域

长连接限定在一次环境初始化任务或一次明确的测试任务内。任务结束、用户取消、工作空间切换或达到最大租期时关闭。第一期不建立跨任务、跨用户或客户端全局永久连接池。

连接及其 asyncio event loop 必须属于同一个工作线程，不允许跨线程共享。Environment Adapter 持有逻辑会话句柄，但不直接操作 AsyncSSH 对象。

连接层需要分别设置 TCP 连接超时、SSH 握手/认证超时、keepalive、命令总超时、输出空闲超时，以及文件传输总超时或停滞超时。

### 3.2 ManagedSession 状态机

```text
DISCONNECTED
    ↓ connect
CONNECTING ──失败──> DISCONNECTED
    ↓ 成功
READY
    ↓ keepalive失败 / I/O异常
SUSPECT
    ↓ 确认失联
RECONNECTING ──成功──> READY
    │
    └──超过重连预算──> DISCONNECTED

任意状态 ── close/cancel/task end ──> CLOSED
```

- `READY`：可以创建新 Channel。
- `SUSPECT`：停止派发新操作，等待当前 I/O 结果或主动探测。
- `RECONNECTING`：旧连接及其全部 Channel 均失效，创建全新连接并重新认证、核验身份。
- `CLOSED`：最终状态，不自动重新打开。

### 3.3 保活与失联检测

第一期同时使用 SSH 应用层 keepalive 和 TCP keepalive。SSH keepalive 是主要健康依据，Channel 创建或 I/O 异常也可以立即把连接标记为 `SUSPECT`。

建议初始默认值为 keepalive 间隔 15 秒、连续无响应 3 次，约 45 秒无法确认响应后进入重连流程。该数值必须通过真实实验室网络验证，且不能替代命令总超时和输出空闲超时。

### 3.4 断开与重连

重连采用有界指数退避并加入随机抖动，例如 1、2、4、8 秒，同时受最大次数和最大总时长限制。重新连接后必须：

1. 建立全新的 SSH Connection，不能复用旧对象。
2. 重新进行密码认证和主机身份核验。
3. 丢弃旧连接上的命令 Channel、SFTP Session 和隧道。
4. 若存在 B 会话，先恢复 A，再重建 A→B 隧道和 B 会话。

“恢复连接”和“重放操作”是两件事：

| 断线时状态 | 重连后的处理 |
| --- | --- |
| 没有正在执行的操作 | 可以透明恢复逻辑会话 |
| 正在执行只读、幂等且显式标记可重试的命令 | 可按命令策略重新执行 |
| 正在执行安装、重启、启动服务等有副作用命令 | 不自动重放；标记 `unknown`，重连后执行专用状态检查 |
| 正在传输临时文件 | 校验临时文件后按传输策略续传或重新上传 |
| 正在执行不可确认的交互操作 | 标记 `unknown` 并停止后续破坏性步骤 |

### 3.5 主机身份与 known_hosts

用户提出环境经常变化，希望每次重新打开 SSH 时清理该 IP 的 known_hosts 记录。设计上不应无条件删除记录并自动信任新密钥，否则错误 IP、错误设备或中间人攻击无法被发现，也与项目避免操作错误板卡的目标冲突。

第一期不直接修改用户系统的全局 `known_hosts`，而由项目维护独立主机身份存储：

| 策略 | 行为 | 用途 |
| --- | --- | --- |
| `STRICT` | 主机密钥必须与已保存值一致 | 稳定主机 |
| `ENVIRONMENT_PINNED` | 密钥绑定环境 ID，而不只绑定 IP | IP 经常调整的实验环境，推荐 |
| `REPLACE_AFTER_VERIFY` | 密钥变化时先独立核验环境身份，再替换记录 | 设备重装或更换后使用 |
| `RESET_FOR_REPROVISION` | 明确重装后仅重置指定环境记录，首次重连接受并固定新密钥 | 每次初始化都会重装系统的环境 |
| `INSECURE_ACCEPT_ANY` | 不校验主机密钥 | 仅显式诊断模式，禁止默认使用 |

A 和 B 分别维护身份记录。B 即使只在 A 的网络中可达，也不能因为使用隧道而跳过 B 的主机密钥检查。

用户已确认环境初始化可以理解为重装系统，目标主机密钥会合理变化。因此第一期增加 `RESET_FOR_REPROVISION`：

1. 只能由 Environment Adapter 在明确进入重装/重新部署步骤后启用，普通 `connect()` 不得自动触发。
2. 只清理项目身份存储中指定环境 ID 的记录，例如只重置 B，保留 A。
3. 不修改用户系统的全局 `known_hosts`。
4. 重装后的第一次连接接受新密钥，并立即绑定该环境 ID。
5. 本次任务后续连接及重连必须匹配这个新密钥；再次变化则报错。
6. 运行记录保存“已授权主机密钥轮换”和新指纹，不保存密码。

`ENVIRONMENT_PINNED` 表示主机密钥绑定 E001、A、B 等逻辑环境身份，而不只绑定 IP，因此环境换 IP 时仍能检查身份。`REPLACE_AFTER_VERIFY` 用于没有已知重装动作却遇到密钥变化的场景：先停止，再通过其他身份信息或人工确认后替换。明确重装场景使用 `RESET_FOR_REPROVISION`，不需要每次人工确认。

## 4. 命令执行模型

短命令和长命令使用统一的命令请求，但长命令可以额外配置输出观察规则。

建议的概念模型：

```text
CommandRequest
├── command
├── total_timeout
├── idle_timeout
├── expected_patterns[]
├── completion_policy
├── side_effect
└── encoding

CommandResult
├── status
├── exit_status / exit_signal
├── matched_pattern
├── stdout_tail / stderr_tail
├── started_at / finished_at
└── remote_state
```

### 4.1 expect 的语义

用户提出长命令最好设置 expect 字符串。第一期需要明确区分：

- `observe`：匹配到字符串只表示出现了阶段性输出，继续等待进程退出。
- `success_signal`：匹配到字符串表示业务成功信号，但仍尝试等待命令正常退出。
- `completion_signal`：适用于不会主动退出或需要匹配后主动结束会话的命令；必须由调用方明确选择。
- `failure_signal`：匹配后立即报告失败，并按安全规则决定是否关闭 Channel。

默认策略应当是“退出码 + 必要的预期输出”共同判断成功，而不是仅看到 expect 字符串就认为远端动作结束。

第一期支持三种匹配器：

- 普通字符串匹配，作为默认方式。
- 正则表达式匹配。
- Adapter 在运行时传入判断函数，用于处理复杂输出。

判断函数属于受信任代码接口，不能从工作空间 JSON 动态加载或序列化。工作空间配置只允许声明普通字符串或正则表达式；复杂判断函数由受信任的 Environment Adapter 注册。

用户已确认：当指定的完成 expect 命中时，可以认为当前步骤成功。为了避免把“步骤成功”和“远端进程退出”混为一谈，结果仍分别记录：

- `step_status`：当前自动化步骤是否达到预期。
- `remote_process_state`：远端进程为 `exited`、`running` 或 `unknown`。
- `connection_state`：SSH 连接是否仍可使用。

完成策略第一期收敛为：

| 策略 | 成功条件 | 命中 expect 后的行为 |
| --- | --- | --- |
| `EXIT_REQUIRED` | 命令正常退出，并满足必要 expect | 等待退出，默认策略 |
| `EXPECT_REQUIRED` | 完成 expect 命中 | 立即返回步骤成功；远端进程状态单独记录 |
| `EXIT_OR_EXPECT` | 正常退出或完成 expect 任一发生 | 返回步骤成功，并记录触发原因 |

命中 expect 后是否关闭命令 Channel 不能由“步骤成功”隐式决定，应由命令请求显式选择。关闭命令 Channel 不会关闭底层长连接，但可能影响该 Channel 上的远端前台进程。若调用方希望进程继续运行，则远端命令本身必须使用可靠的后台化方式并提供 PID 或状态查询手段。

### 4.2 长命令

- stdout 和 stderr 必须持续读取，避免远端输出缓冲区填满后阻塞。
- UI 日志接收增量输出，但结果文件只保留受控大小的内存尾部，完整日志写入运行目录。
- 总超时和输出空闲超时是两个不同概念。
- 本地取消、超时或连接断开不等于远端进程已经结束。
- 对有副作用的命令，无法确认远端结果时返回 `unknown`，不能自动重新执行。

## 5. 文件传输

### 5.1 PC 与 A 之间

第一期使用 SFTP，至少提供：

- 上传文件。
- 下载文件。
- 创建目标目录。
- 覆盖策略。
- 传输进度。
- 本地大小与远端大小检查。
- 可选散列校验。
- 临时文件上传完成后原子改名，避免消费者读取半份文件。

### 5.2 PC → A → B

用户明确要求传输到 B 时走两段：

1. PC 通过 SFTP 上传到 A 的临时目录。
2. Connector 从 A 登录 B。
3. 由 A 将文件传到 B。
4. 在 B 上验证文件大小或散列。
5. 根据策略清理 A 上的中间文件。

这一流程不能伪装成单次传输。结果中应分别记录 PC→A 和 A→B 两段状态；任一段失败都要指出失败位置。

尚待确定 A→B 的具体传输方式：

- 在 A 上执行 `sftp`/`scp` 命令。
- 由程序通过 A 建立到 B 的隧道，再创建第二个 SFTP 会话。

用户补充“一般在 B 上完成相关命令”。因此更接近的候选流程是：先将文件上传到 A，然后登录 B，在 B 上执行从 A 拉取文件的动作。此方案需要确认 B 如何安全认证 A，不能把 A 的密码拼进 `scp` 或 `sftp` 命令行。

## 6. 二次登录

拓扑：

```text
Windows PC ──SSH──> A ──SSH──> B
```

需要区分两种实现语义：

1. 程序通过 A 建立 TCP 隧道，再由 AsyncSSH 创建到 B 的独立 SSH 连接。
2. 在 A 的交互 Shell 内执行 `ssh B`，然后通过提示符进行二次认证和命令交互。

第一种更容易获得结构化退出码、stdout/stderr、超时和连接状态，建议作为默认候选。第二种只在目标环境必须模拟人工交互时使用，因为提示符、回显、终端状态和密码交互更脆弱。

“通过 A 建立隧道”的含义如下：

```text
1. PC 与 A 建立第一条 SSH 连接。
2. PC 请求 A 打开一条到 B:22 的 TCP 通道。
3. 程序通过这条通道与 B 完成第二次、独立的 SSH 握手和密码认证。
4. 对程序而言，A 和 B 是两个结构化 SSH 会话；对网络而言，B 看到的连接来源是 A。

PC ── SSH connection A ──> A
PC ── SSH connection B over A tunnel ──> A ── TCP ──> B:22
```

这不是让 PC 绕过 A 直接访问 B，也不是在 A 的终端里输入 `ssh B`。它保留了“必须经过 A 才能到 B”的网络路径，同时避免解析 `password:`、Shell 提示符和终端回显。第一阶段建议优先验证此方案。

无论采用哪种方式，B 都需要独立的身份核验、认证超时、命令超时和结果记录。

## 7. 状态与错误分类

至少区分：

- 配置无效。
- TCP 连接失败或超时。
- SSH 握手失败。
- 密码认证失败。
- 主机身份不匹配。
- Channel 创建失败。
- 命令退出码非零。
- expect 等待超时。
- 输出长时间无变化。
- 连接中途断开。
- 文件传输失败或校验失败。
- 用户取消。
- 远端动作状态未知。

异常消息和日志不得包含密码。密码只通过受控凭据引用或运行时输入进入 Connector，不写入工作空间快照和命令行。A 和 B 都采用密码认证，但使用两个独立的凭据引用，不假设用户名或密码相同。

## 8. 技术验证

AsyncSSH 验证至少覆盖：

1. 密码认证和主机身份校验。
2. 短命令的 stdout、stderr 和退出码。
3. 10 分钟长命令及增量日志。
4. expect 成功、失败和超时。
5. 大量输出不会阻塞。
6. SFTP 上传、下载和散列验证。
7. PC→A→B 命令执行。
8. PC→A→B 分段文件传输。
9. 命令运行中断网。
10. 空闲连接失效、取消和清理。

## 9. 已确认的接口决定

1. 完成 expect 命中后，当前步骤可以成功；步骤状态、远端进程状态和连接状态分别记录。
2. expect 默认使用普通字符串，同时支持正则表达式和受信任 Adapter 传入的判断函数。
3. A 和 B 均使用密码认证，凭据分别管理。
4. 上传目录、覆盖策略和中间文件清理策略由 Environment Adapter 配置。

## 10. 本轮顶层决定

1. 第一阶段采用任务级长连接；二次登录也复用 A 的任务级长连接。
2. 每条普通命令仍使用独立的短生命周期 Channel。expect 命中后可以关闭该命令 Channel，而不关闭底层 SSH Connection。
3. 二次登录优先使用 A→B 隧道建立 B 的独立结构化 SSH 会话；调用方只关心最终能在 B 上可靠执行命令。
4. A→B 文件通常由 B 发起，并使用用户名、密码访问 A；自动化方式仍需技术验证。
5. 项目不静默清理系统 known_hosts 并接受任意新密钥，而维护适合动态实验环境的独立身份存储。

## 11. 本轮确认

1. 长连接作用域正式确定为一次环境初始化或测试任务；环境初始化完成后关闭 SSH Connection。
2. 二次登录的内部实现以可靠和方便为原则，调用方不依赖具体方式。
3. A→B 文件传输第一期允许使用交互 Channel 处理密码；实现时不得在命令行和日志中暴露密码。
4. 系统重装后的主机密钥轮换使用 `RESET_FOR_REPROVISION`，只重置目标环境的项目记录，不影响 A 或用户全局 known_hosts。
5. 需要内部网络或真实设备验证的参数与场景统一记录在同目录的 `INTERNAL_VALIDATION.md`。
