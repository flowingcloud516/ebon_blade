# Common Host EnvModel 设计

状态：第一版设计已确认，可以进入实现
最近更新：2026-10-26

## 1. 第一期范围

`CommonHostModel`作为第一套参考Environment Model，只完成最小且明确的主机初始化：

```text
Step 1：强制下电
Step 2：上电
最终就绪检查：SSH成功建立连接
```

严格保持两个初始化Step。SSH检查由`EnvironmentModel.verify_ready()`完成，是框架统一的最终就绪判定，不作为第三个初始化Step。

第一期不包含正常下电、重启、Power Cycle、BIOS修改、软件部署或SSH命令执行。BIOS只读快照属于后续日志/配置采集能力，不阻塞最小参考Model落地。

## 2. 本次运行YAML示例

```yaml
schema_version: 1

environment:
  id: server-001
  type: common_host
  name: 通用服务器01
  description: 最小上下电参考环境
  tags: [server]

connections:
  management_bmc:
    type: bmc
    role: power_control
    enabled: true
    host: 192.0.2.30
    protocol_preference: [redfish, ssh]
    system_id: System.Embedded.1
    username: admin
    credential_ref: cred/server-001/bmc

  host_ssh:
    type: ssh
    role: host_control
    enabled: true
    host: 192.0.2.10
    port: 22
    username: tester
    credential_ref: cred/server-001/ssh
    host_key_policy: environment_pinned

initialization:
  force_off_timeout_seconds: 120
  power_off_hold_seconds: 10
  power_on_timeout_seconds: 180
  ssh_ready_timeout_seconds: 600
  ssh_probe_interval_seconds: 10

logging:
  collectors: []

dependencies: []
```

密码和Token只通过`credential_ref`在运行时解析，不进入本次配置快照。`management_bmc`和`host_ssh`是稳定connection_id；Model按ID或Definition约束后的role解析连接，不根据列表位置取连接。

## 3. EnvironmentDefinition

```text
type_id: common_host
display_name: 通用主机

connection_requirements:
├── power_control: type=bmc, min=1, max=1
└── host_control:  type=ssh, min=1, max=1

capabilities:
├── initialize
├── force_off
├── power_on
└── verify_ssh_ready
```

第一版要求电源和SSH连接各一个。未来若需要跳板SSH、多个管理平面或多个主机节点，再通过connection_id和role扩展，不改变公共框架接口。

## 4. CommonHostModel接口实现

| EnvironmentModel函数 | CommonHostModel第一版行为 |
| --- | --- |
| `definition()` | 返回`common_host`的Schema、两类连接约束和能力声明 |
| `validate_config(config)` | 校验唯一BMC、唯一主机SSH、credential_ref、端口和所有超时参数 |
| `dependencies(config)` | 返回YAML显式声明的依赖；普通单主机通常为空 |
| `create_log_collectors(context)` | 第一版返回空元组；不启用持续设备日志。以后按配置创建独立日志Collector，不复用控制连接 |
| `build_initialize_plan(context)` | 返回一个`power` Phase，内部严格包含`force_off`、`power_on`两个OperationStep |
| `verify_ready(context)` | 在总期限内尝试SSH建连；第一次成功即Ready，并立即关闭验证连接 |
| `collect_failure_context(...)` | 尽力执行只读`get_power_state()`；失败不能覆盖原始错误 |

`build_initialize_plan()`和`verify_ready()`从`context.config.raw["initialization"]`读取本次超时与探测间隔，不把配置缓存到`CommonHostModel`成员中。连接对象统一通过`context.resolve_connection(...)`取得。

## 5. 初始化Plan

```text
Plan: common_host.initialize.v1
└── Phase: power（电源初始化）
    ├── OperationStep: power.force_off
    └── OperationStep: power.power_on

Plan完成后
└── verify_ready(): SSH connect
```

概念代码：

```python
def build_initialize_plan(self, context: ControlContext) -> Plan:
    settings = CommonHostSettings.from_config(context.config)
    return Plan(
        plan_id="common_host.initialize.v1",
        version="1",
        timeout=(
            settings.force_off_timeout_seconds
            + settings.power_off_hold_seconds
            + settings.power_on_timeout_seconds
            + 10
        ),
        phases=(
            Phase(
                phase_id="power",
                title="电源初始化",
                steps=(
                    ForceOffStep(
                        connection_id="management_bmc",
                        operation_timeout=settings.force_off_timeout_seconds,
                        hold_seconds=settings.power_off_hold_seconds,
                        timeout=(
                            settings.force_off_timeout_seconds
                            + settings.power_off_hold_seconds
                        ),
                    ),
                    PowerOnStep(
                        connection_id="management_bmc",
                        timeout=settings.power_on_timeout_seconds,
                    ),
                ),
            ),
        ),
    )
```

Plan总超时只覆盖两个电源步骤；SSH就绪检查使用独立的`ssh_ready_timeout_seconds`。`power_off_hold_seconds`属于强制下电Step的一部分；额外10秒只给步骤切换和本地框架开销，不改变任何BMC动作超时。

### 5.1 `power.force_off`

