---
name: uo-update
description: 增量更新 / 刷新已有 UO 知识库（含 diff_only）。用户说更新 KB、刷新知识库时加载。Pilot 管阶段；加载后执行 acp
  start uo-update。
---

# uo-update

增量更新 UO KB。

语义方法：`skills/domain/uo-kb-update/SKILL.md`。  
引擎：`uo_init.update`（与 uo-init 同一包）。

## Pilot

1. `acp start uo-update` → `acp next` → `acp run-action <action_id>`
2. 多数步骤为确定性 Action；语义步骤按 Bundle finalize
3. `acp advance`（仅消费可信收据）
4. 禁止依赖已删除的旧 `extract_plan.yaml` / semantic ledger

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `detect_changes` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-update/detect-changes` | `-` | `change-detect-v1` |
| `plan_update` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-update/plan-update` | `-` | `update-plan-v1` |
| `apply_update` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-update/apply-update` | `-` | `update-apply-v1` |
| `key_triage` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-update/key-triage` | `-` | `key-triage-v1` |
| `key_resolution` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-update/key-resolution` | `-` | `input-derivable-patch-v1` |
| `confidence_report` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-update/confidence-report` | `-` | `confidence-report-v1` |
| `confidence_review` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-update/confidence-review` | `-` | `confidence-reason-review-v1` |
| `export_integrity` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-update/export-integrity` | `-` | `integrity-v1` |
| `diff_summary` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-update/diff-summary` | `-` | `diff-summary-v1` |
| `diff_only` | `deterministic` | `deterministic-uo-engine` | `deterministic_engine` | `uo-update/diff-only` | `-` | `diff-summary-v1` |

<!-- END GENERATED ACTIONS -->
