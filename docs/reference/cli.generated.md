# CLI Reference

本文件从 `pilot/ascendc_pilot/cli.py` 和 engine package metadata 生成，请不要手工编辑。

主 CLI：`acp <command>`；安装 package 后也可使用 `ascendc-pilot <command>`。

## Pilot 命令

| 命令 | 说明 |
| --- | --- |
| `acp abort` | 终止当前 run 并标记为失败 |
| `acp advance` | 仅在当前 phase gate 通过后推进状态 |
| `acp authorize` | 执行 host hook 的授权检查 |
| `acp block` | 标记为 blocked、failed 或 human_required |
| `acp complete` | 全部 gate 通过后标记 workflow 完成 |
| `acp context` | 构建 context pack |
| `acp debug` | 采集诊断信息并导出 session bundle |
| `acp doctor` | 执行环境预检 |
| `acp emit-confidence-report` | 从 KB 生成确定性的 confidence report 与 gate |
| `acp inspect` | 查询结构化 IR（candidates、tasks、YAML 计数） |
| `acp inspect-failure` | 查看结构化 failure 信息 |
| `acp next` | 查看可执行的下一动作与 obligations |
| `acp retry-after-environment-fix` | 环境修复后恢复失败动作的 rework 状态 |
| `acp rework` | 沿声明的 rework edge 恢复 |
| `acp ro-search` | 只读源码搜索，不执行 shell 重定向 |
| `acp route` | 将自然语言或 Slash 路由到 workflow |
| `acp run-action` | 准备或 finalize 一个 workflow action |
| `acp run-summary` | 汇总中断的 uo-init run，供人工询问使用 |
| `acp spec-hashes` | 输出四类 Spec Hash 摘要 |
| `acp start` | 从 entry state 启动 workflow |
| `acp status` | 查看 workflow 状态 |
| `acp uo` | 查询和解释 UO Host contract |
| `acp uo-query` | 通过 Pilot wrapper 查询 UO KB graph |
| `acp uo-scope` | 执行 UO 源码范围扫描与校验 |
| `acp validate` | 执行当前 workflow 的全部 gate |
| `acp validate-key-gates` | 执行关键硬 gate |

## Engine 命令

| 命令 | 软件包 |
| --- | --- |
| `uo-init`、`uo-dump` | `engines/understand-operator` |
| `tg-init`、`tg-plan`、`tg-solve`、`tg-closure` | `engines/testcase-generation` |
| `ce-impact` | `engines/code-engineering` |
