# Compute Execution Model

Separate semantic operation from execution engine.

`semantic_operation` is the mathematical meaning, such as `matmul`, `reduce`, `softmax`, or `cast`.

`execution_engine` is the actual source-level execution unit:

- `cube`
- `vector`
- `scalar`
- `data_movement`
- `conditional`
- `mixed`
- `unknown`

Do not infer the execution engine from the operation name alone.

Evidence priority:

1. Kernel API.
2. Template instantiation.
3. Call relation.
4. Architecture branch.
5. TilingKey branch.
6. dtype/layout/shape branch.
7. Buffer and pipeline structure.

For each operation, record `execution.classification` and `execution.paths[]`. A `cube` classification requires at least one path with `engine: cube`; `vector` requires `engine: vector`; `conditional` requires at least two distinct conditions or engines; `mixed` requires both cube and vector API evidence; `unknown` requires a corresponding unresolved entry.

