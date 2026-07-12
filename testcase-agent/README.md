# Testcase Agent

TestAgent phase 1 and phase 2 implementation for Understand Operator contracts.

Implemented commands:

- `tg-init`: read-only intake from `.understand-operator/<op_name>/`, final validation reuse, full testcase-contract context intake, immutable snapshot.
- `tg-plan`: deterministic atomic coverage-obligation planning from the frozen snapshot.
- `tg-solve`: approved abstract SMT solving that emits semantic candidates and set-cover selection.

Current boundary:

- `tg-solve` only generates abstract candidates.
- It does not generate real shapes, tensors, test CSV, or executable test cases.
- It does not execute operators.
- Phase 3 is not implemented yet.

Not implemented in this repository phase: Input Realizer, runtime adapter, probe, coverage audit, PR incremental mode, and auto repair.
