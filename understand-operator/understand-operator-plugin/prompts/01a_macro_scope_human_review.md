# Macro Scope Human Review

This is the Phase 0.5 human gate. Its goal is to let the user approve the
Phase 1 exploration scope before Macro Boundary Agent starts.

Phase 0.5 has three internal substeps but only one human gate:

```text
Phase 0.5-A: Deterministic Scope Scan
Phase 0.5-B: MCP Semantic Enrichment
Phase 0.5-C: Human Review
```

Do not add a new gate between A/B/C. Stop only at 0.5-C.

## Inputs

- `archive/runs/macro_scope_scan.yaml` from Phase 0.5-A.
- `cbm/index_meta.json`.
- `archive/runs/ignore_rules.md`.
- User request / extra_description.
- Phase 0 artifact skeleton (`index.yaml`, `operator.yaml`, `route.md`).

## Phase 0.5-A: Deterministic Scope Scan

Before the first CBM semantic search for scope discovery, build a deterministic
candidate file and text-hit inventory. Prefer the bundled scanner script:

```powershell
python "$SCRIPT_DIR/macro_scope_scan.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --filesystem-tool python
```

The script performs filesystem traversal and literal text search bounded to
`$PROJECT_ROOT`; it applies `.gitignore`, default ignore rules, and
`.understandoperatorignore`. If the script is unavailable, use the bounded
commands below as fallback and record a warning.

Required scan work:

1. Enumerate files under `$PROJECT_ROOT` with ignore rules applied.
2. Classify paths into:
   - `host`
   - `kernel`
   - `api`
   - `proto`
   - `golden`
   - `tests`
   - `examples`
   - `generated`
   - `docs_config`
   - `unknown`
3. Search architecture / implementation markers:
   - `arch22`
   - `arch35`
   - `regbase`
   - SoC names or architecture condition macros such as `ASCEND[0-9_]+`.
4. Search entry candidate text and macros:
   - tiling registration macros
   - operator registration macros
   - kernel global entries
   - `TILING_KEY_IS`
   - `GET_TILING_DATA`
   - symbols identical or similar to `OP_NAME`
5. Mark:
   - large files
   - same-name multiple implementations
   - architecture-specific directories
   - legacy/test/sample/generated files
   - files with suspicious indirect matches that are not semantically confirmed

Fallback commands:

```powershell
rg --files "$PROJECT_ROOT"
rg -n -i "arch22|arch35|regbase|ASCEND[0-9_]+" "$PROJECT_ROOT"
rg -n "REGISTER_TILING|REGISTER_OP|TILING_KEY_IS|GET_TILING_DATA|__global__" "$PROJECT_ROOT"
```

If `rg` is missing, use ignore-limited `Get-ChildItem` + `Select-String` on
Windows or `find` + `grep` on POSIX. Never scan outside `$PROJECT_ROOT`.

The scan only discovers candidate scope; it cannot confirm semantic facts by
itself.

Write the deterministic result to:

```text
archive/runs/macro_scope_scan.yaml
```

Minimum schema:

```yaml
version: 1
op_name: ""
generated_at: ""
scan_method:
  filesystem_tool: rg # rg | powershell | find
  cbm_project: ""
  ignore_rules_applied: true
directories:
  included: []
  excluded: []
files:
  host: []
  kernel: []
  api: []
  proto: []
  golden: []
  tests: []
  examples: []
  generated: []
  docs_config: []
  unknown: []
architecture_variants:
  - name: arch35
    matched_paths: []
    matched_lines: []
    semantic_status: candidate # candidate | confirmed | rejected
    cbm_evidence: []
entry_candidates:
  - item: ""
    kind: tiling_registration # operator_registration | kernel_entry | macro | unknown
    file: ""
    line: null
    discovery_method: rg
    cbm_status: pending
    cbm_symbol: ""
    evidence: []
large_files:
  - path: ""
    size_bytes: 0
    read_policy: line_scoped_only
uncertain_items: []
warnings: []
```

Sort all paths deterministically and store paths relative to `$PROJECT_ROOT`.
Warnings are acceptable; scan command failures should not abort the workflow if
a bounded fallback produced partial results.

## Phase 0.5-B: MCP Semantic Enrichment

