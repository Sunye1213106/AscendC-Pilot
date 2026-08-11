---
name: uo-init
description: 首次构建 AscendC `.uo` CodeMap：机器解析范围与 BuildVariant、抽取 CompilerFacts、运行确定性
  CodeMap Pass、写入并校验单一 `.uo`。semantic residual 保留在 unresolved.yaml，不由 LLM 写入 canonical
  UO。用户要求建 UO/CodeMap、首次分析算子或指定 architecture 建图时使用。prepare 为确定性步骤：用户定 operator+arch，编译器定
  Source Scope，无人工文件清单确认。
---

# uo-init

Pilot workflow entry. Orchestration authority: `pilot/.../workflows/specs.py`.

Domain method: `skills/operator-analysis/SKILL.md`.

Run via `acp start` / `next` / `run-action` / `advance` / `complete`.

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `prepare` | `deterministic` | `human` | `deterministic_engine` | `uo-init/prepare` | `-` | `uo-prepare-v1` |
| `extract` | `deterministic` | `human` | `deterministic_engine` | `uo-init/extract` | `-` | `uo-extract-v1` |
| `analyze` | `deterministic` | `human` | `deterministic_engine` | `uo-init/analyze` | `-` | `uo-analyze-v1` |
| `commit` | `deterministic` | `human` | `deterministic_engine` | `uo-init/commit` | `-` | `uo-commit-v1` |
| `verify` | `deterministic` | `human` | `deterministic_engine` | `uo-init/verify` | `-` | `uo-verify-v1` |

<!-- END GENERATED ACTIONS -->

## Composed: policy-invariants

Follow pilot policies (short invariants). Full text: `pilot/policies/*/POLICY.md`.

# Control invariants (model-facing, short)

1. Only run Actions returned by `acp next`; never advance Pilot state yourself.
2. Never declare workflow `done` / `passed`; only `acp complete` may finish.
3. Do not call domain CLIs directly; use `acp run-action`.
4. Writes must stay inside Agent `write_scopes` ∩ Action lease ∩ workflow `write_roots`.
5. Primary never writes formal `uo/**` / `tg/**` IR products for a declared sub-actor.
6. Lease invariant: anything you may Write is also Readable.
7. Missing required params → AskQuestion immediately; do not repo-archaeology to guess.
8. Progress only via host Todo sync from `todo.todo_sync.items` — never paste status panels to the user.

Full detail: `pilot/policies/pilot-control/POLICY.md`.

# Evidence invariants (model-facing, short)

1. Search / UO graph locate ≠ proof. High confidence needs a disk source window.
2. `confidence: high` / `source_verified: true` requires **both**:
   - `evidence_window_sha256` for the cited `path:line` window
   - continuous `evidence_snippet` that is a substring of that window
3. Never invent hashes, line numbers, or pasted non-contiguous snippets.
4. Neighbor / wrong-window sha reuse is fabrication → reject.
5. Absence claims need machine-checkable negative evidence, not “I searched a lot”.
6. Intermediate locals are never input roots; ungrounded surfaces stay unresolved.

Full detail: `pilot/policies/evidence/POLICY.md`.

# Code-access invariants (model-facing, short)

1. Locate (graph / Grep) → then windowed Read of the minimal function/macro block.
2. No unbounded repo / parent-repo scans; no whole-file dumps into context.
3. Empty UO graph ≠ symbol does not exist; fall back to scoped source read.
4. Shallow ABI `set_*` writers without value-defining sites → PARTIAL/UNKNOWN, not “unreachable”.

Full detail: `pilot/policies/code-access/POLICY.md` (host/Windows path tips live in docs).

# Authority invariants (model-facing, short)

Priority (high → low): current source window → signed Pilot artifacts → current UO/TG KB → verified local memory → model memory / naming intuition.

MUST NOT close KEY/contract fields from naming guesses or stale memory.

Full detail: `pilot/policies/source-authority/POLICY.md`.

# Output-quality invariants (model-facing, short)

1. Producer write surface ∩ Referee write surface = ∅.
2. Do not forge high confidence; keep unresolved / needs_human explicit.
3. Write only declared output-contract paths.

Full detail: `pilot/policies/output-quality/POLICY.md`.

# Language invariants (model-facing, short)

- User-facing text: 简体中文.
- IDs / status / reason_code / schema field names: English.
- Findings / rationale narrative: 简体中文.

Full detail: `pilot/policies/language/POLICY.md`.

## Composition index

| action_id | policies | capabilities | method | prompt | agent |
|---|---|---|---|---|---|
| `prepare` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-init/prepare` | `-` | `human` |
| `extract` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-init/extract` | `-` | `human` |
| `analyze` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-init/analyze` | `-` | `human` |
| `commit` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-init/commit` | `-` | `human` |
| `verify` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `uo-init/verify` | `-` | `human` |

## Action runtime index

| action_id | method_path | prompt_path | output_contract | role |
|---|---|---|---|---|
| `prepare` | `actions/prepare/action.yaml` | `-` | `uo-prepare-v1` | `deterministic_engine` |
| `extract` | `actions/extract/action.yaml` | `-` | `uo-extract-v1` | `deterministic_engine` |
| `analyze` | `actions/analyze/action.yaml` | `-` | `uo-analyze-v1` | `deterministic_engine` |
| `commit` | `actions/commit/action.yaml` | `-` | `uo-commit-v1` | `deterministic_engine` |
| `verify` | `actions/verify/action.yaml` | `-` | `uo-verify-v1` | `deterministic_engine` |
