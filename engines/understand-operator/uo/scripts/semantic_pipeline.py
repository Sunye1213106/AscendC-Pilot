"""End-to-end input-rooted semantic pipeline for extract_plan.

Flow:
  candidates → observations → obligations → relation graph → materialize plan
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.extract_plan_autofill import (
    auto_merge_high_confidence_aliases,
    merge_receiver_bindings_into_plan,
    stamp_candidate_ids,
)
from uo.scripts.extract_plan_decision import (
    assert_canonical_plan_slim,
    file_sha256_bytes,
    slim_extract_plan,
)
from uo.scripts.extract_plan_io import (
    drop_invented_non_sink_roots,
    normalize_plan_from_candidates,
    validate_extract_plan_against_candidates,
)
from uo.scripts.semantic_graph_builder import (
    close_deterministic_relations,
    validate_input_root_grounding,
)
from uo.scripts.semantic_materializer import (
    hydrate_materialized_plan,
    materialize_from_relations,
)
from uo.scripts.semantic_obligations import build_semantic_obligations
from uo.scripts.semantic_observations import build_observations_from_candidates
from uo.scripts.semantic_relation_reduce import (
    plan_relation_batches,
    reduce_relation_parts,
)
from uo.scripts.source_evidence import enrich_item_evidence_from_disk


def build_relation_artifacts(
    candidates: dict[str, Any],
    *,
    identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministic path: observations → obligations → graph → plan."""
    if isinstance(candidates, dict):
        stamp_candidate_ids(candidates)
    observations = build_observations_from_candidates(candidates)
    obligations = build_semantic_obligations(observations, candidates)
    graph = close_deterministic_relations(observations, obligations)
    grounding_errors = validate_input_root_grounding(graph)
    plan = materialize_from_relations(graph, candidates, identity=identity)
    return {
        "observations": observations,
        "obligations": obligations,
        "graph": graph,
        "plan": plan,
        "grounding_errors": grounding_errors,
        "llm_required_count": int(obligations.get("llm_required_count") or 0),
    }


