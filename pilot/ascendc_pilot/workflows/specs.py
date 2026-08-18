"""Concrete workflow specs (English ids + Chinese labels)."""

from __future__ import annotations

from typing import Any

# Shared stable policies for model-facing semantic Actions. Deterministic
# engines get ``[]`` — they are not LLM context.
DEFAULT_POLICY_IDS: list[str] = [
    "source-authority",
    "code-access",
    "evidence",
    "output-quality",
]
DEFAULT_PRODUCER_POLICY_IDS: list[str] = [
    "source-authority",
    "evidence",
    "output-quality",
]
DEFAULT_PRIMARY_POLICY_IDS: list[str] = [
    "pilot-control",
    "language",
]

# Optional global capabilities merged into every action (prepended, de-duped).
# Keep empty unless a capability is truly universal; prefer per-action lists.
DEFAULT_CAPABILITY_IDS: list[str] = []


def _default_policy_ids(
    *,
    execution_mode: str,
    role_id: str | None,
    output_mode: str | None,
) -> list[str]:
    mode = str(execution_mode or "").strip()
    if mode == "deterministic" or role_id == "deterministic_engine":
        return []
    if mode == "primary_interactive" or role_id == "controller":
        return list(DEFAULT_PRIMARY_POLICY_IDS)
    if str(output_mode or "") == "staged" or role_id == "producer":
        return list(DEFAULT_PRODUCER_POLICY_IDS)
    return list(DEFAULT_POLICY_IDS)


def _merge_capability_ids(capability_ids: list[str] | None) -> list[str]:
    """Merge DEFAULT_CAPABILITY_IDS with per-action ids (defaults first, de-duped)."""
    merged: list[str] = []
    for cid in list(DEFAULT_CAPABILITY_IDS) + list(capability_ids or []):
        if cid and cid not in merged:
            merged.append(cid)
    return merged


def _st(sid: str, label_zh: str) -> dict[str, str]:
    return {"id": sid, "label_zh": label_zh}


def _tr(frm: str, to: str, *, kind: str = "forward", reason_codes: list[str] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"from": frm, "to": to, "kind": kind}
    if reason_codes:
        row["reason_codes"] = reason_codes
    return row


def _act(
    action_id: str,
    *,
    label_zh: str,
    phases: list[str],
    workflow_id: str,
    checker_required: bool = True,
    referee_required: bool = False,
    pre_gates: list[str] | None = None,
    post_gates: list[str] | None = None,
    agent_id: str | None = None,
    role_id: str | None = None,
    execution_mode: str | None = None,
    human_interaction: str = "none",
    policy_ids: list[str] | None = None,
    capability_ids: list[str] | None = None,
    action_method_id: str | None = None,
    task_prompt_id: str | None = None,
    context_profile_id: str | None = None,
    output_contract_id: str | None = None,
    output_mode: str | None = None,
    staging_contract_id: str | None = None,
    merge_action_id: str | None = None,
    allowed_write_paths: list[str] | None = None,
    allowed_read_paths: list[str] | None = None,
    forbidden_write_paths: list[str] | None = None,
    forbidden_read_paths: list[str] | None = None,
    produces: list[str] | None = None,
    consumes: list[str] | None = None,
    consumes_state: list[str] | None = None,
    execution_variant: str | None = None,
    schema_version: str = "1",
) -> dict[str, Any]:
    """Declare a Pilot Action with compositional references.

    ``actors`` is derived from ``agent_id`` for authorize / spawn checks.
    Workflow Spec is the sole editable authority for identity fields.
    ``human_interaction`` is ``none`` | ``confirm`` | ``approve``.
    ``pre_gates`` run before the actor and contribute DAG consumes.
    ``post_gates`` run after finalize and must not be inferred as consumes.
    ``produces`` / ``consumes`` are optional Producer/Consumer DAG edges;
    when ``produces`` is omitted (None), artifact_dag auto-fills from contracts.
    ``consumes_state`` lists run-state fields the deterministic engine reads
    besides identity (``run_id`` / ``op_name`` / ``architecture`` / ``workflow_id``).
    """
    from ascendc_pilot.ownership import (
        ACTION_FORBIDDEN_READ_PATHS,
        ACTION_FINALIZER_WRITE_PATHS,
        ACTION_PRODUCER_WRITE_PATHS,
        ACTION_READ_PATHS,
        ACTION_WRITE_PATHS,
        infer_execution_mode,
    )

    hi = str(human_interaction or "none").strip().lower()
    if hi not in {"none", "confirm", "approve"}:
        raise ValueError(f"{workflow_id}/{action_id}: invalid human_interaction={human_interaction!r}")
    method_id = str(action_method_id or "").strip() or None
    actors = [agent_id] if agent_id else []
    mode = infer_execution_mode(
        agent_id=agent_id,
        role_id=role_id,
        execution_mode=execution_mode,
    )
    writes = allowed_write_paths
    if writes is None:
        if output_mode == "staged" and role_id == "producer":
            writes = list((ACTION_PRODUCER_WRITE_PATHS.get(workflow_id) or {}).get(action_id) or [])
        if not writes:
            writes = list((ACTION_WRITE_PATHS.get(workflow_id) or {}).get(action_id) or [])
    reads = allowed_read_paths
    if reads is None:
        reads = list((ACTION_READ_PATHS.get(workflow_id) or {}).get(action_id) or [])
    forbid_reads = forbidden_read_paths
    if forbid_reads is None:
        forbid_reads = list((ACTION_FORBIDDEN_READ_PATHS.get(workflow_id) or {}).get(action_id) or [])
    # Staged producers must not write finalizer canonical paths.
    forbid_writes = list(forbidden_write_paths or [])
    if output_mode == "staged" and role_id == "producer":
        for p in (ACTION_FINALIZER_WRITE_PATHS.get(workflow_id) or {}).get(action_id) or []:
            if p not in forbid_writes:
                forbid_writes.append(p)
    row: dict[str, Any] = {
        "id": action_id,
        "label_zh": label_zh,
        "phases": list(phases),
        "checker_required": checker_required,
        "referee_required": referee_required,
        "pre_gates": list(pre_gates or []),
        "post_gates": list(post_gates or []),
        "agent_id": agent_id,
        "role_id": role_id,
        "execution_mode": mode,
        "human_interaction": hi,
        "policy_ids": list(
            policy_ids
            if policy_ids is not None
            else _default_policy_ids(
                execution_mode=mode,
                role_id=role_id,
                output_mode=output_mode,
            )
        ),
        "capability_ids": _merge_capability_ids(capability_ids),
        "action_method_id": method_id,
        "task_prompt_id": task_prompt_id,
        # Omit / explicit None for unregistered Actions. Never fabricate a
        # "{workflow}-{action}" id that is not in context.profiles.PROFILES.
        "context_profile_id": context_profile_id,
        "output_contract_id": output_contract_id,
        "allowed_write_paths": list(writes or []),
        "allowed_read_paths": list(reads or []),
        "forbidden_write_paths": list(forbid_writes),
        "forbidden_read_paths": list(forbid_reads or []),
        # Derived for authorize / Task spawn (single primary actor).
        "actors": actors,
        "schema_version": str(schema_version or "1"),
        # None → artifact_dag.normalize_produces auto-fills from contracts.
        "produces": list(produces) if produces is not None else None,
        "consumes": list(consumes) if consumes is not None else [],
        "consumes_state": list(consumes_state or []),
    }
    if output_mode:
        row["output_mode"] = output_mode
    if staging_contract_id:
        row["staging_contract_id"] = staging_contract_id
    if merge_action_id:
        row["merge_action_id"] = merge_action_id
    if execution_variant:
        row["execution_variant"] = str(execution_variant)
    return row


