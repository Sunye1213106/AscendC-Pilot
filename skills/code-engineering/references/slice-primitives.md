# Slice Primitives

Use UO's bounded directed primitives:

- `slice_forward(product, seeds, edge_kinds=..., depth=..., budget=...)`
- `slice_backward(product, seeds, edge_kinds=..., depth=..., budget=...)`

Forward slices expose possible downstream impact; backward slices expose
producers, guards, callers, and prerequisites. Always retain the seed set,
direction, edge-kind filter, depth, budget, evidence-tier hints, and
`truncated` flag with the result.

A slice is a Tier B derivation only to the extent that its included graph facts
are Tier A and its parameters are reproducible. A budget/depth boundary cannot
prove non-reachability. Expand selectively or create an open obligation.
