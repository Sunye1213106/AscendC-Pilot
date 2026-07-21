---
name: uo-query
description: >-
  Query AscendC operator KB (.understand-operator). Use for /uo-query, KB Q&A,
  entrypoint/tiling/ir/coverage lookup. Prefer uo_kb_query.py graph patterns
  over Grep. Do not invent SCRIPT_DIR under skills/*/scripts for the real CLI
  (that path only has a forwarder).
---

# /uo-query

Read-only KB Q&A for AscendC operators. **Invocation = agent follows this skill**
(often inside a **Task/subagent**). The PowerShell blocks below are **tools the
skill uses**, not “skip the skill and only run CLI in the parent terminal.”

## How to call (preferred)

```text
Parent (tg-init / tg-solve / uo-init escalate)
  → Task/subagent  (one KEY, or a small batch of related keys)
       → Read & follow this SKILL.md (+ source-lookup-gate.md)
            → Shell: uo_kb_query.py   ← KB graph lookup (you will see a terminal)
            → MCP: codebase-memory     ← source proof to high confidence
            → Write: key_shape_resolve / TG realization/uo_query_resolve/<KEY>.yaml
```

### TG batch note

When called from TestAgent (`tg-init` / `tg-solve`):

- For **every** `needs_binding_keys` KEY (not optional): Follow this skill in a Task.
- Parent may pack **related keys** (same shape family / same Host entry) into one Task; still Follow this skill.
- Parallel Task cap ~8. **Parent must not** loop `uo_kb_query` as the main path.
- Prefer YAML + MCP conclusions; CLI runs **inside** the skill-following subagent.
- **TG 交付契约**（写入 `realization/uo_query_resolve/<KEY_ID>.yaml`）必须含：
  - `key_id`, `status: resolved|unresolved`, **`confidence: high` only**（禁止 `medium`/`low` 标 resolved）
  - `shape_expr`（可读；禁止留下未展开的 `Get*` / Host API 函数叶）
  - **`key_derivation.expr`**：机器可读 LogicExpr（仅 `if_then_else` / `eq` / `ne` / `lt` / `and` / `or` / …）；**禁止 `op: call` 与未展开函数**
  - **`shape_determined`**：本 KEY 直接依赖的 CSV/shape 根（如 `VAR_CSV_B`）
  - **`derivation_chain`**：`[{id, deps, via}]`，套娃展开中间量；**叶子 deps 必须 ⊆ `VAR_CSV_*` 或 compile-time lit**
  - 字面量必须落在目标 CSV 变量有效域内（禁止 `eq(VAR_CSV_keep_prob, 0)` 当域是 `{1.0,0.9,0.8}`）
  - 禁止 `then`/`else` 为 `deter_branch` 等占位字符串；禁止 `then==else` 恒 KEY
  - 达不到 high → 继续 MCP codebase-memory + 读 Host；仍不行则 `status: unresolved` **并写明原因**（不得 medium resolved）
  - empty 族（如 `KEY_ISEMPTYTENSOR`）可暂 `unresolved` + `skip_reason: empty_tensor`
- Parent **不**直接改 lexicon / `shape_determined`；只跑 `tg-init --merge-uo-resolve`（自动建派生图闭包）。
- 依赖什么就解什么：停在 `deterSparseType`/`bnSparseLimit` 等中间量 → 继续 chain / 再开 Task，直到 CSV/shape。

| Layer | What it is |
|---|---|
| **Skill `/uo-query`** | Procedure the *agent* must follow (taxonomy, gates, answer contract) |
| **Subagent** | Isolated worker parent launches (parallel / batched); prompt: `Follow skills/uo-query/SKILL.md` |
| **`uo_kb_query.py`** | Deterministic graph CLI — *data fetch inside the skill*, like Read/Grep |

Seeing terminal output is normal: the subagent is executing the skill’s query gate.
Wrong pattern: parent alone dumps `python uo_kb_query.py` for every KEY and never
opens a skill-following subagent / never does MCP→high reasoning.

## Variables (resolve once, never invent)

| Name | Canonical value |
|------|-----------------|
| `PLUGIN_ROOT` | `~/.config/opencode/understand-operator-plugin` (junction to plugin repo) |
| `SCRIPT_DIR` | `$PLUGIN_ROOT/uo/scripts` |
| `QUERY_CLI` | `$SCRIPT_DIR/uo_kb_query.py` |
| `PROJECT_ROOT` | operator package directory (contains `.understand-operator/`) |
| `OP_NAME` | operator name (e.g. `flash_attention_score_grad`) |
| `UO_ROOT` | `$PROJECT_ROOT/.understand-operator/$OP_NAME` |

PowerShell (copy exactly):

```powershell
$PLUGIN_ROOT = Join-Path $env:USERPROFILE ".config\opencode\understand-operator-plugin"
$SCRIPT_DIR  = Join-Path $PLUGIN_ROOT "uo\scripts"
$QUERY_CLI   = Join-Path $SCRIPT_DIR "uo_kb_query.py"
# sanity: Test-Path $QUERY_CLI must be True before any query
```

**Forbidden as primary SCRIPT_DIR**

- `skills/uo-query/scripts/` (may contain a forwarder only; still prefer `$PLUGIN_ROOT/uo/scripts`)
- Searching `C:\` or the whole disk for `uo_kb_query.py`
- Inventing `--entity` or `--uo-root` (CLI uses positional `repo` + `--op-name` + `--target`)

If `Test-Path $QUERY_CLI` is False → STOP and report path error. Do **not** fall back to Grep/key_cards and claim the script is missing.

## Hard gate (must pass before any Grep/Read of key_cards)

1. Run status:

```powershell
python -X utf8 "$QUERY_CLI" "$PROJECT_ROOT" --op-name "$OP_NAME" --status-only
```

2. If `freshness=fresh` and `sqlite_ready=true`: run **at least one** graph pattern
   before any Grep/Read of `key_cards/` or `views/`:

```powershell
# patterns: entity_of | neighbors_of | constraints_for | branches_for_key |
#           entities_in_files | affected_shapes
python -X utf8 "$QUERY_CLI" "$PROJECT_ROOT" --op-name "$OP_NAME" --pattern neighbors_of --target "ENTRY::host_tiling"
python -X utf8 "$QUERY_CLI" "$PROJECT_ROOT" --op-name "$OP_NAME" --pattern entity_of --target "TND_BASIC_SWIZZLE"
python -X utf8 "$QUERY_CLI" "$PROJECT_ROOT" --op-name "$OP_NAME" --pattern neighbors_of --target "SYM::GetDeterministicMode"
```

3. Final answer **must** include:

```text
query_backend: kb_graph   # or yaml_fallback / source_lookup with reason
```

If step 2 was skipped → answer is invalid even if Grep found text.

`freshness=stale` → tell user to run `/uo-update`. Do not Grep around it.
`sqlite_ready=false` → yaml/views fallback is allowed; still say so in `query_backend`.

## Taxonomy

Read `references/question-taxonomy.md`. Map the question first.
Primary for `entrypoint` / `tiling_key_hit` / `symbol_hit` = **graph CLI**, then
`detail_ref` / key card only to expand text.

## Complex unresolved / per-KEY shape expr

When residual resolve or TestAgent bind leaves **complex** KEY/shape gaps:

1. Read `references/complex-unresolved-escalation.md`.
2. Parent launches **one subagent per KEY** (parallel, cap 8) — each runs this
   skill’s gate + `branches_for_key` / `affected_shapes` / `neighbors_of`.
3. Output `shape_expr` + evidence to `ir/key_shape_resolve/<KEY_ID>.yaml`.
4. **Forbidden:** return bare unsolved / empty bind without `uo-query` + MCP.

This mode is for escalated KEY resolve, not for replacing `/uo-init` residual
sample of simple false positives.

## Answer contract

- Prefer IDs/paths/line ranges from CLI JSON (`entity_id`, `file`, `start_line`).
- Do not invent symbols or line numbers.
- Source open only via `source-lookup-gate.md` after graph miss or explicit source need.
- Keep answers short; include `query_backend`.

## Failure

If CLI fails with FileNotFound on a wrong path, retry once with `$PLUGIN_ROOT/uo/scripts/uo_kb_query.py`.
If still failing, report the absolute path tried — do not silently switch to Grep-only.
