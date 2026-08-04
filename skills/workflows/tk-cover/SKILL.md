---
name: tk-cover
description: Close TilingKey coverage to U_sound − R = ∅. One subagent (mine_recipe);
  everything else is deterministic CLI.
---

# tk-cover

Dual-track coverage: every declared key has a runtime witness **or** a sound
unreachable certificate. Prefer a large `U_sound` over a false unreachable.

## Composer entry (do this)

```powershell
$env:UO_REPLAY_DISTRO="Ubuntu-2204"
$env:PYTHONPATH="d:\TEST\AscendC-Pilot\pilot;d:\TEST\AscendC-Pilot\engines\understand-operator\src;d:\TEST\AscendC-Pilot\engines\common\src;d:\TEST\AscendC-Pilot\scripts"
python scripts/run_tk_cover.py --reset
```

- Always `python -m ascendc_pilot.cli` via that script — **never** packaged `acp.exe`.
- Exit `0` = full sound coverage (`open_gap_sound=0`).
- Exit `3` = harness OK but residual gap (read `uo/tk/residual.yaml`).
- Exit `1`/`2` = fix the failing action, then `--reset` again.

Optional recipe loop: after prepare reaches `close`, write
`runs/<run_id>/actions/mine_recipe/parts/part_0.yaml`, then
`python scripts/run_tk_cover.py --from-close`.

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `env_probe` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `tk-cover/env-probe` | `-` | `tk-env-v1` |
| `derive_fields` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `tk-cover/derive-fields` | `-` | `tk-derive-v1` |
| `export_codemap` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `tk-cover/export-codemap` | `-` | `tk-codemap-v1` |
| `mine_recipe` | `subagent` | `tk-recipe-miner` | `producer` | `tk-cover/mine-recipe` | `tk/mine-recipe` | `tk-recipe-staging-v1` |
| `apply_recipe` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `tk-cover/apply-recipe` | `-` | `tk-recipe-v1` |
| `coverage_gate` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `tk-cover/coverage-gate` | `-` | `tk-gate-v1` |

<!-- END GENERATED ACTIONS -->

## Rules

1. Set `UO_REPLAY_DISTRO=Ubuntu-2204` before replay.
2. Never fold undeclared runtime keys (fp32+rope) into R/D.
3. After derivation changes: restore corpus if archived; gate must stay PASS
   with `R ∩ excluded = ∅`.
4. Do not migrate FAG `proof_rules` to a second operator.
5. Do not invent exclusions for residual blockers in `uo/tk/residual.yaml`.
