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
    "uo-init": {
        "resolve_gaps": [
            "runs/{run_id}/actions/resolve_gaps/parts/**",
            "runs/{run_id}/actions/resolve_gaps/scratch/**",
            "runs/{run_id}/actions/resolve_gaps/staging.yaml",
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
}
ACTION_FINALIZER_WRITE_PATHS: dict[str, dict[str, list[str]]] = {
    "uo-init": {
        "resolve_gaps": [
            "uo/ir/unresolved.yaml",
            "uo/ir/gap_patch_receipt.yaml",
        ],
        "apply_gap_patch": [
            "uo/ir/gap_patch_receipt.yaml",
            "uo/ir/**",
        ],
    },
    "tg-solve": {
        "lemma_mine": [
            "runs/{run_id}/actions/lemma_mine/staging.yaml",
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
        "closure_audit": [
            "runs/{run_id}/actions/closure_audit/review.yaml",
        ],
        "closure_certify": [
            "tg/closure/closure.csv",
            "tg/closure/certificate.yaml",
            "tg/closure/audit_report.yaml",
        ],
    },
}
ACTION_WRITE_PATHS: dict[str, dict[str, list[str]]] = {
    "uo-init": {
        "prepare_layout": ["uo/manifest.yaml", "uo/operator.yaml", "uo/**"],
        "scope_scan": [
            "uo/runs/{run_id}/scope/**",
            "uo/summary/scope_candidates.yaml",
        ],
        "scope_confirm": [
            "uo/runs/{run_id}/scope/**",
            "uo/summary/scope_confirmed.yaml",
        ],
        "extract_host": ["uo/ir/**"],
        "extract_tiling_key": ["uo/tiling/**"],
        "extract_registry": ["uo/tiling/families.yaml", "uo/tiling/**"],
        "extract_kernel": ["uo/kernel/**"],
        "normalize_variables": ["uo/tiling/**"],
        "derive_key_fields": [
            "uo/ir/host_derivation.yaml",
            "uo/ir/derive_key_fields_receipt.yaml",
            "uo/tiling/key_derivations.yaml",
            "uo/ir/**",
            "uo/tiling/**",
        ],
        "normalize_predicates": ["uo/ir/unresolved.yaml", "uo/ir/**"],
        "resolve_gaps": [
            "runs/{run_id}/actions/resolve_gaps/parts/**",
            "runs/{run_id}/actions/resolve_gaps/scratch/**",
            "runs/{run_id}/actions/resolve_gaps/staging.yaml",
            "uo/ir/resolve_gaps_receipt.yaml",
            "uo/ir/**",
        ],
        "apply_gap_patch": ["uo/ir/gap_patch_receipt.yaml", "uo/ir/**"],
        "export_kb": ["uo/**"],
        "build_index": ["uo/indexes/**"],
        "export_tg_host_view": [
            "uo/ir/tg_host_view.yaml",
            "uo/indexes/kb_graph.sqlite",
            "uo/checks/tg_host_view_receipt.yaml",
        ],
        "export_adapter_pack": [
            "uo/adapter/**",
            "uo/checks/adapter_pack_receipt.yaml",
        ],
        "export_integrity": ["uo/checks/integrity.yaml", "uo/summary/**", "uo/checks/**"],
        "kb_review": ["uo/review/kb_product_review.yaml"],
    },
    "tg-plan": {
        "plan_intent": ["tg/plan/plan_intent.yaml"],
    },
    "tg-solve": {
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
        "closure_explain": ["tg/closure/why.csv", "tg/closure/construct/**"],
        "lemma_leads": [
            "tg/closure/lemmas/leads.yaml",
            "tg/closure/leads.csv",
            "tg/closure/leads3.csv",
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
        "closure_audit": [
            "runs/{run_id}/actions/closure_audit/review.yaml",
        ],
        "closure_certify": [
            "tg/closure/closure.csv",
            "tg/closure/certificate.yaml",
            "tg/closure/audit_report.yaml",
        ],
        "z3_solve": ["tg/solve/**", "tg/cases/**", "tg/realization/**"],
        "cover_confirm": ["tg/solve/**", "tg/cases/**"],
    },
}
ACTION_READ_PATHS: dict[str, dict[str, list[str]]] = {
    "uo-init": {
        "resolve_gaps": [
            "uo/ir/unresolved.yaml",
            "uo/ir/resolve_gaps_staging.yaml",
            "runs/{run_id}/actions/resolve_gaps/parts/**",
            "runs/{run_id}/actions/resolve_gaps/scratch/**",
        ],
        "kb_review": [
            "uo/quality.yaml",
            "uo/ir/unresolved.yaml",
            "uo/checks/integrity.yaml",
            "uo/manifest.yaml",
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
    if action_id == "extract_plan":
        return [
            expand_path_template(
                f"runs/{{run_id}}/actions/extract_plan/staging/relation_parts/part_{sid}.yaml",
                run_id=run_id,
            ),
            expand_path_template(
                "runs/{run_id}/actions/extract_plan/staging/relation_parts/**",
                run_id=run_id,
            ),
            expand_path_template(
                f"runs/{{run_id}}/actions/extract_plan/scratch/{sid}/**",
                run_id=run_id,
            ),
        ]
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
    if action_id == "extract_plan":
        paths = [
            expand_path_template(
                "runs/{run_id}/actions/extract_plan/inputs/relation_batches.yaml",
                run_id=run_id,
            ),
            expand_path_template(
                "runs/{run_id}/actions/extract_plan/inputs/semantic_obligations.yaml",
                run_id=run_id,
            ),
            expand_path_template(
                f"runs/{{run_id}}/actions/extract_plan/inputs/batches/{batch}",
                run_id=run_id,
            ),
            expand_path_template(
                f"runs/{{run_id}}/actions/extract_plan/staging/relation_parts/part_{sid}.yaml",
                run_id=run_id,
            ),
            expand_path_template(
                f"runs/{{run_id}}/actions/extract_plan/scratch/{sid}/**",
                run_id=run_id,
            ),
            # Session pack / env only — NOT full worklist / candidates
            expand_path_template(
                f"runs/{{run_id}}/actions/extract_plan/environment_capabilities.yaml",
                run_id=run_id,
            ),
            expand_path_template(
                f"runs/{{run_id}}/actions/extract_plan/prompt.md",
                run_id=run_id,
            ),
            expand_path_template(
                f"runs/{{run_id}}/actions/extract_plan/method.md",
                run_id=run_id,
            ),
            expand_path_template(
                f"runs/{{run_id}}/actions/extract_plan/bundle.yaml",
                run_id=run_id,
            ),
        ]
        return paths
    if action_id == "resolve_gaps":
        paths = [
            expand_path_template(
                "runs/{run_id}/actions/resolve_gaps/inputs/blocker_batches.yaml",
                run_id=run_id,
            ),
            expand_path_template(
                f"runs/{{run_id}}/actions/resolve_gaps/inputs/batches/{batch}",
                run_id=run_id,
            ),
            "uo/ir/unresolved.yaml",
            "uo/ir/resolve_gaps_staging.yaml",
        ]
        if sid:
            paths.append(
                expand_path_template(
                    f"runs/{{run_id}}/actions/resolve_gaps/parts/part_{sid}.yaml",
                    run_id=run_id,
                )
            )
            paths.append(
                expand_path_template(
                    f"runs/{{run_id}}/actions/resolve_gaps/scratch/{sid}/**",
                    run_id=run_id,
                )
            )
        for extra in (
            f"runs/{{run_id}}/actions/resolve_gaps/environment_capabilities.yaml",
            f"runs/{{run_id}}/actions/resolve_gaps/prompt.md",
            f"runs/{{run_id}}/actions/resolve_gaps/method.md",
            f"runs/{{run_id}}/actions/resolve_gaps/bundle.yaml",
        ):
            paths.append(expand_path_template(extra, run_id=run_id))
        return paths
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
    sid = str(shard_id or "").strip()
    if action_id == "extract_plan":
        return [
            "uo/ir/extract_plan_candidates.yaml",
            expand_path_template(
                "runs/{run_id}/actions/extract_plan/inputs/batches/**",
                run_id=run_id,
            ),
            "uo/ir/extract_plan.yaml",
            "uo/ir/semantic_relations.yaml",
            "uo/ir/llm_tasks.yaml",
            "uo/ir/semantic_patches.yaml",
            "uo/ir/semantic_resolution_ledger.yaml",
        ]
    if action_id == "adjudicate_llm_tasks":
        return [
            "uo/ir/semantic_patches.yaml",
            "uo/ir/semantic_resolution_ledger.yaml",
            expand_path_template(
                "runs/{run_id}/actions/adjudicate_llm_tasks/parts/**",
                run_id=run_id,
            ),
        ]
    if action_id == "resolve_gaps":
        # Do not glob-forbid batches/parts — assigned paths are allow-listed per shard.
        return [
            "uo/ir/gap_bindings.yaml",
            "uo/ir/host_derivation.yaml",
            "uo/ir/operator_graph.yaml",
            "uo/ir/quality.yaml",
        ]
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
            if rel == prefix or rel.startswith(prefix + "/"):
                return True
            continue
        if "*" in p or "?" in p:
            # simple glob: ** already handled; treat * as single-segment wildcard
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
    """
    if not scopes:
        return False
    raw = expand_path_template(str(path_or_pattern or ""), run_id=run_id or "_RUN_")
    rel = raw.replace("\\", "/").lstrip("/")
    ceilings = [
        expand_path_template(str(s or ""), run_id=run_id or "_RUN_").replace("\\", "/").lstrip("/")
        for s in scopes
        if str(s or "").strip()
    ]
    if not ceilings:
        return False
    # Universal ceilings cover every path / pattern.
    if any(c in {"**", "*", "**/**"} for c in ceilings):
        return True
    # Concrete file / already-expanded path.
    if "*" not in rel and "?" not in rel and "[" not in rel:
        return path_matches_patterns(rel, ceilings)
    # Pattern ⊆ ceiling: prefix of the narrower pattern must match a ceiling.
    prefix = _pattern_prefix(rel)
    if prefix and path_matches_patterns(prefix, ceilings):
        return True
    for c in ceilings:
        c_prefix = _pattern_prefix(c)
        if not c_prefix:
            # Broad ``**`` / ``*`` ceiling.
            if c in {"**", "*", "**/**"}:
                return True
            continue
        if prefix == c_prefix or (prefix and prefix.startswith(c_prefix + "/")):
            return True
        if c.endswith("/**") and prefix and (prefix == c[:-3] or prefix.startswith(c[:-3] + "/")):
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
