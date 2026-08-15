# Test-script repository

**When to load**: `/tg-init` bind, `/tg-solve` targeted construct, or any
precision/perf overlay. Complements `references/harness-oracle.md`.

A test-script repository is optional. It is the operator's existing runner
(scripts + CSV/table), not a second CodeMap and not a Pilot `operators/` tree.

```text
no --test-script-root
  → kind: default_input
  → emit knob defaults from InputSemantics / CodeMap construct

--test-script-root <repo>
  → engine scans entry scripts, argparse, CSV headers
  → writes tg/init/test_repo_inventory.yaml (facts)
  → writes tg/init/test_repo_contract.yaml (how to emit/run)
  → generated rows MUST fill that schema so the repo runner can use them
```

## Agent job (do not skip)

The engine does not understand the runner. You must read the repo:

1. Open the entry script (`run_*.py` / `main.py`) and argparse. Confirm
   `--case` (or equivalent) and which flags mean precision vs performance.
2. Open the case table. Map columns to UO host fields / TilingKey dims.
   Write those maps into `test_repo_contract.yaml` `mapping`.
3. Compare scripts with CodeMap: illegal combos the table allows, missing
   required inputs, columns that invent tensors UO never produces. Record
   them under `findings`. Later CE PRs may patch the test scripts; do not
   silently rewrite the runner during TG init.
4. Fill missing columns with documented defaults, never invented tensors.

## Rules

1. Do not hard-code one operator's columns or runner flags into the engine.
2. Host replay still closes dispatch / key `R`. Precision/perf stay on the
   repo's own modes.
3. Missing repo → default input. Missing runner after a repo was named →
   `harness_missing`, not unreachable.
4. `P-ILLEGAL` rows stay disabled; do not send them to NPU.
