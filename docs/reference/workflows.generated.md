# 工作流 Reference

本文件由 `pilot/ascendc_pilot/workflows/specs.py`（经 registry normalize）生成，请不要手工编辑。

`Action 执行` 来自各 Action 的 `execution_mode` / `agent_id`；`Workflow Agents` 是 workflow 声明的身份清单（含 Primary），**不是**逐步执行者。

| 工作流 | 入口 | 状态 | Action | Action 执行 | Workflow Agents | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| `uo-init` | `/uo-init` | prepare, extract, analyze, commit, verify | prepare, extract, analyze, commit, verify | `prepare`:deterministic<br>`extract`:deterministic<br>`analyze`:deterministic<br>`commit`:deterministic<br>`verify`:deterministic | `ascendc-pilot`, `deterministic-uo-engine` | layout_receipt, scope_receipt, extract_receipt, uo_product_ready |
| `uo-update` | `/uo-update` | detect, plan, apply, export, diff | detect_changes, plan_update, apply_update, export_integrity, diff_summary, diff_only | `detect_changes`:deterministic<br>`plan_update`:deterministic<br>`apply_update`:deterministic<br>`export_integrity`:deterministic<br>`diff_summary`:deterministic<br>`diff_only`:deterministic | `deterministic-uo-engine` | integrity |
| `uo-query` | `/uo-query` | route, lookup, answer | kb_lookup | `kb_lookup`:subagent(`uo-query`) | `uo-query` |  |
| `uo-investigate` | `/uo-investigate` | investigate, report | investigate | `investigate`:subagent(`uo-gap-investigator`) | `uo-gap-investigator`, `ascendc-pilot` |  |
| `ce-review` | `/ce-review` | context, bug, functional, summary | code_review | `code_review`:subagent(`ce-reviewer`) | `ce-reviewer` | kb_ready, context_pack |
| `tg-init` | `/tg-init` | intent, kb_ready, contract, bind, gate, confirm | init_intent, kb_check, contract_build, semantic_bind, integrity_gate, init_audit, human_confirm | `init_intent`:deterministic<br>`kb_check`:deterministic<br>`contract_build`:deterministic<br>`semantic_bind`:deterministic<br>`integrity_gate`:deterministic<br>`init_audit`:subagent(`tg-init-audit`)<br>`human_confirm`:primary_interactive(`ascendc-pilot`) | `tg-init-audit`, `deterministic-tg-engine`, `ascendc-pilot` | uo_ready, kb_fingerprint_fresh, tilingkey_binding_ready, audit_pass, init_confirmed |
| `tg-plan` | `/tg-plan` | intent, scope, gate, build, filter, review, approve | plan_intent, plan_scope, plan_precheck, plan_build, plan_approve | `plan_intent`:deterministic<br>`plan_scope`:deterministic<br>`plan_precheck`:deterministic<br>`plan_build`:deterministic<br>`plan_approve`:primary_interactive(`ascendc-pilot`) | `ascendc-pilot`, `deterministic-tg-engine` | tg_init_confirmed, plan_approved |
| `tg-solve` | `/tg-solve` | gate, oracle, ledger, search, residual, construct, lemma, audit, certify | solve_precheck, oracle_probe, closure_ledger, closure_search, closure_residual, closure_construct, closure_explain, lemma_leads, lemma_evidence, lemma_mine, lemma_verify, lemma_review, lemma_apply, lemma_loop, closure_audit, closure_certify | `solve_precheck`:deterministic<br>`oracle_probe`:deterministic<br>`closure_ledger`:deterministic<br>`closure_search`:deterministic<br>`closure_residual`:deterministic<br>`closure_construct`:deterministic<br>`closure_explain`:deterministic<br>`lemma_leads`:deterministic<br>`lemma_evidence`:deterministic<br>`lemma_mine`:subagent(`tg-lemma-producer`)<br>`lemma_verify`:deterministic<br>`lemma_review`:subagent(`tg-closure-referee`)<br>`lemma_apply`:deterministic<br>`lemma_loop`:deterministic<br>`closure_audit`:subagent(`tg-closure-referee`)<br>`closure_certify`:deterministic | `deterministic-tg-engine`, `tg-lemma-producer`, `tg-closure-referee` | plan_approved, closure_soundness, kb_fingerprint_fresh |
| `code-edit` | 内部（无 Slash 入口） |  |  |  |  |  |
| `git-ops` | 内部（无 Slash 入口） |  |  |  |  |  |
| `build` | 内部（无 Slash 入口） |  |  |  |  |  |
| `test-run` | 内部（无 Slash 入口） |  |  |  |  |  |
| `perf-analyze` | 内部（无 Slash 入口） |  |  |  |  |  |
