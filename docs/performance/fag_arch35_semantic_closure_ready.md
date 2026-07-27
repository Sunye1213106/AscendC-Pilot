# FAG arch35 uo-init 语义闭合就绪报告（2026-07-27）

## 范围
- 回归目标算子路径：`D:\ops-transformer\attention\flash_attention_score_grad`（代码未硬编码算子名）
- 架构：arch35
- 本报告覆盖：共享层修复 + 单测 + boundary 局部回归；完整 Host LLM `acp complete` 需人工 W3

## 修复闭环对照

| 问题 | 判定 |
|---|---|
| recheck→adjudicate 假 N/A 死循环 | 已修：`ADJUDICATION_ROUTED_NON_LLM` + route recovery；同指纹 → `human_required` |
| can_auto_mark_missing 过宽 | 已修：类别禁止 + negative_evidence + validate-only auto |
| operator_boundary 空/路径 | 已修：`source_path_resolve` + `OPERATOR_BOUNDARY_EMPTY` |
| rework session | 已修：`dispatch.yaml` / `handoff.yaml` / `resume_session_id`；无 lineage=`fork_with_context` |
| incomplete_scope | 已修：`apply_scope_expansion` action + recovery 链 |
| typed bridge / quality | 已修：`bridge_metrics` + integrity 分层 status |
| KEY 全 unsolved | 已修：compile/platform → `false`+`non_input_reason`；consumer_ready 禁全 unresolved |

## FAG 局部回归（确定性）

见 `docs/performance/fag_arch35_semantic_closure_report.json`：

- confirmed_source_count = readable_source_count = 90
- inputs=27, outputs=7
- `OPERATOR_BOUNDARY_EMPTY` = false
- 仍有 accessor/attr 类 unresolved（属后续语义闭合，非路径静默失败）

## Ready 分层（定义）

| 层 | 含义 | 本轮 FAG 状态 |
|---|---|---|
| structural_ready | host/kernel subgraph + closure | 未跑全量 extract（需 extract_plan） |
| semantic_ready | boundary 非空 + blocking unresolved=0 + integrity 无 error | boundary 非空已验证；全量语义待 W3 |
| tg_consumer_ready | typed bridge>0 且 KEY 非全 unresolved | 待全量 bridge/KEY |
| overall | 三层皆 pass | **未宣称 ready**（诚实） |

## 单测

- `test_operator_boundary_path_resolve.py`
- `test_semantic_closure_p0_p2.py`
- 相关 lifecycle / pipeline 回归已对齐 negative_evidence 合同

## 后续 W3（Host）

1. 全新 `uo-init`（scope→extract→adjudicate→apply→rebuild→recheck→key→export）
2. 对比 integrity：`structural_status` / `semantic_status` / `consumer_ready_status` / `overall_status`
3. 确认 rework 带 `resume_session_id`，无假 N/A 循环
