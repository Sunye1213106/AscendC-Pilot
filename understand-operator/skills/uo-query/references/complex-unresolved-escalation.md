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

**Build-time note:** `/uo-init` must **not** dispatch uo-query for
`input_derivable` gaps (use `uo-semantic-resolve` task E). This file is for
**post-KB** escalation only.

## Forbidden

| Forbidden | Why |
|---|---|
| Return `unsolved` / leave KEY gap after a thin residual sample | No shape expr produced |
| One subagent owns **all** KEYs | Context dilution; slow and shallow |
| Invent `then==else` / fake domain to clear the gap | Gate bypass |
| Skip `uo_kb_query.py` and Grep-only for KEY hit conditions | Violates uo-query gate |
| TG Task writes `$UO_ROOT/**` or `key_shape_resolve/` | Hard isolation: TG → OUT_ROOT only |

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

4. Follow `source-lookup-gate.md`: default mode loops MCP until **high**.
5. Each KEY subagent writes **only** its own file (avoid write races) — **pick one mode**:

### Mode A — TG bind (testcase-agent parent)

```text
<OUT_ROOT>/realization/uo_query_resolve/<KEY_ID>.yaml
```

- `confidence: high` only when `status: resolved`
- CSV↔HOST / `VAR_CSV_*` / mid nesting: follow
  `testcase-agent/skills/tg-init/references/tg-uo-query-escalation.md`
- Parent merges with **`tg-init --merge-uo-resolve` only**
- **Never** read or write `$UO_ROOT/ir/key_shape_resolve/**`

### Mode B — UO staging (understand-operator parent, non-TG)

```text
<UO_ROOT>/ir/key_shape_resolve/<KEY_ID>.yaml
```

- Leaves stay on operator interface / compile-time / `not_input_derivable`
- **Do not** put `VAR_CSV_*` in UO graph staging
- Parent merges into `ir/resolution_patch.yaml` via `apply_resolution.py --check` then apply

Schema (shared fields; TG fills CSV leaves per TG skill):

```yaml
version: 1
key_id: KEY_EXAMPLE
status: resolved | unresolved | needs_human
shape_expr: "<normalized predicate / shape condition>"
shape_determined: [...]
derivation_chain:
  - {id: ..., deps: [...], via: set_by}
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
confidence: high
mcp_checked: [SYM::..., ...]
```

6. Only if a KEY subagent returns `needs_human` / `unresolved` **with** MCP evidence + missing
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

## TestAgent (TG) consumers

When gaps surface on the TestAgent side (`binding_gaps`, abstract `UNBOUND_*`,
`KEY_DERIVATION_MISSING`, `RUNTIME_DOMAIN_NOT_PARTITIONED`, KEY-related
`REALIZE_EMPTY`), follow:

`testcase-agent/skills/tg-init/references/tg-uo-query-escalation.md`

Same rule: parallel **one KEY per subagent**, `uo-query` first, write **OUT_ROOT only**, no bare unsolved.
