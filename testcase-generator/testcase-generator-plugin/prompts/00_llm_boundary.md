# LLM Boundary

## Python must do

YAML parse, schema validation, factor extraction, rule compile, candidate generation (L0/L1/L2), constraint pruning, pairwise (L1), set cover, probe case generation, tiling_key decode, coverage audit, percentage stats.

## LLM may do

- Coverage plan natural language explanation
- Missing rule patch suggestions -> `review/`
- Missing input realization suggestions -> `review/realization_patch_suggestion.yaml`
- Multi-round probe failure diagnosis (suggestion only)
- Final report narrative (after Python audit)
- Explain ST↔TG level mapping to users

## LLM must NOT

- Compute coverage percentages
- Decide observed_tiling_key coverage
- Substitute probe
- Modify `coverage_audit.yaml`
- Treat expected_key as observed_key
- Relabel pairwise as L2
- Invent factor domains when KB marks unknown
