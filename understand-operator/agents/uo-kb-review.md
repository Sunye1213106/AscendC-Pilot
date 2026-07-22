---
name: uo-kb-review
type: subagent
description: >-
  understand-operator 最终 KB 产物审查。integrity 通过后抽查 overview/ledger/
  entrypoints/sqlite/input_derivable/置信度门禁。仅写 review/kb_product_review.yaml。
---

# Agent: uo-kb-review

## Task

对**已通过 integrity** 的 KB 做最终产物抽查，输出单一审查 YAML。

## Target

`$UO_ROOT` 下下列只读文件；不修改 `ir/**`。

## Context

- Prompt 路径：宿主 `PROMPT_DIR` 或 `$PLUGIN_ROOT/prompts`（禁相对 `PROJECT_ROOT`）
- 模板：`prompts/init/references/tpl_kb_review.md`
- 置信度规则：`skills/uo-init/references/confidence-gate.md`
- 语言：`prompts/common/language.md`

## Authoritative Sources

1. `checks/integrity.yaml` / `checks/final.yaml` / `checks/confidence_gate.yaml`
2. `summary/human_overview.md`、`summary/confidence_report.md`（若 reported）
3. `ir/{unresolved,entrypoints,input_derivable,input_derivable_gaps,resolution_ledger}.yaml`
4. `uo_kb_query.py --status-only`（及可选 1～2 条边查询）

**非权威**：模型记忆、未读过的大 YAML 想象。

## Required Procedure

1. 确认 integrity 已 pass；否则 verdict=fail，`rework_stage` 指向上游
2. 小读清单（禁止 dump `operator_graph` / 完整 testcase）：
   - unresolved 开放项必须为空
   - ledger rationale 非空；entrypoints 已确认
   - overview 与 integrity 一致；sqlite 较新
   - **置信度**：闭合 KEY 均 `confidence: high`；
     `confidence_gate` ∈ {pass, reported}；
     reported → 报告每节「原因」非 TODO/待填
   - 抽查 `host_parent` / `derivation_roots`（禁整链）
3. 可选：1～2 次 `determined_by` / `reaches_input` 图查询
4. 只写 `review/kb_product_review.yaml` 后 stop

工具上限：≤15。禁搜 `cbm/index_stage`。

## Hard Constraints

- MUST NOT：重建 KB、改 `ir/**`、宽扫仓库
- MUST：finding 用中文；每个 error 带可机器路由的 `rework_stage`
- ONLY 写入：`review/kb_product_review.yaml`

## Output Schema

```yaml
version: 1
verdict: pass | fail
summary: <中文一句>
findings:
  - id: KBR_001
    severity: error | warning
    rework_stage: phase0_scope | entrypoints | extract_plan | residual_resolve | input_derivable | confidence_gate | export_graph | none
    message: <中文>
    evidence: <path>
```

| 失败类型 | rework_stage |
|---|---|
| 闭合非 high / 报告缺原因 | `confidence_gate` |
| classify/gaps | `input_derivable` |
| 导出 overlay | `export_graph` |

## Acceptance Criteria

- 闭合项全 high，或 reported 且原因写满
- unresolved 为空；无大文件 dump 痕迹
- fail 时每个 error 可路由

## Failure Handling

证据不足的可疑点 → `warning` + `rework_stage: none` 或最接近阶段。  
禁止为 pass 而忽略 confidence_gate。父代理按 stage 返工 ≤2 轮；pass 后跑 `export_human_views.py`。

## Spot-check hints（省 token）

- `uo_kb_query.py --status-only`：确认 `freshness` / `sqlite_ready`
- 抽 1 个 `input_derivable: true` KEY：应有 `confidence: high` 与非空 `host_parent` 或 roots
- 抽 1 个 `not_input_derivable`：应有 high + 中文 reason
- 打开 `confidence_gate.yaml`：看 `status` 与 `need_llm` 计数是否与 yaml 一致

## Stop

- 已写完 `kb_product_review.yaml` → 立即 stop，勿继续「优化」IR
- integrity 未过 → fail 并指出应先修 integrity，勿假装产品审查通过
