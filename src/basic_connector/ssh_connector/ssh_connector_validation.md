# SSH Connector验证清单

> **文档定位**：SSH Connector真实环境验证清单。
>
> **主要作用**：覆盖保活、重连、Expect、主机密钥、SFTP和跳板场景。
>
> **使用方式**：在内网提供脱敏测试参数后逐项执行并记录结果，不在本文填写凭据。

设计依据：[SSH Connector设计](ssh_connector_design.md)

状态：待内部执行
最近更新：2026-10-24

## 1. 使用说明

本文件只记录必须在真实内部网络、设备或部署环境中验证的事项。不要填写真实密码、密钥、IP、内部命令或其他敏感信息；可使用环境编号和脱敏结果。

每项完成后填写测试日期与执行人、脱敏环境、实际参数、观察结果、是否通过，以及对[SSH Connector设计](ssh_connector_design.md)的修改建议。

### 内网执行人员需要准备

必选：

- 一台允许测试的标准 Linux OpenSSH 主机。
- 主机 IP、SSH 端口、测试用户名和密码。
- 一个不会影响业务的脱敏环境编号。
- 明确允许执行的基础命令；默认测试只使用 `printf`。

可选：

- 一个明确允许写入和删除测试文件的远端临时目录，用于 SFTP 往返测试。
- 一台只能从 A 到达的 B 主机及其独立账号密码，用于二次跳转测试。
- 可以控制网络断开/恢复的测试时段，用于重连验证。
- 可以执行一次测试性重装的环境，用于主机密钥轮换验证。

### 安全要求

- 不要使用生产任务正在占用的环境。
- 不要把密码写进本文件、Git、命令参数、日志截图或测试结果。
- `EBON_SSH_REMOTE_TMP` 必须指向明确允许测试程序写入的目录。
- 断网、重装和长时间稳定性测试应单独安排，不与基础连通测试混在同一轮执行。
- 测试完成后移除当前 PowerShell 会话中的密码环境变量。

