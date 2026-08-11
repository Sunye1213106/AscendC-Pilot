---
name: tg-init
description: 测例契约与绑定：变量/IO/TilingKey 维信息提取。用户说 tg-init、建测例契约、tilingkey 绑定时加载。默认 tilingkey_full_coverage（无需
  CSV）。Pilot 管阶段；加载后 acp start tg-init。
---

# tg-init

Pilot workflow entry. Orchestration authority: `pilot/.../workflows/specs.py`.

Domain method: `skills/testcase-generation/SKILL.md`.

Run via `acp start` / `next` / `run-action` / `advance` / `complete`.

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `init_intent` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-init/init-intent` | `-` | `tg-init-intent-v1` |
| `kb_check` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-init/kb-check` | `-` | `uo-ready-v1` |
| `contract_build` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-init/contract-build` | `-` | `tilingkey-contract-v1` |
| `semantic_bind` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-init/semantic-bind` | `-` | `tilingkey-binding-v1` |
| `bind_merge` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-init/bind-merge` | `-` | `bind-merge-v1` |
| `mid_nest` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-init/mid-nest` | `-` | `mid-nest-v1` |
| `integrity_gate` | `deterministic` | `deterministic-tg-engine` | `deterministic_engine` | `tg-init/integrity-gate` | `-` | `tilingkey-integrity-v1` |
| `init_audit` | `subagent` | `tg-init-audit` | `referee` | `tg-init/init-audit` | `tg/init-audit` | `init-audit-v1` |
| `human_confirm` | `primary_interactive` | `ascendc-pilot` | `controller` | `tg-init/human-confirm` | `tg/human-confirm` | `init-confirmed-v1` |

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
| `init_intent` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-init/init-intent` | `-` | `deterministic-tg-engine` |
| `kb_check` | source-authority,code-access,evidence,language,pilot-control,output-quality | kb-query | `tg-init/kb-check` | `-` | `deterministic-tg-engine` |
| `contract_build` | source-authority,code-access,evidence,language,pilot-control,output-quality | contract-building,kb-query | `tg-init/contract-build` | `-` | `deterministic-tg-engine` |
| `semantic_bind` | source-authority,code-access,evidence,language,pilot-control,output-quality | kb-query | `tg-init/semantic-bind` | `-` | `deterministic-tg-engine` |
| `bind_merge` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-init/bind-merge` | `-` | `deterministic-tg-engine` |
| `mid_nest` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-init/mid-nest` | `-` | `deterministic-tg-engine` |
| `integrity_gate` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-init/integrity-gate` | `-` | `deterministic-tg-engine` |
| `init_audit` | source-authority,code-access,evidence,language,pilot-control,output-quality | kb-query | `tg-init/init-audit` | `tg/init-audit` | `tg-init-audit` |
| `human_confirm` | source-authority,code-access,evidence,language,pilot-control,output-quality | - | `tg-init/human-confirm` | `tg/human-confirm` | `ascendc-pilot` |

## Action runtime index

| action_id | method_path | prompt_path | output_contract | role |
|---|---|---|---|---|
| `init_intent` | `actions/init-intent/action.yaml` | `-` | `tg-init-intent-v1` | `deterministic_engine` |
| `kb_check` | `actions/kb-check/action.yaml` | `-` | `uo-ready-v1` | `deterministic_engine` |
| `contract_build` | `actions/contract-build/action.yaml` | `-` | `tilingkey-contract-v1` | `deterministic_engine` |
| `semantic_bind` | `actions/semantic-bind/action.yaml` | `-` | `tilingkey-binding-v1` | `deterministic_engine` |
| `bind_merge` | `actions/bind-merge/action.yaml` | `-` | `bind-merge-v1` | `deterministic_engine` |
| `mid_nest` | `actions/mid-nest/action.yaml` | `-` | `mid-nest-v1` | `deterministic_engine` |
| `integrity_gate` | `actions/integrity-gate/action.yaml` | `-` | `tilingkey-integrity-v1` | `deterministic_engine` |
| `init_audit` | `actions/init-audit/action.yaml` | `prompts/tasks/tg/init-audit.md` | `init-audit-v1` | `referee` |
| `human_confirm` | `actions/human-confirm/action.yaml` | `prompts/tasks/tg/human-confirm.md` | `init-confirmed-v1` | `controller` |
