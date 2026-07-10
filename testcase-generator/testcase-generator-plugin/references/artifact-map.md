# Artifact Map

| Path under `.testcase-generator/<op>/` | Producer | Consumer |
|---|---|---|
| `kb_snapshot.yaml` | tg-init | all later stages |
| `route.md` | tg-init | human |
| `plan/coverage_obligations.yaml` | tg-plan | tg-generate, tg-audit |
| `generate/factor_space.yaml` | tg-generate | review / pairwise |
| `generate/rule_model.yaml` | tg-generate | prune |
| `generate/candidate_keys_raw.yaml` | tg-generate | review |
| `generate/candidate_keys_valid.yaml` | tg-generate | set cover |
| `generate/selected_targets.yaml` | tg-generate | realize |
| `generate/realized_cases.yaml` | tg-generate | tg-audit |
| `generate/probe_cases.jsonl` | tg-generate | tg-probe（仅正向） |
| `generate/l2_negative_cases.yaml` | tg-generate | review / 负例 dry-run |
| `probe/observed_keys.jsonl` | tg-probe | tg-audit |
| `audit/coverage_audit.yaml` | tg-audit | tg-repair, tg-report |
| `audit/coverage_matrix.md` | tg-audit | human |
| `report/final_report.md` | tg-report | human |

## Understand KB mapping

| Snapshot field | Source |
|---|---|
| `quality_gate` | `quality.yaml` |
| `operator_io` | `operator.yaml` → `io` |
| `tiling.key_space` | `tiling/key_space.yaml` |
| `tiling.families` | `tiling/families.yaml` |
| `tiling.data_model` | `tiling/data_model.yaml` |
| `tiling.coverage_model` | `tiling/coverage_model.yaml` |
| `kernel.kernel_path_matrix` | `kernel/paths.yaml` |
