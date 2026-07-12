# Testcase Agent

Phase 1 TestAgent implementation for Understand Operator contracts.

Implemented commands:

- `tg-init`: read-only intake from `.understand-operator/<op_name>/`, final validation reuse, testcase-contract export, immutable snapshot.
- `tg-plan`: deterministic coverage-obligation planning from the frozen snapshot.

This phase intentionally does not implement SMT solving, real shape generation, tensor data generation, CSV generation, operator execution, Probe, Coverage Audit, PR mode, or auto repair.
