from __future__ import annotations

from typing import Any

from .hashing import stable_hash


PRIORITY_WEIGHT = {"hard": 100, "high": 10, "normal": 1}


class CandidateError(RuntimeError):
    pass


def build_candidate(obligation: dict[str, Any], solve_result: dict[str, Any], covered_obligation_ids: list[str] | None = None) -> dict[str, Any]:
    model = solve_result.get("model") if isinstance(solve_result.get("model"), dict) else {}
    signature = coverage_signature(model)
    covered = sorted(dict.fromkeys(covered_obligation_ids or [str(obligation.get("id"))]))
    candidate = {
        "id": "",
        "source_obligation_ids": [str(obligation.get("id"))],
        "abstract_model": abstract_candidate_model(model, obligation),
        "coverage_signature": signature,
        "covered_obligation_ids": covered,
        "status": "candidate",
    }
    candidate["id"] = "CAND_" + stable_hash(signature)[:12].upper()
    return candidate


def abstract_candidate_model(model: dict[str, Any], obligation: dict[str, Any]) -> dict[str, Any]:
    return {
        "shape_dimensions": {key: value for key, value in sorted(model.items()) if key.startswith("VAR_SHAPE_") or key.endswith("_DIM")},
        "dtype_enum": model.get("VAR_DTYPE"),
        "layout_enum": model.get("VAR_LAYOUT"),
        "optional_input_presence": {key.removeprefix("VAR_OPTIONAL_").lower(): value for key, value in sorted(model.items()) if key.startswith("VAR_OPTIONAL_")},
        "attrs": {key.removeprefix("VAR_ATTR_").lower(): value for key, value in sorted(model.items()) if key.startswith("VAR_ATTR_")},
        "tiling_key_fields": {key.removeprefix("VAR_KEY_").lower(): value for key, value in sorted(model.items()) if key.startswith("VAR_KEY_")},
        "family": model.get("VAR_FAMILY"),
        "expected_template": model.get("VAR_TEMPLATE"),
        "expected_kernel_path": model.get("VAR_KERNEL_PATH"),
        "expected_branch_truth": branch_truth(model),
        "tilingdata_boundary_bucket": model.get("VAR_TILINGDATA_BUCKET"),
        "core_split_boundary_bucket": model.get("VAR_CORE_SPLIT_BUCKET"),
        "tail_boundary_bucket": model.get("VAR_TAIL_BUCKET"),
        "workspace_boundary_bucket": model.get("VAR_WORKSPACE_BUCKET"),
        "pipeline_resource_mode": model.get("VAR_PIPELINE_RESOURCE_MODE"),
        "dtype_layout_class": model.get("VAR_DTYPE_LAYOUT_CLASS"),
        "numerical_mode": model.get("VAR_NUMERICAL_MODE"),
        "obligation_kind": obligation.get("kind"),
    }


def coverage_signature(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "key_fields": {key: value for key, value in sorted(model.items()) if key.startswith("VAR_KEY_")},
        "family_ref": model.get("VAR_FAMILY"),
        "template_ref": model.get("VAR_TEMPLATE"),
        "path_ref": model.get("VAR_KERNEL_PATH"),
        "branch_truth": branch_truth(model),
        "tilingdata_buckets": {
            "TDF": model.get("VAR_TILINGDATA_BUCKET"),
            "core_split": model.get("VAR_CORE_SPLIT_BUCKET"),
            "tail": model.get("VAR_TAIL_BUCKET"),
            "workspace": model.get("VAR_WORKSPACE_BUCKET"),
            "pipeline_resource_mode": model.get("VAR_PIPELINE_RESOURCE_MODE"),
        },
        "optional_input_mask": {key.removeprefix("VAR_OPTIONAL_").lower(): value for key, value in sorted(model.items()) if key.startswith("VAR_OPTIONAL_")},
        "dtype_layout_class": model.get("VAR_DTYPE_LAYOUT_CLASS"),
        "numerical_mode": model.get("VAR_NUMERICAL_MODE"),
    }


def dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_signature: dict[str, dict[str, Any]] = {}
    for candidate in sorted(candidates, key=lambda item: item["id"]):
        signature_key = stable_hash(candidate["coverage_signature"])
        if signature_key not in by_signature:
            by_signature[signature_key] = candidate
            continue
        existing = by_signature[signature_key]
        merged = sorted(set(existing["covered_obligation_ids"]) | set(candidate["covered_obligation_ids"]))
        _ensure_no_contradictory_branch_coverage(merged)
        sources = sorted(set(existing.get("source_obligation_ids") or []) | set(candidate.get("source_obligation_ids") or []))
        existing["covered_obligation_ids"] = merged
        existing["source_obligation_ids"] = sources
    return sorted(by_signature.values(), key=lambda item: item["id"])


def is_branch_variable(var_id: str) -> bool:
    return var_id.startswith(("VAR_BRANCH_", "VAR_KBR_", "VAR_KDEC_"))


def branch_stable_key(var_id: str) -> str:
    if var_id.startswith("VAR_KBR_") or var_id.startswith("VAR_KDEC_"):
        return var_id.removeprefix("VAR_")
    if var_id.startswith("VAR_BRANCH_"):
        return var_id.removeprefix("VAR_BRANCH_")
    raise ValueError(f"Not a branch variable: {var_id}")


def branch_truth(model: dict[str, Any]) -> dict[str, Any]:
    return {branch_stable_key(key): value for key, value in sorted(model.items()) if is_branch_variable(key)}


def _ensure_no_contradictory_branch_coverage(obligation_ids: list[str]) -> None:
    states: dict[str, set[str]] = {}
    for oid in obligation_ids:
        text = str(oid).upper()
        if "_TRUE" in text:
            states.setdefault(text.split("_TRUE", 1)[0], set()).add("true")
        if "_FALSE" in text:
            states.setdefault(text.split("_FALSE", 1)[0], set()).add("false")
    conflicts = sorted(key for key, values in states.items() if values == {"true", "false"})
    if conflicts:
        raise CandidateError(f"CONTRADICTORY_BRANCH_COVERAGE: {', '.join(conflicts)}")


def greedy_set_cover(candidates: list[dict[str, Any]], obligations: list[dict[str, Any]]) -> dict[str, Any]:
    obligation_by_id = {str(item["id"]): item for item in obligations}
    uncovered = set(obligation_by_id)
    selected: list[dict[str, Any]] = []
    remaining = sorted(candidates, key=lambda item: item["id"])

    while uncovered:
        scored = []
        for candidate in remaining:
            covers = sorted(set(candidate.get("covered_obligation_ids") or []) & uncovered)
            if not covers:
                continue
            score = sum(PRIORITY_WEIGHT.get(obligation_by_id[cid].get("priority"), 1) for cid in covers)
            scored.append((score, len(covers), candidate["id"], candidate, covers))
        if not scored:
            break
        scored.sort(key=lambda row: (-row[0], -row[1], row[2]))
        _score, _count, _cid, chosen, covers = scored[0]
        selected.append(chosen)
        uncovered -= set(covers)
        remaining = [item for item in remaining if item["id"] != chosen["id"]]

    uncovered_items = [
        {
            "id": oid,
            "kind": obligation_by_id[oid].get("kind"),
            "priority": obligation_by_id[oid].get("priority"),
            "reason": "no SAT candidate covers this obligation",
        }
        for oid in sorted(uncovered)
    ]
    return {"selected_candidates": selected, "uncovered_obligations": uncovered_items}