运行基础单元测试：

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m unittest tests.test_ssh_connector -v
```

运行内网基础连接测试：

```powershell
$env:PYTHONPATH = "$PWD\src"
$env:EBON_SSH_HOST = "目标IP"
$env:EBON_SSH_PORT = "22"
$env:EBON_SSH_USER = "用户名"
$env:EBON_SSH_PASSWORD = "密码"
$env:EBON_SSH_ENV_ID = "脱敏环境编号"
python -m unittest tests.test_ssh_connector_live -v
```

基础内网测试会验证：连接和密码认证、主机密钥首次记录、命令退出码、stdout/stderr、expect，以及同一长连接连续创建多个命令 Channel。没有设置可选变量时，不会上传文件或连接 B。

可选测试 SFTP 和 A→B 跳转：

```powershell
$env:EBON_SSH_REMOTE_TMP = "/明确允许写入的临时目录"
$env:EBON_SSH_B_HOST = "B的目标地址（从A可达）"
$env:EBON_SSH_B_PORT = "22"
$env:EBON_SSH_B_USER = "B用户名"
$env:EBON_SSH_B_PASSWORD = "B密码"
$env:EBON_SSH_B_ENV_ID = "B的脱敏环境编号"
python -m unittest tests.test_ssh_connector_live -v
```

测试结束后建议从当前 PowerShell 会话移除密码变量：

```powershell
Remove-Item Env:EBON_SSH_PASSWORD
Remove-Item Env:EBON_SSH_B_PASSWORD -ErrorAction SilentlyContinue
```

## 2. Keepalive 参数

目标：确定任务级长连接在实验室网络中的合理保活参数。

| 编号 | 空闲时长 | keepalive interval | count max | 网络条件 | 预期 |
| --- | ---: | ---: | ---: | --- | --- |
| KA-01 | 30 分钟 | 15 秒 | 3 | 正常网络 | 连接保持可用 |
| KA-02 | 2 小时 | 15 秒 | 3 | 正常网络 | 连接保持可用 |
| KA-03 | 30 分钟 | 30 秒 | 3 | 正常网络 | 连接保持可用 |
| KA-04 | 运行中断网 | 15 秒 | 3 | 物理或策略断网 | 约 45 秒进入失联处理 |
| KA-05 | 空闲时断网再恢复 | 15 秒 | 3 | 短暂断网 | 有界重连后恢复 |

内部结果：

<!-- 待填写。 -->

## 3. 长连接稳定性

- 同一 Connection 依次执行至少 100 条短命令，每条命令使用独立 Channel。
- 连接空闲后再次创建命令 Channel。
- 连续执行短命令、10 分钟长命令、SFTP，再执行短命令。
- 验证命令 Channel 关闭后底层 Connection 仍然可用。
- 验证任务结束后 Connection、Channel、SFTP 和后台任务全部关闭。
- 观察客户端进程句柄、线程、内存和 socket 是否持续增长。

内部结果：

<!-- 待填写。 -->

## 4. 断线和重连

- 空闲时断线：应自动进入 `SUSPECT/RECONNECTING`，成功后恢复 `READY`。
- 执行只读且允许重试的命令时断线：验证重连和显式重试。
- 执行有副作用命令时断线：不得自动重放，结果应为 `unknown`。
- A 连接断开时：B 会话与隧道必须失效；恢复 A 后重新创建 B 会话。
- 超过最大重连次数或总时长后：明确失败，不无限重试。
- 用户取消时：停止重连并进入 `CLOSED`。

建议验证退避序列：1、2、4、8 秒并带随机抖动；具体上限由内部测试决定。

内部结果：

<!-- 待填写。 -->

## 5. expect 与长命令

- 普通字符串、正则表达式和受信任判断函数均能匹配增量输出。
- stdout 与 stderr 同时大量输出时不会阻塞。
- `EXIT_REQUIRED`、`EXPECT_REQUIRED`、`EXIT_OR_EXPECT` 行为符合设计。
- expect 命中后关闭命令 Channel，不影响底层 Connection 创建后续 Channel。
- expect 命中但远端进程继续运行时，能正确记录 `remote_process_state`。
- 总超时与输出空闲超时分别生效。

内部结果：

<!-- 待填写。 -->

## 6. 系统重装与主机密钥轮换

验证 `RESET_FOR_REPROVISION`：

1. 初始连接记录目标环境旧主机密钥。
2. 明确进入重装步骤，只清理该环境在项目身份存储中的记录。
3. 保留其他环境及第一跳 A 的记录。
4. 系统重装后首次连接接受并记录新密钥。
5. 本次任务后续重连必须匹配新密钥。
6. 未再次授权轮换时模拟密钥再次变化，必须阻止连接。
7. 确认用户系统全局 known_hosts 未被修改。

内部结果：

<!-- 待填写。 -->

## 7. 二次登录与文件传输

- 通过 A 的隧道连接 B，并在 B 上获得结构化退出码、stdout 和 stderr。
- A 长连接断开后，B 会话能正确失效并重建。
- PC→A 上传成功后，在 B 上通过密码交互从 A 拉取文件。
- 密码不出现在命令行、日志、异常和运行快照中。
- 两段传输分别记录状态、进度和校验结果。
- A→B 失败时不把 PC→A 成功报告成整体成功。
- 验证中间文件的保留、覆盖和清理策略。

内部结果：

<!-- 待填写。 -->

## 8. 第一阶段验收结论

| 项目 | 结论 |
| --- | --- |
| AsyncSSH 是否适合作为默认后端 | 待验证 |
| keepalive interval / count max | 待验证 |
| 最大重连次数与总时长 | 待验证 |
| 任务级长连接是否稳定 | 待验证 |
| A→B 隧道是否兼容目标网络 | 待验证 |
| 交互式 A→B 文件传输是否可靠 | 待验证 |
| 主机密钥轮换策略是否可用 | 待验证 |

## 9. 行式交互Channel

- 运行一个文本提示式程序，验证同一Channel内多轮`wait_for()`只匹配本轮新增输出。
- 验证普通字符串、正则和失败Matcher，且失败Matcher优先阻止后续输入。
- 验证不分配PTY与显式分配PTY两种模式；不把curses/全屏TUI误判为已支持。
- 验证多个业务Step复用同一进程，上一步输入形成的状态可被下一步继续使用。
- 发送敏感输入后，确认Transcript、异常、`repr`和运行日志均不包含明文。
- 等待提示期间分别测试总超时、空闲超时、用户取消、远端进程提前退出和A链路断开。
- 父`ManagedSSHSession`关闭时，确认所有交互Channel和后台读取任务被回收。

内部结果：

<!-- 待填写。 -->

## 10. 内部执行记录模板

```text
测试批次：
日期：
执行人：
代码提交/版本：
Python 版本：
AsyncSSH 版本：
脱敏环境编号：
执行的测试编号：
通过项：
失败项：
失败现象与脱敏日志位置：
是否建议修改默认参数：
备注：
```
