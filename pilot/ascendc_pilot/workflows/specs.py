"""Concrete workflow specs (English ids + Chinese labels)."""

from __future__ import annotations

from typing import Any

# Shared stable policies for model-facing semantic Actions. Deterministic
# engines get ``[]`` — they are not LLM context.
DEFAULT_POLICY_IDS: list[str] = [
    "source-authority",
    "code-access",
    "evidence",
    "semantic-grounding",
    "output-quality",
]
DEFAULT_PRODUCER_POLICY_IDS: list[str] = [
    "source-authority",
    "evidence",
    "semantic-grounding",
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
    if mode in {"primary_interactive", "primary_review"} or role_id == "controller":
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
    skill_id: str | None = None,
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
    fanout_axes: list[dict[str, Any]] | None = None,
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
    sid = str(skill_id or action_method_id or "").strip() or None
    if sid and "/" in sid:
        sid = sid.rsplit("/", 1)[-1].strip() or None
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
        "skill_id": sid,
        "action_method_id": sid,
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
    if fanout_axes:
        row["fanout_axes"] = [dict(axis) for axis in fanout_axes]
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
    "ce-plan": {"read": ["uo_product"], "write": ["ce_plan"]},
    "ce-apply": {"read": ["uo_product", "ce_plan"], "write": ["operator_source"]},
    "handoff": {"read": ["uo_product", "ce_plan", "tg_plan", "tg_init"], "write": []},
    "goal-intake": {"read": [], "write": []},
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
            _st("heal", "补 include 路径（脚本失败才进入）"),
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
            _tr(
                "prepare",
                "heal",
                kind="rework",
                reason_codes=["INCLUDE_HEAL_UNRESOLVED"],
            ),
            _tr("heal", "prepare"),
            _tr(
                "heal",
                "prepare",
                kind="rework",
                reason_codes=["INCLUDE_HEAL_PROMOTED"],
            ),
            _tr("extract", "prepare", kind="rework", reason_codes=["SCOPE_REWORK", "SCOPE_FAILED"]),
            _tr("analyze", "extract", kind="rework", reason_codes=["EXTRACT_REWORK"]),
            _tr("commit", "analyze", kind="rework", reason_codes=["INTEGRITY_REWORK", "GAP_REWORK"]),
            _tr("verify", "analyze", kind="rework", reason_codes=["CODEMAP_VERIFY_REWORK"]),
            _tr("verify", "commit", kind="rework", reason_codes=["CODEMAP_COMMIT", "integrity"]),
            _tr("verify", "prepare", kind="rework", reason_codes=["scope", "SCOPE_REWORK"]),
        ],
        "phase_gates": {
            "prepare": ["layout_receipt", "scope_receipt"],
            "heal": [],
            "extract": ["extract_receipt"],
            "analyze": [],
            "commit": ["uo_product_ready"],
            "verify": ["integrity"],
        },
        "pipelines": {
            "prepare": ["prepare"],
            "heal": ["propose_include_heal", "heal_promote"],
            "extract": ["extract"],
            "analyze": ["analyze"],
            "commit": ["commit"],
            "verify": ["verify"],
        },
        "complete_gates": ["scope_receipt", "uo_product_ready", "integrity"],
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
                "INCLUDE_HEAL_UNRESOLVED": {
                    "type": "transition",
                    "target_phase": "heal",
                    "next_action": "propose_include_heal",
                },
                "INCLUDE_HEAL_PROMOTED": {
                    "type": "transition",
                    "target_phase": "prepare",
                    "next_action": "prepare",
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
                "propose_include_heal",
                label_zh="建议补 -I（仅写 staging）",
                phases=["heal"],
                workflow_id="uo-init",
                agent_id="uo-heal-analyst",
                role_id="producer",
                capability_ids=[
                    "source-reading",
                    "source-navigation",
                    "readonly-source-search",
                    "action-scratch",
                ],
                skill_id="propose-include-heal",
                task_prompt_id="uo/propose-include-heal",
                context_profile_id="uo-init-propose-include-heal",
                output_contract_id="include-heal-extras-v1",
                output_mode="staged",
                staging_contract_id="include-heal-staging-v1",
                merge_action_id="heal_promote",
                forbidden_write_paths=[
                    "uo/summary/build_context_extras.yaml",
                    "spec/build_context.yaml",
                ],
            ),
            _act(
                "heal_promote",
                label_zh="校验并写入 extras -I",
                phases=["heal"],
                workflow_id="uo-init",
                agent_id=None,
                role_id="deterministic_engine",
                execution_mode="deterministic",
                capability_ids=[],
                task_prompt_id=None,
                output_contract_id="include-heal-extras-v1",
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
                post_gates=["integrity"],
                capability_ids=[],
                task_prompt_id=None,
                output_contract_id="uo-verify-v1",
            ),
        ],
        "agents": [
            {"id": "ascendc-pilot", "role": "controller"},
            {"id": "uo-heal-analyst", "role": "producer"},
        ],
        "static_obligations": [
            {"id": "scope_validated", "label_zh": "范围已校验"},
            {"id": "uo_product_ready", "label_zh": ".uo CodeMap 已写入"},
            {"id": "kb_integrity_passed", "label_zh": "完整性通过"},
        ],
        "dynamic_obligation_sources": ["ir/unresolved.yaml"],
        "write_roots": ["uo", "runs", "state", "context"],
        "reset_policy": {
            "reinit_delete": ["uo"],
            "reinit_preserve": ["uo/cache"],
            "reinit_wipe_runs": "current",
            "continue_scrub": "from_contracts",
        },
        "phases": ["prepare", "heal", "extract", "analyze", "commit", "verify"],
        "gates": [
            "layout_receipt",
            "scope_receipt",
            "extract_receipt",
            "uo_product_ready",
            "integrity",
        ],
    },
    "uo-update": {
        "slash": "/uo-update",
        "engine": "uo",
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
        # Instant Command: Primary investigates via pilot_cli / Task.
        # Keep this registry row as a shim so start_workflow tests and
        # kb_lookup Task bundles still resolve. Host must not pilot_run it.
        "kind": "command",
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
                skill_id="uo-query",
                task_prompt_id="uo/codemap-query",
                context_profile_id="uo-query-kb-lookup",
                output_contract_id="kb-answer-v1",
                # Ephemeral Q&A: child answers in the Task message; primary synthesizes.
                output_mode="return_value",
                execution_variant="delegated_query",
            ),
        ],
        "agents": [{"id": "uo-query", "role": "readonly_analyst"}],
        "static_obligations": [],
        "dynamic_obligation_sources": [],
        "write_roots": ["runs", "context"],
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
                skill_id="uo-investigate",
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
    }

}

from ascendc_pilot.workflows.tg_specs import attach_tg_workflows
from ascendc_pilot.workflows.ce_specs import attach_ce_workflows
from ascendc_pilot.workflows.goal_specs import attach_goal_workflows

attach_tg_workflows(WORKFLOWS, _act=_act, _st=_st, _tr=_tr)
attach_ce_workflows(WORKFLOWS, _act=_act, _st=_st, _tr=_tr)
attach_goal_workflows(WORKFLOWS, _act=_act, _st=_st, _tr=_tr)
