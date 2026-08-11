# CLI 参考

主 CLI：

```bash
acp <command>
```

Package alias：

```bash
ascendc-pilot <command>
```

## 常用命令

| Command | 作用 |
| --- | --- |
| `acp doctor` | 检查环境与 generated runtime drift。 |
| `acp route <text>` | 把自然语言或 slash text 路由到 workflow。 |
| `acp start <workflow_id>` | 启动 workflow。 |
| `acp status` | 查看 active workflow state。 |
| `acp next` | 查看 next actions 与 obligations。 |
| `acp run-action <action_id>` | prepare 或 finalize action。 |
| `acp advance <phase>` | gate 通过后推进 phase。 |
| `acp rework --reason <code>` | 沿声明的 rework edge 恢复。 |
| `acp complete` | gate 全部通过后标记 workflow passed。 |
| `acp block <status>` | 标记 blocked、failed 或 human required。 |
| `acp inspect-failure` | 查看结构化 failure 信息。 |
| `acp authorize` | Host hook authorization check。 |
| `acp context --intent <intent>` | 构建 context pack。 |
| `acp uo-query` | 通过 Pilot wrapper 查询 UO KB graph。 |
| `acp uo <subcommand>` | UO explain / search / dump helpers。 |
| `acp debug <subcommand>` | Debug capture 与 export utilities。 |

## Engine CLIs

| Command | Package |
| --- | --- |
| `uo-init` | `engines/understand-operator` |
| `uo-dump` | `engines/understand-operator` |
| `tg-init` | `engines/testcase-generation` |
| `tg-plan` | `engines/testcase-generation` |
| `tg-solve` | `engines/testcase-generation` |
| `tg-closure` | `engines/testcase-generation` |
| `ce-impact` | `engines/code-engineering` |
