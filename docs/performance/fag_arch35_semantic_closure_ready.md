# FAG arch35 uo-init 语义闭合就绪报告（2026-07-27，A56 更新）

## 范围
- 回归目标算子路径：`D:\ops-transformer\attention\flash_attention_score_grad`（代码未硬编码算子名）
- 架构：arch35
- 本报告覆盖：P0 审查缺口修复（session / scope / integrity）+ P1 contract·enrich·bridge·KEY + 单测 + compose；完整 Host LLM `acp complete` 需人工 W3

## A56 修复闭环对照

| 问题 | 判定 |
|---|---|
| Debug off 不登记 child / 假 resume | 已修：`external_session_registry` always-on；仅 `host_reported_resumed_from==previous_child` → verified resume |
| scope sibling / 无可达性 / apply 无派生 | 已修：roots=operator∪common；include/符号证据；snapshot+closure+CBM；recovery 互斥 |
| `ok` 与 overall 不一致 | 已修：`ok==overall_ok`；quality fail-closed |
| contract / enrichment / bridge / KEY | 已修：contract fail-closed；enrichment 再 triage；missing_producer blocking；KEY 禁子串 false/high |

## FAG 局部观测（确定性，非全量 uo-init）

| 项 | 值 |
|---|---|
| boundary inputs / outputs | 27 / 7 |
| scope confirmed_source_count | 90 |
| `check_kb_integrity` overall | fail（structural/semantic 未齐；诚实 fail-closed） |
| overall ready | **未宣称** |

见既有 `docs/performance/fag_arch35_semantic_closure_report.json`（boundary 局部）。全量 extract/bridge/KEY 需 Host LLM 流水线。

## Ready 分层（定义）

| 层 | 含义 | 本轮 FAG 状态 |
|---|---|---|
| structural_ready | host/kernel subgraph + closure | 当前 integrity 为 false（缺全量 extract 产物） |
| semantic_ready | boundary 非空 + blocking unresolved=0 + integrity 无 error | boundary 非空已验证；全量语义待 W3 |
| tg_consumer_ready | typed bridge 与 KEY 非假通过 | 代码侧 fail-closed 已加固；全量指标待 W3 |
| overall | 三层皆 pass 且 `ok==overall_ok` | **未宣称 ready** |

## 单测 / compose

- `pilot/tests/test_external_session_lineage.py`
- `engines/understand-operator/tests/test_scope_expansion_closure.py`
- `engines/understand-operator/tests/test_integrity_overall_ok.py`
- `engines/understand-operator/tests/test_closure_p1_contract_enrich_key.py`
- `engines/understand-operator/tests/test_semantic_closure_p0_p2.py`
- `python scripts/compose_runtime.py --host opencode` → ok

## 后续 W3（Host）

1. 全新 `uo-init`（scope→extract→adjudicate→apply→rebuild→recheck→key→export）
2. 对比 integrity：`structural_ready` / `semantic_ready` / `tg_consumer_ready` / `overall_status` / `ok`
3. 确认 rework 带控制面 `resume_session_id`（debug off 亦可）；无假 N/A / 空 apply 循环
4. 核对 bridge classifications 与 KEY true·false·unsolved 证据窗
