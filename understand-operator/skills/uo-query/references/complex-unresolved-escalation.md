# Complex Unresolved → Per-KEY `uo-query` Escalation

When residual resolve / KEY bind hits **complex** gaps, do **not** stop at
`unsolved` / blank `binding_gaps` / thin `accepted` without a shape expression.

## What counts as complex

Any unresolved / bind gap that is **KEY- or shape-conditioned**, including:

- Tiling KEY predicate / `set_by` / hit condition unknown or `needs_alignment`
- Field tied to KEY routing whose producer/expression is shape-dependent
- Residual item whose label would be “unknown” / “needs host proof” after one
  weak MCP miss
- TestAgent `UNBOUND_KEY` / `MISSING_CSV_REF` where KEY↔CSV needs a real expr

Simple analyzer false positives (nested `set_*` already proven) may stay on the
sample-and-propagate path. **KEY shape expr must escalate.**

## Forbidden

| Forbidden | Why |
|---|---|
| Return `unsolved` / leave KEY gap after a thin residual sample | No shape expr produced |
| One subagent owns **all** KEYs | Context dilution; slow and shallow |
| Invent `then==else` / fake domain to clear the gap | Gate bypass |
| Skip `uo_kb_query.py` and Grep-only for KEY hit conditions | Violates uo-query gate |

## Parent orchestration (required)

1. Classify remaining complex items → group by **KEY id** (or by the KEY that
   consumes the field). Cap concurrent KEY groups (default **8**).
2. Dispatch **one subagent per KEY** in parallel (separate Task / dispatch
   identity). Do not serialise unless the runtime cannot parallelise.
3. Each KEY subagent **must** run `/uo-query` (or the same CLI + MCP gate):

```powershell
python -X utf8 "$QUERY_CLI" "$PROJECT_ROOT" --op-name "$OP_NAME" --status-only
python -X utf8 "$QUERY_CLI" "$PROJECT_ROOT" --op-name "$OP_NAME" --pattern branches_for_key --target "<KEY_ID>"
python -X utf8 "$QUERY_CLI" "$PROJECT_ROOT" --op-name "$OP_NAME" --pattern affected_shapes --target "<KEY_ID>"
python -X utf8 "$QUERY_CLI" "$PROJECT_ROOT" --op-name "$OP_NAME" --pattern neighbors_of --target "<KEY_ID_or_SYM>"
```

4. Follow `source-lookup-gate.md`: default mode loops MCP until **high**
   confidence on the KEY’s shape / set condition. **TG: `confidence` must be
   `high` for resolved; never `medium`/`low` resolved. Intermediate Host symbols
   must be unfolded in `derivation_chain` until `VAR_CSV_*` (or compile-time lit).
   If a mid-symbol blocks (e.g. `bnSparseLimit`), spawn a **nested Task** for that
   symbol (call-stack style) — do not stop at “depends on X”.**
5. Each KEY subagent writes **only** its own file (avoid write races):

```text
<UO_ROOT>/ir/key_shape_resolve/<KEY_ID>.yaml
# TG also: <OUT_ROOT>/realization/uo_query_resolve/<KEY_ID>.yaml
```

Schema:

```yaml
version: 1
key_id: KEY_EXAMPLE
status: resolved | unresolved | needs_human
shape_expr: "<normalized predicate / shape condition>"
shape_determined: [VAR_CSV_...]
derivation_chain:
  - {id: VAR_KEY_EXAMPLE, deps: [VAR_CSV_B], via: set_by}
set_by:
  symbol: ...
  file_path: ...
  start_line: ...
  expr_raw: ...
related_unresolved_ids: [DIAG_..., ...]
resolutions:
  - id: DIAG_...
    status: resolved | accepted | false_positive | alias
    rationale: <Chinese>
    resolution: {kind: shape_expr, label: ..., evidence: "path:line"}
query_backend: kb_graph
confidence: high   # TG: high only when resolved; never medium/low resolved
mcp_checked: [SYM::..., ...]
```

6. Parent **merges** all `ir/key_shape_resolve/*.yaml` into
   `ir/resolution_patch.yaml` (and/or TestAgent lexicon via `--merge-uo-resolve`), then
   `apply_resolution.py --check` / bind confirm.
7. Only if a KEY subagent returns `needs_human` / `unresolved` **with** MCP evidence + missing
   symbols listed may the parent keep that KEY open — still not
   a silent unsolved return. Non-empty TG keys that stay unresolved block confirm
   (empty-tensor allowlist excepted).

## Dispatch identity (per KEY)

```text
<run_id>:resolve:uo-query-key:<KEY_ID>
```

Resume the same identity on repair; do not open a second fresh agent for the
same KEY while one is open.

## Residual sample path vs escalation

| Path | Use when |
|---|---|
| Pattern sample ≤12 + propagate | Clear false_positive / host-only intermediate with shared evidence |
| **Per-KEY uo-query parallel** | Complex KEY / shape expression / bind expr still missing |

Open unresolved → 0 remains the parent success criterion; escalation is how
complex KEY gaps get closed without inventing facts.

## TestAgent (TG) consumers

When gaps surface on the TestAgent side (`binding_gaps`, abstract `UNBOUND_*`,
`KEY_DERIVATION_MISSING`, `RUNTIME_DOMAIN_NOT_PARTITIONED`, KEY-related
`REALIZE_EMPTY`), follow the TG companion table:

`testcase-agent/skills/tg-domain-review/references/tg-uo-query-escalation.md`

Same rule: parallel **one KEY per subagent**, `uo-query` first, no bare unsolved.