# Static obligation id → gate id that settles it when that gate passes.
STATIC_OBLIGATION_GATE_MAP: dict[str, str] = {
    "scope_validated": "scope_receipt",
    "uo_product_ready": "uo_product_ready",
    "kb_integrity_passed": "integrity",
    "kb_ready": "kb_ready",
    "uo_ready": "uo_ready",
    "init_confirmed": "init_confirmed",
    "plan_approved": "plan_approved",
    "worklog_closed": "worklog_closed",
    "closure_soundness": "closure_soundness",
    "impact_ledger_ready": "impact_ledger_ready",
    "obligations_classified": "obligations_classified",
    "ce_certificate_sound": "ce_certificate_sound",
    "scenario_coverage_sound": "scenario_coverage_sound",
}

# Wave 4: ``operator_snapshot`` is a distinct resource (immutable workspace).
# TG solve reads the snapshot; CE apply writes live ``operator_source``.
RESOURCE_SNAPSHOT_ALIASES: dict[str, str] = {}

WORKFLOW_RESOURCES: dict[str, dict[str, list[str]]] = {
    "uo-init": {"read": ["operator_source"], "write": ["uo_product"]},
    "uo-update": {"read": ["operator_source"], "write": ["uo_product"]},
    "uo-query": {"read": ["uo_product"], "write": []},
    "uo-investigate": {"read": ["uo_product"], "write": []},
    "tg-init": {"read": [], "write": ["tg_init"]},
    "tg-plan": {"read": ["tg_init"], "write": ["tg_plan"]},
    "tg-solve": {
        "read": ["uo_product", "operator_snapshot", "replay_runtime", "tg_plan", "tg_init"],
        "write": ["tg_worklog", "tg_cases"],
    },
    "ce-review": {"read": ["uo_product", "operator_source"], "write": []},
    "ce-intent": {"read": ["uo_product"], "write": ["ce_intent"]},
    "ce-apply": {"read": ["uo_product"], "write": ["operator_source"]},
    "ce-handoff": {"read": ["ce_intent"], "write": []},
    "ce-impact": {"read": ["uo_product", "operator_source"], "write": ["ce_impact"]},
    "ce-verify": {"read": ["uo_product", "tg_worklog", "tg_plan", "ce_impact"], "write": ["ce_verify"]},
}


def expand_resource_names(names: list[str] | tuple[str, ...] | set[str]) -> set[str]:
    out: set[str] = set()
    for raw in names or []:
        name = str(raw or "").strip()
        if not name:
            continue
        out.add(name)
        alias = RESOURCE_SNAPSHOT_ALIASES.get(name)
        if alias:
            out.add(alias)
    return out


def workflow_resource_sets(workflow_id: str) -> tuple[set[str], set[str]]:
    row = WORKFLOW_RESOURCES.get(str(workflow_id or "").strip()) or {}
    return expand_resource_names(row.get("read") or []), expand_resource_names(row.get("write") or [])


def resource_sets_conflict(left_id: str, right_id: str) -> bool:
    left_r, left_w = workflow_resource_sets(left_id)
    right_r, right_w = workflow_resource_sets(right_id)
    return bool((left_r & right_w) or (left_w & right_r) or (left_w & right_w))


CLOSED_OBLIGATION_STATUSES = frozenset(
    {
        "resolved",
        "verified",
        "not_applicable",
        "human_required",
        "rejected",
    }
)

_CAPS_INVESTIGATE = [
    "source-reading",
    "source-navigation",
    "kb-query",
    "readonly-source-search",
    "action-scratch",
]
_CAPS_OBLIGATION = ["kb-query"]

# requires_architecture (uo-init / uo-update) and requires_uo_product (tg-* / ce-* /
# uo-query / uo-investigate) are mutually exclusive. The latter inherits <arch>
# from the existing .uo; find_uo_product must not pick candidates[0] across arches.

