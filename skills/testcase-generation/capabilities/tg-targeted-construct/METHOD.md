# TG Targeted Construct Method

Solve overlay `scenario_targeted`. Do not freeze or enlarge `T`.

1. Read approved ScenarioSet items (`T` is those ids, not all of `D`).
2. For each item, retrieve corpus rows with the same scenario / nearby knobs.
3. Mutate 1–3 knobs on the producer cone from CodeMap packing / writers.
4. Repair with InputSemantics; drop illegal combos (`P-ILLEGAL`).
5. Emit rows that fill the test-repo schema, or default input if none.
   Run the repo's precision or perf flags. See `references/test-script-repo.md`.
6. Optionally Host-replay if dispatch evidence is also required.
7. Write construct trace (scenario id, corpus hits, knobs, csv path).

Forbidden: cartesian over `D`; treating Host HIT as precision/perf `V`;
sending Disable/illegal rows to NPU.
