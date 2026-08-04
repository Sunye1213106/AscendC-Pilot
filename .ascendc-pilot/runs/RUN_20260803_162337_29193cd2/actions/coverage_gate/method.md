# coverage-gate

> 确定性 Action：只允许 `acp run-action coverage_gate`（或 `python scripts/run_tk_cover.py`）。

## Goal

跑 `replay_runtime_counterexample_gate.py`，写入：

- `uo/tk/coverage_gate.yaml` — 含 `open_gap_sound` / `complete` / `residual_blockers`
- `uo/tk/residual.yaml` — 为何还不能 `U_sound - R = ∅`

## Done When

- `gate_pass: true`（`R ∩ excluded = ∅`）
- `complete: true` **仅当** `open_gap_sound == 0`
- 若 `complete: false`，`residual_blockers` 必须非空且不得靠假排除凑零