WORKFLOWS: dict[str, dict[str, Any]] = {
    "uo-init": {
        "slash": "/uo-init",
        "engine": "uo",
        "cognitive_skill_id": "operator-analysis",
        "requires_project": True,
        "requires_architecture": True,
        "requires_uo_product": False,
        "occupancy": "exclusive",
        "occupancy_group": "uo",
        "entry_state": "prepare",
        "terminal_ready_states": ["verify"],
        "retry_budget": 3,
        "states": [
            _st("prepare", "准备 BuildVariant / 范围"),
            _st("extract", "Clang 抽取 CompilerFacts"),
            _st("analyze", "确定性 CodeMap Pass"),
            _st("commit", "写入 <op>.<arch>.uo"),
            _st("verify", "结构合法性校验"),
        ],
        "transitions": [
            _tr("prepare", "extract"),
            _tr("extract", "analyze"),
            _tr("analyze", "commit"),
            _tr("commit", "verify"),
            _tr("extract", "prepare", kind="rework", reason_codes=["SCOPE_REWORK", "SCOPE_FAILED"]),
            _tr("analyze", "extract", kind="rework", reason_codes=["EXTRACT_REWORK"]),
            _tr("commit", "analyze", kind="rework", reason_codes=["INTEGRITY_REWORK", "GAP_REWORK"]),
            _tr("verify", "analyze", kind="rework", reason_codes=["CODEMAP_VERIFY_REWORK"]),
            _tr("verify", "commit", kind="rework", reason_codes=["CODEMAP_COMMIT", "integrity"]),
            _tr("verify", "prepare", kind="rework", reason_codes=["scope", "SCOPE_REWORK"]),
        ],
        "phase_gates": {
            "prepare": ["layout_receipt", "scope_receipt"],
            "extract": ["extract_receipt"],
            "analyze": [],
            "commit": ["uo_product_ready"],
            "verify": [],
        },
        "pipelines": {
            "prepare": ["prepare"],
            "extract": ["extract"],
            "analyze": ["analyze"],
            "commit": ["commit"],
            "verify": ["verify"],
        },
        "complete_gates": ["scope_receipt", "uo_product_ready"],
        "meta": {
            "product": "codemap-uo",
            "canonical_policy": "compiler_plus_deterministic_only",
            "unresolved_policy": "retain",
            "recovery_by_reason": {
                "SCOPE_REWORK": {
                    "type": "transition",
                    "target_phase": "prepare",
                    "next_action": "prepare",
                },
                "EXTRACT_REWORK": {"type": "action", "action_id": "extract"},
                "GAP_REWORK": {"type": "action", "action_id": "analyze"},
                "INTEGRITY_REWORK": {"type": "action", "action_id": "commit"},
                "CODEMAP_VERIFY_REWORK": {
                    "type": "human_required",
                    "diagnosis": "deterministic_verify_failed",
                },
            },
        },
        "actions": [
            _act(
                "prepare",
                label_zh="准备范围与 BuildVariant",
                phases=["prepare"],
                workflow_id="uo-init",
                agent_id=None,
                role_id="deterministic_engine",
                execution_mode="deterministic",
                post_gates=["layout_receipt", "scope_receipt"],
                capability_ids=[],
                task_prompt_id=None,
                output_contract_id="uo-prepare-v1",
            ),
            _act(
                "extract",
                label_zh="Clang 抽取 CompilerFacts",
                phases=["extract"],
                workflow_id="uo-init",
                agent_id=None,
                role_id="deterministic_engine",
                post_gates=["extract_receipt"],
                capability_ids=[],
                task_prompt_id=None,
                output_contract_id="uo-extract-v1",
            ),
            _act(
                "analyze",
                label_zh="确定性 CodeMap Pass",
                phases=["analyze"],
                workflow_id="uo-init",
                agent_id=None,
                role_id="deterministic_engine",
                capability_ids=[],
                task_prompt_id=None,
                output_contract_id="uo-analyze-v1",
            ),
            _act(
                "commit",
                label_zh="写入 <op>.<arch>.uo CodeMap",
                phases=["commit"],
                workflow_id="uo-init",
                agent_id=None,
                role_id="deterministic_engine",
                post_gates=["uo_product_ready"],
                capability_ids=[],
                task_prompt_id=None,
                output_contract_id="uo-commit-v1",
            ),
            _act(
                "verify",
                label_zh="CodeMap 结构合法性校验",
                phases=["verify"],
                workflow_id="uo-init",
                agent_id=None,
                role_id="deterministic_engine",
                referee_required=False,
                capability_ids=[],
                task_prompt_id=None,
                output_contract_id="uo-verify-v1",
            ),
        ],
        "agents": [{"id": "ascendc-pilot", "role": "controller"}],
        "static_obligations": [
            {"id": "scope_validated", "label_zh": "范围已校验"},
            {"id": "uo_product_ready", "label_zh": ".uo CodeMap 已写入"},
        ],
        "dynamic_obligation_sources": ["ir/unresolved.yaml"],
        "write_roots": ["uo", "runs", "state", "context"],
        "reset_policy": {
            "reinit_delete": ["uo"],
            "reinit_preserve": [],
            "reinit_wipe_runs": "current",
            "continue_scrub": "from_contracts",
        },
        "phases": ["prepare", "extract", "analyze", "commit", "verify"],
        "gates": [
            "layout_receipt",
            "scope_receipt",
            "extract_receipt",
            "uo_product_ready",
        ],
    },
    "uo-update": {
        "slash": "/uo-update",
        "engine": "uo",
        "cognitive_skill_id": "operator-analysis",
        "requires_project": True,
        "requires_architecture": True,
        "requires_uo_product": False,
        "occupancy": "exclusive",
        "occupancy_group": "uo",
        "entry_state": "detect",
        "terminal_ready_states": ["diff"],
        "retry_budget": 3,
        "states": [
            _st("detect", "变更检测"),
            _st("plan", "更新计划"),
            _st("apply", "应用变更"),
            _st("export", "导出与校验"),
            _st("diff", "差异摘要"),
        ],
        "transitions": [
            _tr("detect", "plan"),
            _tr("plan", "apply"),
            _tr("apply", "export"),
            _tr("export", "diff"),
            _tr(
                "export",
                "apply",
                kind="rework",
                reason_codes=["EXTRACT_REWORK", "INTEGRITY_REWORK"],
            ),
            _tr("detect", "diff", kind="forward", reason_codes=["DIFF_ONLY"]),
        ],
        "phase_gates": {
            "export": ["integrity"],
        },
        "pipelines": {
            "detect": ["detect_changes"],
            "plan": ["plan_update"],
            "apply": ["apply_update"],
            "export": ["export_integrity"],
            "diff": ["diff_summary"],
        },
        "complete_gates": [
            "integrity",
        ],
        "complete_gates_diff_only": [],
        "actions": [
            _act(
                "detect_changes",
                label_zh="检测源码变更",
                phases=["detect"],
                workflow_id="uo-update",
                agent_id=None,
                role_id="deterministic_engine",
                execution_mode="deterministic",
                capability_ids=[],
                output_contract_id="change-detect-v1",
            ),
            _act(
                "plan_update",
                label_zh="规划 CodeMap 增量更新",
                phases=["plan"],
                workflow_id="uo-update",
                agent_id=None,
                role_id="deterministic_engine",
                execution_mode="deterministic",
                capability_ids=[],
                output_contract_id="update-plan-v1",
            ),
            _act(
                "apply_update",
                label_zh="应用 CodeMap 增量更新",
                phases=["apply"],
                workflow_id="uo-update",
                agent_id=None,
                role_id="deterministic_engine",
                execution_mode="deterministic",
                capability_ids=[],
                output_contract_id="update-apply-v1",
            ),
            _act(
                "export_integrity",
                label_zh="校验 CodeMap 完整性",
                phases=["export"],
                workflow_id="uo-update",
                agent_id=None,
                role_id="deterministic_engine",
                execution_mode="deterministic",
                post_gates=["integrity"],
                capability_ids=[],
                output_contract_id="integrity-v1",
            ),
            _act(
                "diff_summary",
                label_zh="CodeMap 差异摘要",
                phases=["diff", "detect"],
                workflow_id="uo-update",
                checker_required=False,
                agent_id=None,
                role_id="deterministic_engine",
                execution_mode="deterministic",
                capability_ids=[],
                output_contract_id="diff-summary-v1",
            ),
            _act(
                "diff_only",
                label_zh="仅生成 CodeMap 差异摘要",
                phases=["detect", "diff"],
                workflow_id="uo-update",
                checker_required=False,
                agent_id=None,
                role_id="deterministic_engine",
                execution_mode="deterministic",
                capability_ids=[],
                output_contract_id="diff-summary-v1",
            ),
        ],
        "agents": [
            {"id": "deterministic-uo-engine", "role": "deterministic_engine"},
        ],
        "static_obligations": [{"id": "kb_integrity_passed", "label_zh": "完整性通过"}],
        "dynamic_obligation_sources": ["ir/unresolved.yaml"],
        "write_roots": ["uo", "runs", "state", "context"],
        "reset_policy": {
            "reinit_delete": [
                "uo/diff",
                "uo/summary/update_plan.yaml",
            ],
            "reinit_preserve": ["uo"],
            "reinit_wipe_runs": "current",
            "continue_scrub": "from_contracts",
        },
        "phases": ["detect", "plan", "apply", "export", "diff"],
        "gates": [
            "integrity",
        ],
    },
    "uo-query": {
        "slash": "/uo-query",
        "engine": "uo",
        "cognitive_skill_id": "operator-analysis",
        # Primary LLM router: classify in the visible chat, then DIY or Task.
        # Host Session Driver must not start / drain this workflow.
        "host_driver": False,
        "requires_project": True,
        "requires_architecture": False,
        "requires_uo_product": True,
        "occupancy": "shared",
        "occupancy_group": "",
        "entry_state": "answer",
        "terminal_ready_states": ["answer"],
        "retry_budget": 3,
        "states": [
            _st("answer", "查询"),
        ],
        "transitions": [],
        "phase_gates": {},
        "complete_gates": [],
        "pipelines": {
            "answer": ["kb_lookup"],
        },
        "actions": [
            _act(
                "kb_lookup",
                label_zh="CodeMap 查询",
                phases=["answer"],
                workflow_id="uo-query",
                agent_id="uo-query",
                role_id="readonly_analyst",
                capability_ids=["kb-query", "source-navigation", "source-reading"],
                action_method_id="operator-analysis/uo-query",
                task_prompt_id="uo/codemap-query",
                context_profile_id="uo-query-kb-lookup",
                output_contract_id="kb-answer-v1",
                # Ephemeral Q&A: child answers in the Task message; primary synthesizes.
                output_mode="return_value",
                execution_variant="delegated_query",
                allowed_write_paths=[
                    "runs/{run_id}/actions/kb_lookup/answer.yaml",
                    "runs/{run_id}/actions/kb_lookup/scratch/**",
                ],
            ),
        ],
        "agents": [{"id": "uo-query", "role": "readonly_analyst"}],
        "static_obligations": [],
        "dynamic_obligation_sources": [],
        "write_roots": ["runs", "context", "memory"],
        "reset_policy": {
            "reinit_delete": [],
            "reinit_preserve": ["uo", "tg", "ce"],
            "reinit_wipe_runs": "current",
            "continue_scrub": "from_contracts",
        },
        "phases": ["answer"],
        "gates": [],
    },
    "uo-investigate": {
        "slash": "/uo-investigate",
        "engine": "uo",
        "cognitive_skill_id": "operator-analysis",
        "requires_project": True,
        "requires_architecture": False,
        "requires_uo_product": True,
        "occupancy": "shared",
        "occupancy_group": "",
        "entry_state": "investigate",
        "terminal_ready_states": ["report"],
        "retry_budget": 2,
        "states": [
            _st("investigate", "调查 unresolved residual"),
            _st("report", "输出调查报告"),
        ],
        "transitions": [
            _tr("investigate", "report"),
        ],
        "phase_gates": {},
        "pipelines": {
            "investigate": ["investigate"],
            "report": [],
        },
        "complete_gates": [],
        "meta": {
            "product": "gap-investigation",
            "canonical_policy": "read_only_no_uo_mutation",
            "purpose": "Classify deterministic-engine gaps; never patch canonical .uo",
        },
        "actions": [
            _act(
                "investigate",
                label_zh="调查 semantic residual",
                phases=["investigate"],
                workflow_id="uo-investigate",
                agent_id="uo-gap-investigator",
                role_id="readonly_analyst",
                execution_mode="subagent",
                capability_ids=_CAPS_INVESTIGATE,
                action_method_id="operator-analysis/uo-investigate",
                task_prompt_id="uo/investigate-gaps",
                context_profile_id="uo-investigate-investigate",
                output_contract_id="uo-investigate-v1",
                allowed_write_paths=[
                    "runs/{run_id}/actions/investigate/parts/**",
                    "runs/{run_id}/actions/investigate/scratch/**",
                    "runs/{run_id}/actions/investigate/report.yaml",
                    "uo/ir/gap_investigation.yaml",
                ],
            ),
        ],
        "agents": [
            {"id": "uo-gap-investigator", "role": "readonly_analyst"},
            {"id": "ascendc-pilot", "role": "controller"},
        ],
        "static_obligations": [],
        "dynamic_obligation_sources": ["ir/unresolved.yaml"],
        "write_roots": ["runs", "context", "uo/ir"],
        "reset_policy": {
            "reinit_delete": [],
            "reinit_preserve": ["uo", "tg", "ce"],
            "reinit_wipe_runs": "current",
            "continue_scrub": "from_contracts",
        },
        "phases": ["investigate", "report"],
        "gates": [],
    },
    "ce-review": {
        "slash": "/ce-review",
        "engine": "ce",
        "cognitive_skill_id": "code-review",
        "requires_project": True,
        "requires_architecture": False,
        "requires_uo_product": True,
        "occupancy": "shared",
        "occupancy_group": "",
        "entry_state": "scope",
        "terminal_ready_states": ["summary"],
        "retry_budget": 3,
        "states": [
            _st("scope", "判定入口与侧别"),
            _st("review", "假设检验"),
            _st("summary", "结论或落盘"),
        ],
        "transitions": [
            _tr("scope", "review"),
            _tr("review", "summary"),
        ],
        "phase_gates": {"scope": ["kb_ready", "context_pack"]},
        "complete_gates": ["kb_ready", "context_pack"],
        "pipelines": {
            "scope": ["code_review"],
            "review": ["code_review"],
            "summary": ["review_persist"],
        },
        "actions": [
            _act(
                "code_review",
                label_zh="代码审查",
                phases=["scope", "review"],
                workflow_id="ce-review",
                agent_id="ce-reviewer",
                role_id="readonly_reviewer",
                capability_ids=["kb-query", "source-navigation", "source-reading"],
                action_method_id="code-review/standalone-review",
                task_prompt_id="ce/standalone-review",
                context_profile_id="ce-review-code-review",
                output_contract_id="code-review-v1",
                pre_gates=["kb_ready", "context_pack"],
            ),
            _act(
                "review_persist",
                label_zh="结论或落盘审查报告",
                phases=["summary"],
                workflow_id="ce-review",
                agent_id="ascendc-pilot",
                role_id="controller",
                execution_mode="primary_interactive",
                human_interaction="confirm",
                capability_ids=[],
                task_prompt_id=None,
                context_profile_id="ce-review-persist",
                output_contract_id="review-persist-v1",
            ),
        ],
        "agents": [
            {"id": "ce-reviewer", "role": "readonly_reviewer"},
            {"id": "ascendc-pilot", "role": "controller"},
        ],
        "static_obligations": [{"id": "kb_ready", "label_zh": "KB 就绪"}],
        "dynamic_obligation_sources": [],
        "write_roots": ["ce/review", "runs", "context"],
        "reset_policy": {
            "reinit_delete": ["ce/review"],
            "reinit_preserve": ["uo", "tg"],
            "reinit_wipe_runs": "current",
            "continue_scrub": "from_contracts",
        },
        "phases": ["scope", "review", "summary"],
        "gates": ["kb_ready", "context_pack"],
    },
    "ce-impact": {
        "slash": "/ce-impact",
        "engine": "ce",
        "cognitive_skill_id": "code-engineering",
        "requires_project": True,
        "requires_architecture": False,
        "requires_uo_product": True,
        "occupancy": "exclusive",
        "occupancy_group": "ce-impact",
        "entry_state": "capture",
        "terminal_ready_states": ["audit"],
        "retry_budget": 3,
        "states": [
            _st("capture", "捕获变更"),
            _st("freshness", "校验 CodeMap 新鲜度"),
            _st("slice", "计算影响切片"),
            _st("classify", "风险分类"),
            _st("scenarios", "推断精度性能场景"),
            _st("obligations", "建立验证义务"),
            _st("audit", "审计影响账本"),
        ],
        "transitions": [
            _tr("capture", "freshness"),
            _tr("freshness", "slice"),
            _tr("slice", "classify"),
            _tr("classify", "scenarios"),
            _tr("scenarios", "obligations"),
            _tr("obligations", "audit"),
            _tr("audit", "obligations", kind="rework", reason_codes=["OBLIGATION_REWORK"]),
        ],
        "phase_gates": {
            "freshness": ["kb_ready"],
            "obligations": ["obligations_classified"],
            "audit": ["impact_ledger_ready"],
        },
        "complete_gates": ["kb_ready", "obligations_classified", "impact_ledger_ready"],
        "pipelines": {
            "capture": ["change_capture"],
            "freshness": ["uo_freshness"],
            "slice": ["impact_slice"],
            "classify": ["risk_classify"],
            "scenarios": ["scenario_infer"],
            "obligations": ["obligation_build"],
            "audit": ["impact_audit"],
        },
        "meta": {
            "recovery_by_reason": {
                "OBLIGATION_REWORK": {"type": "phase", "phase": "obligations"},
            },
        },
        "actions": [
            _act(
                "change_capture",
                label_zh="捕获可复现变更",
                phases=["capture"],
                workflow_id="ce-impact",
                agent_id="deterministic-ce-engine",
                role_id="deterministic_engine",
                capability_ids=[],
                output_contract_id="change-capture-v1",
            ),
            _act(
                "uo_freshness",
                label_zh="校验 CodeMap 指纹",
                phases=["freshness"],
                workflow_id="ce-impact",
                agent_id="deterministic-ce-engine",
                role_id="deterministic_engine",
                pre_gates=["kb_ready"],
                capability_ids=["kb-query"],
                output_contract_id="uo-freshness-v1",
                consumes_state=["pinned_digest"],
            ),
            _act(
                "impact_slice",
                label_zh="生成变更影响切片",
                phases=["slice"],
                workflow_id="ce-impact",
                agent_id="deterministic-ce-engine",
                role_id="deterministic_engine",
                capability_ids=["kb-query"],
                output_contract_id="impact-slice-v1",
            ),
            _act(
                "risk_classify",
                label_zh="分类影响风险",
                phases=["classify"],
                workflow_id="ce-impact",
                agent_id="deterministic-ce-engine",
                role_id="deterministic_engine",
                capability_ids=[],
                output_contract_id="risk-classify-v1",
            ),
            _act(
                "scenario_infer",
                label_zh="推断精度性能场景骨架",
                phases=["scenarios"],
                workflow_id="ce-impact",
                agent_id="deterministic-ce-engine",
                role_id="deterministic_engine",
                capability_ids=["kb-query"],
                output_contract_id="ce-scenario-set-v1",
            ),
            _act(
                "scenario_knobs",
                label_zh="补充场景 knobs 与预算",
                phases=["scenarios"],
                workflow_id="ce-impact",
                agent_id="ce-analyst",
                role_id="producer",
                capability_ids=["kb-query", "source-navigation", "source-reading"],
                action_method_id="code-engineering/ce-scenario-knobs",
                task_prompt_id="ce/scenario-knobs",
                context_profile_id="ce-impact-scenario-knobs",
                output_contract_id="ce-scenario-set-v1",
                output_mode="staged",
                staging_contract_id="scenario-knobs-staging-v1",
                merge_action_id="scenario_apply",
            ),
            _act(
                "scenario_apply",
                label_zh="合并场景 knobs 到 ScenarioSet",
                phases=["scenarios"],
                workflow_id="ce-impact",
                agent_id="deterministic-ce-engine",
                role_id="deterministic_engine",
                capability_ids=[],
                output_contract_id="ce-scenario-set-v1",
            ),
            _act(
                "scenario_confirm",
                label_zh="确认精度性能场景",
                phases=["scenarios"],
                workflow_id="ce-impact",
                agent_id="ascendc-pilot",
                role_id="controller",
                execution_mode="primary_interactive",
                human_interaction="confirm",
                capability_ids=[],
                task_prompt_id=None,
                context_profile_id="ce-impact-scenario-confirm",
                output_contract_id="scenario-confirm-v1",
            ),
            _act(
                "obligation_build",
                label_zh="建立验证义务账本",
                phases=["obligations"],
                workflow_id="ce-impact",
                agent_id="deterministic-ce-engine",
                role_id="deterministic_engine",
                post_gates=["obligations_classified"],
                capability_ids=[],
                output_contract_id="obligation-ledger-v1",
            ),
            _act(
                "impact_audit",
                label_zh="审计影响与验证义务",
                phases=["audit"],
                workflow_id="ce-impact",
                agent_id="ce-change-referee",
                role_id="referee",
                referee_required=True,
                pre_gates=["impact_ledger_ready"],
                capability_ids=["kb-query", "source-reading"],
                action_method_id="code-engineering/ce-impact-audit",
                task_prompt_id="ce/impact-audit",
                context_profile_id="ce-impact-impact-audit",
                output_contract_id="impact-audit-v1",
            ),
        ],
        "agents": [
            {"id": "deterministic-ce-engine", "role": "deterministic_engine"},
            {"id": "ce-change-referee", "role": "referee"},
            {"id": "ce-analyst", "role": "producer"},
            {"id": "ascendc-pilot", "role": "controller"},
        ],
        "static_obligations": [
            {"id": "impact_ledger_ready", "label_zh": "影响账本已建立"},
            {"id": "obligations_classified", "label_zh": "验证义务已分类"},
        ],
        "dynamic_obligation_sources": ["ce/impact/ledger.yaml"],
        "write_roots": ["ce/impact", "ce/scenarios", "runs", "context"],
        "reset_policy": {
            "reinit_delete": ["ce/impact", "ce/scenarios"],
            "reinit_preserve": ["uo", "tg"],
            "reinit_wipe_runs": "current",
            "continue_scrub": "from_contracts",
        },
        "phases": ["capture", "freshness", "slice", "classify", "scenarios", "obligations", "audit"],
        "gates": ["kb_ready", "obligations_classified", "impact_ledger_ready"],
        "mode_overlays": {
            "scenario_targeted": {
                "pipelines": {
                    "capture": ["change_capture"],
                    "freshness": ["uo_freshness"],
                    "slice": ["impact_slice"],
                    "classify": ["risk_classify"],
                    "scenarios": ["scenario_infer", "scenario_knobs", "scenario_apply", "scenario_confirm"],
                    "obligations": ["obligation_build"],
                    "audit": ["impact_audit"],
                },
            },
        },
    },
    "ce-verify": {
        "slash": "/ce-verify",
        "engine": "ce",
        "cognitive_skill_id": "code-engineering",
        "requires_project": True,
        "requires_architecture": False,
        "requires_uo_product": True,
        "occupancy": "exclusive",
        "occupancy_group": "ce-verify",
        "entry_state": "gate",
        "terminal_ready_states": ["certify"],
        "retry_budget": 3,
        "states": [
            _st("gate", "验证前置"),
            _st("review", "义务驱动审查"),
            _st("coverage", "桥接 TG 覆盖证据"),
            _st("residual", "分析剩余义务"),
            _st("external", "摄取外部证据"),
            _st("certify", "签发 CE 证书"),
        ],
        "transitions": [
            _tr("gate", "review"),
            _tr("review", "coverage"),
            _tr("coverage", "residual"),
            _tr("residual", "external"),
            _tr("external", "certify"),
            _tr("certify", "residual", kind="rework", reason_codes=["OBLIGATION_REWORK"]),
        ],
        "phase_gates": {
            "gate": ["impact_ledger_ready"],
            "certify": ["ce_certificate_sound"],
        },
        "complete_gates": ["impact_ledger_ready", "ce_certificate_sound"],
        "pipelines": {
            "gate": ["verify_gate"],
            "review": ["code_review"],
            "coverage": ["coverage_bridge"],
            "residual": ["residual_analyse"],
            "external": ["harness_evidence", "harness_evidence_check", "external_ingest", "exclusion_review"],
            "certify": ["ce_certify"],
        },
        "meta": {
            "recovery_by_reason": {
                "OBLIGATION_REWORK": {"type": "phase", "phase": "residual"},
            },
        },
        "actions": [
            _act(
                "verify_gate",
                label_zh="校验影响账本",
                phases=["gate"],
                workflow_id="ce-verify",
                agent_id="deterministic-ce-engine",
                role_id="deterministic_engine",
                pre_gates=["impact_ledger_ready"],
                capability_ids=[],
                output_contract_id="verify-gate-v1",
            ),
            _act(
                "code_review",
                label_zh="按义务执行代码审查",
                phases=["review"],
                workflow_id="ce-verify",
                agent_id="ce-reviewer",
                role_id="readonly_reviewer",
                capability_ids=["kb-query", "source-navigation", "source-reading"],
                action_method_id="code-review/verify-review",
                task_prompt_id="ce/code-review",
                context_profile_id="ce-verify-code-review",
                output_contract_id="verify-code-review-v1",
            ),
            _act(
                "coverage_bridge",
                label_zh="桥接 TG 覆盖证据",
                phases=["coverage"],
                workflow_id="ce-verify",
                agent_id="deterministic-ce-engine",
                role_id="deterministic_engine",
                capability_ids=[],
                output_contract_id="coverage-bridge-v1",
            ),
            _act(
                "residual_analyse",
                label_zh="分析未闭合验证义务",
                phases=["residual"],
                workflow_id="ce-verify",
                agent_id="deterministic-ce-engine",
                role_id="deterministic_engine",
                capability_ids=[],
                output_contract_id="residual-analysis-v1",
            ),
            _act(
                "harness_evidence",
                label_zh="把测试仓跑测译成验证收据",
                phases=["external"],
                workflow_id="ce-verify",
                agent_id="deterministic-ce-engine",
                role_id="deterministic_engine",
                capability_ids=[],
                output_contract_id="harness-evidence-v1",
            ),
            _act(
                "harness_evidence_check",
                label_zh="核对精度性能收据是否覆盖场景义务",
                phases=["external"],
                workflow_id="ce-verify",
                agent_id="deterministic-ce-engine",
                role_id="deterministic_engine",
                capability_ids=[],
                output_contract_id="harness-evidence-check-v1",
            ),
            _act(
                "external_ingest",
                label_zh="摄取声明的外部证据",
                phases=["external"],
                workflow_id="ce-verify",
                agent_id="deterministic-ce-engine",
                role_id="deterministic_engine",
                capability_ids=[],
                output_contract_id="external-evidence-v1",
            ),
            _act(
                "exclusion_review",
                label_zh="审查义务排除项",
                phases=["external"],
                workflow_id="ce-verify",
                agent_id="ce-change-referee",
                role_id="referee",
                referee_required=True,
                capability_ids=["kb-query", "source-reading"],
                action_method_id="code-engineering/ce-exclusion-review",
                task_prompt_id="ce/exclusion-review",
                context_profile_id="ce-verify-exclusion-review",
                output_contract_id="exclusion-review-v1",
            ),
            _act(
                "ce_certify",
                label_zh="签发 CE 验证证书",
                phases=["certify"],
                workflow_id="ce-verify",
                agent_id="deterministic-ce-engine",
                role_id="deterministic_engine",
                post_gates=["ce_certificate_sound"],
                capability_ids=[],
                output_contract_id="ce-certificate-v1",
            ),
        ],
        "agents": [
            {"id": "deterministic-ce-engine", "role": "deterministic_engine"},
            {"id": "ce-reviewer", "role": "readonly_reviewer"},
            {"id": "ce-change-referee", "role": "referee"},
        ],
        "static_obligations": [
            {"id": "ce_certificate_sound", "label_zh": "CE 验证证书健全"},
        ],
        "dynamic_obligation_sources": ["ce/impact/ledger.yaml", "ce/verify/residual.yaml"],
        "write_roots": ["ce/verify", "runs", "context"],
        "reset_policy": {
            "reinit_delete": ["ce/verify"],
            "reinit_preserve": ["uo", "tg", "ce/impact", "ce/scenarios"],
            "reinit_wipe_runs": "current",
            "continue_scrub": "from_contracts",
        },
        "phases": ["gate", "review", "coverage", "residual", "external", "certify"],
        "gates": ["impact_ledger_ready", "ce_certificate_sound"],
    },
    "ce-intent": {
        "slash": "/ce-intent",
        "engine": "ce",
        "cognitive_skill_id": "code-engineering",
        "requires_project": True,
        "requires_architecture": False,
        "requires_uo_product": True,
        "occupancy": "exclusive",
        "occupancy_group": "ce-intent",
        "entry_state": "intent",
        "terminal_ready_states": ["confirm"],
        "retry_budget": 3,
        "states": [
            _st("intent", "捕获变更意图"),
            _st("kb_ready", "校验知识库"),
            _st("grill", "问清需求"),
            _st("decompose", "分解特性"),
            _st("review", "审查特性分解"),
            _st("locate", "定位代码锚点"),
            _st("confirm", "人工确认"),
        ],
        "transitions": [
            _tr("intent", "kb_ready"),
            _tr("kb_ready", "grill"),
            _tr("grill", "decompose"),
            _tr("decompose", "review"),
            _tr("review", "locate"),
            _tr("locate", "confirm"),
            _tr("grill", "grill", kind="rework", reason_codes=["GRILL_OPEN"]),
        ],
        "phase_gates": {"kb_ready": ["kb_ready"]},
        "complete_gates": ["kb_ready"],
        "pipelines": {
            "intent": ["intent_capture"],
            "kb_ready": ["kb_check"],
            "grill": ["intent_grill", "grill_promote", "grill_confirm"],
            "decompose": ["feature_decompose"],
            "locate": ["anchor_locate", "scenario_infer"],
            "review": ["plan_review", "feature_promote"],
            "confirm": ["human_confirm"],
        },
        "actions": [
            _act(
                "intent_capture",
                label_zh="捕获变更意图",
                phases=["intent"],
                workflow_id="ce-intent",
                agent_id="deterministic-ce-engine",
                role_id="deterministic_engine",
                capability_ids=[],
                output_contract_id="intent-capture-v1",
                consumes_state=["intent", "targets", "constraints"],
            ),
            _act(
                "kb_check",
                label_zh="校验 CodeMap 就绪",
                phases=["kb_ready"],
                workflow_id="ce-intent",
                agent_id="deterministic-ce-engine",
                role_id="deterministic_engine",
                pre_gates=["kb_ready"],
                capability_ids=["kb-query"],
                output_contract_id="intent-kb-check-v1",
            ),
            _act(
                "intent_grill",
                label_zh="问清变更需求",
                phases=["grill"],
                workflow_id="ce-intent",
                agent_id="ce-analyst",
                role_id="producer",
                capability_ids=["kb-query", "source-navigation", "source-reading"],
                action_method_id="code-engineering/ce-intent-grill",
                task_prompt_id="ce/intent-grill",
                context_profile_id="ce-intent-intent-grill",
                output_contract_id="intent-grill-v1",
                output_mode="staged",
                staging_contract_id="intent-grill-staging-v1",
                merge_action_id="grill_promote",
            ),
            _act(
                "grill_promote",
                label_zh="合并问清后的意图字段",
                phases=["grill"],
                workflow_id="ce-intent",
                agent_id="deterministic-ce-engine",
                role_id="deterministic_engine",
                capability_ids=[],
                output_contract_id="intent-grill-v1",
            ),
            _act(
                "grill_confirm",
                label_zh="确认需求已问清",
                phases=["grill"],
                workflow_id="ce-intent",
                agent_id="ascendc-pilot",
                role_id="controller",
                execution_mode="primary_interactive",
                human_interaction="confirm",
                capability_ids=[],
                task_prompt_id=None,
                context_profile_id="ce-intent-grill-confirm",
                output_contract_id="intent-grilled-v1",
            ),
            _act(
                "feature_decompose",
                label_zh="分解变更特性",
                phases=["decompose"],
                workflow_id="ce-intent",
                agent_id="ce-analyst",
                role_id="producer",
                capability_ids=["kb-query", "source-navigation", "source-reading"],
                action_method_id="code-engineering/ce-feature-decompose",
                task_prompt_id="ce/feature-decompose",
                context_profile_id="ce-intent-feature-decompose",
                output_contract_id="feature-decompose-v1",
                output_mode="staged",
                staging_contract_id="feature-decompose-staging-v1",
                merge_action_id="feature_promote",
            ),
            _act(
                "anchor_locate",
                label_zh="定位 CodeMap 锚点",
                phases=["locate"],
                workflow_id="ce-intent",
                agent_id="deterministic-ce-engine",
                role_id="deterministic_engine",
                capability_ids=["kb-query"],
                output_contract_id="anchor-locate-v1",
            ),
            _act(
                "scenario_infer",
                label_zh="从定位锚点推断精度性能场景",
                phases=["locate"],
                workflow_id="ce-intent",
                agent_id="deterministic-ce-engine",
                role_id="deterministic_engine",
                capability_ids=["kb-query"],
                output_contract_id="ce-scenario-set-v1",
            ),
            _act(
                "plan_review",
                label_zh="审查变更计划",
                phases=["review"],
                workflow_id="ce-intent",
                agent_id="ce-change-referee",
                role_id="referee",
                referee_required=True,
                capability_ids=["kb-query", "source-reading"],
                action_method_id="code-engineering/ce-plan-review",
                task_prompt_id="ce/plan-review",
                context_profile_id="ce-intent-plan-review",
                output_contract_id="plan-review-v1",
            ),
            _act(
                "feature_promote",
                label_zh="提升已审特性清单",
                phases=["review"],
                workflow_id="ce-intent",
                agent_id="deterministic-ce-engine",
                role_id="deterministic_engine",
                capability_ids=[],
                output_contract_id="feature-decompose-v1",
            ),
            _act(
                "human_confirm",
                label_zh="确认变更计划",
                phases=["confirm"],
                workflow_id="ce-intent",
                agent_id="ascendc-pilot",
                role_id="controller",
                execution_mode="primary_interactive",
                human_interaction="confirm",
                capability_ids=[],
                task_prompt_id=None,
                context_profile_id="ce-intent-human-confirm",
                output_contract_id="intent-confirmed-v1",
            ),
        ],
        "agents": [
            {"id": "deterministic-ce-engine", "role": "deterministic_engine"},
            {"id": "ce-analyst", "role": "producer"},
            {"id": "ce-change-referee", "role": "referee"},
            {"id": "ascendc-pilot", "role": "controller"},
        ],
        "static_obligations": [],
        "dynamic_obligation_sources": ["ce/intent/feature_decomposition.yaml"],
        "write_roots": ["ce/intent", "ce/scenarios", "ce/session_handoff.md", "runs", "context"],
        "reset_policy": {
            "reinit_delete": ["ce/intent"],
            "reinit_preserve": ["uo", "tg", "ce/impact", "ce/verify", "ce/scenarios"],
            "reinit_wipe_runs": "current",
            "continue_scrub": "from_contracts",
        },
        "phases": ["intent", "kb_ready", "grill", "decompose", "review", "locate", "confirm"],
        "gates": ["kb_ready"],
    },
    "ce-apply": {
        "slash": "/ce-apply",
        "engine": "ce",
        "cognitive_skill_id": "code-engineering",
        "requires_project": True,
        "requires_architecture": False,
        "requires_uo_product": True,
        "occupancy": "exclusive",
        "occupancy_group": "ce-apply",
        "entry_state": "gate",
        "terminal_ready_states": ["report"],
        "retry_budget": 3,
        "states": [
            _st("gate", "校验已确认意图"),
            _st("patch", "按锚点改源码"),
            _st("capture", "捕获改动并校验范围"),
            _st("review", "双轴审查"),
            _st("refresh", "刷新 CodeMap"),
            _st("report", "汇报改动与结论"),
        ],
        "transitions": [
            _tr("gate", "patch"),
            _tr("patch", "capture"),
            _tr("capture", "review"),
            _tr("review", "refresh"),
            _tr("refresh", "report"),
            _tr("capture", "patch", kind="rework", reason_codes=["PATCH_OUT_OF_ANCHORS"]),
        ],
        "phase_gates": {},
        "complete_gates": [],
        "pipelines": {
            "gate": ["apply_gate"],
            "patch": ["patch"],
            "capture": ["change_capture", "patch_guard"],
            "review": ["code_review"],
            "refresh": ["codemap_refresh"],
            "report": ["apply_report"],
        },
        "actions": [
            _act(
                "apply_gate",
                label_zh="校验意图已确认且锚点非空",
                phases=["gate"],
                workflow_id="ce-apply",
                agent_id="deterministic-ce-engine",
                role_id="deterministic_engine",
                capability_ids=[],
                output_contract_id="apply-gate-v1",
            ),
            _act(
                "patch",
                label_zh="按已锁定 spec 改算子源码",
                phases=["patch"],
                workflow_id="ce-apply",
                agent_id="ce-applier",
                role_id="producer",
                capability_ids=["kb-query", "source-navigation", "source-reading"],
                action_method_id="code-engineering/ce-apply",
                task_prompt_id="ce/apply",
                context_profile_id="ce-apply-patch",
                output_contract_id="apply-patch-v1",
            ),
            _act(
                "change_capture",
                label_zh="捕获本次改动",
                phases=["capture"],
                workflow_id="ce-apply",
                agent_id="deterministic-ce-engine",
                role_id="deterministic_engine",
                capability_ids=[],
                output_contract_id="apply-capture-v1",
            ),
            _act(
                "patch_guard",
                label_zh="校验改动落在锚点文件内",
                phases=["capture"],
                workflow_id="ce-apply",
                agent_id="deterministic-ce-engine",
                role_id="deterministic_engine",
                capability_ids=[],
                output_contract_id="apply-patch-guard-v1",
            ),
            _act(
                "code_review",
                label_zh="对照意图做双轴审查",
                phases=["review"],
                workflow_id="ce-apply",
                agent_id="ce-reviewer",
                role_id="readonly_reviewer",
                capability_ids=["kb-query", "source-navigation", "source-reading"],
                action_method_id="code-review/standalone-review",
                task_prompt_id="ce/standalone-review",
                context_profile_id="ce-apply-code-review",
                output_contract_id="code-review-v1",
            ),
            _act(
                "codemap_refresh",
                label_zh="确定性刷新 CodeMap",
                phases=["refresh"],
                workflow_id="ce-apply",
                agent_id="deterministic-ce-engine",
                role_id="deterministic_engine",
                capability_ids=[],
                output_contract_id="codemap-refresh-v1",
            ),
            _act(
                "apply_report",
                label_zh="汇报改动与审查结论",
                phases=["report"],
                workflow_id="ce-apply",
                agent_id="ascendc-pilot",
                role_id="controller",
                execution_mode="primary_interactive",
                human_interaction="confirm",
                capability_ids=[],
                task_prompt_id=None,
                context_profile_id="ce-apply-report",
                output_contract_id="apply-report-v1",
            ),
        ],
        "agents": [
            {"id": "deterministic-ce-engine", "role": "deterministic_engine"},
            {"id": "ce-applier", "role": "producer"},
            {"id": "ce-reviewer", "role": "readonly_reviewer"},
            {"id": "ascendc-pilot", "role": "controller"},
        ],
        "static_obligations": [],
        "dynamic_obligation_sources": [],
        "write_roots": ["ce/apply", "ce/review", "ce/session_handoff.md", "uo", "op_host", "op_kernel", "common", "test_script", "runs", "context"],
        "reset_policy": {
            "reinit_delete": ["ce/apply", "ce/review"],
            "reinit_preserve": ["uo", "tg", "ce/intent", "ce/impact", "ce/verify", "ce/scenarios"],
            "reinit_wipe_runs": "current",
            "continue_scrub": "from_contracts",
        },
        "phases": ["gate", "patch", "capture", "review", "refresh", "report"],
        "gates": [],
    },
    "ce-handoff": {
        "slash": "/ce-handoff",
        "engine": "ce",
        "cognitive_skill_id": "code-engineering",
        "requires_project": True,
        "requires_architecture": False,
        "requires_uo_product": True,
        "occupancy": "shared",
        "occupancy_group": "",
        "entry_state": "session",
        "terminal_ready_states": ["session"],
        "retry_budget": 3,
        "states": [
            _st("session", "写会话交接"),
        ],
        "transitions": [],
        "phase_gates": {},
        "complete_gates": [],
        "pipelines": {
            "session": ["session_handoff"],
        },
        "actions": [
            _act(
                "session_handoff",
                label_zh="写会话交接",
                phases=["session"],
                workflow_id="ce-handoff",
                agent_id="ce-analyst",
                role_id="producer",
                capability_ids=["kb-query"],
                action_method_id="code-engineering/ce-handoff",
                task_prompt_id="ce/handoff",
                context_profile_id="ce-handoff-session",
                output_contract_id="session-handoff-v1",
            ),
        ],
        "agents": [
            {"id": "ce-analyst", "role": "producer"},
            {"id": "ascendc-pilot", "role": "controller"},
        ],
        "static_obligations": [],
        "dynamic_obligation_sources": [],
        "write_roots": ["ce/session_handoff.md", "runs", "context"],
        "reset_policy": {
            "reinit_delete": [],
            "reinit_preserve": ["uo", "tg", "ce"],
            "reinit_wipe_runs": "current",
            "continue_scrub": "from_contracts",
        },
        "phases": ["session"],
        "gates": [],
    }
}


from ascendc_pilot.workflows.tg_specs import attach_tg_workflows

attach_tg_workflows(WORKFLOWS, _act=_act, _st=_st, _tr=_tr)