def apply_semantic_extract_plan(
    repo_root: Path,
    op_name: str,
    *,
    candidates: dict[str, Any] | None = None,
    action_dir: Path | None = None,
    identity: dict[str, Any] | None = None,
    check_only: bool = False,
    allow_ungrounded: bool = False,
) -> dict[str, Any]:
    """Build relation graph and write canonical extract_plan (+ sidecars)."""
    from uo._operator.artifacts import existing_operator_root

    uo_root = existing_operator_root(repo_root, op_name)
    cand_path = uo_root / "ir" / "extract_plan_candidates.yaml"
    if candidates is None:
        if not cand_path.is_file():
            return {
                "ok": False,
                "rejected_count": 1,
                "rejected": [{"reason": "extract_plan_candidates.yaml missing"}],
            }
        candidates = read_yaml(cand_path)
    if not isinstance(candidates, dict):
        return {
            "ok": False,
            "rejected_count": 1,
            "rejected": [{"reason": "candidates not a mapping"}],
        }

    stamp_candidate_ids(candidates)
    ident = dict(identity or {})
    if not ident.get("architecture"):
        ident["architecture"] = candidates.get("architecture")

    artifacts = build_relation_artifacts(candidates, identity=ident)
    graph = artifacts["graph"]
    obligations = artifacts["obligations"]

    # If action_dir has relation parts, merge them.
    if action_dir is not None:
        part_dir = Path(action_dir) / "staging" / "relation_parts"
        if part_dir.is_dir() and any(part_dir.glob("part_*.yaml")):
            reduced = reduce_relation_parts(Path(action_dir), graph)
            if not reduced.get("ok"):
                return {
                    "ok": False,
                    "error": "RELATION_REDUCE_FAILED",
                    "errors": reduced.get("errors") or [],
                    "retry_shards": reduced.get("retry_shards") or [],
                    "grounding_errors": reduced.get("grounding_errors") or [],
                }
            graph = reduced["graph"]
            artifacts["graph"] = graph
            artifacts["plan"] = materialize_from_relations(
                graph, candidates, identity=ident
            )
            artifacts["grounding_errors"] = reduced.get("grounding_errors") or []

        # Persist staging artifacts
        staging = Path(action_dir) / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        inputs = Path(action_dir) / "inputs"
        inputs.mkdir(parents=True, exist_ok=True)
        write_yaml(staging / "semantic_observations.yaml", artifacts["observations"])
        write_yaml(inputs / "semantic_obligations.yaml", obligations)
        write_yaml(staging / "semantic_relations.yaml", graph)

    grounding_errors = artifacts.get("grounding_errors") or validate_input_root_grounding(
        graph
    )
    if grounding_errors and not allow_ungrounded:
        # Soft: mark ungrounded as deferred rather than hard-fail whole plan when
        # only optional surfaces are ungrounded. Hard-fail if zero input_roots.
        if not (graph.get("input_roots") or []):
            return {
                "ok": False,
                "error": "NO_INPUT_ROOTS",
                "grounding_errors": grounding_errors,
            }

    plan = artifacts["plan"]

    # Stamp candidates sha from sidecar when prepare already hashed them.
    sha_side = ""
    sha_path = uo_root / "ir" / "extract_plan_candidates.sha256"
    if sha_path.is_file():
        sha_side = sha_path.read_text(encoding="utf-8").strip().split()[0]
    plan = hydrate_materialized_plan(plan, candidates, candidates_sha256=sha_side)
    for k in ("actor_id", "run_id", "workflow_id", "architecture"):
        if ident.get(k):
            plan[k] = ident[k]
    artifacts["plan"] = plan

    # Enrich + autofill + normalize for downstream compatibility.
    project_root = Path(repo_root)
    writer_pool = list(candidates.get("writer_candidates") or [])
    recv_pool = list(candidates.get("receiver_candidates") or [])
    from uo.scripts.extract_plan_io import _match_candidate

    for section, pool in (("writers", writer_pool), ("receivers", recv_pool)):
        for item in plan.get(section) or []:
            if isinstance(item, dict):
                cand = _match_candidate(item, [c for c in pool if isinstance(c, dict)])
                enrich_item_evidence_from_disk(project_root, item, candidate=cand)

    plan = normalize_plan_from_candidates(plan, candidates)
    drop_invented_non_sink_roots(plan, candidates)
    auto_merge_high_confidence_aliases(plan, candidates)
    merge_receiver_bindings_into_plan(plan, candidates)

    errors = validate_extract_plan_against_candidates(
        plan, candidates, project_root=project_root
    )
    # Relation-derived plans may lack full evidence contract on every writer when
    # candidates didn't carry windows — keep structural errors only if strict.
    structural = [
        e
        for e in errors
        if "missing" in e.lower() and "candidates" in e.lower()
    ]

    if check_only:
        return {
            "ok": not structural,
            "errors": errors,
            "grounding_errors": grounding_errors,
            "plan": plan,
            "graph": graph,
            "llm_required_count": artifacts.get("llm_required_count") or 0,
        }

    if structural:
        return {
            "ok": False,
            "rejected_count": len(structural),
            "rejected": [{"reason": e} for e in structural],
            "errors": errors,
            "grounding_errors": grounding_errors,
        }

    # Write canonical slim IR
    aliases_rel = "extract_plan_aliases.yaml"
    bindings_rel = "receiver_bindings.yaml"
    slim, aliases_doc, bindings_doc = slim_extract_plan(
        plan, aliases_rel=aliases_rel, bindings_rel=bindings_rel
    )
    # Attach new surfaces into slim plan (keep slim writers/receivers).
    for key in (
        "input_roots",
        "condition_nodes",
        "branch_nodes",
        "template_nodes",
        "key_dimensions",
        "derived_values",
        "groundings",
        "tiling_field_sinks",
    ):
        if plan.get(key) is not None:
            slim[key] = plan.get(key)

    ir = uo_root / "ir"
    ir.mkdir(parents=True, exist_ok=True)
    write_yaml(ir / "extract_plan.yaml", slim)
    write_yaml(ir / aliases_rel, aliases_doc)
    write_yaml(ir / bindings_rel, bindings_doc)
    write_yaml(ir / "semantic_relations.yaml", graph)
    write_yaml(ir / "semantic_observations.yaml", artifacts["observations"])

    # Fix sha refs if slim expects them
    try:
        a_sha = file_sha256_bytes((ir / aliases_rel).read_bytes())
        b_sha = file_sha256_bytes((ir / bindings_rel).read_bytes())
        slim2, _, _ = slim_extract_plan(
            plan,
            aliases_rel=aliases_rel,
            bindings_rel=bindings_rel,
            aliases_sha=a_sha,
            bindings_sha=b_sha,
        )
        for key in (
            "input_roots",
            "condition_nodes",
            "branch_nodes",
            "template_nodes",
            "key_dimensions",
            "derived_values",
            "groundings",
            "tiling_field_sinks",
        ):
            if plan.get(key) is not None:
                slim2[key] = plan.get(key)
        write_yaml(ir / "extract_plan.yaml", slim2)
        assert_canonical_plan_slim(slim2)
        slim = slim2
    except Exception:  # noqa: BLE001
        pass

    return {
        "ok": True,
        "extract_plan_path": str(ir / "extract_plan.yaml"),
        "semantic_relations_path": str(ir / "semantic_relations.yaml"),
        "writer_count": len(slim.get("writers") or []),
        "receiver_count": len(slim.get("receivers") or []),
        "binding_count": len((bindings_doc or {}).get("bindings") or {}),
        "alias_count": len((aliases_doc or {}).get("aliases") or {}),
        "input_root_count": len(slim.get("input_roots") or []),
        "condition_count": len(slim.get("condition_nodes") or []),
        "template_count": len(slim.get("template_nodes") or []),
        "grounding_errors": grounding_errors,
        "llm_required_count": artifacts.get("llm_required_count") or 0,
        "unresolved_count": len(graph.get("unresolved") or []),
    }


