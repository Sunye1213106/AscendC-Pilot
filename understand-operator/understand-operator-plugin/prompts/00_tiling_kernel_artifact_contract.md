## Canonical KB v2 Layers

The KB is logically split into three layers:

1. Fact layer: source-confirmed files, symbols, functions, classes, structs, fields, macros, enums, constexprs, template parameters, IO, attributes, shapes, dtype/layout, calls, reads/writes, branches, kernel entries, tiling entries, and evidence locations.
2. Semantic relation layer: typed relations such as `derives`, `reads`, `writes`, `controls`, `determines`, `implies`, `requires`, `conflicts_with`, `compatible_with`, `encodes`, `binds`, `dispatches_to`, `enables`, `maps_to`, `affects`, `consumes`, and `produces`.
3. Derived view layer: query, code-change impact, PR review, testcase contract, and documentation views.

Canonical v2 adds these logical folders while keeping the existing canonical files compatible:

```text
registry/
  symbols.yaml
  variables.yaml
  aliases.yaml
  evidence.yaml
kernel/
  compile_model.yaml
  variables.yaml
  branches.yaml
cross_layer/
  input_to_tiling.yaml
  tiling_to_kernel.yaml
  variable_lineage.yaml
  behavior_graph.yaml
  impact_graph.yaml
query/
  routes.yaml
  terminology.yaml
contracts/
  query.yaml
  code_change.yaml
  pr_review.yaml
  testcase.yaml
archive/
  proposals/
  intermediate/
  conflicts/
```

Do not create empty files outside the prepared schema skeleton. When agents discover real facts, write proposal/intermediate artifacts first; only the deterministic KB compiler/host merge may promote them into canonical v2 files.

## Stable ID and Registry Rules

All cross-file joins should prefer stable ids:

- `SYM_*` for source symbols.
- `VAR_*` for input, derived, tiling, kernel, buffer, and sync variables.
- `REL_*` for semantic relations.
- `EV_*` / `SRC_*` for evidence/source spans.
- `COMP_*` / `GOLD_*` for compute and golden semantic steps.
- `KPATH_*`, `KTPL_*`, `KBR_*` for kernel path, template binding, and branch entities.

### Hard format contract (apply before writing, not at final quality gate)

Every value in an `id` or `stable_id` field must be exactly one of:

```text
SYM_|VAR_|REL_|EV_|SRC_|KEY_|FAM_|COMP_|GOLD_|KPATH_|KBR_|KTPL_|CL_|CON_|VIEW_|BUF_|SYNC_|RES_|TDF_|KVAR_|KDEC_|PIPE_|COV_|NUM_
```

followed by uppercase letters, digits, or underscores. Legacy `TF123`, `K123`, `C123`, `D123`, and `P123` are tolerated only when already present in input; do not create them in new material. Never invent shorthand namespaces such as `BFxxx`, `TPxxx`, `KDxxx`, or `SPxxx`: use the mapped canonical namespace (`KBR_*`, `KTPL_*`, `KDEC_*`, `SRC_*`) instead. Every `evidence_refs` value must be a YAML list containing only `EV_*` or `SRC_*` ids. A source path, line span, prose explanation, or a bare `SPxxx` is not an evidence ref.

Before the completion manifest, audit all YAML written in the phase for these fields. The subagent barrier rejects violations immediately; do not defer them to Phase 8.

Handle alias merge, same-name-different-meaning, different-name-same-meaning, dangling references, duplicate definitions, scope conflicts, and type conflicts in `registry/aliases.yaml` and compiler reports. Do not join host/tiling/kernel artifacts by natural-language string equality alone.

## Deterministic KB Compiler

LLM/subagents are responsible for discovery and proposals. Deterministic code is responsible for:

- schema validation
- stable id/reference validation
- type and evidence validation
- alias/duplicate detection
- cross-layer consistency checks
- unresolved/conflict aggregation
- canonical artifact hashes
- quality report inputs

Do not trust `complete: true`, `confidence: high`, `all branches covered`, or `no conflict` unless the compiler and quality gate validate the relevant fields.

# Tiling / Kernel Task Artifact Contract

This is a schema contract, not a workflow phase. It prepares traceability and downstream impact analysis only.

Do not generate tests, do not run tests, do not add coverage, and do not add instrumentation.

## Two-Step Tiling Extraction

Host tiling extraction is modeled as **two ordered steps**, both first-class canonical (queryable by uo-query, consumed by TestGenerate):

- **Step 1 鈥?Variable model** (`variables.yaml`): how tiling is computed, which variables / influencing factors exist, classified by **impact scope**. This is the raw inventory, written to disk before Step 2.
- **Step 2 鈥?Constraint model** (`constraints.yaml`): abstract the code relations of those variables into constraints (**value / range / relation**), plus explicit **tiling_key pruning (鍓灊)** and **merging (鍚堝苟)** analysis, so downstream can build tests.

