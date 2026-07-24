## Task

Perform `extract_plan` for the Pilot-prepared action.

You are the **producer** actor `uo-semantic-resolve` (not primary).  
Do not manage workflow state or declare completion.

## Mode

- mode: `task`
- task_id: `extract-plan`
- workflow_id: `uo-init`
- action_id: `extract_plan`
- actor_id: `uo-semantic-resolve`
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

## Required Procedure

1. Read `ir/extract_plan_candidates.yaml` (writers / receivers / aliases / non_sink / extra).
2. Optionally skim `ir/entrypoint_graph.yaml` for identity context — do **not** rewrite it.
3. For each **writer / receiver / alias** candidate: accept with evidence, or **omit** it. No guessing.
4. **Source windows (mandatory for weak candidates)** — open the repo file and read the function body before accepting or rejecting when **any** of:
   - candidate `score` is low (heuristic below ~0.55)
   - `role_suggested` is `tiling_writer`, `key_writer`, or non-sink / `is_tiling_sink_suggested: false`
   - duplicate `name` among candidates (same short name)
   - incomplete identity (`qualified_name` equals bare `name`, missing class/namespace)
   - overlapping `start_line` in the same `file_path` as another candidate
   - candidate `evidence` is only `assign_lhs_only` and/or `has_set_field` ( **`set_*` alone is not a TilingData writer** )
   For those, confirm from source (not snippet alone): `file_path`, `start_line`, `end_line`, `owning_function`, `owning_class`, `function_signature`, `actual_calls`, `actual_writes`, `evidence_snippet`.
   Classify: real **TilingData writer** vs alignment/helper (e.g. `AlignTo`) vs temp/local vs **non-sink** intermediate. Helpers/temps → `role: ignore` or omit; do not promote by setter name only.
5. Write **only** `ir/extract_plan.yaml` with schema fields:
   - `version: 1`
   - `actor_id: uo-semantic-resolve` (**required**)
   - `run_id: <RUN_ID>` (**required**, must match prepare session)
   - `workflow_id: uo-init` (**required**)
   - `candidates_sha256: <sha256 of ir/extract_plan_candidates.yaml>` (**required**)
   - `writers` / `receivers` / `aliases` — **mappings** (see below)
   - `non_sink_roots` / `derived_roots` — **bare string name lists only**
   - `extra_host_entries` — mappings or names from candidates
   - each **accepted writer/receiver** must carry `file_path` or `qualified_name` or `identity_key` (no short-name-only when ambiguous)
   - **every writer MUST include `role`**: copy `role_suggested` from the matching candidate  
     (`tiling_writer` | `key_writer` | `workspace_writer` | `provenance_helper` | `ignore`)
   - **every receiver MUST include `is_tiling_sink`**: copy `is_tiling_sink_suggested` from the matching candidate  
     (`true` = real TilingData sink; `false` = intermediate / non-sink)
   - **every accepted writer/receiver** SHOULD carry decision metadata (required when not fully source-proven):
     - `evidence_source`: `source` | `cbm` | `candidate_only`
     - `source_verified`: `true` | `false` — **`true` only** after reading source/cbm with `evidence_files` + `evidence_lines` populated
     - `evidence_files`: `[]` — repo-relative paths you read
     - `evidence_lines`: `[]` — line ranges or anchors from those files
     - `decision_reason`: short string (required for weak `candidate_only` promotions)
     - If `evidence_source: candidate_only` → **`source_verified: false`** and `confidence: candidate` — never mark source-verified without files.
6. Stop. Return a short summary. Do **not** finalize; primary runs `acp run-action extract_plan --finalize`.

## Schema (hard)

### writers / receivers / aliases — mappings

```yaml
writers:
  - name: SaveStuff
    file_path: op_host/arch35/foo_tiling.cpp
    start_line: 10
    role: tiling_writer
    evidence_source: source
    source_verified: true
    evidence_files: [op_host/arch35/foo_tiling.cpp]
    evidence_lines: [10-18]
    decision_reason: body writes blob_->set_x/y on TilingData sink
receivers:
  - name: blob_
    file_path: op_host/arch35/foo_tiling.cpp
    is_tiling_sink: true
aliases:
  - local: localType
    tdf_leaf: layout
```

### non_sink_roots / derived_roots — string lists only

```yaml
non_sink_roots:
  - ALIGN128
  - blockIdx
derived_roots: []
```

- Items are **bare strings** (candidate `name` values).
- Candidate may have empty `file_path` / `assign_lhs_only` — that is OK for this list; **do not** invent `adjudication` / `unresolved` / `missing_evidence` objects.
- Still **read source** before confirming a non-sink name (same weak-candidate rules); list entries stay bare strings — put read proof on writers/receivers metadata, not under `non_sink_roots`.
- Confirm → append the string name. Reject → **omit** the name. Never write a mapping under these keys.

## Out of scope (do NOT do)

- Do **not** read/adjudicate `ir/llm_tasks.yaml` blocking `mark_missing` / call_edge tasks here.
- Do **not** invent `call_edge_adjudications` / `blocking_reasons` sections inside `extract_plan.yaml`.
- Do **not** invent writer/receiver names that are absent from candidates.
- Do **not** ACCEPT empty-candidate edges (false closure). Those wait for `adjudicate_llm_tasks` then `apply_semantic_patch`.
- Do **not** run `acp`, advance phases, or write ledger / graphs other than `extract_plan.yaml`.

## Hard Constraints

- MUST write as actor `uo-semantic-resolve` with `action_id=extract_plan` (ASCENDC_ACTION).
- MUST NOT: modify Pilot state; invent evidence; write referee verdicts; patch derived graphs.
- MUST NOT: call domain scripts (`build_layered_kb.py` / `propose_extract_plan.py` / `apply_extract_plan.py`).
- MUST NOT: put mappings under `non_sink_roots` / `derived_roots`.

## Output Contract

Contract id: `extract-plan-v1`  
Path: `<UO_ROOT>/ir/extract_plan.yaml`

## Acceptance Criteria

- Every candidate class was attempted (writers/receivers/aliases/non_sink/…).
- Every accepted writer/receiver has required identity fields + `role` / `is_tiling_sink`.
- `non_sink_roots` / `derived_roots` are string lists (or empty).
- Output matches extract_plan schema (not llm_tasks patches).
- No undeclared file was modified.

## Failure Handling

- Writers/receivers: evidence insufficient → **omit** that item (do not invent unresolved mappings).
- Non-sink / derived: confirm as bare string, or omit. Summarize omitted names in the Task reply text only — not as YAML adjudication objects.
