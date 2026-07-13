# Understand Operator

`understand-operator` builds and maintains an evidence-backed knowledge base for AscendC operators. It uses `codebase-memory-mcp` (CBM) as the code-intelligence backend. The host coding agent does semantic analysis through staged prompts and four user-facing commands.

**Default UI language is Chinese (zh-CN):** TodoWrite titles, progress blocks, review summaries, and `/uo-query` answers to the user must be Chinese. See `prompts/00_language.md`.

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

Choose tools by question type. Repository structure, file boundaries, path
membership, generated/test/sample classification, and raw text occurrence
locations use deterministic filesystem/Glob/`rg` first. Symbol resolution, call
relations, registration semantics, IO semantics, Host/Kernel correspondence, and
source behavior validation remain CBM MCP-first via `codebase-memory-mcp`
(`search_graph` / `search_code` / `get_code_snippet` / `trace_path`).

Do **not** use `cbm_query.py` / `uo-cbm` for interactive agent lookups. If CBM
fails for semantic source work, fall back to targeted `rg` and line-scoped
source reads; whole-file reads are the last resort. See
`prompts/00_cbm_first_rule.md` and `docs/cbm-mcp-setup.md`.

KB artifact reads under `.understand-operator/` are always allowed and preferred for `/uo-query`.

## What It Builds

```text
<repo>/.understand-operator/<op_name>/
  index.yaml              # machine routing entry (read first)
  route.md                # human map
  operator.yaml           # boundary / IO / ontology / analysis_plan
  quality.yaml
  human/review.md
  tiling/                 # canonical tiling (9 files + archive/): variables/key_space/constraints/families/data_model/coverage_model/route/index/evidence_index
  flow/                   # compute_graph / dataflow / golden_model / numerical_model
  kernel/                 # paths / pipeline / resources
  test/                   # contract only (no real tests)
  evidence/               # source_index / fact_index / deps / issues
  archive/                # cbm dumps / runs / legacy / raw_agents (default: do not read)
  cbm/                    # live CBM working dir
```

Designed for later GoldenGenerate / TestGenerate / kernel debug. It does **not** generate real tests, CSV, or golden code.

`coverage_model.yaml` and `test/contract.yaml` only declare obligations/hints. Downstream tools generate actual tests/golden.

Export views:

```powershell
uo-kb-export D:\path\to\repo --op-name MyOp --view tiling-test
uo-kb-export D:\path\to\repo --op-name MyOp --view golden-gen
uo-kb-export D:\path\to\repo --op-name MyOp --view testgenerate
uo-kb-export D:\path\to\repo --op-name MyOp --view kernel-debug
uo-kb-export D:\path\to\repo --op-name MyOp --view human
```

## Core Artifacts

Canonical tiling schemas: `prompts/00_tiling_kernel_artifact_contract.md`.  
Start reading at `index.yaml` → `route.md` → domain indexes (`tiling/index.yaml`, `flow/index.yaml`, …).

Host tiling extraction is **two steps** (single agent, sequential):

- **Step 1 — `tiling/variables.yaml`**: `tiling_mechanism` + every variable / influencing factor, classified by impact scope (`impact_classification`). `tiling/key_space.yaml` holds pure tiling_key **encoding** (macro / `fields_order` / key fields).
- **Step 2 — `tiling/constraints.yaml`**: typed `relations` (`mutex` / `implies` / `requires` / `compatible_set` / `compile_time_fixed` / `runtime_guard`), explicit `tiling_key_pruning` (剪枝) + `tiling_key_merging` (合并), `input_realization` (key_pattern → operator IO / shape·dtype intent), and key-level `key_unreachable` (separate from family unreachable).

`derived_fields` / `independent: false` are computed, not free cartesian dims.  
Relation coverage debts live in `tiling/coverage_model.yaml` → `key_relation_obligations` (`must_cover` + `linked_relations` / `linked_input_realization`).  
`test/contract.yaml` tells TestGenerate: variables → constraints/pruning/merging → input_realization; never blind-cartesian fields.

## Workflow (`/uo-init`)

```text
Preflight full/incremental + ignore rules
  -> CBM index
  -> Phase 0.5-A deterministic scope scan
  -> Phase 0.5-B targeted MCP semantic enrichment
  -> Phase 0.5-C Macro Scope Human Review (user approval)
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

Human gates: **0.5** (scope) and **3.5** (kernel dispatch with full family/tiling brief). Only these gates pause and show judgment briefs in chat. Phase 1.5 is retired — after Macro Boundary, continue silently into host/flow parallel (no Boundary/IO dump).

`/uo-update` reuses the same phases but only re-runs areas listed in `summary/update_plan.yaml`.

## Quick Start - OpenCode

1. Install skills + plugin prompts (required for human-review button UI):

```powershell
cd understand-operator
./install.ps1 opencode
```

This links:

- `~/.config/opencode/skills/uo-init` … `uo-diff` / `understand-operator`
- `~/.config/opencode/understand-operator-plugin` → `prompts/` + `agents/`（Phase 0.5/3.5 的 `question` 交互规则在这里）

2. Ensure `~/.config/opencode/opencode.json` allows the question tool:

```json
{
  "permission": {
    "question": "allow"
  }
}
```

3. Configure MCP `codebase-memory-mcp` — see `docs/cbm-mcp-setup.md`.

4. In Agent mode on an AscendC repo:

```text
/uo-init D:\path\to\ascendc-repo --op-name FlashAttentionScore
```

Phase 0.5 / 3.5 human gates must use OpenCode **`question`** (selectable buttons), not free-text chat confirmation.

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

# Quality gate
uo-quality D:\path\to\repo --op-name MyOp

# Export canonical tiling for TestGenerate
uo-kb-export D:\path\to\repo --op-name MyOp --view tiling-test
```

## CBM (MCP)

Agent-side indexing and lookups use the **MCP server** `codebase-memory-mcp` (see [upstream](https://github.com/DeusData/codebase-memory-mcp)).

Setup: `docs/cbm-mcp-setup.md`

- OpenCode / Cursor: configure MCP `codebase-memory-mcp`
- **`/uo-init` Phase 0 自动**：MCP `index_repository` 生成 graph DB，再写 `cbm/index_meta.json`
- `prepare_operator.py` **只建 KB 目录**，默认不调 CLI 索引
- Runtime Q&A / subagents: **MCP tools only**
- `/uo-update`: MCP `index_repository` + `detect_changes`

Graph DB 由 MCP 服务维护（通常在 `~/.cache/codebase-memory-mcp/`），不是手写进仓库。

## Core Artifacts

See `prompts/00_tiling_kernel_artifact_contract.md` for canonical tiling schemas. Start reading at `route.md`, then `summary/operator_io.yaml`.