After 0.5-A has produced candidate files and text hits, use CBM MCP to enrich
only targeted candidates:

- Resolve candidate entry symbols.
- Find registration relations.
- Find host and kernel main entries.
- Confirm primary call relations.
- Semantically enrich candidate architecture paths.
- Mark macros/templates/strings that CBM could not index or confirm.

Each MCP query must be based on one of:

```text
discovered candidate file
discovered candidate symbol
discovered registration macro
discovered architecture variant
```

Do not perform repeated whole-project `search_code` searches for the same
`arch35`, `arch22`, `regbase`, or path marker after the deterministic scan has
already found the candidate list.

## Phase 0.5-C: Human Review

Combine `macro_scope_scan.yaml` and MCP enrichment into the current review:

```text
include_scope
exclude_scope
branch_skip_rules
uncertain_scope
next_phase_effect
```

`macro_scope_review.yaml` may reference `macro_scope_scan.yaml` instead of
duplicating large scan content.

Must show the user:

1. `include_scope`
   - Directories, file patterns, entry symbols, and host/kernel/api/proto/golden
     candidate groups that Phase 1 will explore.
2. `exclude_scope`
   - Directories, patterns, unrelated branches, legacy paths, tests/samples, and
     generated/build outputs that Phase 1 will not explore.
3. `branch_skip_rules`
   - Platform, dtype, feature flag, legacy, or inactive branches that Macro
     Boundary Agent should skip.
4. `uncertain_scope`
   - Candidate files, symbols, directories, or branches that still require user
     confirmation.
5. `next_phase_effect`
   - How the decision affects `operator.yaml.scope`, `analysis_plan`, and later
     subagent `source_hints`.

For every uncertain item, include:

- `item`
- `current_observation`
- `why_uncertain`
- `decision_needed`
- `impact_if_included`
- `impact_if_excluded`
- `suggested_default`
- `evidence_refs`

User-facing summaries should explain each decision item in Chinese in 2-4
sentences; do not list only paths.

## Required Review Artifact

Write `archive/runs/macro_scope_review.yaml` and sync the conclusion summary to
`human/review.md` Boundary Review:

```yaml
phase: "0.5"
status: pending_user_review
scan_artifact: archive/runs/macro_scope_scan.yaml
internal_steps:
  scope_scan: completed
  semantic_enrichment: completed
  human_review: pending
include_scope:
  files: []
  dirs: []
  symbols: []
  notes: []
exclude_scope:
  files: []
  dirs: []
  patterns: []
  notes: []
branch_skip_rules:
  - condition: ""
    reason: ""
    evidence: []
uncertain_scope:
  - item: ""
    question: ""
    current_observation: ""
    why_uncertain: ""
    impact_if_included: ""
    impact_if_excluded: ""
    suggested_default: ""
    evidence: []
next_phase_effect:
  operator_scope: []
  analysis_plan: []
  source_hints: []
decision:
  value: pending # continue | revise | stop | manual_supplement | pending
  decided_at: null
  notes: ""
```

## Interaction Choice

After showing the summary, use `prompts/00_review_menu.md`:

1. Use OpenCode `question` or Cursor AskQuestion choice UI.
2. Options must include:
   - `continue` - enter Phase 1 with current scope.
   - `revise` - adjust include/exclude/skip and show the review again.
   - `stop` - end workflow.
   - `manual_supplement` - user provides extra scope notes.
3. STOP and wait for the choice UI result.
4. Persist the decision:

```powershell
python "$SCRIPT_DIR/review_checkpoint.py" "$PROJECT_ROOT" --op-name "$OP_NAME" --gate macro_scope --decision <choice> [--notes "..."]
```

Read `UO_REVIEW_DECISION=...` and `archive/runs/macro_scope_decision.json`.

Gate rules:

- Do not start Phase 1 before the user explicitly chooses `continue`.
- If the user chooses `revise`, update `macro_scope_review.yaml`, re-display the
  review, and run the menu again.
- If the user chooses `manual_supplement`, add notes to review YAML, re-display
  the review, and run the menu again.
- If the user chooses `stop`, end the workflow and report current artifacts.
- Do not use keyboard-grabbing `--interactive` / `--arrows`.