- 类型：`OperationStep`。
- 调用`management_bmc.force_off()`。
- BMC Connector内部可以在已经为Off时幂等返回`changed=False`，但Step仍记录本轮明确调用过强制下电语义。
- 只有BMC确认最终PowerState为Off，Step才成功。
- 确认Off后继续保持断电`power_off_hold_seconds`；第一版默认10秒。等待结束后Step才成功，因此仍然只有两个初始化Step。
- 请求是否已接受无法确认时，结果必须是`unknown`，禁止继续执行`power_on`。
- 不自动切换成正常下电或其他动作。

### 5.2 `power.power_on`

- 类型：`OperationStep`。
- 仅当前一步成功后执行。
- 调用`management_bmc.power_on()`。
- 只有BMC确认最终PowerState为On，Step才成功。
- 请求状态未知时不得自动重放。
- 本Step成功只表示电源状态为On，不表示操作系统或环境已经Ready。

## 6. SSH最终就绪检查

`verify_ready()`通过`context.resolve_connection("host_ssh", connector_type="ssh")`取得由框架创建的任务级`ManagedSSHSession`：

```text
开始ssh_ready_timeout总期限
→ 尝试建立SSH连接
→ 成功：返回ready=True，并关闭SSH验证连接
→ 网络未就绪：等待probe_interval后重试
→ 认证失败/主机身份不匹配：立即失败
→ 总期限耗尽：返回ready=False
→ 收到取消：返回cancelled
```

第一期“SSH成功连接”就是最终Ready依据，不额外执行远端命令。主机密钥验证仍必须遵守SSH Connector策略，不能为了就绪检查自动接受未知密钥。

SSH验证连接只属于本次ControlContext。`verify_ready()`不把它转交给LogSession；无论验证成功、失败还是取消，框架都会在初始化结束时关闭整个ControlContext。未来日志Collector如果需要SSH，应建立自己的独立连接。

## 7. 窄Connector协议

BMC真实实现等待内网文档，但CommonHostModel不应依赖Redfish或厂商命令细节。Step只依赖上下文提供的最小能力：

```python
class PowerControl(Protocol):
    async def get_power_state(self) -> PowerState: ...
    async def force_off(self, *, timeout: float) -> PowerOperationResult: ...
    async def power_on(self, *, timeout: float) -> PowerOperationResult: ...

class SSHReadinessProbe(Protocol):
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
```

UT使用Fake PowerControl和Fake SSHReadinessProbe。以后BmcConnector与ManagedSSHSession适配到上述能力，不需要修改CommonHostModel的Plan。

## 8. 结果与失败传播

| 场景 | `force_off` | `power_on` | SSH验证 | 最终结果 |
| --- | --- | --- | --- | --- |
| 全部成功 | succeeded | succeeded | ready | `ready=True` |
| 已经Off | succeeded, changed=False | succeeded | ready | `ready=True` |
| 强制下电失败 | failed | blocked | 不执行 | `ready=False, action_state=completed` |
| 强制下电状态未知 | unknown | blocked | 不执行 | `ready=False, action_state=unknown` |
| 上电失败 | succeeded | failed | 不执行 | `ready=False` |
| 上电成功但SSH超时 | succeeded | succeeded | timeout | `ready=False, action_state=completed` |
| SSH认证/身份错误 | succeeded | succeeded | failed-fast | `ready=False, action_state=completed` |
| 用户在步骤开始前取消 | 按取消时点落定 | 后续blocked | 不执行或cancelled | `ready=False, status=cancelled` |
| 修改设备的步骤执行中被取消 | unknown | 后续blocked | 不执行 | `ready=False, status=unknown, action_state=unknown` |

`action_state=completed`只表示电源动作已经有确定结果，不等于环境Ready。

## 9. 关键UT

第一版至少覆盖：

1. Definition要求且只允许一个`power_control`和一个`host_control`。
2. Plan只有两个Step，ID和顺序固定。
3. `force_off`成功后才执行`power_on`。
4. `force_off`失败或unknown时不执行`power_on`。
5. `power_on`完成后才进入`verify_ready()`。
6. SSH第一次失败、后续成功时最终Ready。
7. SSH超时、认证失败和主机密钥不匹配分别返回正确结果。
8. SSH验证连接无论成功、失败或取消都被关闭。
9. 初始化ControlContext关闭后不存在遗留控制连接。
10. Fake BMC动作不会因框架重试而重复执行。

真实BMC和SSH验证继续分别使用Connector目录下的`INTERNAL_VALIDATION.md`。

## 10. 已确认策略

已确认：

1. `ssh_ready_timeout_seconds`第一版默认600秒，探测间隔10秒。
2. SSH认证失败和主机密钥不匹配立即失败，不继续等待总超时。
3. 强制下电确认Off后保持断电10秒，再执行上电。该等待包含在`power.force_off`中，不增加第三个Step。
4. 第一版`create_log_collectors()`返回空元组，不启用持续设备日志。框架仍创建LogSession和环境日志目录；Plan/Step执行结果继续正常记录。后续增加串口、BMC事件或SSH轮询Collector时，不改变两个电源Step和SSH Ready语义。
