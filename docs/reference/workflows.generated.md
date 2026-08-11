# 工作流 Reference

本文件由 `pilot/ascendc_pilot/workflows/specs.py` 生成，请不要手工编辑。

| 工作流 | 入口 | 状态 | 动作 | 执行者 | Gate |
| --- | --- | --- | --- | --- | --- |
| `uo-init` | `/uo-init` | prepare, extract, analyze, commit, verify | prepare, extract, analyze, commit, verify | ascendc-pilot | layout_receipt, extract_receipt, uo_product_ready |
| `uo-update` | `/uo-update` | detect, plan, apply, export, diff | detect_changes, plan_update, apply_update, export_integrity, diff_summary, diff_only | deterministic-uo-engine | integrity |
| `uo-query` | `/uo-query` | route, lookup, answer | kb_lookup | uo-query |  |
| `uo-investigate` | `/uo-investigate` | investigate, report | investigate | uo-gap-investigator, ascendc-pilot |  |
| `ce-review` | `/ce-review` | context, bug, functional, summary | code_review | ce-reviewer | kb_ready, context_pack |
| `tg-init` | `/tg-init` | intent, kb_ready, contract, bind, gate, confirm | init_intent, kb_check, contract_build, semantic_bind, integrity_gate, init_audit, human_confirm | tg-init-audit, deterministic-tg-engine, ascendc-pilot | uo_ready, kb_fingerprint_fresh, tilingkey_binding_ready, audit_pass, init_confirmed |
| `tg-plan` | `/tg-plan` | intent, scope, gate, build, filter, review, approve | plan_intent, plan_scope, plan_precheck, plan_build, plan_approve | ascendc-pilot, deterministic-tg-engine | tg_init_confirmed, plan_approved |
| `tg-solve` | `/tg-solve` | gate, oracle, ledger, search, residual, construct, lemma, audit, certify | solve_precheck, oracle_probe, closure_ledger, closure_search, closure_residual, closure_construct, closure_explain, lemma_leads, lemma_evidence, lemma_mine, lemma_verify, lemma_review, lemma_apply, lemma_loop, closure_audit, closure_certify | deterministic-tg-engine, tg-lemma-producer, tg-closure-referee | plan_approved, closure_soundness, kb_fingerprint_fresh |
| `code-edit` | 内部（无 Slash 入口） |  |  |  |  |
| `git-ops` | 内部（无 Slash 入口） |  |  |  |  |
| `build` | 内部（无 Slash 入口） |  |  |  |  |
| `test-run` | 内部（无 Slash 入口） |  |  |  |  |
| `perf-analyze` | 内部（无 Slash 入口） |  |  |  |  |
