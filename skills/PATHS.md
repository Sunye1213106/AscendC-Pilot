# AscendC Agent — 统一路径与入口

Harness 是唯一控制面。本地产物根：

```text
$PROJECT_ROOT/.ascendc-agent/
  uo/       # UO KB（原 .understand-operator/<op>/）
  tg/       # TG 产物（原 .testcase-generator/<op>/）
  memory/   # 本地算子记忆
  runs/     # 工作流 run / subagent 收据
  context/  # Context Pack
  state/    # workflow.yaml / resume.yaml
```

## 用户命令

| Skill | 引擎 |
|---|---|
| `/uo-init` `/uo-update` `/uo-query` `/uo-code-review` | UO |
| `/tg-init` `/tg-plan` `/tg-solve` | TG |

状态迁移与完成条件由 **`harness` 脚本门禁**决定，Skill/Agent 不得自行宣布完成。

## 变量

| 变量 | 含义 |
|---|---|
| `PROJECT_ROOT` | 算子仓 |
| `AGENT_ROOT` | `$PROJECT_ROOT/.ascendc-agent` |
| `UO_ROOT` | `$AGENT_ROOT/uo` |
| `TG_ROOT` | `$AGENT_ROOT/tg`（亦称 OUT_ROOT） |
| `PLUGIN_ROOT` | 装机后的统一 plugin 根 |

## PLUGIN_ROOT（装机后）

| 平台 | `PLUGIN_ROOT` |
|------|----------------|
| OpenCode | `$HOME/.config/opencode/ascendc-agent-plugin` |
| Cursor | `$HOME/.cursor/ascendc-agent-plugin` |
| Codex | `$HOME/.agents/ascendc-agent-plugin` |

## 硬隔离

- TG **只读** `$UO_ROOT`；**只写** `$TG_ROOT`
- 缺库 / integrity fail / KEY 门禁 fail → 先 `/uo-init` 或 `/uo-update`
- Legacy：`harness migrate-legacy <仓> --op-name <op>`

## KEY 门禁（脚本权威）

```powershell
harness validate-key-gates <算子仓>
harness advance <next_phase> --project <算子仓>
harness complete --project <算子仓>   # 唯一合法 pass
```

`escalate_keys` / gaps open → 必须 `ir/key_triage.yaml` + `uo-key-resolve`；非 high 须原因 + `uo-confidence-review`；禁止 empty-only 假闭合；禁止同文 bit-pack `reported` 空过。
