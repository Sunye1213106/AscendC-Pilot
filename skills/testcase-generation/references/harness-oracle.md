# Harness oracle vs Host replay

**When to load**: deciding whether a run may grow R or may enter CE `V`
for precision/perf.

The operator's test-script repo (optional `--test-script-root`) owns the
precision/perf runner. Engine scan only records flags; the agent reads the
scripts to learn which argv is precision vs performance. See
`references/test-script-repo.md`.

| Mode | What it observes | May close |
| --- | --- | --- |
| Host replay | actual TilingKey, reject/crash | dispatch / key `R` |
| repo precision flags | golden vs device (atol/rtol class) | `P-*` via `ce-external-evidence/v1` |
| repo perf flags | kernel time / pipe metrics | `F-*` via profiling receipt |

Host replay is not a precision or perf measurement. Missing repo / runner →
precision/perf stay Open with `harness_missing`. Crash / not-run is
environment, not unreachable and not a failed golden. Later CE PRs may
patch the test scripts from `test_repo_contract.yaml` `findings`.
