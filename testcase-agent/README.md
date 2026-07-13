# Testcase Agent

TestAgent phase 1 and phase 2 implementation for Understand Operator contracts.

Implemented commands:

- `tg-init`: read-only intake from `.understand-operator/<op_name>/`, final validation reuse, full testcase-contract context intake, immutable snapshot.
- `tg-plan`: deterministic level-aware coverage planning from the frozen snapshot.
- `tg-solve`: approved abstract SMT solving that emits semantic candidates and set-cover selection.

Planning levels:

- `L0`: minimal legal smoke for interface, tiling, kernel dispatch, and the simplest execution chain.
- `L1`: reachable runtime variables/branches, main functional paths, dtype/layout, optional inputs, legal boundaries, tail/tail-core/resource boundaries, and expected-reject negative cases.
- `L2`: exhaustive reachable TilingKey coverage from `tiling/exhaustive_key_space.yaml.template_blocks`, with pruning, relations, merging, and per-key input-realization matching.

Example:

```powershell
tg-plan <project_root> --op-name <op_name> --level L1 --focus "TND 场景中 PostNz 分支"
```

Current boundary:

- `tg-solve` only generates abstract candidates.
- It does not generate real shapes, tensors, test CSV, or executable test cases.
- It does not execute operators.
- Phase 3 is not implemented yet.

Not implemented in this repository phase: Input Realizer, runtime adapter, probe, coverage audit, PR incremental mode, and auto repair.
