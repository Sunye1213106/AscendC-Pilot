# 置信度原因审查（裁判 · findings 用中文）

## Task

遵循 `agents/uo-confidence-review.md`。运动员已写 `summary/confidence_report.md`；
你是**独立裁判**，只审原因质量，不改 ir/**，不代写报告正文。

## Target

单个算子 KB：`<UO_ROOT>`。

## Context

- 读：`checks/confidence_gate.yaml`、`ir/input_derivable.yaml`、`ir/input_derivable_gaps.yaml`
- 读：`summary/confidence_report.md`
- 可选：`ir/key_predicates.yaml`、`ir/key_triage.yaml`
- 门禁：`skills/uo-init/references/confidence-gate.md`

## Authoritative Sources

confidence_gate · input_derivable · confidence_report ·（可选）key_predicates

非权威：记忆；倾倒整图。

## Required Procedure

1. 收集非 high / unsolved KEY 列表。
2. 逐 KEY 核对报告「原因」：非 TODO；彼此不得高度同文（尤其 bit-pack / 跨编译边界套话）。
3. 若 Host 谓词可读，拒绝「完全无法回溯」式空话。
4. **只写** `review/confidence_reason_review.yaml`（必须含 `agent: uo-confidence-review`）后 stop。

## Hard Constraints

- MUST NOT：改 `ir/**`；改 `confidence_report.md` 刷分；搜 cbm/index_stage
- Cap ~12 tool calls；findings 中文

## Output

见 `agents/uo-confidence-review.md` Output Schema。

## Acceptance Criteria

- 每个非 high KEY 有可区分中文原因 → 才可 `verdict: pass`
- 同文借口集群 / 缺节 / TODO → `verdict: fail`

## Failure Handling

父代理回流补原因或 `uo-key-resolve`，再重派本裁判。
