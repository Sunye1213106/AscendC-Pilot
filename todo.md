# 任务：generic closure agent v4 修复清单落地

## 目标
让默认 tilingkey_full_coverage 路径可执行且闭环结论可信；顺带瘦身仓库。

## 待办事项
- [x] 0.1 同步 uo-init phase（resolve→normalize / KEY→uo-update）
- [x] 0.2 coverage_from_codemap 调用方
- [x] 0.3 W0 arch 路径漂移（rel_under_agent_dir + 测试路径）
- [x] 0.4 标记/翻转错误断言（lemma_mine merge、csv mode）
- [x] 5.1 CI compose + 停跟踪 generated/
- [x] 5.2 直接删除零引用文件
- [x] 1.1 legal_key_count + fail-closed
- [x] 1.2 tilingkey_binding_ready gate（mode-aware bind）
- [x] 1.3 mode-specific pipeline（tg-solve overlays）
- [x] 1.4 tg-init.phases 补 intent
- [x] 2.1 继承规则不得绕审进 E
- [x] 2.2 freshness 对比当前 UO
- [x] 2.3 生产模式强制 live（CI 可 opt-out）
- [x] 2.4 lemma_mine merge→review
- [x] 2.5 rework 移出 action
- [x] 3.x search_round 统计修复

## 本轮续作（未提交）
- [x] ownership：referee 仅 review.yaml；canon→lemma_apply/closure_certify；tg-plan/solve write_roots + context；ACTION_WRITE_PATHS 补齐；ownership audit OK
- [x] tk-cover skill 树删除；compose 跳过 alias_of
- [x] W1：construct yaml 解释器；constraints ImportError；obligations named_bindings 外置到 search_hints
- [x] FAG CSV / 转换脚本已删
- [x] CODEMAP_* 标 legacy read-only（保留兼容读）
- [x] synthetic E2E（StubOracle / overlay / CI）`pilot/tests/test_synthetic_tg_e2e.py`
- [x] 一批测试对齐产品（path arch、KB determinants、detect_score_pre 移除、control_plane）

## 仍红（非本轮 P0，多为 UO/CSV 遗留）
- phase1/phase2 CSV 端到端大套件
- 部分 debug/run_resume/scope_contract/tg_engines_real
- 全量套件需分目录跑（避免 scripts/tests conftest 遮蔽）