`key_space.yaml` remains the pure **tiling_key encoding** truth (macro, `fields_order`, key fields). It references Step 1 variables and defers all constraints/pruning/merging/input construction to Step 2 `constraints.yaml`.

`exhaustive_key_space.yaml` is the source-backed full TilingKey enumeration model when the source provides a pruned macro/template file such as `*template_tiling_key*.h`. It stores macro blocks and product counts, not generated tests and not thousands of expanded rows.

## Shared Rules

- Canonical tiling output lives under `tiling/` as **ten** primary files plus optional `tiling/archive/`.
- `variables.yaml` is the **Step 1 variable-model source of truth** (mechanism + variables + impact classification).
- `constraints.yaml` is the **Step 2 constraint-model source of truth** (value/range/relation constraints + tiling_key pruning + merging + input_realization + key-level unreachable).
- `key_space.yaml` is the **tiling_key encoding source of truth** (encoding macro, `fields_order`, key fields only; no constraints/pruning here).
- `exhaustive_key_space.yaml` is the **full TilingKey macro-block enumeration source of truth** when a pruned template enumeration exists; do not list all expanded rows, record source-backed blocks.
- `families.yaml` is the **structural route source of truth**.
- `data_model.yaml` is the **tilingdata source of truth**.
- `coverage_model.yaml` is the **TestGenerate coverage obligation source of truth** (declares what should be covered, not what is already covered).
- `route.md` is the human QA quick entry.
- `index.yaml` is the uo-query / TestGenerate routing entry.
- `evidence_index.yaml` is the evidence traceability entry; do not read by default.
- `families.yaml` does **not** enumerate all tiling_key values.
- `coverage_model.yaml` `seed_cases` are representative seeds only, not full key enumeration.
- Full exhaustive TilingKey coverage is allowed only through `exhaustive_key_space.yaml.template_blocks` expansion, not through `seed_cases`, family count, or blind cartesian over `key_space.fields`.
- Family coverage != tiling_key coverage.
- Branch representative samples != full key enumeration.
- Key relation coverage != field-value coverage: TestGenerate needs typed `constraints.relations`, `constraints.input_realization`, and executable `key_relation_obligations`.
- Key-level `key_unreachable` in `constraints.yaml` is distinct from family-level `unreachable` in `families.yaml`.
- tiling_key **pruning** (鍓灊: impossible/folded combos) and **merging** (鍚堝苟: distinct variable combos sharing one key/family) must be explicitly recorded in `constraints.yaml`, not implied.
- Tiling-side kernel facts are hints unless tiling source explicitly selects kernel entry, kernel type, or template instance.
- Unknown tiling-side kernel facts must not stay unknown after Kernel Path Agents provide direct evidence. Kernel Alignment Builder must backfill only those fields that kernel evidence resolves, preserving the original tiling evidence and recording the kernel evidence used.
- Numeric tiling data variants do not split kernel tasks by themselves.
- Variables like `has_varlen` that share tiling_key but differ in tilingdata numeric behavior belong in `data_model.yaml` / `coverage_model.yaml`, not as fake tiling_key bits.
- Intermediate analysis artifacts live under `tiling/archive/`. **Five archive files are REQUIRED during `/uo-init` host extraction** (anti-laziness). uo-query / TestGenerate still default-read only the ten canonical files; archive is for depth + gate + debug.
- Skipping archive intermediates and jumping straight to thin `key_space` / `families` is a **workflow failure** (barrier + quality gate).

## Canonical Tiling Folder

```text
tiling/
鈹溾攢鈹€ route.md
鈹溾攢鈹€ index.yaml
鈹溾攢鈹€ variables.yaml                   # STEP 1: mechanism + variables + impact classification
鈹溾攢鈹€ key_space.yaml                   # tiling_key encoding truth (fields only)
鈹溾攢鈹€ exhaustive_key_space.yaml        # source-backed pruned macro blocks for full key enumeration
鈹溾攢鈹€ constraints.yaml                 # STEP 2: constraints + pruning + merging + input_realization
鈹溾攢鈹€ families.yaml
鈹溾攢鈹€ data_model.yaml
鈹溾攢鈹€ coverage_model.yaml
鈹溾攢鈹€ evidence_index.yaml
鈹斺攢鈹€ archive/                         # REQUIRED intermediates (not optional for init)
    鈹溾攢鈹€ frontier.yaml                # decision sites (guard/key/writer/template)
    鈹溾攢鈹€ dispatch_variables.yaml      # raw variable capture before variables.yaml merge
    鈹溾攢鈹€ predicate_space.yaml         # normalized predicates + relations (feeds constraints)
    鈹溾攢鈹€ compile_time_bindings.yaml   # macros / constexpr / templates / if constexpr
    鈹溾攢鈹€ decision_tree.md             # human decision tree (compile vs runtime)
    鈹斺攢鈹€ kernel_evidence_backfill.yaml  # written later by alignment
```

