# lemma_loop

Domain: `skills/domain/tg-closure/SKILL.md`

Inputs: residual analysis (`open_patterns`, `r_witness_values`) + optional proved
candidates from `lemma_mine` parts / review.
Output: `tg/closure/lemma_loop.yaml` and per-round `tg/closure/rounds/round_N/lemma.yaml`.
Deterministic orchestration — does not invent source citations.

## What it does

One call runs up to `max_rounds` (default 8) of:

1. `residual.analyse` → open patterns + R witness values
2. `hypothesis.propose` → minimised, R-consistent antecedents
3. `lemma_verify` against the R ledger
4. If proved candidates exist → `lemma_apply` (still gated by provenance + R)
5. Else → stage survivors for a producer and stop with `NEED_PRODUCER`

Stops early on `GAP_ZERO`, `GAP_STALLED`, `PROVENANCE_REQUIRED`, or
`NEED_PRODUCER`.

## Placement

Optional acceleration of the lemma phase. Agents that previously wrote one-shot
`artifacts/*/lemma_*_apply.py` scripts should call this instead and read
`stop_reason`.
