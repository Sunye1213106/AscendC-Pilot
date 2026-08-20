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
EXECUTION_PRIMARY_REVIEW = "primary_review"
EXECUTION_MODES = frozenset(
    {
        EXECUTION_DETERMINISTIC,
        EXECUTION_SUBAGENT,
        EXECUTION_PRIMARY_INTERACTIVE,
        EXECUTION_PRIMARY_REVIEW,
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
    "uo-init": {
        "propose_include_heal": [
            "runs/{run_id}/actions/propose_include_heal/parts/**",
            "runs/{run_id}/actions/propose_include_heal/scratch/**",
            "runs/{run_id}/actions/propose_include_heal/staging.yaml",
        ],
    },
    "uo-investigate": {
        "investigate": [
            "runs/{run_id}/actions/investigate/parts/**",
            "runs/{run_id}/actions/investigate/scratch/**",
            "runs/{run_id}/actions/investigate/report.yaml",
            "uo/ir/gap_investigation.yaml",
        ],
    },
    "tg-init": {
        "bind_init": [
            "runs/{run_id}/actions/bind_init/parts/**",
            "runs/{run_id}/actions/bind_init/scratch/**",
            "runs/{run_id}/actions/bind_init/staging.yaml",
        ],
    },
    "tg-plan": {
        "plan_fuse": [
            "runs/{run_id}/actions/plan_fuse/parts/**",
            "runs/{run_id}/actions/plan_fuse/scratch/**",
            "runs/{run_id}/actions/plan_fuse/staging.md",
            "runs/{run_id}/actions/plan_fuse/staging.yaml",
        ],
    },
    "tg-solve": {
        "construct_cases": [
            "runs/{run_id}/actions/construct_cases/parts/**",
            "runs/{run_id}/actions/construct_cases/scratch/**",
            "runs/{run_id}/actions/construct_cases/staging.yaml",
        ],
        "analyze_round": [
            "runs/{run_id}/actions/analyze_round/parts/**",
            "runs/{run_id}/actions/analyze_round/scratch/**",
            "runs/{run_id}/actions/analyze_round/staging.md",
            "runs/{run_id}/actions/analyze_round/staging.yaml",
        ],
    },
    "ce-plan": {
        "intent_grill": [
            "runs/{run_id}/actions/intent_grill/parts/**",
            "runs/{run_id}/actions/intent_grill/scratch/**",
            "runs/{run_id}/actions/intent_grill/staging.md",
        ],
        "plan_draft": [
            "ce/plan/*_plan.md",
            "runs/{run_id}/actions/plan_draft/**",
        ],
    },
    "ce-apply": {
        "plan_revise": [
            "ce/plan/*_plan.md",
            "runs/{run_id}/actions/plan_revise/**",
        ],
    },
    "handoff": {
        "session_handoff": [
            "session_handoff.md",
            "runs/{run_id}/actions/session_handoff/**",
        ],
    },
    "goal-intake": {},
}
ACTION_FINALIZER_WRITE_PATHS: dict[str, dict[str, list[str]]] = {
    "uo-init": {
        "heal_promote": ["uo/summary/build_context_extras.yaml"],
    },
    "tg-init": {
        "bind_promote": ["tg/init.yaml"],
        "bind_review": ["runs/{run_id}/actions/bind_review/verdict.yaml"],
    },
    "tg-plan": {
        "plan_promote": ["tg/plan.md"],
        "plan_approve": ["tg/plan.md"],
    },
    "tg-solve": {
        "construct_promote": ["tg/cases.csv", "tg/cases.xls", "tg/cases.xlsx"],
        "analyze_promote": ["tg/worklog.md"],
    },
    "ce-plan": {
        "plan_draft": [
            "ce/plan/*_plan.md",
        ],
    },
    "ce-apply": {
        "plan_revise": [
            "ce/plan/*_plan.md",
        ],
    },
    "handoff": {
        "session_handoff": ["session_handoff.md"],
    },
    "goal-intake": {
        "intent_promote": ["runs/{run_id}/receipts/intent_promoted.yaml"],
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
        "propose_include_heal": [
            "runs/{run_id}/actions/propose_include_heal/parts/**",
            "runs/{run_id}/actions/propose_include_heal/scratch/**",
            "runs/{run_id}/actions/propose_include_heal/staging.yaml",
        ],
        "heal_promote": ["uo/summary/build_context_extras.yaml"],
    },
    "uo-update": {
        "detect_changes": ["uo/diff/**"],
        "plan_update": ["uo/diff/**", "uo/summary/**"],
        "apply_update": [
            "uo/**",
            "uo/*.uo",
        ],
        "export_integrity": ["uo/checks/**"],
        "diff_summary": ["uo/diff/**", "uo/summary/**"],
        "diff_only": ["uo/diff/**", "uo/summary/**"],
    },
    "uo-investigate": {
        "investigate": [
            "runs/{run_id}/actions/investigate/parts/**",
            "runs/{run_id}/actions/investigate/scratch/**",
            "runs/{run_id}/actions/investigate/report.yaml",
            "uo/ir/gap_investigation.yaml",
        ],
    },
    "tg-init": {
        "kb_check": ["runs/{run_id}/receipts/uo_ready.yaml"],
        "repo_scan": ["runs/{run_id}/receipts/repo_scan.yaml"],
        "bind_init": [
            "runs/{run_id}/actions/bind_init/parts/**",
            "runs/{run_id}/actions/bind_init/scratch/**",
            "runs/{run_id}/actions/bind_init/staging.yaml",
        ],
        "bind_review": [],
        "bind_promote": ["tg/init.yaml"],
        "validate_init": ["runs/{run_id}/receipts/validate_init.yaml"],
    },
    "tg-plan": {
        "plan_precheck": ["runs/{run_id}/receipts/plan_precheck.yaml"],
        "plan_fuse": [
            "runs/{run_id}/actions/plan_fuse/parts/**",
            "runs/{run_id}/actions/plan_fuse/scratch/**",
            "runs/{run_id}/actions/plan_fuse/staging.md",
            "runs/{run_id}/actions/plan_fuse/staging.yaml",
        ],
        "plan_promote": ["tg/plan.md"],
        "plan_validate": ["runs/{run_id}/receipts/plan_validate.yaml"],
        "plan_approve": ["tg/plan.md"],
    },
    "tg-solve": {
        "solve_precheck": ["runs/{run_id}/receipts/solve_precheck.yaml"],
        "construct_cases": [
            "runs/{run_id}/actions/construct_cases/parts/**",
            "runs/{run_id}/actions/construct_cases/scratch/**",
            "runs/{run_id}/actions/construct_cases/staging.yaml",
        ],
        "construct_promote": ["tg/cases.csv", "tg/cases.xls", "tg/cases.xlsx"],
        "replay_round": ["runs/{run_id}/receipts/replay_round.yaml"],
        "analyze_round": [
            "runs/{run_id}/actions/analyze_round/parts/**",
            "runs/{run_id}/actions/analyze_round/scratch/**",
            "runs/{run_id}/actions/analyze_round/staging.md",
            "runs/{run_id}/actions/analyze_round/staging.yaml",
        ],
        "analyze_promote": ["tg/worklog.md"],
        "solve_certify": ["runs/{run_id}/receipts/solve_certify.yaml"],
    },
    "goal-intake": {
        "intent_promote": ["runs/{run_id}/receipts/intent_promoted.yaml"],
    },
    "ce-review": {
        "change_capture": [
            "runs/{run_id}/actions/change_capture/**",
        ],
        "code_review": [],
    },
    "ce-plan": {
        "intent_grill": [
            "runs/{run_id}/actions/intent_grill/parts/**",
            "runs/{run_id}/actions/intent_grill/scratch/**",
            "runs/{run_id}/actions/intent_grill/staging.md",
        ],
        "plan_draft": [
            "ce/plan/*_plan.md",
            "runs/{run_id}/actions/plan_draft/**",
        ],
    },
    "ce-apply": {
        "patch": [
            "source:op_host/**",
            "source:op_kernel/**",
            "source:common/**",
            "source:test_script/**",
            "ce/plan/*_plan.md",
            "runs/{run_id}/actions/patch/**",
        ],
        "plan_revise": [
            "ce/plan/*_plan.md",
            "runs/{run_id}/actions/plan_revise/**",
        ],
    },
    "handoff": {
        "session_handoff": ["session_handoff.md"],
    },
}
ACTION_READ_PATHS: dict[str, dict[str, list[str]]] = {
    "uo-init": {
        "prepare": ["uo/**"],
        "extract": ["uo/**"],
        "analyze": ["uo/**"],
        "commit": ["uo/**", "uo/*.uo"],
        "verify": ["uo/**", "uo/*.uo"],
        "propose_include_heal": [
            "uo/summary/scope_candidates.yaml",
            "uo/runs/{run_id}/scope/**",
            "uo/summary/build_context_extras.yaml",
            "runs/{run_id}/actions/propose_include_heal/**",
        ],
        "heal_promote": [
            "uo/summary/build_context_extras.yaml",
            "runs/{run_id}/actions/propose_include_heal/**",
        ],
    },
    "uo-update": {
        "detect_changes": ["uo/**", "uo/*.uo"],
        "plan_update": ["uo/**", "uo/*.uo"],
        "apply_update": ["uo/**", "uo/*.uo"],
        "export_integrity": ["uo/**", "uo/*.uo"],
        "diff_summary": ["uo/**", "uo/*.uo"],
        "diff_only": ["uo/**", "uo/*.uo"],
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
            "context/**",
        ],
    },
    "tg-init": {
        "kb_check": ["uo/*.uo"],
        "repo_scan": ["uo/*.uo", "runs/{run_id}/receipts/uo_ready.yaml", "source:test_script/**"],
        "bind_init": [
            "uo/*.uo",
            "tg/init.yaml",
            "runs/{run_id}/receipts/repo_scan.yaml",
            "runs/{run_id}/actions/bind_init/**",
            "source:test_script/**",
            "context/**",
        ],
        "bind_review": [
            "runs/{run_id}/actions/bind_init/parts/**",
            "runs/{run_id}/receipts/repo_scan.yaml",
            "runs/{run_id}/actions/bind_review/**",
            "uo/*.uo",
            "context/**",
        ],
        "bind_promote": [
            "tg/init.yaml",
            "runs/{run_id}/actions/bind_init/**",
            "runs/{run_id}/actions/bind_review/**",
            "runs/{run_id}/receipts/repo_scan.yaml",
        ],
        "validate_init": ["tg/init.yaml"],
    },
    "goal-intake": {
        "intent_promote": [
            "runs/{run_id}/actions/intent_promote/**",
            "runs/{run_id}/receipts/intent_promoted.yaml",
        ],
    },
    "tg-plan": {
        "plan_precheck": ["uo/*.uo", "tg/init.yaml"],
        "plan_fuse": [
            "uo/*.uo",
            "tg/init.yaml",
            "tg/plan.md",
            "ce/plan/*_plan.md",
            "session_handoff.md",
            "runs/{run_id}/actions/plan_fuse/**",
            "context/**",
        ],
        "plan_promote": ["tg/plan.md", "runs/{run_id}/actions/plan_fuse/**"],
        "plan_validate": ["tg/init.yaml", "tg/plan.md"],
        "plan_approve": ["tg/plan.md", "tg/init.yaml"],
    },
    "tg-solve": {
        "solve_precheck": ["uo/*.uo", "tg/init.yaml", "tg/plan.md"],
        "construct_cases": [
            "uo/*.uo",
            "tg/init.yaml",
            "tg/plan.md",
            "runs/{run_id}/actions/construct_cases/**",
            "source:test_script/**",
        ],
        "construct_promote": [
            "tg/init.yaml",
            "tg/plan.md",
            "runs/{run_id}/actions/construct_cases/**",
        ],
        "replay_round": ["tg/init.yaml", "tg/cases.csv", "tg/cases.xls", "tg/cases.xlsx", "local/**"],
        "analyze_round": [
            "uo/*.uo",
            "tg/init.yaml",
            "tg/plan.md",
            "tg/worklog.md",
            "tg/cases.csv",
            "tg/cases.xls",
            "tg/cases.xlsx",
            "runs/{run_id}/receipts/replay_round.yaml",
            "runs/{run_id}/actions/analyze_round/**",
        ],
        "analyze_promote": ["tg/worklog.md", "runs/{run_id}/actions/analyze_round/**"],
        "solve_certify": ["tg/worklog.md", "tg/plan.md", "tg/cases.csv", "tg/cases.xls", "tg/cases.xlsx"],
    },
    "ce-review": {
        "change_capture": ["context/**", "source/**"],
        "code_review": [
            "uo/*.uo",
            "ce/plan/**",
            "source:op_host/**",
            "source:op_kernel/**",
            "source:common/**",
            "source:tests/**",
            "runs/**",
            "context/**",
            "skills/code-review/**",
        ],
        "review_report": [
            "ce/plan/**",
            "runs/{run_id}/actions/code_review/**",
        ],
    },
    "ce-plan": {
        "kb_check": ["uo/*.uo"],
        "intent_grill": ["uo/*.uo", "ce/plan/**", "context/**", "runs/**"],
        "grill_promote": ["runs/{run_id}/actions/intent_grill/**"],
        "grill_confirm": ["ce/plan/**", "runs/{run_id}/actions/intent_grill/**"],
        "plan_draft": ["uo/*.uo", "ce/plan/**", "context/**", "runs/**"],
        "human_confirm": ["ce/plan/**"],
    },
    "ce-apply": {
        "apply_gate": ["ce/plan/**"],
        "patch": [
            "uo/*.uo",
            "ce/plan/**",
            "source:op_host/**",
            "source:op_kernel/**",
            "source:common/**",
            "source:test_script/**",
            "runs/**",
            "context/**",
        ],
        "patch_guard": ["ce/plan/**", "source/**"],
        "codemap_refresh": ["uo/**"],
        "apply_report": ["ce/plan/**", "uo/checks/**"],
        "plan_revise": ["uo/*.uo", "ce/plan/**", "context/**", "runs/**"],
        "plan_revise_check": ["ce/plan/**", "runs/{run_id}/actions/plan_revise/**"],
    },
    "handoff": {
        "session_handoff": [
            "ce/plan/**",
            "session_handoff.md",
            "tg/init.yaml",
            "tg/plan.md",
            "tg/worklog.md",
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


def write_paths_overlap(left: str, right: str) -> bool:
    """Glob-aware overlap: exact, pattern-match, or shared /** prefix."""
    a = str(left or "").replace("\\", "/").lstrip("/")
    b = str(right or "").replace("\\", "/").lstrip("/")
    if not a or not b:
        return False
    if a == b:
        return True
    if path_matches_patterns(a, [b]) or path_matches_patterns(b, [a]):
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
    "EXECUTION_PRIMARY_REVIEW",
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
