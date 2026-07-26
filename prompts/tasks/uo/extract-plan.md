## Task

Bundle identity is authoritative.
Do not replace, infer, normalize, or copy identity from old artifacts.

Perform `extract_plan` for the Pilot-prepared action.

You are the **producer** actor `<ACTOR_ID>` (not primary).  
Do not manage workflow state or declare completion.

## Mode

- mode: `task`
- task_id: `extract-plan`
- workflow_id: `<WORKFLOW_ID>`
- action_id: `<ACTION_ID>`
- actor_id: `<ACTOR_ID>`
- run_id: `<RUN_ID>`

## Target

Confirm **only** the extraction-plan candidates listed below.  
Do **not** expand into `llm_tasks` / `mark_missing` / `dispatches_to` adjudication.

## Context

- Project root: `<PROJECT_ROOT>`
- UO root: `<UO_ROOT>`
- TG root: `<TG_ROOT>`
- Topic: `<TOPIC>`
- Context pack: `<CONTEXT_PACK_PATH>`
- CBM project (MCP `project` / `acp cbm lookup`): `<CBM_PROJECT>`
- Architecture preference: `<ARCHITECTURE>`
- **candidates_sha256 (copy verbatim into plan):** `<CANDIDATES_SHA256>`

## Required Procedure

1. Read session `prompt.md` / `method.md` / `bundle.yaml`.
2. Follow public **large-IR** read order (`code-access`): Read
   `extract_plan_candidates.summary.yaml` first (counts / sinks /
   `key_writer_suggested` / `alias_candidates` / **`section_lines`**), then
   `extract_plan.rework_hints.yaml` if present. **FORBIDDEN**: Grep/offset-hunt the full
   candidates file before summary.
3. Use `section_lines` to Read only needed windows of the full candidates file
   (writers carry deterministic `source_window` + `sha256`). Optionally skim
   `entrypoint_graph.yaml` and `uo/cbm/index_meta.json`.
4. For **each** writer / tiling-sink receiver you **accept**：follow `cbm-navigation` +
   `source-reading` and policies `evidence` / `code-access`.
   Locate-only Grep/`rg`/`Select-String` OK; **not** evidence alone.
   **Required evidence (AND)**: `evidence_files` + `evidence_lines` +
   `evidence_window_sha256` (copy from candidate `source_window.sha256`) **and** contiguous
   `evidence_snippet` from that window + `decision_reason`. Helpers (`AlignTo`, `CeilDivide`, …) → `role: ignore` / omit.
5. Write **only** `<UO_ROOT>/ir/extract_plan.yaml`. Set `candidates_sha256` to **exactly** `<CANDIDATES_SHA256>`.
6. Stop. Do **not** finalize.

## Schema (hard)

```yaml
version: 1
actor_id: <ACTOR_ID>
run_id: <RUN_ID>
workflow_id: <WORKFLOW_ID>
candidates_sha256: <CANDIDATES_SHA256>
writers:
  - name: SaveStuff
    file_path: op_host/arch35/foo_tiling.cpp
    start_line: 10
    role: tiling_writer
    evidence_source: cbm
    source_verified: true
    evidence_files: [op_host/arch35/foo_tiling.cpp]
    evidence_lines: ["10-40"]
    evidence_snippet: |
      ge::graphStatus Foo::SaveStuff() {
        blob_->set_x(...);
        ...
      }
    decision_reason: window shows blob_->set_* on TilingData sink
receivers:
  - name: blob_
    file_path: op_host/arch35/foo_tiling.cpp
    is_tiling_sink: true
    evidence_source: cbm
    source_verified: true
    evidence_files: [op_host/arch35/foo_tiling.cpp]
    evidence_lines: ["10-40"]
    evidence_snippet: |
      blob_->set_x(...);
    decision_reason: sink receiver confirmed in same window
aliases:
  - local: localType
    tdf_leaf: layout
non_sink_roots:
  - ALIGN128
derived_roots: []
```

## Hard Constraints

- MUST: follow composed policies `evidence` + `code-access` + `source-authority` (not Action-local exceptions).
- MUST: `candidates_sha256` equals prepare stub value (no placeholders).
- MUST NOT: invent snippet text; promote AlignTo/CeilDivide; write `semantic_groups` / `llm_tasks`.
- MUST NOT: call domain scripts (`propose_extract_plan.py` / `apply_extract_plan.py`).

## Output Contract

Contract id: `extract-plan-v1`  
Path: `<UO_ROOT>/ir/extract_plan.yaml`

## Failure Handling

- Cannot obtain a matching source window → **omit** that item.
- Do not write placeholder sha256 / fake snippets.
