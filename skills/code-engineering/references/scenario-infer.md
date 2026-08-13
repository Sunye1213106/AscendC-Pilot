# Infer scenarios from code or a diff

**When to load**: building or reviewing a `ce-scenario-set/v1` after a
static scan or an impact slice.

## Two entries

| Entry | Source | What to scan |
| --- | --- | --- |
| `static` | no diff; operator as-is | `kernel_api` Cast/DataCopy/DataCopyPad/EnQue/DeQue, `buffer`, split-field writers |
| `diff` | change capture | anchors in the slice, including OPERATION / BUFFER / BRANCH / KERNEL |

A truncated slice or stale UO is a disclosed boundary, never “no precision
or perf impact”.

## Deterministic mapping (Agent must not invent ids)

Use the engine table (same ids as `references/scenario-catalog.md`):

| Anchor kind / callee | scenario_id |
| --- | --- |
| OPERATION `Cast` | `P-CAST`, `P-DTYPE` |
| OPERATION `DataCopy` / `DataCopyPad` | `P-COPY-ALIGN` |
| OPERATION `EnQue` / `DeQue` | `P-QUEUE` |
| INPUT / OUTPUT dtype, key dim InputDType | `P-DTYPE` |
| optional INPUT (mask, pse, dropout, rope) | `P-OPTIONAL` |
| BRANCH tail / empty / remainder | `P-TAIL` |
| reduction / online-softmax accumulate | `P-REDUCE-LONG` |
| illegal combo (source guard or distilled matrix) | `P-ILLEGAL` |
| TILING_FIELD split writer / rhs | `F-SPLIT`, `F-SHAPE-TYPICAL` |
| BUFFER / QUEUE / `InitBuffer` | `F-BUFFER`, `F-SHAPE-TYPICAL` |
| usedCoreNum / multi-core predicate | `F-BALANCE` |
| compute dtype path (perf) | `F-DTYPE` |

Engine writes the skeleton. Agent fills knobs via `ce-scenario-knobs` staging
(`ce-scenario-knobs/v1`); Host `scenario_apply` merges into `scenario_set.yaml`
before confirm. Agent may not add unknown `scenario_id` values or close
precision/perf into `V` with a review narrative.

## Output shape

Each item: `id`, `risk_class`, `anchors[]` (`id/kind/file/line/callee`),
`knobs`, `budget`, `oracle`, `origin` (`inferred` | `user`).
`retrieve_from` is corpus (engine), not a skill playbook.
