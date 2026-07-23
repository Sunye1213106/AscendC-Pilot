# KB 产物审查（findings 用中文）

## Task

遵循 `agents/uo-kb-review.md`。integrity 通过后的最终 KB 产物审查。

## Target

单个算子 KB：`<UO_ROOT>`。禁止修改 `ir/**`。

## Context

- 读：`summary/human_overview.md`、`checks/integrity.yaml`、`checks/final.yaml`
- 读：`ir/resolution_ledger.yaml`、`ir/unresolved.yaml`（须为空）
- 读：`ir/entrypoints.yaml`、`ir/input_derivable.yaml`、`ir/input_derivable_gaps.yaml`
- 读：`ir/key_triage.yaml`（若 need_llm/gaps/escalate 非空则 **必须存在**）
- 读：`checks/confidence_gate.yaml`、`checks/harness_key_gates.yaml`、`review/confidence_reason_review.yaml`
  若 status=reported → 报告每节「原因」非 TODO，且须裁判 `uo-confidence-review` verdict=pass；不得多 KEY 同文 bit-pack
- 跑：`uo_kb_query.py --status-only`；可选 1–2 次 determined_by/reaches_input
- 门禁：`skills/uo-init/references/confidence-gate.md`

## Authoritative Sources

checks/* · 列出的 ir/* · overview · confidence_report · confidence_reason_review · status-only CLI · harness key gates

非权威：记忆；倾倒 operator_graph / 完整 testcase。

## Required Procedure

1. 确认 integrity 已通过；确认 `harness validate-key-gates` 未 fail（或等价检查）。
2. 检查清单：unresolved 空；ledger rationale；entrypoints 已确认；
   overview↔integrity；sqlite fresh；已闭合 KEY confidence=high；
   `need_llm_count>0` 则必须有 `key_triage.yaml` + **`confidence_reason_review` pass**；
   `closed_high_count=0` 且 KEY 非空 → **verdict=fail**（除非 human_accept_reported）；
   抽样 ≥2 个 KEY（如 KEY_ISNZOUT、KEY_SPLITAXIS）核对 Host GetTilingKey 谓词是否写入 shape 语义；仅 empty 路径证据 → fail。
3. **只写** `review/kb_product_review.yaml` 后 stop。

## Hard Constraints

- MUST NOT：重建 KB；编辑 ir/**；搜 cbm/index_stage；倾倒大 YAML
- MUST NOT：在 KEY 门禁失败时写 verdict=pass
- Cap ~15 tool calls；findings 中文

## Output

`review/kb_product_review.yaml`：verdict ∈ {pass,fail}；closed_high_count；need_llm_count；抽查记录。

## Output Schema

```yaml
version: 1
verdict: pass | fail
summary: <中文一句>
findings:
  - id: KBR_...
    severity: error | warning
    rework_stage: phase0_scope | entrypoints | extract_plan | residual_resolve | input_derivable | confidence_gate | export_graph | none
    message: <中文>
    evidence: <path>
```

## Acceptance Criteria

- 已闭合 KEY confidence≠high → fail
- 未解残留却无写满 confidence_report → fail
- 每个 error 有可路由的 rework_stage

## Failure Handling

父代理按 rework_stage 返工（最多 2 次）。
`input_derivable` / `confidence_gate` → **uo-key-resolve**（triage→分流）+ classify + check_final_confidence + export。
pass 后：父代理跑 `export_human_views.py`。
