# 子代理派发合同（`/tg-init`）

## Task

父代理按 init 阶段派发**唯一**允许的子代理 / uo-query Task，完成有界绑定与终审。

## Allowed Agents / Skills

| 目标 | 何时 |
|---|---|
| Task Follow `uo-query` | 每个 `needs_binding_keys` / mid 符号语义 |
| `tg-csv-contract` | thin contract 后 inventory 内 LLM 补 gap（非语义主路径） |
| `tg-init-audit` | merge + verify 后、`--confirm` 前 |

**MUST NOT：** 向用户要求 `/tg-contract` 或 `/tg-domain-review`；写入 `$UO_ROOT/**`；
安装面不部署 `tg-domain-review` agent。

**允许：** Task Follow `uo-query` 修 **TG 绑定断边**（含 `unsolved` KEY→`VAR_CSV_*`），只写 `$OUT_ROOT`。  
合法 skip：`$PLUGIN_ROOT/skills/tg-init/references/legitimate-skips.md`。

## Identity / Resume

```text
<op_name>:tg-init:<phase>:<KEY_ID_or_audit>
```

同身份已 open → 续跑；无法续跑 → `SUBAGENT_RESUME_UNAVAILABLE`。

显式传入：`PLUGIN_ROOT` · `PROJECT_ROOT` · `OP_NAME` · `UO_ROOT`（只读）· `OUT_ROOT`。

## Authoritative Sources

- 定稿 KB + `uo_kb_query` 图（在 **uo-query Task 内**，只读）
- `realization/binding_inventory.yaml` / unresolved / host_parent_hints
- 测试脚本 / CSV schema（CSV↔HOST 映射权威在 TG）

**Non-authoritative：** 记忆、命名直觉、父代理裸 Grep、未 merge 的猜测 expr。

## Writable Surfaces

| Writer | 可写（均在 `$OUT_ROOT`） |
|---|---|
| uo-query Task | `realization/uo_query_resolve/<KEY_ID>.yaml` |
| tg-csv-contract | lexicon/domain/unresolved/agent_report（见 agent 合同） |
| tg-init-audit | **仅** `init/audit_report.yaml` |
| 父代理 CLI | `--merge-uo-resolve` / `--verify-csv-closure` / `--confirm` 产物 |

**MUST NOT** 改：`$UO_ROOT/**`、`plan/**`、算子源码、测试脚本、伪造 audit pass。

## Parallelism

- 并行 Task cap = **8**
- 父代理 MUST NOT 循环 `uo_kb_query` 当主路径

## Hard Constraints

- resolved → `confidence: high` only；叶子 ⊆ `VAR_CSV_*`
- 禁伪 not_csv；合法 skip 白名单见 `$PLUGIN_ROOT/skills/tg-init/references/legitimate-skips.md`
- audit/verify fail → 自动下一轮，禁止问用户「是否继续」
- `tg-csv-contract` 的 AskQuestion 仅域锁定，不得插入绑定 WHILE

## Acceptance

- `--verify-csv-closure` pass + `audit_report.status=pass` → 才允许 `--confirm`
- 否则保留 unresolved + reason_code，禁止猜满
