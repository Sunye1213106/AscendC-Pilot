# 控制面剩余问题闭合 — 审计报告

> 日期：2026-07-24  
> 仓库：AscendC-Pilot  
> 基线 commit（修改前 HEAD）：`a29010f54d8defb71a473bcd6a1dba16b72e577d`  
> 本轮改动：**尚未单独 commit**（按约定仅在明确要求时提交）

## 1. 修改文件列表（本轮控制面核心）

- Gates: `pilot/ascendc_pilot/gates/__init__.py`
- Finalize/prepare: `pilot/ascendc_pilot/actions/runtime.py`
- Lease: `pilot/ascendc_pilot/authorize/lease.py`
- Resume: `pilot/ascendc_pilot/run_resume.py`
- Consistency/Spec: `pilot/ascendc_pilot/workflows/consistency.py`, `specs.py`
- Contracts: `pilot/ascendc_pilot/actions/engines.py`
- Semantic patches: `engines/understand-operator/uo/scripts/llm_tasks.py`
- Scope writers: `finalize_scope.py`, `review_checkpoint.py`
- Compose/CI: `scripts/compose_runtime.py`, `scripts/check_contracts.py`
- Prompt/METHOD: `prompts/tasks/uo/extract-plan.md`, `skills/actions/uo-init/extract-plan/METHOD.md`
- Tests: `pilot/tests/test_control_plane_round2.py` (new) + adapter updates
- Generated: regenerated via compose

## 2. 每个问题的根因

1. Scope: glob other runs + mtime; empty status/files pass
2. uo_ready: empty status fail-open vs integrity exact pass
3. Finalize: no lease_id/prepare_nonce bind; success kept lease
4. Patch: adjudicate coverage-only vs Apply full validate
5. Resume: weak YAML issued_by + ok!=false
6. Consistency: zero write coverage continue
7. Generated: structural validate only, no content drift
8. Bugs: detect_score_post OR + dead branch; extract_plan optional fields

## 3. 删除的 fallback / fail-open

- Scope cross-run/mtime/files-without-status
- uo_ready empty/ok/reported status pass
- Finalize without active/lease/nonce
- Patch gate coverage-only; soft source hash skip
- Resume weak receipts
- Consistency zero-coverage continue
- detect_score_post plan-or-host; extract_plan skip-if-missing fields

## 4. 新的完成态和收据判断规则

Action done = verify_receipt(Pilot+HMAC+action_id+run_id+spec_hash+hashes+checker_ok)
Advance = pipeline verified receipts + phase_gates
Resume: verified_receipts keep; invalid_receipts -> dirty scrub
Finalize bind: prepare_nonce + lease_id match active/current lease; revoke after ok/fail

## 5. 旧产物迁移

Required. Missing binding fields return migration/mismatch errors. Re-prepare / continue scrub / reinit.

## 6. 测试结果

python scripts/check_contracts.py -> ok
python -m pytest pilot/tests engines/understand-operator/tests/test_semantic_batch_tx.py -q -> 171 passed

## 7. 残留风险

Hook authorize not OS isolation; extract_plan gate still receipt-optional by design; same-action staged merge convention; working tree may include unrelated prior edits.

## 8. git diff --stat

98 files changed, 1640 insertions(+), 367 deletions(-)

## 9. commit hash

HEAD (uncommitted changes): a29010f54d8defb71a473bcd6a1dba16b72e577d
