# iteration-6 live bind0 re-eval

Correctness is the hard gate. Composer 2.5 only.

Live run not wiped. Host-equivalent injection of production `columns.md`.

| Round | Score | Wall | Miss |
| --- | --- | --- | --- |
| 1 | 52/63 | — | dim_names Template/DType/operands |
| 2 | 61/63 | 4m22s | Atten_mask_* unwired |
| 3–5 | 61/63 | ~3m | N1 empty (candidate n1, head_num in call_args) |
| **6** | **63/63** | **3m00s** | none |

Round 6 skill: mandatory post-write scan — scalar kwargs source `uo.id` = `call_args.name` before inspect. YAML example shows N1 ← head_num.

Agent: `b9b43947-31dc-4517-bcce-9bafe1c1e17f`. Artifact: `pr_workspace/bind_eval/round6/bind0.yaml`. Live `parts/bind0.yaml` is the passing file.