Step mapping: `archive/frontier.yaml` + `archive/dispatch_variables.yaml` -> **Step 1** `variables.yaml`; `archive/predicate_space.yaml` + `archive/compile_time_bindings.yaml` -> **Step 2** `constraints.yaml`; `archive/compile_time_bindings.yaml` + direct macro block parsing -> `exhaustive_key_space.yaml`.

## REQUIRED Intermediate Archive (anti-laziness)

Host extraction **must write non-placeholder** content to all five files before claiming Phase 2 complete. Merge into canonical files only after these exist.

| File | Must capture | Merge target |
|---|---|---|
| `archive/frontier.yaml` | Every tiling decision site: guard, key setter, tilingdata writer, compile-time binding, optional IO gate, kernel hint, template instantiation | `evidence_index` + family/key sources |
| `archive/dispatch_variables.yaml` | Every dispatch / shape / dtype / deter / performance variable with `kind` + `domain_source` | **Step 1** `variables.yaml` + `key_space.fields` / `constants` / `derived_fields` + `data_model` |
| `archive/predicate_space.yaml` | Stable predicate atoms + mutex/implies/compile_time relations | **Step 2** `constraints.relations` + `families.guard` |
| `archive/compile_time_bindings.yaml` | Macros, `constexpr`, template instantiations, each `if constexpr` reachability (`taken` / `not_taken` / `unknown`) | `key_space.constants`, `families.reachability`, `constraints.relations` type `compile_time_fixed`, `constraints.tiling_key_pruning` |
| `archive/decision_tree.md` | Ordered decision tree; compile-time vs runtime nodes; leaves 鈫?`family_id` | human QA + `families.dispatch_tree` |

### Minimum bar (empty = fail)

- `frontier_nodes` non-empty when a tiling entry exists.
- `dispatch_variables.variables` non-empty when hard_dispatch / deter / dtype switches exist in source.
- `compile_time_bindings`: if source has `#define` / `enum` / `constexpr` / templates affecting branches, corresponding lists must be non-empty **or** `unresolved_symbols` + `blocking_questions` must list them (never silent empty).
- `decision_tree.md` must not still say `(unknown 鈥?host extraction must replace this skeleton)`.
- DeterType / arch / dtype compile-time axes must appear in `compile_time_bindings` **and** either split families or be proven foldable with `not_taken` proof 鈥?do not collapse into one shallow 鈥渄eterministic fusion鈥?family without archive evidence.

### Schema sketches

```yaml
# tiling/archive/frontier.yaml
version: 1
status: analyzed
frontier_nodes:
  - id: SYM_FRONTIER_EXAMPLE
    role: key_setter | guard | tilingdata_writer | compile_time_binding | optional_io_gate | kernel_hint | template_inst | other
    symbol: ""
    file: ""
    lines: []
    affects: [key, family, tilingdata, template, kernel_hint]
    evidence_refs: []
unresolved_frontier: []
```

```yaml
# tiling/archive/dispatch_variables.yaml
version: 1
status: analyzed
variables:
  - name: ""
    kind: hard_dispatch | optional_io_gate | performance_knob | derived | constant | tiling_data_value | unknown
    domain: []
    domain_source: enum_macro | constexpr | runtime_branch | derived | unknown
    enters_tiling_key: true | false
    maps_to_key_space: ""
    source: {file: "", lines: [], symbol: ""}
unknown_variables: []
```

```yaml
# tiling/archive/predicate_space.yaml
version: 1
status: analyzed
predicate_atoms:
  - id: CON_PREDICATE_EXAMPLE
    expr: ""
    kind: runtime_guard | compile_time | optional_io | dtype_layout | shape | deter | other
    source: {file: "", lines: [], symbol: ""}
predicate_relations:
  - id: REL_PREDICATE_EXAMPLE
    type: mutex | implies | requires | compatible_set | compile_time_fixed | runtime_guard | other
    atoms: []
    expr: ""
    case_impact: exclude | force_combo | narrow_domain
    maps_to_legal_constraint: CON_LEGAL_EXAMPLE
```

```yaml
# tiling/archive/compile_time_bindings.yaml
version: 1
status: analyzed
macros: []          # name / value / kind / affects_branches / source
constexpr_constants: []
templates:
  instantiations: []  # template_name / args / call_site / specialization / maps_to_families
if_constexpr_sites: []  # condition / reachability / proof_kind / folds_to_family / source
unresolved_symbols: []
blocking_questions: []
```

