# Skill gaps — full_closure_run_20260810

## UO-init review-only path missing
- Skill says run `uo-init review` when product `.uo` exists; acp has no jump-to-review. Full chain requires extract/analyze (~300s+). **Mitigation used**: `acp validate-key-gates` + tg-init `kb_check` as readiness proxy; aborted uo-init after accidental `--force-new` wiped `arch35/uo`.

## uo-init `--force-new` destructive
- `acp start uo-init --force-new` deleted `arch35/uo` exports though product `.uo` at `.ascendc-pilot/uo/` survived. Required `python -m uo_init.dump … --all --out arch35/uo` to restore YAML tree for `kb_fingerprint_fresh`.

## kb_fingerprint_fresh gate false negative (fixed)
- `require_kb_fingerprint_fresh` returned `{stored, current}` without `ok: true`; `_wrap_exc` failed closed. **Fixed** one line in `testcase_agent/init_status.py`.

## plan_intent primary_interactive gap
- `plan_intent` is `primary_interactive` but `materialize_primary_decision` only handles `human_confirm` / `plan_approve`. Finalize requires pre-existing `plan_intent.yaml`. Had to run `plan_intent()` engine before `--finalize`. Skill should document engine pre-write or extend materialize.

## init_audit subagent lease lifecycle
- Failed finalize revokes lease; must re-`prepare` before retry. Document in tg-init skill.

## plan_precheck ARTIFACT_OWNER_MISMATCH (hard block)
- `plan_precheck` finalize fails identity on `tg/init/status.yaml` because `run_id` is from tg-init (`RUN_…22145`) while tg-plan run is different (`RUN_…22900`). Gates pass; only output-contract identity injection fails. **Blocked** tg-plan approve and all tg-solve.

## lemma_loop not in generated acp actions
- `acp doctor` reports `SKILL_ACTION_SET_DRIFT`: spec lists `lemma_loop`, generated CLI omits it. Use discrete lemma_* actions.

## WSL / PowerShell friction
- `$VAR` eaten by PowerShell; required `wsl_run.sh` wrapper and LF-only scripts.

## Missing UO views (known)
- Product `.uo` lacks `views/kernel.yaml` / `views/tilingdata.yaml` in view_blob; expect `I0_kernel` / `I0_tilingdata` certificate gaps when solve reaches certify.
