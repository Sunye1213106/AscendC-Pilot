# Scenario catalog

Legal `scenario_id` values. Do not invent new ids. Engine mapping table is
the same set.

## Precision (`risk_class: precision`, oracle `only_grad`)

| id | When it attaches | Targeted knobs | Budget |
| --- | --- | --- | --- |
| `P-DTYPE` | INPUT dtype / key dim InputDType / Cast path | affected dtypes, same shape | 2–4 / dtype |
| `P-CAST` | OPERATION callee `Cast` in the slice | that dtype path + typical and boundary shape | ≤4 |
| `P-COPY-ALIGN` | `DataCopy` / `DataCopyPad` | last-dim aligned vs +1 unaligned | ≤4 |
| `P-QUEUE` | `EnQue` / `DeQue` around compute | smallest reproducible shape | ≤2 |
| `P-REDUCE-LONG` | reduction / softmax accumulate path | long sequence / large reduce axis | ≤2 |
| `P-OPTIONAL` | optional mask / pse / dropout / rope | present vs absent, legal shapes only | ≤4 |
| `P-ILLEGAL` | source or distilled illegal combo | Disable / exclusion; **do not run NPU** | 0 NPU |
| `P-TAIL` | tail core / empty tensor / min shape | `[1]`, zero-axis, remainder tile | ≤3 |

## Performance (`risk_class: perf`, oracle `profiler`)

| id | When it attaches | Targeted knobs | Budget |
| --- | --- | --- | --- |
| `F-SPLIT` | TilingData split-field writer / rhs changed | shapes sensitive to that field | 3–8 |
| `F-BUFFER` | BUFFER / QUEUE / `InitBuffer` | queue direction + mid-size shape | 3–8 |
| `F-SHAPE-TYPICAL` | any perf obligation baseline | competitive / network shapes (L1 intent) | 3–8 |
| `F-SHAPE-TAIL` | tail / unaligned split | non-divisible tile, core-boundary | ≤3 |
| `F-DTYPE` | compute dtype path | fp16 vs fp32, same shape | ≤2 |
| `F-BALANCE` | usedCoreNum / multi-core predicate | single-core vs full-core | ≤2 |

Do not treat all legal keys as a precision or perf matrix.
Full tilingkey coverage is a TG intent on `plan.md`, not a CE overlay.
