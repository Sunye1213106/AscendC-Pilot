# Risk Classes

Classify each impacted anchor by observable failure mode, not file name.

- **API/contract:** signature, shape, dtype, optionality, or compatibility.
- **Control/selection:** predicate, TilingKey, template, architecture, or branch.
- **Data/layout:** TilingData field, size, offset, alignment, or serialization.
- **Kernel/memory:** bounds, address space, copy extent, buffer, queue, or register.
- **Synchronization:** explicit event/pipe/queue facts or ordering assumptions.
- **Build/variant:** macro, include closure, specialization, or architecture.
- **Quality:** correctness evidence, regression coverage, precision, or performance.

Severity and likelihood must cite evidence separately. Synchronization facts do
not imply pairing or happens-before. Precision and performance risks require
external measurements before they can be verified.
