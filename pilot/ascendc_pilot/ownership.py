"""Unified ownership / identity model for Pilot Actions.

Authority layers (single editable authority per concern):

* Workflow Spec (`workflows/specs.py`) — action order, phase, actor, role,
  execution_mode, contracts, gates, and action-scoped write paths.
* Runtime Bundle / Action Lease — authoritative run/action/actor/session identity
  and the precise paths the current Action may write.
* Finalizer — injects trusted ``artifact_identity``; LLM declarations are not trusted.
* Skill / action.yaml — generated mirrors of Spec; never independent authorities.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

EXECUTION_DETERMINISTIC = "deterministic"
EXECUTION_SUBAGENT = "subagent"
EXECUTION_PRIMARY_INTERACTIVE = "primary_interactive"
EXECUTION_MODES = frozenset(
    {
        EXECUTION_DETERMINISTIC,
        EXECUTION_SUBAGENT,
        EXECUTION_PRIMARY_INTERACTIVE,
    }
)

PRIMARY_AGENT_ID = "ascendc-pilot"

# Action-precise write paths relative to `.ascendc-pilot/` (may include `{run_id}`).
# Agent write_scopes are ceilings; lease must be a subset.
#
# Producer vs finalizer split (Phase 0.5):
# - ACTION_PRODUCER_WRITE_PATHS: subagent / Map worker staging only
# - ACTION_FINALIZER_WRITE_PATHS: deterministic finalize / reduce canonical IR
# - ACTION_WRITE_PATHS: union fallback for engines that do not yet split roles
ACTION_PRODUCER_WRITE_PATHS: dict[str, dict[str, list[str]]] = {
    "uo-investigate": {
        "investigate": [
            "runs/{run_id}/actions/investigate/parts/**",
            "runs/{run_id}/actions/investigate/scratch/**",
            "runs/{run_id}/actions/investigate/report.yaml",
            "uo/ir/gap_investigation.yaml",
        ],
    },
    "uo-query": {
        "kb_lookup": [
            "runs/{run_id}/actions/kb_lookup/answer.yaml",
            "runs/{run_id}/actions/kb_lookup/scratch/**",
        ],
    },
    "tg-solve": {
        "lemma_mine": [
            "runs/{run_id}/actions/lemma_mine/parts/**",
            "runs/{run_id}/actions/lemma_mine/scratch/**",
            "runs/{run_id}/actions/lemma_mine/staging.yaml",
        ],
        "lemma_review": [
            "runs/{run_id}/actions/lemma_review/review.yaml",
        ],
        "closure_audit": [
            "runs/{run_id}/actions/closure_audit/review.yaml",
        ],
    },
    "ce-intent": {
        "feature_decompose": [
            "runs/{run_id}/actions/feature_decompose/parts/**",
            "runs/{run_id}/actions/feature_decompose/scratch/**",
            "runs/{run_id}/actions/feature_decompose/staging.yaml",
        ],
        "intent_grill": [
            "runs/{run_id}/actions/intent_grill/parts/**",
            "runs/{run_id}/actions/intent_grill/scratch/**",
            "runs/{run_id}/actions/intent_grill/staging.yaml",
        ],
    },
    "ce-impact": {
        "scenario_knobs": [
            "runs/{run_id}/actions/scenario_knobs/parts/**",
            "runs/{run_id}/actions/scenario_knobs/scratch/**",
            "runs/{run_id}/actions/scenario_knobs/staging.yaml",
        ],
    },
}
ACTION_FINALIZER_WRITE_PATHS: dict[str, dict[str, list[str]]] = {
    "tg-solve": {
        "lemma_mine": [
            "runs/{run_id}/actions/lemma_mine/staging.yaml",
        ],
        "lemma_verify": [
            "runs/{run_id}/actions/lemma_verify/verify.yaml",
            "tg/closure/lemmas/verify.yaml",
        ],
        "lemma_review": [
            "runs/{run_id}/actions/lemma_review/review.yaml",
        ],
        "lemma_apply": [
            "tg/closure/excluded.txt",
            "tg/closure/excluded_why.csv",
            "tg/closure/open.txt",
            "tg/closure/lemmas/active_rules.yaml",
            "tg/closure/lemmas/revoked_rules.yaml",
            "tg/closure/lemmas/reviews.yaml",
        ],
        "lemma_loop": [
            "tg/closure/lemma_loop.yaml",
            "tg/closure/rounds/**/lemma.yaml",
            "runs/{run_id}/actions/lemma_mine/staging.yaml",
            "runs/{run_id}/actions/lemma_review/review.yaml",
            "tg/closure/excluded.txt",
            "tg/closure/excluded_why.csv",
            "tg/closure/open.txt",
            "tg/closure/lemmas/active_rules.yaml",
            "tg/closure/lemmas/reviews.yaml",
        ],
        "closure_audit": [
            "runs/{run_id}/actions/closure_audit/review.yaml",
        ],
        "closure_certify": [
            "tg/closure/certificate.yaml",
            "tg/closure/audit_report.yaml",
        ],
    },
    "ce-intent": {
        "feature_decompose": [
            "ce/intent/feature_decomposition.yaml",
        ],
        "intent_grill": [
            "ce/intent/intent.yaml",
        ],
    },
    "ce-impact": {
        "scenario_knobs": [
            "ce/scenarios/scenario_set.yaml",
        ],
    },
}
ACTION_WRITE_PATHS: dict[str, dict[str, list[str]]] = {
    "uo-init": {
        "prepare": [
            "uo/manifest.yaml",
            "uo/operator.yaml",
            "uo/runs/{run_id}/scope/**",
            "uo/summary/**",
            "uo/ir/build_variant.yaml",
            "uo/**",
        ],
        "extract": ["uo/ir/**", "uo/tiling/**", "uo/kernel/**", "uo/runs/{run_id}/**"],
        "analyze": ["uo/ir/**", "uo/tiling/**", "uo/kernel/**", "uo/checks/**"],
        "commit": ["uo/*.uo", "uo/checks/**"],
        "verify": ["uo/checks/**"],
    },
    "uo-investigate": {
        "investigate": [
            "runs/{run_id}/actions/investigate/parts/**",
            "runs/{run_id}/actions/investigate/scratch/**",
            "runs/{run_id}/actions/investigate/report.yaml",
            "uo/ir/gap_investigation.yaml",
        ],
    },
    "uo-query": {
        "kb_lookup": [
            "runs/{run_id}/actions/kb_lookup/answer.yaml",
            "runs/{run_id}/actions/kb_lookup/scratch/**",
        ],
    },
    "tg-init": {
        "init_intent": ["tg/init/init_intent.yaml"],
        "kb_check": ["runs/{run_id}/receipts/uo_ready.yaml"],
        "contract_build": [
            "tg/intake/**",
            "tg/snapshot/**",
            "tg/realization/**",
            "tg/contract/**",
            "tg/plan/coverage_obligations.yaml",
            "tg/run.yaml",
            "context/pilot_params.yaml",
        ],
        "semantic_bind": [
            "tg/realization/binding_inventory.yaml",
            "tg/init/test_repo_inventory.yaml",
            "tg/init/test_repo_contract.yaml",
        ],
        "integrity_gate": ["runs/{run_id}/receipts/integrity_gate.yaml"],
        "init_audit": ["tg/init/audit_report.yaml"],
        "human_confirm": [
            "tg/init/status.yaml",
            "tg/init/kb_fingerprint.yaml",
            "tg/init/confirmation.yaml",
        ],
    },
    "tg-plan": {
        "plan_intent": ["tg/plan/plan_intent.yaml"],
        "scenario_plan": ["tg/plan/scenario_plan.yaml", "tg/plan/plan_intent.yaml"],
        "plan_scope": [
            "tg/plan/levels/*/plan_scope.yaml",
            "tg/plan/plan_intent.yaml",
        ],
        "plan_precheck": [],
        "plan_build": [
            "tg/plan/**",
            "tg/extract/**",
            "tg/realization/**",
            "tg/contract/**",
            "tg/run.yaml",
        ],
        "plan_approve": ["tg/plan/levels/*/human_supplement.yaml"],
    },
    "tg-solve": {
        "solve_precheck": [],
        "oracle_probe": ["tg/closure/oracle_probe.yaml"],
        "closure_ledger": [
            "tg/closure/R.txt",
            "tg/closure/open.txt",
            "tg/closure/excluded.txt",
            "tg/closure/excluded_why.csv",
        ],
        "closure_search": ["tg/closure/rounds/**", "tg/closure/models/**"],
        "closure_residual": ["tg/closure/residual/**", "tg/closure/route.yaml"],
        "closure_construct": ["tg/closure/construct/**"],
        "targeted_construct": ["tg/closure/scenarios/**"],
        "harness_run": ["tg/closure/scenarios/harness_results.yaml"],
        "scenario_certify": ["tg/closure/scenario_certificate.yaml"],
        "closure_explain": ["tg/closure/why.csv", "tg/closure/construct/**"],
        "lemma_leads": [
            "tg/closure/lemmas/leads.yaml",
        ],
        "lemma_evidence": [
            "tg/closure/lemmas/evidence/**",
            "tg/closure/lemmas/evidence_receipt.yaml",
            "tg/closure/lemmas/leads.yaml",
        ],
        "lemma_mine": [
            "runs/{run_id}/actions/lemma_mine/parts/**",
            "runs/{run_id}/actions/lemma_mine/scratch/**",
            "runs/{run_id}/actions/lemma_mine/staging.yaml",
        ],
        "lemma_verify": [
            "runs/{run_id}/actions/lemma_verify/verify.yaml",
            "tg/closure/lemmas/verify.yaml",
        ],
        "lemma_review": [
            "runs/{run_id}/actions/lemma_review/review.yaml",
        ],
        "lemma_apply": [
            "tg/closure/excluded.txt",
            "tg/closure/excluded_why.csv",
            "tg/closure/open.txt",
            "tg/closure/lemmas/active_rules.yaml",
            "tg/closure/lemmas/revoked_rules.yaml",
            "tg/closure/lemmas/reviews.yaml",
        ],
        "lemma_loop": [
            "tg/closure/lemma_loop.yaml",
            "tg/closure/rounds/**/lemma.yaml",
            "runs/{run_id}/actions/lemma_mine/staging.yaml",
            "runs/{run_id}/actions/lemma_review/review.yaml",
            "tg/closure/excluded.txt",
            "tg/closure/excluded_why.csv",
            "tg/closure/open.txt",
            "tg/closure/lemmas/active_rules.yaml",
            "tg/closure/lemmas/reviews.yaml",
        ],
        "closure_audit": [
            "runs/{run_id}/actions/closure_audit/review.yaml",
        ],
        "closure_certify": [
            "tg/closure/certificate.yaml",
            "tg/closure/audit_report.yaml",
        ],
    },
    "ce-review": {
        "code_review": [
            "ce/review/**",
            "runs/**/actions/code_review/**",
        ],
    },
    "ce-impact": {
        "change_capture": ["ce/impact/change_capture.yaml"],
        "uo_freshness": ["ce/impact/freshness.yaml"],
        "impact_slice": ["ce/impact/impact_slice.yaml"],
        "risk_classify": ["ce/impact/risk_classification.yaml"],
        "scenario_infer": ["ce/scenarios/scenario_set.yaml"],
        "scenario_apply": ["ce/scenarios/scenario_set.yaml"],
        "obligation_build": ["ce/impact/obligations.yaml", "ce/impact/ledger.yaml"],
        "impact_audit": ["ce/impact/audit_report.yaml"],
        "scenario_confirm": ["ce/scenarios/confirmation.yaml"],
    },
    "ce-verify": {
        "verify_gate": ["ce/verify/gate.yaml"],
        "code_review": ["ce/verify/code_review.yaml"],
        "coverage_bridge": ["ce/verify/tg_handoff.yaml", "ce/verify/regress_cases.csv"],
        "residual_analyse": ["ce/verify/residual.yaml", "ce/verify/ledger.yaml"],
        "harness_evidence": ["ce/verify/harness_evidence.yaml"],
        "harness_evidence_check": ["ce/verify/harness_evidence_check.yaml"],
        "external_ingest": ["ce/verify/external_evidence.yaml", "ce/verify/ledger.yaml"],
        "exclusion_review": ["ce/verify/exclusion_review.yaml"],
        "ce_certify": ["ce/verify/certificate.yaml"],
    },
    "ce-intent": {
        "intent_capture": ["ce/intent/intent.yaml"],
        "kb_check": ["ce/intent/kb_check.yaml"],
        "intent_grill": [
            "runs/{run_id}/actions/intent_grill/parts/**",
            "runs/{run_id}/actions/intent_grill/scratch/**",
            "runs/{run_id}/actions/intent_grill/staging.yaml",
        ],
        "grill_promote": ["ce/intent/intent.yaml"],
        "grill_confirm": ["ce/intent/grill_confirmation.yaml", "ce/session_handoff.md"],
        "feature_decompose": [
            "runs/{run_id}/actions/feature_decompose/parts/**",
            "runs/{run_id}/actions/feature_decompose/scratch/**",
            "runs/{run_id}/actions/feature_decompose/staging.yaml",
        ],
        "anchor_locate": ["ce/intent/anchors.yaml"],
        "scenario_infer": ["ce/scenarios/scenario_set.yaml"],
        "plan_review": ["ce/intent/plan_review.yaml"],
        "feature_promote": ["ce/intent/feature_decomposition.yaml"],
        "human_confirm": ["ce/intent/confirmation.yaml", "ce/session_handoff.md"],
    },
    "ce-apply": {
        "apply_gate": ["ce/apply/gate.yaml"],
        "patch": [
            "source:op_host/**",
            "source:op_kernel/**",
            "source:common/**",
            "ce/apply/patch_notes.yaml",
            "runs/{run_id}/actions/patch/**",
        ],
        "change_capture": ["ce/apply/change_capture.yaml"],
        "patch_guard": ["ce/apply/patch_report.yaml"],
        "code_review": [
            "ce/review/**",
            "runs/**/actions/code_review/**",
        ],
        "codemap_refresh": ["ce/apply/codemap_refresh.yaml"],
        "apply_report": ["ce/apply/report.yaml", "ce/session_handoff.md"],
    },
    "ce-handoff": {
        "session_handoff": ["ce/session_handoff.md"],
    },
}
ACTION_READ_PATHS: dict[str, dict[str, list[str]]] = {
    "uo-init": {
        "prepare": ["uo/**"],
        "extract": ["uo/**"],
        "analyze": ["uo/**"],
        "commit": ["uo/**", "uo/*.uo"],
        "verify": ["uo/**", "uo/*.uo"],
    },
    "uo-investigate": {
        "investigate": [
            "uo/ir/unresolved.yaml",
            "uo/ir/codemap_analyze_receipt.yaml",
            "uo/ir/gap_investigation.yaml",
            "runs/{run_id}/actions/investigate/**",
            "uo/*.uo",
        ],
    },
    "uo-query": {
        "kb_lookup": [
            "uo/**",
            "uo/*.uo",
            "runs/{run_id}/actions/kb_lookup/**",
            "context/**",
        ],
    },
    "tg-init": {
        "init_intent": ["context/**"],
        "kb_check": ["uo/*.uo"],
        "contract_build": [
            "uo/*.uo",
            "runs/{run_id}/receipts/uo_ready.yaml",
            "context/**",
        ],
        "semantic_bind": [
            "uo/*.uo",
            "tg/contract/**",
            "tg/realization/binding_inventory.yaml",
        ],
        "integrity_gate": [
            "tg/snapshot/**",
            "tg/realization/**",
            "tg/contract/**",
            "runs/{run_id}/receipts/uo_ready.yaml",
        ],
        "init_audit": [
            "tg/snapshot/**",
            "tg/contract/**",
            "tg/realization/**",
            "tg/init/**",
            "runs/{run_id}/receipts/**",
        ],
        "human_confirm": [
            "tg/init/**",
            "tg/realization/**",
            "tg/snapshot/**",
            "tg/contract/**",
        ],
    },
    "tg-plan": {
        "plan_intent": ["uo/*.uo", "tg/init/**", "context/**", "ce/scenarios/**"],
        "scenario_plan": ["ce/scenarios/**", "tg/plan/plan_intent.yaml"],
        "plan_scope": [
            "uo/*.uo",
            "tg/init/**",
            "tg/plan/plan_intent.yaml",
            "tg/snapshot/**",
            "tg/realization/**",
            "context/**",
        ],
        "plan_precheck": [
            "uo/*.uo",
            "tg/init/status.yaml",
            "tg/snapshot/**",
        ],
        "plan_build": [
            "uo/*.uo",
            "tg/init/**",
            "tg/plan/plan_intent.yaml",
            "tg/snapshot/**",
            "tg/realization/**",
            "tg/contract/**",
            "context/**",
        ],
        "plan_approve": [
            "tg/plan/levels/*/**",
            "tg/plan/plan_intent.yaml",
        ],
    },
    "tg-solve": {
        "solve_precheck": [
            "uo/*.uo",
            "tg/init/**",
            "tg/plan/**",
            "tg/snapshot/**",
        ],
        "oracle_probe": ["uo/*.uo", "tg/init/**", "local/**"],
        "closure_ledger": ["uo/*.uo", "tg/closure/**"],
        "closure_search": ["uo/*.uo", "tg/closure/**"],
        "closure_residual": ["tg/closure/**"],
        "closure_construct": ["uo/*.uo", "tg/closure/**", "ce/scenarios/**"],
        "targeted_construct": ["uo/*.uo", "ce/scenarios/**", "tg/plan/**", "tg/closure/**", "local/**"],
        "harness_run": ["tg/closure/scenarios/**", "local/**"],
        "scenario_certify": ["tg/closure/scenarios/**", "tg/plan/**", "ce/scenarios/**"],
        "closure_explain": ["tg/closure/**"],
        "lemma_leads": ["tg/closure/**"],
        "lemma_evidence": ["uo/*.uo", "tg/closure/lemmas/leads.yaml"],
        "lemma_mine": [
            "uo/*.uo",
            "tg/closure/lemmas/leads.yaml",
            "tg/closure/lemmas/evidence/**",
            "runs/**/actions/lemma_mine/**",
        ],
        "lemma_verify": [
            "runs/**/actions/lemma_mine/**",
            "tg/closure/**",
        ],
        "lemma_review": [
            "uo/*.uo",
            "runs/**/actions/lemma_mine/**",
            "runs/**/actions/lemma_verify/**",
            "tg/closure/lemmas/**",
        ],
        "lemma_apply": [
            "runs/**/actions/lemma_review/review.yaml",
            "tg/closure/lemmas/**",
            "local/**",
        ],
        "lemma_loop": [
            "uo/*.uo",
            "tg/closure/**",
            "runs/**/actions/lemma_mine/**",
            "runs/**/actions/lemma_review/**",
        ],
        "closure_audit": ["uo/*.uo", "tg/closure/**"],
        "closure_certify": [
            "tg/closure/**",
            "runs/**/actions/closure_audit/review.yaml",
        ],
    },
    "ce-review": {
        "code_review": [
            "uo/**",
            "ce/**",
            "runs/**",
            "context/**",
            "skills/code-review/**",
        ],
    },
    "ce-impact": {
        "change_capture": ["context/**", "source/**"],
        "uo_freshness": ["uo/*.uo", "ce/impact/change_capture.yaml"],
        "impact_slice": ["uo/*.uo", "ce/impact/change_capture.yaml", "ce/impact/freshness.yaml"],
        "risk_classify": ["ce/impact/impact_slice.yaml"],
        "scenario_infer": [
            "ce/impact/impact_slice.yaml",
            "ce/impact/freshness.yaml",
            "ce/intent/anchors.yaml",
            "uo/*.uo",
        ],
        "scenario_knobs": [
            "ce/scenarios/scenario_set.yaml",
            "ce/impact/**",
            "uo/*.uo",
            "skills/code-engineering/**",
            "skills/testcase-generation/**",
        ],
        "scenario_apply": [
            "ce/scenarios/scenario_set.yaml",
            "runs/{run_id}/actions/scenario_knobs/**",
        ],
        "scenario_confirm": ["ce/scenarios/**"],
        "obligation_build": ["ce/impact/impact_slice.yaml", "ce/impact/risk_classification.yaml"],
        "impact_audit": ["uo/*.uo", "ce/impact/**", "ce/scenarios/**", "runs/**", "context/**"],
    },
    "ce-verify": {
        "verify_gate": ["uo/*.uo", "ce/impact/**"],
        "code_review": ["uo/*.uo", "ce/impact/**", "ce/verify/**", "context/**"],
        "coverage_bridge": ["ce/impact/**", "tg/closure/**"],
        "residual_analyse": ["ce/impact/**", "ce/verify/**"],
        "harness_evidence": [
            "ce/impact/**",
            "ce/scenarios/**",
            "ce/verify/**",
            "tg/closure/scenarios/**",
            "local/**",
        ],
        "harness_evidence_check": [
            "ce/impact/**",
            "ce/scenarios/**",
            "ce/verify/**",
            "tg/closure/scenarios/**",
        ],
        "external_ingest": ["ce/impact/**", "ce/verify/**", "context/**", "local/**"],
        "exclusion_review": ["uo/*.uo", "ce/impact/**", "ce/verify/**", "runs/**"],
        "ce_certify": ["ce/impact/**", "ce/verify/**"],
    },
    "ce-intent": {
        "intent_capture": ["context/**"],
        "kb_check": ["uo/*.uo"],
        "intent_grill": ["uo/*.uo", "ce/intent/**", "context/**", "runs/**"],
        "grill_promote": ["ce/intent/intent.yaml", "runs/**"],
        "grill_confirm": ["ce/intent/**"],
        "feature_decompose": ["uo/*.uo", "ce/intent/**", "context/**", "runs/**"],
        "anchor_locate": ["uo/*.uo", "ce/intent/**", "runs/**"],
        "scenario_infer": ["uo/*.uo", "ce/intent/**", "ce/impact/**"],
        "plan_review": ["uo/*.uo", "ce/intent/**", "runs/**"],
        "feature_promote": ["ce/intent/plan_review.yaml", "runs/**"],
        "human_confirm": ["ce/intent/**"],
    },
    "ce-apply": {
        "apply_gate": ["ce/intent/**"],
        "patch": [
            "uo/*.uo",
            "ce/intent/**",
            "ce/apply/**",
            "source:op_host/**",
            "source:op_kernel/**",
            "source:common/**",
            "runs/**",
            "context/**",
        ],
        "change_capture": ["context/**", "source/**"],
        "patch_guard": ["ce/apply/**", "ce/intent/anchors.yaml"],
        "code_review": [
            "uo/**",
            "ce/**",
            "runs/**",
            "context/**",
            "skills/code-review/**",
        ],
        "codemap_refresh": ["uo/**", "ce/apply/**"],
        "apply_report": ["ce/apply/**", "ce/review/**", "uo/checks/**", "ce/intent/**"],
    },
    "ce-handoff": {
        "session_handoff": [
            "ce/intent/**",
            "ce/review/**",
            "ce/apply/**",
            "ce/session_handoff.md",
            "uo/*.uo",
            "context/**",
        ],
    },
}
ACTION_FORBIDDEN_READ_PATHS: dict[str, dict[str, list[str]]] = {
    "uo-init": {},
}
STAGING_RELATIONS_NAME = "staging/semantic_relations.yaml"
STAGING_RELATIONS_BASE_NAME = "staging/semantic_relations.base.yaml"

_UNRESOLVED_RE = re.compile(r"\[UNRESOLVED:[A-Z][A-Z0-9_]{2,}\]")
_ANGLE_TOKEN_RE = re.compile(r"<([A-Z][A-Z0-9_]{2,})>")


def infer_execution_mode(
    *,
    agent_id: str | None,
    role_id: str | None,
    execution_mode: str | None = None,
) -> str:
    if execution_mode:
        mode = str(execution_mode).strip().lower()
        if mode not in EXECUTION_MODES:
            raise ValueError(f"unknown execution_mode: {execution_mode!r}")
        return mode
    if role_id == "deterministic_engine":
        return EXECUTION_DETERMINISTIC
    if not agent_id or agent_id == PRIMARY_AGENT_ID:
        return EXECUTION_PRIMARY_INTERACTIVE
    return EXECUTION_SUBAGENT


def action_write_paths(workflow_id: str, action_id: str, *, run_id: str = "") -> list[str]:
    rows = (ACTION_WRITE_PATHS.get(workflow_id) or {}).get(action_id) or []
    return [expand_path_template(p, run_id=run_id) for p in rows]


def action_producer_write_paths(workflow_id: str, action_id: str, *, run_id: str = "") -> list[str]:
    rows = (ACTION_PRODUCER_WRITE_PATHS.get(workflow_id) or {}).get(action_id) or []
    if rows:
        return [expand_path_template(p, run_id=run_id) for p in rows]
    return action_write_paths(workflow_id, action_id, run_id=run_id)


def action_finalizer_write_paths(workflow_id: str, action_id: str, *, run_id: str = "") -> list[str]:
    rows = (ACTION_FINALIZER_WRITE_PATHS.get(workflow_id) or {}).get(action_id) or []
    if rows:
        return [expand_path_template(p, run_id=run_id) for p in rows]
    return action_write_paths(workflow_id, action_id, run_id=run_id)


def action_read_paths(workflow_id: str, action_id: str, *, run_id: str = "") -> list[str]:
    rows = (ACTION_READ_PATHS.get(workflow_id) or {}).get(action_id) or []
    return [expand_path_template(p, run_id=run_id) for p in rows]


def action_forbidden_read_paths(workflow_id: str, action_id: str, *, run_id: str = "") -> list[str]:
    rows = (ACTION_FORBIDDEN_READ_PATHS.get(workflow_id) or {}).get(action_id) or []
    return [expand_path_template(p, run_id=run_id) for p in rows]


def shard_producer_write_paths(
    workflow_id: str,
    action_id: str,
    *,
    run_id: str,
    shard_id: str,
) -> list[str]:
    """Narrow Map-worker lease to one shard part + scratch."""
    sid = str(shard_id or "").strip()
    if not sid:
        return action_producer_write_paths(workflow_id, action_id, run_id=run_id)
    return [
        expand_path_template(
            f"runs/{{run_id}}/actions/{action_id}/parts/part_{sid}.yaml",
            run_id=run_id,
        ),
        expand_path_template(
            f"runs/{{run_id}}/actions/{action_id}/scratch/{sid}/**",
            run_id=run_id,
        ),
    ]


def shard_producer_read_paths(
    workflow_id: str,
    action_id: str,
    *,
    run_id: str,
    shard_id: str,
    batch_name: str = "",
) -> list[str]:
    """Narrow Map-worker reads to assigned batch + own part (rework)."""
    sid = str(shard_id or "").strip()
    batch = str(batch_name or f"batch_{sid}.yaml").strip()
    paths = [
        expand_path_template(
            f"runs/{{run_id}}/actions/{action_id}/semantic_batches.yaml",
            run_id=run_id,
        ),
        expand_path_template(
            f"runs/{{run_id}}/actions/{action_id}/batches/{batch}",
            run_id=run_id,
        ),
    ]
    if sid:
        paths.append(
            expand_path_template(
                f"runs/{{run_id}}/actions/{action_id}/parts/part_{sid}.yaml",
                run_id=run_id,
            )
        )
        paths.append(
            expand_path_template(
                f"runs/{{run_id}}/actions/{action_id}/scratch/{sid}/**",
                run_id=run_id,
            )
        )
    paths.extend(action_read_paths(workflow_id, action_id, run_id=run_id))
    return paths


def shard_producer_forbidden_read_paths(
    workflow_id: str,
    action_id: str,
    *,
    run_id: str,
    shard_id: str = "",
) -> list[str]:
    """Cross-shard / full-IR reads forbidden for Map workers."""
    _ = workflow_id
    _ = action_id
    _ = run_id
    _ = shard_id
    return []


def expand_path_template(path: str, *, run_id: str = "", **extra: str) -> str:
    mapping = {"run_id": run_id or "", **extra}
    try:
        return path.format(**mapping)
    except (KeyError, ValueError):
        return path


def expand_contract_paths(paths: list[str], *, run_id: str = "", **extra: str) -> list[str]:
    return [expand_path_template(p, run_id=run_id, **extra) for p in paths]


def unresolved_placeholders(text: str) -> list[str]:
    found: list[str] = []
    for m in _UNRESOLVED_RE.finditer(text or ""):
        found.append(m.group(0))
    for m in _ANGLE_TOKEN_RE.finditer(text or ""):
        tok = m.group(1)
        found.append(f"<{tok}>")
    # de-dupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for item in found:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def prompt_has_unresolved(text: str) -> bool:
    return bool(unresolved_placeholders(text))


def build_bundle_identity(
    *,
    run_id: str,
    workflow_id: str,
    phase: str,
    action_id: str,
    actor_id: str,
    role_id: str,
    action_session_id: str = "",
    prepare_nonce: str = "",
    lease_id: str = "",
    execution_mode: str = "",
) -> dict[str, Any]:
    nonce_hash = ""
    if prepare_nonce:
        nonce_hash = hashlib.sha256(prepare_nonce.encode("utf-8")).hexdigest()
    return {
        "run_id": run_id,
        "workflow_id": workflow_id,
        "phase": phase,
        "action_id": action_id,
        "actor_id": actor_id,
        "role_id": role_id,
        "action_session_id": action_session_id,
        "prepare_nonce_hash": nonce_hash,
        "lease_id": lease_id,
        "execution_mode": execution_mode,
    }


def artifact_identity_from_session(
    session: dict[str, Any],
    *,
    source_snapshot_hash: str = "",
    produced_by: str = "pilot-finalizer",
) -> dict[str, Any]:
    identity = dict(session.get("identity") or {})
    if not identity:
        identity = build_bundle_identity(
            run_id=str(session.get("run_id") or ""),
            workflow_id=str(session.get("workflow_id") or ""),
            phase=str(session.get("phase") or ""),
            action_id=str(session.get("action_id") or ""),
            actor_id=str(session.get("actor_id") or ""),
            role_id=str(session.get("role_id") or ""),
            action_session_id=str(session.get("action_session_id") or ""),
            prepare_nonce=str(session.get("prepare_nonce") or ""),
            lease_id=str(session.get("lease_id") or ""),
            execution_mode=str(session.get("execution_mode") or ""),
        )
    out = dict(identity)
    out["produced_by"] = produced_by
    if source_snapshot_hash:
        out["source_snapshot_hash"] = source_snapshot_hash
    # Never expose plaintext prepare_nonce in canonical artifacts.
    out.pop("prepare_nonce", None)
    return out


def inject_trusted_identity(doc: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    """Overwrite LLM-declared identity with finalizer-trusted values."""
    out = dict(doc)
    out["artifact_identity"] = dict(identity)
    # Keep top-level mirrors for older readers, but always overwrite from session.
    for key in ("run_id", "workflow_id", "action_id", "actor_id"):
        if identity.get(key):
            out[key] = identity[key]
    return out


def path_matches_patterns(rel_posix: str, patterns: list[str]) -> bool:
    """Match a `.ascendc-pilot`-relative posix path against lease patterns."""
    rel = rel_posix.replace("\\", "/").lstrip("/")
    for pat in patterns:
        p = str(pat or "").replace("\\", "/").lstrip("/")
        if not p:
            continue
        if p.endswith("/**"):
            prefix = p[:-3].rstrip("/")
            # Literal directory ceiling (no mid-path globs).
            if prefix and not any(ch in prefix for ch in "*?["):
                if rel == prefix or rel.startswith(prefix + "/"):
                    return True
                continue
            # Mid-path globs such as runs/**/actions/** — fall through to regex.
        if "*" in p or "?" in p:
            # ** = any path segment sequence; * = single segment
            rx = re.escape(p).replace(r"\*\*", ".*").replace(r"\*", "[^/]*").replace(r"\?", ".")
            if re.fullmatch(rx, rel):
                return True
            continue
        if rel == p:
            return True
    return False


def _pattern_prefix(pattern: str) -> str:
    """Literal directory prefix of a path pattern (before first glob metachar)."""
    norm = str(pattern or "").replace("\\", "/").lstrip("/")
    parts: list[str] = []
    for part in norm.split("/"):
        if any(ch in part for ch in "*?["):
            break
        parts.append(part)
    return "/".join(parts)


def path_within_scopes(path_or_pattern: str, scopes: list[str], *, run_id: str = "_RUN_") -> bool:
    """True if a concrete path or glob pattern is covered by ceiling scopes.

    Used for Action ⊆ Agent ⊆ Workflow ownership audits.

    Scope namespaces (``pilot:`` / ``method:`` / ``source:``) are part of the
    ownership type — patterns only compare within the same namespace. Bare
    legacy paths normalize to ``pilot:`` (or ``method:`` / ``source:`` via
    ``split_scope_ns`` heuristics).
    """
    if not scopes:
        return False
    from ascendc_pilot.agents_registry import split_scope_ns

    path_ns, path_raw = split_scope_ns(str(path_or_pattern or ""))
    rel = expand_path_template(path_raw, run_id=run_id or "_RUN_").replace("\\", "/").lstrip("/")

    ceilings: list[tuple[str, str]] = []
    for s in scopes:
        if not str(s or "").strip():
            continue
        c_ns, c_raw = split_scope_ns(str(s))
        c_pat = expand_path_template(c_raw, run_id=run_id or "_RUN_").replace("\\", "/").lstrip("/")
        ceilings.append((c_ns, c_pat))
    if not ceilings:
        return False

    same = [(ns, pat) for ns, pat in ceilings if ns == path_ns]
    if not same:
        return False

    # Universal ceilings cover every path / pattern in this namespace.
    if any(pat in {"**", "*", "**/**"} for _ns, pat in same):
        return True

    same_pats = [pat for _ns, pat in same]

    # Concrete file / already-expanded path.
    if "*" not in rel and "?" not in rel and "[" not in rel:
        return path_matches_patterns(rel, same_pats)
    # Pattern ⊆ ceiling: prefix of the narrower pattern must match a ceiling.
    prefix = _pattern_prefix(rel)
    if prefix and path_matches_patterns(prefix, same_pats):
        return True
    for c in same_pats:
        c_prefix = _pattern_prefix(c)
        if not c_prefix:
            if c in {"**", "*", "**/**"}:
                return True
            continue
        if prefix == c_prefix or (prefix and prefix.startswith(c_prefix + "/")):
            return True
        if c.endswith("/**") and prefix and (prefix == c[:-3] or prefix.startswith(c[:-3] + "/")):
            return True
        # Exact pattern match after namespace strip (pilot:uo/** vs uo/**).
        if rel == c:
            return True
    return False


def write_roots_as_scopes(write_roots: list[str]) -> list[str]:
    """Expand workflow write_roots into patterns usable by ``path_within_scopes``."""
    out: list[str] = []
    for root in write_roots or []:
        r = str(root or "").replace("\\", "/").strip("/")
        if not r:
            continue
        out.append(r)
        if not r.endswith("/**"):
            out.append(f"{r}/**")
    return out


def action_session_id(run_id: str, action_id: str, prepare_nonce: str) -> str:
    raw = f"{run_id}:{action_id}:{prepare_nonce}"
    return f"ACTION_SESSION_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def staging_dir(session_dir: Path) -> Path:
    return Path(session_dir) / "staging"


def staging_output_path(session_dir: Path) -> Path:
    """Relation Graph 权威 staging 路径（不再使用 output.yaml）。"""
    return Path(session_dir) / STAGING_RELATIONS_NAME


__all__ = [
    "ACTION_FINALIZER_WRITE_PATHS",
    "ACTION_FORBIDDEN_READ_PATHS",
    "ACTION_PRODUCER_WRITE_PATHS",
    "ACTION_READ_PATHS",
    "ACTION_WRITE_PATHS",
    "EXECUTION_DETERMINISTIC",
    "EXECUTION_MODES",
    "EXECUTION_PRIMARY_INTERACTIVE",
    "EXECUTION_SUBAGENT",
    "PRIMARY_AGENT_ID",
    "STAGING_RELATIONS_NAME",
    "STAGING_RELATIONS_BASE_NAME",
    "action_finalizer_write_paths",
    "action_forbidden_read_paths",
    "action_producer_write_paths",
    "action_read_paths",
    "action_session_id",
    "action_write_paths",
    "artifact_identity_from_session",
    "build_bundle_identity",
    "expand_contract_paths",
    "expand_path_template",
    "infer_execution_mode",
    "inject_trusted_identity",
    "path_matches_patterns",
    "path_within_scopes",
    "prompt_has_unresolved",
    "shard_producer_forbidden_read_paths",
    "shard_producer_read_paths",
    "shard_producer_write_paths",
    "staging_dir",
    "staging_output_path",
    "unresolved_placeholders",
    "write_roots_as_scopes",
]
