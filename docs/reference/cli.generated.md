# CLI Reference

本文件从 `pilot/ascendc_pilot/cli.py` 和 engine package metadata 生成，请不要手工编辑。

本页是命令清单，不是协议。OpenCode 上如何调用 `pilot_run` / 插件 `pilot_cli`、为什么不要 `--help`，见 [ACP 工具使用](../getting-started/acp-tools.md)。

主 CLI：`acp <command>`；安装 package 后也可使用 `ascendc-pilot <command>`。

## Pilot 命令

| 命令 | 说明 |
| --- | --- |
| `acp abort` | 终止当前 run 并标记为失败 |
| `acp advance` | 仅在当前 phase gate 通过后推进状态 |
| `acp answer` | 把 Host 问答结果记为已签名的 HumanDecisionReceipt |
| `acp authorize` | 执行 host hook 的授权检查 |
| `acp block` | 标记为 blocked、failed 或 human_required |
| `acp complete` | 全部 gate 通过后标记 workflow 完成 |
| `acp debug` | 采集诊断信息并导出 session bundle |
| `acp dispatch-result` | Host Session Driver：消费 dispatch ticket、finalize 并继续驱动 |
| `acp doctor` | 执行环境预检 |
| `acp host-context` | 解析 arch 作用域的 Host 适配器上下文 |
| `acp inspect` | 查询结构化 IR / 证据窗口（tasks、YAML 计数、evidence-window） |
| `acp inspect-failure` | 查看结构化 failure 信息 |
| `acp interpret-user-turn` | 把用户本轮回复映射到待确认选项，或因打断而取消该确认 |
| `acp next` | 查看可执行的下一动作与 obligations |
| `acp pin-facts` | 从 clone_receipt promote 为 change_contract；无 PR 候选时才允许本地 implementation_coverage |
| `acp retry-after-environment-fix` | 环境修复后恢复失败动作的 rework 状态 |
| `acp rework` | 沿声明的 rework edge 恢复 |
| `acp ro-search` | 只读源码搜索，不执行 shell 重定向 |
| `acp route` | 将自然语言或 Slash 路由到 workflow |
| `acp run-action` | 准备或 finalize 一个 workflow action |
| `acp run-summary` | 汇总中断的 uo-init run，供人工询问使用 |
| `acp scan-architectures` | 快速扫描算子 op_host/op_kernel 布局与 arch* 实现选项；无 arch* 时产物槽 default |
| `acp serve-authorize` | 长驻 authorize 守护进程（stdio JSON-lines） |
| `acp spec-hashes` | 输出四类 Spec Hash 摘要 |
| `acp start` | 从 entry state 启动 workflow |
| `acp status` | 查看 workflow 状态 |
| `acp uo` | 查询和解释 UO Host contract |
| `acp uo-query` | 通过 Pilot wrapper 查询 UO KB graph |
| `acp uo-scope` | 执行 UO 源码范围扫描与校验 |
| `acp validate` | 执行当前 workflow 的全部 gate |

## Engine 命令

| 命令 | 软件包 |
| --- | --- |
| `uo-init`、`uo-dump` | `engines/understand-operator` |
| `tg-closure` | `engines/testcase-generation` |

