---
name: uo-update
description: '在已有 `.uo` 上根据源码变更执行确定性增量刷新、重建受影响 CodeMap 关系、 校验完整性并输出差异摘要。用户要求刷新已有 UO/CodeMap
  或查看源码变更对 CodeMap 的影响时使用。

  '
---

# uo-update

`uo-update` 是确定性增量编译流程，不创建语义 subagent，也不绑定 task prompt。源码变更中无法由确定性 frontend/pass 可靠重建的关系必须保持 unresolved，不能由 update 流程猜测补齐。

## 原则

- `.uo` 是更新对象与查询 authority。
- 只重建受变更影响的事实/关系；未受影响证据保持稳定。
- macro、template、compile var、TilingKey/TilingData、Host/Kernel 与 architecture 依赖都按 CodeMap provenance 失效/重算。
- 完整性审查失败时 fail closed，并返回明确 rework reason。
- `diff_only` 只比较，不修改产品。

## Actions

<!-- BEGIN GENERATED ACTIONS -->

| action_id | execution_mode | agent | role | method | prompt | output_contract |
|---|---|---|---|---|---|---|
| `detect_changes` | `deterministic` | `human` | `deterministic_engine` | `uo-update/detect-changes` | `-` | `change-detect-v1` |
| `plan_update` | `deterministic` | `human` | `deterministic_engine` | `uo-update/plan-update` | `-` | `update-plan-v1` |
| `apply_update` | `deterministic` | `human` | `deterministic_engine` | `uo-update/apply-update` | `-` | `update-apply-v1` |
| `key_triage` | `deterministic` | `human` | `deterministic_engine` | `uo-update/key-triage` | `-` | `key-triage-v1` |
| `key_resolution` | `deterministic` | `human` | `deterministic_engine` | `uo-update/key-resolution` | `-` | `input-derivable-patch-v1` |
| `confidence_report` | `deterministic` | `human` | `deterministic_engine` | `uo-update/confidence-report` | `-` | `confidence-report-v1` |
| `confidence_review` | `deterministic` | `human` | `deterministic_engine` | `uo-update/confidence-review` | `-` | `confidence-reason-review-v1` |
| `export_integrity` | `deterministic` | `human` | `deterministic_engine` | `uo-update/export-integrity` | `-` | `integrity-v1` |
| `diff_summary` | `deterministic` | `human` | `deterministic_engine` | `uo-update/diff-summary` | `-` | `diff-summary-v1` |
| `diff_only` | `deterministic` | `human` | `deterministic_engine` | `uo-update/diff-only` | `-` | `diff-summary-v1` |

<!-- END GENERATED ACTIONS -->
