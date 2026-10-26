# 网络串口 Connector 内部验证清单

状态：待内部执行
最近更新：2026-10-24

## 1. 准备条件

- 一个明确允许测试的串口服务器端点，使用脱敏编号记录。
- IP、Port及对应物理环境信息，不要写入本文档或Git。
- 确认测试时不会影响他人任务。
- 准备一条无副作用的探测流程：通常为发送回车并等待已知提示符。
- 准备至少一条立即响应命令和一条延迟响应命令，并为每条命令提供脱敏expect。
- 如需断线测试，安排允许断开网络或重启串口服务器的测试窗口。

### 1.1 第一版内网 live 测试

第一版提供 `tests/test_serial_connector_live.py`。未设置端点环境变量时全部测试会安全跳过，不会尝试连接任何设备。请只使用明确授权且当前无人占用的串口端点。

```powershell
$env:PYTHONPATH = "$PWD\src"
$env:EBON_SERIAL_HOST = "串口服务器IP"
$env:EBON_SERIAL_PORT = "端口"

# CONTROL 建连探测；字符串不得包含秘密或不可脱敏的设备信息
$env:EBON_SERIAL_PROBE_EXPECT = "已知提示符"
$env:EBON_SERIAL_PROBE_TIMEOUT = "10"

# 可选：无副作用命令测试
$env:EBON_SERIAL_SAFE_COMMAND = "无副作用命令"
$env:EBON_SERIAL_SAFE_EXPECT = "命令预期输出"
$env:EBON_SERIAL_COMMAND_TIMEOUT = "30"
# $env:EBON_SERIAL_IDLE_TIMEOUT = "10"

python -m unittest tests.test_serial_connector_live -v
```

行尾默认是 `\r`，可用 `EBON_SERIAL_LINE_ENDING` 设置为 `\n` 或 `\r\n`。PowerShell中推荐使用字面字符串 `"\n"`/`"\r\n"`，测试代码会将反斜杠转义转换为真实控制字符。

OBSERVE_ONLY 测试不会写入任何字节，但必须等待串口自身产生可识别的日志：

```powershell
$env:EBON_SERIAL_OBSERVE_EXPECT = "启动日志中的安全标志"
$env:EBON_SERIAL_OBSERVE_TIMEOUT = "60"
python -m unittest tests.test_serial_connector_live.InternalObserveOnlyTests -v
```

执行后清除可能暴露内部信息的变量：

```powershell
Remove-Item Env:EBON_SERIAL_HOST -ErrorAction SilentlyContinue
Remove-Item Env:EBON_SERIAL_PORT -ErrorAction SilentlyContinue
Remove-Item Env:EBON_SERIAL_SAFE_COMMAND -ErrorAction SilentlyContinue
Remove-Item Env:EBON_SERIAL_SAFE_EXPECT -ErrorAction SilentlyContinue
```

自动 live 测试只覆盖建连探测、一个安全命令以及只读观察。断网、重连、长时间空闲、IAC识别、多个客户端竞争等仍需按下文章节人工执行并记录；不得为了跑自动测试而对生产设备执行破坏性命令。

## 2. Raw TCP与Telnet协议识别

目标：判断RawTcpTransport能否正确使用现有串口服务器。

验证内容：

- Raw TCP建立连接后收到的初始原始字节。
- 是否出现`0xFF`开头的Telnet IAC协商序列。
- Raw TCP发送回车后，输出是否与Xshell Telnet模式一致。
- 是否存在重复字符、缺少字符、IAC字节进入业务日志或服务端等待协商等现象。

结论：

```text
端点类型：Raw TCP可用 / 需要Telnet协商 / 待确认
是否需要telnetlib3：
脱敏证据位置：
```

## 3. 行尾验证

分别测试：

| 编号 | 发送内容 | 预期 |
| --- | --- | --- |
| LE-01 | `\r` | 出现目标提示符或执行命令 |
| LE-02 | `\n` | 记录设备行为 |
| LE-03 | `\r\n` | 记录是否产生一次或两次提交 |

确认默认行尾，并判断是否需要按端点配置。

内部结果：

<!-- 待填写。 -->

## 4. 建连探测与重连

- CONTROL模式建连后发送一次回车，指定expect命中才判定串口可操作。
- expect未命中时区分连接超时、输出空闲和错误输出。
- 物理断网或服务端断开后，Reader应检测EOF/异常。
- 有界重连后重新发送回车并等待expect。
- 断线时正在执行的命令不得自动重放。
- OBSERVE_ONLY模式建连和重连后不得发送任何字节。

内部结果：

<!-- 待填写。 -->

## 5. expect与输出缓冲

- 立即响应命令匹配成功expect。
- 延迟响应命令在预期时间内匹配成功expect。
- 失败expect优先结束等待并返回失败。
- 旧缓冲区中已有相同字符串时，新命令不得误命中。
- 命令回显与结果混合时仍能正确匹配。
- 持续大量启动日志不会阻塞Reader。
- 总超时和输出空闲超时分别生效。

内部结果：

<!-- 待填写。 -->

## 6. 只读日志观察

- OBSERVE_ONLY连接不发送回车或命令。
- 能持续保存原始日志并匹配指定启动字符串。
- 多个进程内观察器订阅同一Reader时均能收到数据，不相互消费。
- 验证串口服务器是否允许CONTROL和独立OBSERVE_ONLY两个TCP客户端同时连接。
- 如果只允许单连接，确认观察器可挂接到已有CONTROL Session。

内部结果：

<!-- 待填写。 -->

## 7. TCP keepalive

测试空闲30分钟、2小时以及空闲时断网。记录操作系统TCP keepalive参数、实际发现断线时间和是否存在误断。

不得使用周期性回车替代TCP keepalive。显式`probe()`应只在没有命令执行时调用。

内部结果：

<!-- 待填写。 -->

## 8. 执行记录模板

```text
测试批次：
日期：
执行人：
代码提交/版本：
脱敏端点编号：
串口服务器型号/类型（可脱敏）：
执行测试编号：
Raw TCP是否可用：
默认行尾：
连接探测expect：
通过项：
失败项：
脱敏日志位置：
建议修改：
```
