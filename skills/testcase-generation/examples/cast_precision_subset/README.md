# Cast precision subset

## Source

Distilled from cannbot precision decision tree (Cast path). Not a full legal-key matrix.

## Given

Kernel slice contains `Cast` (OPERATION callee) on a compute path that also carries InputDType.

## Task (TG)

Retrieve at most four corpus rows for `P-CAST` / `P-DTYPE`. Mutate only dtype or one boundary shape. Oracle is golden compare (`only_grad`), not Host TilingKey hit.

## Correct outcome

- Scenario ids: `P-CAST`, `P-DTYPE` only.
- CSV row count ≤ 4 per scenario, ≤ 10 total.
- No cartesian over all legal keys.

## Why correct

A Cast-only diff does not justify `F-SPLIT` or full `tilingkey_full_coverage`.