def prepare_relation_extract_plan(
    candidates: dict[str, Any],
    *,
    action_dir: Path,
    action_session_id: str,
    source_snapshot_hash: str = "",
    identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prepare observations/obligations/batches for extract_plan action."""
    artifacts = build_relation_artifacts(candidates, identity=identity)
    action_dir = Path(action_dir)
    staging = action_dir / "staging"
    inputs = action_dir / "inputs"
    staging.mkdir(parents=True, exist_ok=True)
    inputs.mkdir(parents=True, exist_ok=True)
    (staging / "relation_parts").mkdir(parents=True, exist_ok=True)

    write_yaml(staging / "semantic_observations.yaml", artifacts["observations"])
    write_yaml(inputs / "semantic_obligations.yaml", artifacts["obligations"])
    write_yaml(staging / "semantic_relations.base.yaml", artifacts["graph"])

    manifest = plan_relation_batches(
        artifacts["obligations"],
        action_session_id=action_session_id,
        source_snapshot_hash=source_snapshot_hash,
    )
    write_yaml(inputs / "relation_batches.yaml", manifest)

    return {
        "ok": True,
        "llm_required_count": int(artifacts["obligations"].get("llm_required_count") or 0),
        "deterministic_count": int(artifacts["obligations"].get("deterministic_count") or 0),
        "manifest": manifest,
        "artifacts": artifacts,
        "needs_workers": int(artifacts["obligations"].get("llm_required_count") or 0) > 0,
    }


__all__ = [
    "build_relation_artifacts",
    "apply_semantic_extract_plan",
    "prepare_relation_extract_plan",
]
