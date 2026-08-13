# Harness oracle vs Host replay

**When to load**: deciding whether a run may grow R or may enter CE `V`
for precision/perf.

| Mode | What it observes | May close |
| --- | --- | --- |
| Host replay | actual TilingKey, reject/crash | dispatch / key `R` |
| harness `only_grad` | golden vs device (atol/rtol class) | `P-*` via `ce-external-evidence/v1` |
| harness `profiler` | kernel time / pipe metrics | `F-*` via profiling receipt |

Host replay is not a precision or perf measurement. Missing harness →
precision/perf stay Open with `harness_missing`. Crash / not-run is
environment, not unreachable and not a failed golden.
