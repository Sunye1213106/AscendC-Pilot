"""Apply harness-bounded semantic bind patches against llm_bind_prompt_bundle candidates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .binding_lexicon import merge_lexicons, normalize_lexicon
from .io import read_yaml, write_yaml
from .realization_contract import realization_paths


class SemanticBindError(RuntimeError):
    pass


def apply_semantic_bind_patch(out_root: Path, patch: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge candidate-cited bind decisions into realization/binding_lexicon.yaml.

    LLM may only accept/select among candidates in llm_bind_prompt_bundle.yaml.
    Empty accept without candidate refs is rejected. No free-repo invention.
    """
    out_root = Path(out_root)
    paths = realization_paths(out_root)
    realization = paths["dir"]
    lexicon_path = realization / "binding_lexicon.yaml"
    bundle_path = realization / "llm_bind_prompt_bundle.yaml"
    unresolved_path = paths["unresolved"]
    gaps_path = realization / "binding_gaps.yaml"

    if patch is None:
        patch = read_yaml(realization / "semantic_bind_patch.yaml")
    if not isinstance(patch, dict) or not patch:
        raise SemanticBindError("missing realization/semantic_bind_patch.yaml")

    bundle = read_yaml(bundle_path) if bundle_path.is_file() else {}
    allowed_ids = _candidate_ids(bundle)
    unresolved = read_yaml(unresolved_path) if unresolved_path.is_file() else {}
    prior_gaps = list((unresolved.get("binding_gaps") if isinstance(unresolved, dict) else None) or [])
    if gaps_path.is_file():
        gaps_doc = read_yaml(gaps_path)
        if isinstance(gaps_doc, dict) and gaps_doc.get("gaps"):
            prior_gaps = list(gaps_doc.get("gaps") or prior_gaps)

    lexicon = normalize_lexicon(read_yaml(lexicon_path) if lexicon_path.is_file() else {})
    applied: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    action = str(patch.get("action") or patch.get("action_type") or "bind").lower()
    items = list(patch.get("bindings") or patch.get("items") or patch.get("key_derivations") or [])
    if action in {"accept", "select", "accept_all"} and not items and not patch.get("key_derivations"):
        raise SemanticBindError(
            f"semantic bind action {action!r} requires candidate-backed bindings; empty accept forbidden"
        )

    derivations = list(lexicon.get("key_derivations") or [])
    tokens = dict(lexicon.get("key_tokens") or {})
    aliases = dict(lexicon.get("csv_field_aliases") or {})

    for item in items:
        if not isinstance(item, dict):
            rejected.append({"item": item, "reason": "not_a_dict"})
            continue
        cid = str(item.get("candidate_id") or item.get("id") or item.get("gap_id") or "")
        if allowed_ids and cid and cid not in allowed_ids:
            rejected.append({"id": cid, "reason": "candidate_not_in_bundle"})
            continue
        if allowed_ids and not cid and not item.get("key_id"):
            rejected.append({"item": item, "reason": "missing_candidate_id"})
            continue
        key_id = str(item.get("key_id") or item.get("key") or "")
        expr = item.get("expr") or item.get("expression") or item.get("derivation")
        if key_id and expr:
            # Replace existing derivation for same key_id
            derivations = [d for d in derivations if str((d or {}).get("key_id") or "") != key_id]
            derivations.append(
                {
                    "key_id": key_id,
                    "expr": expr,
                    "evidence": item.get("evidence") or [],
                    "candidate_id": cid,
                    "source": "semantic_bind",
                }
            )
            applied.append({"id": cid or key_id, "key_id": key_id, "change": "key_derivation"})
        if item.get("token") and item.get("value") is not None:
            tokens[str(item["token"])] = item.get("value")
            applied.append({"id": cid or str(item["token"]), "change": "key_token"})
        if item.get("csv_field") and item.get("alias") is not None:
            aliases[str(item["csv_field"])] = item.get("alias")
            applied.append({"id": cid or str(item["csv_field"]), "change": "csv_alias"})
        if not (
            (key_id and expr)
            or (item.get("token") and item.get("value") is not None)
            or (item.get("csv_field") and item.get("alias") is not None)
        ):
            rejected.append({"id": cid, "reason": "no_lexicon_mutation"})

    if not applied:
        raise SemanticBindError(
            f"semantic bind produced no lexicon changes; rejected={rejected[:8]}"
        )

    lexicon["key_derivations"] = derivations
    lexicon["key_tokens"] = tokens
    lexicon["csv_field_aliases"] = aliases
    lexicon["source"] = "semantic_bind"
    lexicon = normalize_lexicon(merge_lexicons(lexicon, {}))
    write_yaml(lexicon_path, lexicon)

    # Shrink gaps that were addressed
    resolved_keys = {str(a.get("key_id") or a.get("id") or "") for a in applied}
    remaining_gaps = []
    for gap in prior_gaps:
        if isinstance(gap, dict):
            gid = str(gap.get("id") or gap.get("key_id") or gap.get("candidate_id") or "")
            if gid and gid in resolved_keys:
                continue
            if str(gap.get("key_id") or "") in resolved_keys:
                continue
        remaining_gaps.append(gap)

    new_status = "ready_for_llm" if remaining_gaps else "ready"
    unresolved_out = {
        "version": 1,
        "status": new_status,
        "ok": new_status == "ready",
        "binding_gaps": remaining_gaps,
        "applied": applied,
        "rejected": rejected,
        "lexicon_ref": "realization/binding_lexicon.yaml",
        "next": "harness run-action bind_merge" if new_status == "ready" else "harness run-action semantic_bind",
    }
    write_yaml(unresolved_path, unresolved_out)
    write_yaml(gaps_path, {"version": 1, "gaps": remaining_gaps, "status": new_status})

    return {
        "ok": True,
        "status": "pass" if new_status == "ready" else "ready_for_llm",
        "applied_count": len(applied),
        "rejected_count": len(rejected),
        "remaining_gaps": len(remaining_gaps),
        "applied": applied,
        "rejected": rejected,
        "lexicon_path": lexicon_path.as_posix(),
    }


def _candidate_ids(bundle: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    if not isinstance(bundle, dict):
        return out
    for key in ("candidates", "items", "gaps", "binding_gaps", "prompts", "tasks"):
        rows = bundle.get(key)
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    for k in ("id", "candidate_id", "gap_id", "key_id"):
                        if row.get(k):
                            out.add(str(row[k]))
                elif isinstance(row, str):
                    out.add(row)
    # Nested prompt tasks
    for task in bundle.get("tasks") or []:
        if isinstance(task, dict):
            for row in task.get("candidates") or []:
                if isinstance(row, dict) and row.get("id"):
                    out.add(str(row["id"]))
    return out
