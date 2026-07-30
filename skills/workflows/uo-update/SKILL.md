---
name: uo-update
description: 增量更新 / 刷新已有 UO 知识库（含 diff_only）。用户说更新 KB、刷新知识库时加载。Pilot 管阶段；加载后执行 acp
  start uo-update。
---

# uo-update

增量更新 UO KB。引擎：`uo_init.update`（与 `uo-init` 同一包，消费新分层 KB）。

## 硬规则

1. `acp start uo-update` → `acp next` → `acp run-action <action_id>`。
2. 变更检测 / 计划 / 应用 / diff / 置信度 / 完整性均为确定性 Action。
3. `key_triage` / `key_resolution` / `confidence_review` 当前为**确定性 stub**（新 KB 尚无旧 escalate 链）；见 `docs/debug/open-problems.md`。
4. **禁止**读取或依赖 `extract_plan.yaml` / 旧 semantic ledger。

## 启动

```text
acp start uo-update --project <算子目录>
acp next
acp run-action detect_changes
```

diff_only：按 Bundle 进入 `diff` 管线即可。

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