`decision_tree.md` must label each node compile-time vs runtime and map leaves to `FAM_*`.

## 1. route.md Schema

Human-readable tiling route (100鈥?00 lines). Must include:

- scope
- tiling entry
- top-level dispatch
- registry dispatch order
- family overview table
- varlen / swizzle / deter and other high-risk notes
- explicit note: family coverage != tiling_key coverage
- explicit note: branch representative samples != full key enumeration
- step 1 summary: variable count + impact_classification breakdown (how many affect key / template / family / tilingdata / core_split / buffer 鈥?
- step 2 summary: constraint/relation counts by type, input_realization coverage, key-level vs family-level unreachable, and whether tiling_key **pruning** / **merging** were performed
- pointers to machine files: `index.yaml`, `variables.yaml`, `key_space.yaml`, `constraints.yaml`, `families.yaml`, `data_model.yaml`, `coverage_model.yaml`, `evidence_index.yaml`
- when exhaustive TilingKey coverage is possible, pointer to `exhaustive_key_space.yaml` and its `summary.expanded_key_count`

## 2. index.yaml Schema

Machine routing entry for uo-query and TestGenerate.

```yaml
version: 1
op_name: ""
scope:
  arch: ""
  path_group: ""
  excluded: []

canonical_files:
  route: route.md
  variables: variables.yaml
  key_space: key_space.yaml
  exhaustive_key_space: exhaustive_key_space.yaml
  constraints: constraints.yaml
  families: families.yaml
  data_model: data_model.yaml
  coverage_model: coverage_model.yaml
  evidence: evidence_index.yaml

qa_routes:
  overview:
    read: [route.md]
  entry_or_dispatch:
    read: [route.md, families.yaml]
  tiling_mechanism:
    read: [variables.yaml, route.md]
  tiling_variables:
    read: [variables.yaml]
  tiling_key:
    read: [key_space.yaml, families.yaml]
  tiling_key_exhaustive:
    read: [exhaustive_key_space.yaml, key_space.yaml, constraints.yaml]
  key_constraints_relations:
    read: [constraints.yaml, key_space.yaml]
  tiling_key_pruning_merging:
    read: [constraints.yaml, key_space.yaml, families.yaml]
  input_realization:
    read: [constraints.yaml, key_space.yaml]
  optional_input:
    read: [variables.yaml, key_space.yaml, data_model.yaml]
  dtype_layout_shape:
    read: [key_space.yaml, families.yaml]
  tilingdata:
    read: [data_model.yaml, families.yaml]
  coverage:
    read: [coverage_model.yaml, constraints.yaml, key_space.yaml, families.yaml]
  evidence:
    read: [evidence_index.yaml]

testgenerate_contract:
  required_files:
    - variables.yaml
    - key_space.yaml
    - exhaustive_key_space.yaml
    - constraints.yaml
    - families.yaml
    - data_model.yaml
    - coverage_model.yaml
  rules:
    - "Do not treat family coverage as full tiling_key coverage."
    - "Do not treat seed_cases as full enumeration."
    - "Use variables.yaml for the variable inventory and impact classification."
    - "Use key_space.yaml as tiling_key encoding truth."
    - "Use exhaustive_key_space.yaml for source-backed full TilingKey macro-block enumeration."
    - "Do not blind-cartesian fields; apply constraints.relations + constraints.key_unreachable first."
    - "For exhaustive TilingKey coverage, expand exhaustive_key_space.template_blocks, then solve inputs using reverse_realization_index."
    - "Honor constraints.tiling_key_pruning (do not generate pruned combos) and tiling_key_merging (treat merged combos as one key, differ only in overlay)."
    - "Use constraints.input_realization to construct inputs for key patterns."
    - "Treat derived_fields / independent:false as computed, not free dimensions."
    - "Use key_relation_obligations.must_cover for relation witnesses, not full key enum."
    - "Use data_model.yaml for varlen and numeric tilingdata coverage."
    - "Use families.yaml for reachability and structural family coverage."
```

## 3. variables.yaml Schema (STEP 1 鈥?variable model)

Source of truth for **how tiling is computed** and **which variables / influencing factors** exist, classified by **impact scope**. Written before Step 2. Merges/promotes `archive/frontier.yaml` + `archive/dispatch_variables.yaml`.

```yaml
version: 1
op_name: ""
scope: ""

tiling_mechanism:
  entry: {file: "", symbol: "", lines: []}
  key_setter: {macro: "", file: "", symbol: "", lines: []}   # GET_TPL_TILING_KEY or equiv
  produces: []          # subset of [tiling_key, tilingdata, blockdim, workspace, sync]
  flow_summary: ""      # 3-6 lines: how host decides split / key / data
  registry_dispatch: [] # ordered dispatch entry points, if any

variables: {}
# VAR_EXAMPLE:
#   name: ""
#   meaning: ""
#   raw_domain: [] | {min, max} | expression   # observed/declared domain before constraints
#   domain_source: enum_macro | constexpr | runtime_branch | derived | input_shape | attr | unknown
#   kind: hard_dispatch | optional_io_gate | performance_knob | derived | constant | tiling_data_value | unknown
#   impact_scope: []    # 1+ from the impact_classification enum below
#   influences: []      # [tiling_key, template, family, tilingdata, blockdim, workspace, buffer, none]
#   enters_tiling_key: true | false
#   maps_to: {key_field: "", constant: "", data_model: ""}  # cross-ref to key_space / data_model
#   source: {file: "", lines: [], symbol: ""}
#   evidence_refs: []

impact_classification:
  tiling_key: []            # variable ids that change tiling_key / dispatch
  template_compile_time: [] # affect template specialization / if constexpr
  family_structural: []     # change structural route / family
  tilingdata_numeric: []    # only numeric tilingdata values
  core_split: []            # blockDim / multi-core split
  buffer_workspace: []      # UB / L1 / workspace / buffer_num
  optional_io_gate: []      # optional input/output presence
  derived: []               # computed from other variables
  constant: []              # compile-time constants
  unknown: []               # evidence insufficient

unresolved_variables: []
# - {name, why_unknown, blocking_questions, evidence_refs}   # never silently empty when gaps exist
```

Rules:

- Every influencing factor discovered in the key setter / guards / tilingdata writers / compile-time bindings must appear as a `VAR_*` with at least one `impact_scope`.
- `impact_classification` is a fast index; every variable id must appear in exactly the scopes listed in its own `impact_scope`.
- Do not resolve constraints here 鈥?Step 1 records domains and classification only; relations belong to `constraints.yaml`.
- Unknown / unresolved variables must be listed in `unresolved_variables`, not dropped.

## 4. key_space.yaml Schema

Tiling_key **encoding** source of truth (encoding macro, `fields_order`, key fields). No constraints / pruning / input construction here 鈥?those live in `constraints.yaml`.

```yaml
version: 1
op_name: ""
scope: ""

encoding:
  macro: ""
  source:
    file: ""
    lines: []
  fields_order: []

fields: {}
# Each key field (required keys when field exists):
#   domain: [] | {min, max} | expression
#   domain_source: enum_macro | constexpr | runtime_branch | derived | unknown
#   independent: true | false   # false => do not cartesian-product in TestGenerate
#   affects: [key, struct, tilingdata, kernel_template]
#   kind: hard_dispatch | optional_io_gate | performance_knob | constant | derived
#   set_when: ""                # host predicate / guard that selects this field value
#   variable_ref: VAR_*         # back-ref to variables.yaml
#   source: {file, lines, symbol}

constants: {}
# name: {value, affects: [], source: {file, lines, symbol}}

derived_fields: {}
# Each derived field (required):
#   from: []                    # parent field names
#   rule: ""                    # executable-ish: e.g. "hasMask = (mask != nullptr)"
#   rule_kind: bool_expr | enum_map | arithmetic | host_helper | unknown
#   enters_key_bit: true | false
#   affects: [key, struct, tilingdata]
#   variable_ref: VAR_*
#   source: {file, lines, symbol}
```

Rules:

- Extract from `GET_TPL_TILING_KEY` or equivalent key setter.
- Optional inputs affecting key (mask, pse, dropout, rope) must appear in `fields` or `derived_fields`, each with a `variable_ref`.
- Do not use `branch_matrix` or family count as full tiling_key enumeration.
- Constraints, pruning, merging, and input construction are **not** in this file 鈥?see `constraints.yaml`.

## 5. constraints.yaml Schema (STEP 2 鈥?constraint model)

Abstracts variable relations from code into constraints (**value / range / relation**) for testing, and records tiling_key **pruning (鍓灊)** and **merging (鍚堝苟)**. Merges/promotes `archive/predicate_space.yaml` + `archive/compile_time_bindings.yaml`.

Empty `relations` / `input_realization` is a quality failure when hard_dispatch fields exist.

```yaml
version: 1
op_name: ""
scope: ""

variable_constraints: []
# Per-variable value/range refinement. Each item:
#   id: CON_VARIABLE_EXAMPLE
#   variable: VAR_*             # -> variables.yaml (or key field name)
#   legal_values: [] | {min, max} | expression
#   boundary_values: []         # values TestGenerate should hit for boundary coverage
#   independent: true | false   # false => bound by a relation, not a free dimension
#   reason: ""
#   evidence_refs: []

relations: []
# Typed cross-variable relations. Each item:
#   id: REL_CONSTRAINT_EXAMPLE
#   type: mutex | implies | requires | compatible_set | compile_time_fixed | runtime_guard | other
#   variables: []               # variable ids / key field names involved
#   expr: ""                    # machine-oriented: "A=x => B in {y,z}" / "not (A=x and B=y)"
#   when: ""                    # optional scope / family / template context
#   reason: ""
#   case_impact: exclude | force_combo | narrow_domain
#   evidence_refs: []

tiling_key_pruning:                # 鍓灊: combos the code makes impossible / folds away
  performed: true | false | unknown
  pruned_combinations: []
  # - id: CON_PRUNING_EXAMPLE
  #   pattern: {}                  # field->value combo that never occurs
  #   reason: ""
  #   proof_kind: compile_time_fold | runtime_guard | encoding_gap | domain_constraint | evidence_gap
  #   evidence_refs: []
  notes: ""

tiling_key_merging:                # 鍚堝苟: distinct variable combos sharing one key / family
  performed: true | false | unknown
  merged_groups: []
  # - id: CON_MERGING_EXAMPLE
  #   merged_into: ""              # resulting key pattern or FAM_*
  #   source_combinations: []      # distinct variable combos that collapse together
  #   reason: ""                   # equivalent dispatch / numeric-only diff / ...
  #   differs_in: []               # e.g. tilingdata numeric fields (overlay), if any
  #   evidence_refs: []
  notes: ""

input_realization: {}
# Pattern id -> how TestGenerate should construct inputs for a key / field pattern.
# Required for every hard_dispatch field value in a reachable family key_pattern,
# and for every key_relation_obligation.must_cover combination.
#   CON_INPUT_REALIZATION_EXAMPLE:
#     matches: {key_pattern: {}, family_refs: []}
#     inputs: {required: [], optional_present: [], optional_absent: []}
#     shape_intent: ""            # e.g. "TND with S>1", not a full case
#     dtype_layout_intent: ""
#     feature_flags: {}
#     notes: ""
#     evidence_refs: []

key_unreachable: []
# Key-level unreachable only (not family-level). Each item:
#   id: CON_KEY_UNREACHABLE_EXAMPLE
#   level: key
#   constraint: ""                # field pattern that cannot occur
#   reason: ""
#   proof_kind: compile_time_fold | runtime_guard | encoding_gap | evidence_gap
#   evidence_refs: []
```

Rules:

- **TestGenerate must not blind-cartesian key fields.** Apply `relations` + `key_unreachable` + `tiling_key_pruning` first; use `input_realization` to build inputs; treat `derived_fields` / `independent: false` as computed.
- Every `relations[].type` must be one of the allowed enum values.
- `tiling_key_pruning.performed` and `tiling_key_merging.performed` must be answered (`true`/`false`/`unknown` with `notes`), never omitted 鈥?this is the explicit 鍓灊/鍚堝苟 record the KB must carry.
- `key_unreachable` is **key-level** only; family-level unreachable belongs in `families.yaml`.
- If evidence is insufficient, write an explicit stub with `reason: evidence_gap` and raise it in `coverage_model` obligations 鈥?do not silently leave lists empty when hard_dispatch fields exist.
- Minimum bar when `key_space.fields` has any `kind: hard_dispatch`:
  - at least one `relations` entry **or** all such fields marked `independent: true` in `variable_constraints` with an explicit independence relation; and
  - non-empty `input_realization` covering each reachable family `key_pattern`; and
  - `tiling_key_pruning.performed` and `tiling_key_merging.performed` explicitly set.

## 6. families.yaml Schema

Structural route source of truth. Merges legacy `tiling_branch_families.yaml`, `tiling_route.yaml`, `tiling_decision_tree.md`.

```yaml
version: 1
op_name: ""
scope: ""

dispatch_tree:
  entry: ""
  top_level: []
  # nodes: {id, guard, children, family_id, compile_time, runtime, unreachable_reason}

families:
  TF001:
    name: ""
    reachability: reachable | reachable_narrow | runtime_conditional | unreachable | excluded | unknown
    unreachable_reason: ""
    struct_signature: ""
    guard: {}
    key_pattern: {}
    variable_key_fields: []
    route_action: normal_kernel_task | needs_alignment | excluded | needs_review
    coverage_role:
      structural: true
      key_witness: false
    has_dedicated_key_bit: true | false
    data_behavior: ""
    needs_alignment: false
    varlen_overlay: false
    kernel_entry_hint:
      status: known | unknown | conflicting
      possible_entries: []
      reason: ""
    risks: []
    evidence_refs: []
```

Rules:

- Do not enumerate all tiling_key values here.
- Preserve unreachable families (e.g. TF008) with `unreachable_reason`.
- Varlen paths sharing tiling_key: `has_dedicated_key_bit: false`, document `data_behavior`.

## 7. data_model.yaml Schema

Tilingdata source of truth. Merges legacy `tiling_data_signature.yaml`, `tiling_data_map.yaml`.

```yaml
version: 1
op_name: ""
scope: ""

structs:
  EmptyTensor: {}
  RegbaseTemplate: {}
  # Each struct block:
  #   role: ""
  #   fields: ["fieldName", "dqIsNeedDeter[36]"]   # quote names with []
  #   coverage_points: []
  #   present_when: ""
  #   used_by: []

family_to_struct: {}

numeric_overlay: {}
# e.g. has_varlen:
#   shared_key_with: TF001
#   differs_in: [TndParam, TndSwizzleParam]
#   coverage_points: []
```

RegbaseTemplate blocks (minimum):

- always: BaseParams, SplitCoreParams, BlockNumList, PreParams, PostParams
- conditional: BaseDeterParam, DeterParam, TndParam, TndSwizzleParam

YAML readability: field names containing `[]` must be quoted strings in lists.

## 8. coverage_model.yaml Schema

TestGenerate coverage obligations only. Does **not** claim cases are generated or covered.

```yaml
version: 1
op_name: ""
scope: ""

coverage_policy:
  family_coverage: required
  key_field_value_coverage: required
  exhaustive_key_space_coverage: optional
  key_relation_coverage: required
  tilingdata_coverage: required
  unreachable_proof: required
  observed_key_audit: required
  input_realization_coverage: required

family_obligations: []
# - {family_id, reachability, reason, evidence_refs}

key_field_obligations: {}
# field_name:
#   values: []
#   min_cases: 0
#   independent: true | false
#   notes: ""

key_relation_obligations: []
# Each obligation (required keys):
#   id: COV_RELATION_EXAMPLE
#   name: ""
#   relation_type: pairwise | implies | mutex | boundary | risk | compatible_set
#   fields: []
#   must_cover: []              # list of combo maps or expr strings TestGenerate must hit
#   linked_relations: []        # REL_* ids from constraints.yaml
#   linked_input_realization: []  # CON_* ids from constraints.yaml
#   min_cases: 1
#   reason: ""
#   evidence_refs: []

exhaustive_key_obligations:
  source: exhaustive_key_space.yaml
  mode: macro_block_cartesian
  required_when_requested: true
  notes: "For full TilingKey enumeration, expand template_blocks; do not infer the universe from families or seed_cases."

tilingdata_obligations: []
# - {block, fields, boundary_values, families, reason}

seed_cases: []
# - {id, role: representative | boundary | risk | manual_keep, family_id, key_snapshot, reason}
# MUST NOT be treated as full enumeration

audit_requirements:
  expected_key_required: true
  observed_key_required: true
  mismatch_is_failure: true
  report_missing_field_values: true
  report_missing_relations: true
  report_missing_input_realization: true
  report_illegal_cartesian_without_constraints: true
```

Rules:

- `key_relation_obligations` must be executable for TestGenerate: prefer `must_cover` + `linked_relations` over free-text `reason` alone.
- When `constraints.relations` is non-empty, each relation that affects reachable keys should appear in `linked_relations` of at least one relation obligation **or** be reflected in `constraints.tiling_key_pruning` with a proof.
- Do not duplicate full key enumeration into `must_cover`; list relation witnesses / critical combos only.
- `seed_cases` remain representative; relation coverage is owned by `key_relation_obligations`, not seed count.

## 8b. exhaustive_key_space.yaml Schema

Source-backed full TilingKey enumeration model. Use this when source contains a pruning/template enumeration file, for example `op_kernel/**/flash_attention_score_grad_template_tiling_key.h`.

```yaml
version: 1
op_name: ""
scope: ""
status: analyzed

enumeration_source:
  status: analyzed
  files: []
  block_macro: ASCENDC_TPL_ARGS_SEL
  domain_macros: [ASCENDC_TPL_BOOL_SEL, ASCENDC_TPL_UINT_SEL]
  terminator_macro: ASCENDC_TPL_TILING_STRUCT_SEL
  evidence_refs: []

summary:
  block_count: 0
  expanded_key_count: 0
  by_dtype: {}
  by_source_file: {}

field_order: []

template_blocks:
  - id: KTPL_TILING_KEY_BLOCK_001
    source: {file: "", lines: [], evidence_refs: []}
    dtype_section: ""
    fixed_fields: {}
    field_domains: {}
    derived_requirements: {}
    reverse_input_hints: []
    tiling_struct: ""
    product_count: 0
    family_refs: []
    kernel_path_refs: []
    pruning_refs: []

reverse_realization_index:
  SplitAxis:
    rule: ""
    requires_shape: []
    requires_dtype: []
    requires_attrs: []
    input_realization_refs: []
    evidence_refs: []

exhaustive_coverage_contract:
  mode: macro_block_cartesian
  total_expected_keys: 0
  testgenerate_strategy:
    - "expand template_blocks.field_domains"
    - "merge fixed_fields into every expanded row"
    - "reject rows listed by constraints.key_unreachable or pruning_refs"
    - "solve concrete inputs through reverse_realization_index and constraints.input_realization"
    - "audit observed tiling_key against expected expanded row"
  audit:
    expected_key_required: true
    observed_key_required: true
    mismatch_is_failure: true
    missing_reverse_realization_is_failure: true
```

Rules:

- `summary.expanded_key_count` must equal the sum of `template_blocks[].product_count`.
- `template_blocks` are the pruned source truth; do not recompute the universe by blindly cartesianing `key_space.fields`.
- Do not dump all expanded key rows into the KB by default. TestGenerate expands blocks on demand.
- Fields that are hard to realize from inputs, such as `SplitAxis`, `S1TemplateNum`, `S2TemplateNum`, `DTemplateNum`, `IsNzOut`, `IsTndSwizzle`, `IsBn2MultiBlk`, `IsDNoEqual`, and `DeterType`, need entries in `reverse_realization_index`.

## 9. evidence_index.yaml Schema

Evidence traceability index. Default: do not expand unless needed.

```yaml
version: 1
op_name: ""

symbols:
  SymbolName:
    file: ""
    lines: []
    role: ""

evidence_policy:
  default_read: false
  use_when:
    - "user asks for source evidence"
    - "user asks exact source line"
    - "quality gate detects conflict"
    - "TestGenerate requires traceability report"
```

## Kernel Path Skeleton Schema锛坈anonical锛?
Kernel path planning writes `kernel/paths.yaml` (not legacy `kernel/kernel_task_plan.yaml`).

Each `kernel_paths.Kxxx` item must include:

```yaml
K001:
  stable_key: ""
  name: ""
  source_family: TF001
  reachability: reachable | runtime_conditional | unreachable | excluded | unknown
  route_action: normal_kernel_task | needs_review | excluded
  entry:
    file: ""
    symbol: ""
    class: ""
    function: ""
  template_context:
    templates: []
    compile_time_bindings: []
    unresolved_symbols: []
  tiling:
    family_ref: TF001
    key_pattern_ref: ""
    data_model_ref: ""
  compute_scope:
    required_steps: []
    skipped_steps: []
  pipeline_ref: ""
  resource_refs: []
  representative_cases: []
  risks: []
  evidence_refs: []
  confidence: high | medium | low
  source_locator:
    primary: null
    reason: "pending kernel path analysis"
```

Top-level companion fields in `kernel/paths.yaml`:

```yaml
version: 1
status: analyzed
kernel_paths: {}
excluded_families: []
needs_review: []
task_generation_summary:
  source_family_count: 0
  normal_task_count: 0
  needs_review_count: 0
  excluded_count: 0
  merge_count: 0
  split_count: 0
```

Rules:

- Do not split kernel paths by tiling_key enumeration or numeric tilingdata variants.
- Default one structural family 鈫?one kernel path.
- Kernel task builder reads `tiling/families.yaml`, `tiling/key_space.yaml`, and `tiling/constraints.yaml` (not family count as key coverage).
- Legacy `kernel/kernel_task_plan.yaml` may exist only under `archive/legacy/`.

## Dispatch Review Fields

Retired kernel dispatch review artifacts must include:

```yaml
dispatchable_task_ids: []
non_dispatchable_task_ids: []
needs_review_task_ids: []
approved_task_ids: []
```

For `decision: dispatch_all`, `approved_task_ids` must equal `dispatchable_task_ids`.

## Kernel Evidence Backfill Schema

`tiling/archive/kernel_evidence_backfill.yaml` (or legacy path if migrating) records facts learned from kernel path analysis.

The builder may update existing `tiling/*.yaml` canonical artifacts only when all of these are true:

- the target field is currently `unknown`, empty, hint-only, or listed under unresolved/blocking/downstream questions;
- at least one approved `kernel/paths/Kxxx_kernel_path.yaml` contains direct evidence for the replacement;
- the replacement does not contradict host/tiling source evidence.

Do not overwrite tiling-source facts with kernel guesses. If kernel evidence conflicts with host evidence, leave the original field unchanged and write the conflict under `conflicts`.

```yaml
version: 1
status: pending | applied | partial | skipped
backfills:
  - target_artifact: tiling/families.yaml
    target_selector: "families[family_id=TF001].kernel_entry_hint"
    previous_value: unknown
    new_value: {}
    source_kernel_paths: [K001]
    evidence: []
    applied: true | false
    reason: ""
conflicts: []
unresolved_after_backfill: []
```

