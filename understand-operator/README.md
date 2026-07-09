# Understand Operator

`understand-operator` builds and maintains an evidence-backed knowledge base for AscendC operators. It uses `codebase-memory-mcp` (CBM) as the code-intelligence backend. The host coding agent does semantic analysis through staged prompts and four user-facing commands.

The plugin does not implement its own AST parser, call graph, reference graph, or symbol graph.

## Commands (only these)

| Command | Alias intent | What happens |
|---|---|---|
| `/uo-init` | end-to-end KB build | In a target AscendC repo, run the full pipeline into `.understand-operator/<op_name>/` |
| `/uo-query` | KB Q&A | Answer from KB first; use CBM only when source proof is needed |
| `/uo-update` | incremental KB update | Detect code changes vs last KB state and patch impacted artifacts |
| `/uo-diff` | reserved diff API | Read-only change summary; **kept as-is, not redesigned** |

Other former single-entry `/understand-operator` usage is retired; that skill only routes to the four commands above.

## Underlying rule (all commands)

**Source lookups are CBM-first.** If CBM fails (empty/error), fall back to reading source (whole file allowed as last resort). Never open source before attempting CBM. See `prompts/00_cbm_first_rule.md`.

KB artifact reads under `.understand-operator/` are always allowed and preferred for `/uo-query`.

## What It Builds

```text
<repo>/.understand-operator/<op_name>/
  route.md
  route.json
  quality_gate.yaml
  cbm/
  summary/
  tiling/
  flows/
  kernel/
  evidence/
  testing_hints/
```

Designed for later accuracy/performance test design. It does **not** generate real tests.

## Workflow (`/uo-init`)

```text
Preflight full/incremental + ignore rules
  -> CBM index
  -> Macro Scope Human Review (user approval)
  -> Macro Boundary Agent          # no Phase 1.5 stop
  -> Parallel: uo-host-extraction + uo-flow-extraction
  -> Kernel Path Task Builder
  -> Kernel Dispatch Human Review  # must show full tiling/family info
  -> Parallel Kernel Path Agents (approved tasks only)
  -> Kernel Alignment Builder
  -> Evidence Consistency Agent
  -> Operator KB / Route Builder
  -> Quality Gate
```

Human gates: **0.5** (scope) and **3.5** (kernel dispatch with full family/tiling brief). Phase 1.5 is retired.

`/uo-update` reuses the same phases but only re-runs areas listed in `summary/update_plan.yaml`.

## Quick Start - Cursor

1. Open Cursor Settings > Plugins > Add local plugin.
2. Select this repository root (the folder that contains `understand-operator-plugin`).
3. Optional: install skills + subagents:

```powershell
./install.ps1 cursor
```

This links:

- `~/.cursor/skills/uo-init`
- `~/.cursor/skills/uo-query`
- `~/.cursor/skills/uo-update`
- `~/.cursor/skills/uo-diff`
- shared scripts skill `~/.cursor/skills/understand-operator`
- subagents `~/.cursor/agents/uo-*.md`

4. In **Agent mode**:

```text
/uo-init D:\path\to\ascendc-repo --op-name FlashAttentionScore --full
/uo-query D:\path\to\ascendc-repo --op-name FlashAttentionScore 这个算子的必选输入有哪些？
/uo-update D:\path\to\ascendc-repo --op-name FlashAttentionScore
/uo-diff D:\path\to\ascendc-repo --op-name FlashAttentionScore
```

Analysis subagents appear only at two parallel points:

- `uo-host-extraction` + `uo-flow-extraction`
- `uo-kernel-path` × N (approved tasks)

## Manual Scripts

```powershell
# Phase 0 prepare (also used by /uo-init)
uo-prepare D:\path\to\repo --op-name MyOp --full

# Incremental change plan (also used by /uo-update)
uo-update D:\path\to\repo --op-name MyOp

# On-demand CBM
uo-cbm D:\path\to\repo search_graph --op-name MyOp --name-pattern ".*MyOpTiling.*" --label Function

# Quality gate
uo-quality D:\path\to\repo --op-name MyOp
```

## CBM

- Phase 0 / update index steps → `cbm/index_meta.json`, `cbm/cbm_query_log.md`
- Runtime queries → stdout + `cbm/query_journal.jsonl`
- Update delta → `cbm/change_set.yaml`, `summary/update_plan.yaml`

Resolve binary via `UNDERSTAND_OPERATOR_CBM_BIN`, `[scanner].cbm_binary`, `thirdparty/codebase-memory-mcp.exe`, or `PATH`.

## Core Artifacts

See previous docs for tiling/kernel schemas. Start reading at `route.md`, then `summary/operator_io.yaml`.
