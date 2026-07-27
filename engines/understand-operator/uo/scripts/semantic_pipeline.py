"""extract_plan 语义主链：prepare 快照 → finalize 物化。

严格两阶段：
  prepare  → observations / obligations / immutable base graph / batches / snapshot
  finalize → 校验 snapshot → reduce parts → materialize → slim IR（禁止重算 obs/obl/base）
"""
from __future__ import annotations

import hashlib
import traceback
from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.extract_plan_autofill import (
    auto_merge_high_confidence_aliases,
    merge_receiver_bindings_into_plan,
    stamp_candidate_ids,
)
from uo.scripts.extract_plan_io import (
    drop_invented_non_sink_roots,
    normalize_plan_from_candidates,
    validate_extract_plan_against_candidates,
)
from uo.scripts.extract_plan_slim import (
    RELATION_ONLY_KEYS,
    assert_canonical_plan_slim,
    atomic_write_yaml,
    file_sha256_bytes,
    slim_extract_plan,
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


def _sha_of_yaml_doc(doc: Any) -> str:
    import json

    raw = json.dumps(doc, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _file_sha(path: Path) -> str:
    if not path.is_file():
        return ""
    return file_sha256_bytes(path.read_bytes())


def _stage_fail(
    stage: str,
    exc: BaseException | None = None,
    *,
    message: str = "",
    error: str = "EXTRACT_PLAN_STAGE_FAILED",
    retryable: bool = True,
    debug_dir: Path | None = None,
) -> dict[str, Any]:
    tb = ""
    if exc is not None:
        tb = traceback.format_exc()
        message = message or f"{type(exc).__name__}: {exc}"
        if debug_dir is not None:
            try:
                debug_dir.mkdir(parents=True, exist_ok=True)
                (debug_dir / f"{stage}.traceback.txt").write_text(tb, encoding="utf-8")
            except OSError:
                pass
    return {
        "ok": False,
        "error": error,
        "stage": stage,
        "exception_type": type(exc).__name__ if exc else "",
        "message": message,
        "message_zh": message,
        "retryable": retryable,
    }


def prepare_semantic_relation_snapshot(
    candidates: dict[str, Any],
    *,
    identity: dict[str, Any] | None = None,
    operator_boundary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """唯一 prepare 入口：observations → obligations → immutable base graph。

    不做 materialize / hydrate / slim / layered KB。
    """
    if not isinstance(candidates, dict):
        raise TypeError("candidates 必须为 dict")
    stamp_candidate_ids(candidates)
    observations = build_observations_from_candidates(candidates)
    obligations = build_semantic_obligations(observations, candidates)
    graph = close_deterministic_relations(
        observations,
        obligations,
        operator_boundary=operator_boundary,
    )
    grounding_errors = validate_input_root_grounding(graph)
    return {
        "observations": observations,
        "obligations": obligations,
        "graph": graph,
        "grounding_errors": grounding_errors,
        "llm_required_count": int(obligations.get("llm_required_count") or 0),
        "deterministic_count": int(obligations.get("deterministic_count") or 0),
        "identity": dict(identity or {}),
    }


# 兼容旧测试名：仅 prepare 快照，不含 materialize。
def build_relation_artifacts(
    candidates: dict[str, Any],
    *,
    identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snap = prepare_semantic_relation_snapshot(candidates, identity=identity)
    plan = materialize_from_relations(snap["graph"], candidates, identity=identity)
    return {**snap, "plan": plan}


def prepare_relation_extract_plan(
    candidates: dict[str, Any],
    *,
    action_dir: Path,
    action_session_id: str,
    source_snapshot_hash: str = "",
    identity: dict[str, Any] | None = None,
    run_id: str = "",
    workflow_id: str = "uo-init",
    action_id: str = "extract_plan",
    prepare_nonce_hash: str = "",
    architecture: str = "",
    operator_boundary_path: Path | None = None,
    entrypoint_graph_path: Path | None = None,
) -> dict[str, Any]:
    """Runtime prepare：写权威 snapshot 产物，不 finalize。"""
    action_dir = Path(action_dir)
    staging = action_dir / "staging"
    inputs = action_dir / "inputs"
    staging.mkdir(parents=True, exist_ok=True)
    inputs.mkdir(parents=True, exist_ok=True)
    (staging / "relation_parts").mkdir(parents=True, exist_ok=True)
    debug_dir = action_dir / "scratch" / "debug"

    boundary = None
    if operator_boundary_path and Path(operator_boundary_path).is_file():
        loaded = read_yaml(Path(operator_boundary_path))
        if isinstance(loaded, dict):
            boundary = loaded

    try:
        artifacts = prepare_semantic_relation_snapshot(
            candidates,
            identity=identity,
            operator_boundary=boundary,
        )
    except Exception as exc:  # noqa: BLE001
        return _stage_fail("prepare_semantic_relation_snapshot", exc, debug_dir=debug_dir)

    try:
        write_yaml(staging / "semantic_observations.yaml", artifacts["observations"])
        write_yaml(inputs / "semantic_obligations.yaml", artifacts["obligations"])
        write_yaml(staging / "semantic_relations.base.yaml", artifacts["graph"])

        manifest = plan_relation_batches(
            artifacts["obligations"],
            action_session_id=action_session_id,
            source_snapshot_hash=source_snapshot_hash,
        )
        write_yaml(inputs / "relation_batches.yaml", manifest)

        obs_sha = _sha_of_yaml_doc(artifacts["observations"])
        obl_sha = _sha_of_yaml_doc(artifacts["obligations"])
        base_sha = _sha_of_yaml_doc(artifacts["graph"])
        cand_sha = str(
            (identity or {}).get("candidates_sha256") or source_snapshot_hash or ""
        )
        snap = {
            "version": 1,
            "run_id": run_id,
            "workflow_id": workflow_id,
            "action_id": action_id,
            "action_session_id": action_session_id,
            "prepare_nonce_hash": prepare_nonce_hash,
            "architecture": architecture
            or str((identity or {}).get("architecture") or ""),
            "candidates_sha256": cand_sha,
            "operator_boundary_sha256": _file_sha(Path(operator_boundary_path))
            if operator_boundary_path
            else "",
            "entrypoint_graph_sha256": _file_sha(Path(entrypoint_graph_path))
            if entrypoint_graph_path
            else "",
            "observations_sha256": obs_sha,
            "obligations_sha256": obl_sha,
            "base_graph_sha256": base_sha,
            "source_snapshot_hash": source_snapshot_hash or cand_sha,
            "llm_required_count": artifacts["llm_required_count"],
            "deterministic_count": artifacts["deterministic_count"],
        }
        write_yaml(inputs / "extract_plan_snapshot.yaml", snap)
    except Exception as exc:  # noqa: BLE001
        return _stage_fail("write_prepare_artifacts", exc, debug_dir=debug_dir)

    return {
        "ok": True,
        "llm_required_count": artifacts["llm_required_count"],
        "deterministic_count": artifacts["deterministic_count"],
        "manifest": manifest,
        "snapshot": snap,
        "needs_workers": artifacts["llm_required_count"] > 0,
        "finalize_required": True,
        "deterministic_only": artifacts["llm_required_count"] == 0,
    }


def _load_and_validate_snapshot(
    action_dir: Path,
    *,
    expected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """加载 prepare snapshot 并校验 SHA；失败返回错误 dict。"""
    action_dir = Path(action_dir)
    snap_path = action_dir / "inputs" / "extract_plan_snapshot.yaml"
    if not snap_path.is_file():
        return {
            "ok": False,
            "error": "EXTRACT_PLAN_PREPARE_SNAPSHOT_STALE",
            "message": "缺少 inputs/extract_plan_snapshot.yaml；请重新 prepare",
            "message_zh": "缺少 inputs/extract_plan_snapshot.yaml；请重新 prepare",
        }
    snap = read_yaml(snap_path)
    if not isinstance(snap, dict):
        return {
            "ok": False,
            "error": "EXTRACT_PLAN_PREPARE_SNAPSHOT_STALE",
            "message": "snapshot 不是 mapping",
        }

    obs_path = action_dir / "staging" / "semantic_observations.yaml"
    obl_path = action_dir / "inputs" / "semantic_obligations.yaml"
    base_path = action_dir / "staging" / "semantic_relations.base.yaml"
    for p, label in (
        (obs_path, "observations"),
        (obl_path, "obligations"),
        (base_path, "base_graph"),
    ):
        if not p.is_file():
            return {
                "ok": False,
                "error": "EXTRACT_PLAN_PREPARE_SNAPSHOT_STALE",
                "message": f"缺少 prepare 产物 {label}",
                "message_zh": f"缺少 prepare 产物 {label}",
            }

    observations = read_yaml(obs_path)
    obligations = read_yaml(obl_path)
    base_graph = read_yaml(base_path)
    if not all(isinstance(x, dict) for x in (observations, obligations, base_graph)):
        return {
            "ok": False,
            "error": "EXTRACT_PLAN_PREPARE_SNAPSHOT_STALE",
            "message": "prepare 产物 schema 损坏",
        }

    checks = {
        "observations_sha256": _sha_of_yaml_doc(observations),
        "obligations_sha256": _sha_of_yaml_doc(obligations),
        "base_graph_sha256": _sha_of_yaml_doc(base_graph),
    }
    for key, actual in checks.items():
        expected_sha = str(snap.get(key) or "")
        if expected_sha and expected_sha != actual:
            return {
                "ok": False,
                "error": "EXTRACT_PLAN_PREPARE_SNAPSHOT_STALE",
                "message": f"{key} 不匹配（snapshot={expected_sha[:12]}… actual={actual[:12]}…）",
                "message_zh": f"prepare snapshot 过期：{key} 不匹配，禁止静默重算",
                "field": key,
            }

    if expected:
        for key in ("candidates_sha256", "prepare_nonce_hash", "action_session_id", "run_id"):
            exp = str(expected.get(key) or "")
            got = str(snap.get(key) or "")
            if exp and got and exp != got:
                return {
                    "ok": False,
                    "error": "EXTRACT_PLAN_PREPARE_SNAPSHOT_STALE",
                    "message": f"{key} 与会话不一致",
                    "message_zh": f"prepare snapshot 过期：{key} 与会话不一致",
                    "field": key,
                }

    return {
        "ok": True,
        "snapshot": snap,
        "observations": observations,
        "obligations": obligations,
        "base_graph": base_graph,
    }


def apply_semantic_extract_plan(
    repo_root: Path,
    op_name: str,
    *,
    action_dir: Path | None = None,
    identity: dict[str, Any] | None = None,
    check_only: bool = False,
    allow_ungrounded: bool = False,
    progress: Any | None = None,
) -> dict[str, Any]:
    """Finalize：只读 prepare snapshot，禁止重建 observations/obligations/base graph。"""
    from uo._operator.artifacts import existing_operator_root

    def _p_start(sid: str) -> None:
        if progress is not None:
            progress.start_stage(sid)

    def _p_done() -> None:
        if progress is not None:
            progress.complete_stage()

    uo_root = existing_operator_root(repo_root, op_name)
    ir = uo_root / "ir"
    cand_path = ir / "extract_plan_candidates.yaml"
    debug_dir = (Path(action_dir) / "scratch" / "debug") if action_dir else (ir / ".debug")

    if action_dir is None:
        return {
            "ok": False,
            "error": "EXTRACT_PLAN_PREPARE_SNAPSHOT_STALE",
            "message_zh": "finalize 需要 action_dir（含 prepare snapshot）",
        }

    action_dir = Path(action_dir)
    _p_start("load_snapshot")
    loaded = _load_and_validate_snapshot(
        action_dir,
        expected={
            "candidates_sha256": str((identity or {}).get("candidates_sha256") or ""),
            "prepare_nonce_hash": str((identity or {}).get("prepare_nonce") or ""),
            "action_session_id": str((identity or {}).get("action_session_id") or ""),
            "run_id": str((identity or {}).get("run_id") or ""),
        },
    )
    if not loaded.get("ok"):
        return loaded
    _p_done()

    snap = loaded["snapshot"]
    observations = loaded["observations"]
    obligations = loaded["obligations"]
    base_graph = loaded["base_graph"]
    llm_n = int(snap.get("llm_required_count") or obligations.get("llm_required_count") or 0)

    _p_start("validate_snapshot")
    if not cand_path.is_file():
        return {
            "ok": False,
            "error": "EXTRACT_PLAN_PREPARE_SNAPSHOT_STALE",
            "message_zh": "缺少 extract_plan_candidates.yaml",
        }
    candidates = read_yaml(cand_path)
    if not isinstance(candidates, dict):
        return {"ok": False, "error": "candidates not a mapping"}
    stamp_candidate_ids(candidates)
    cand_sha = ""
    sha_path = ir / "extract_plan_candidates.sha256"
    if sha_path.is_file():
        cand_sha = sha_path.read_text(encoding="utf-8").strip().split()[0]
    snap_cand = str(snap.get("candidates_sha256") or "")
    if snap_cand and cand_sha and snap_cand != cand_sha:
        return {
            "ok": False,
            "error": "EXTRACT_PLAN_PREPARE_SNAPSHOT_STALE",
            "message_zh": "candidates_sha256 与 prepare snapshot 不一致，禁止静默重算",
        }
    _p_done()

    ident = dict(identity or {})
    if not ident.get("architecture"):
        ident["architecture"] = snap.get("architecture") or candidates.get("architecture")

    staging = action_dir / "staging"
    relations_path = staging / "semantic_relations.yaml"

    _p_start("reduce_relation_parts")
    try:
        # 若 Runtime 已 reduce 并写入 staging/semantic_relations.yaml，直接复用。
        if relations_path.is_file() and llm_n > 0:
            loaded_g = read_yaml(relations_path)
            if isinstance(loaded_g, dict) and (loaded_g.get("relations") is not None or loaded_g.get("entities") is not None):
                graph = loaded_g
                grounding_errors = validate_input_root_grounding(graph)
            else:
                reduced = reduce_relation_parts(action_dir, base_graph)
                if not reduced.get("ok"):
                    return {
                        "ok": False,
                        "error": "RELATION_REDUCE_FAILED",
                        "errors": reduced.get("errors") or [],
                        "retry_shards": reduced.get("retry_shards") or [],
                        "grounding_errors": reduced.get("grounding_errors") or [],
                    }
                graph = reduced["graph"]
                grounding_errors = list(reduced.get("grounding_errors") or [])
        elif llm_n > 0:
            reduced = reduce_relation_parts(action_dir, base_graph)
            if not reduced.get("ok"):
                return {
                    "ok": False,
                    "error": "RELATION_REDUCE_FAILED",
                    "errors": reduced.get("errors") or [],
                    "retry_shards": reduced.get("retry_shards") or [],
                    "grounding_errors": reduced.get("grounding_errors") or [],
                }
            graph = reduced["graph"]
            grounding_errors = list(reduced.get("grounding_errors") or [])
        else:
            graph = base_graph
            atomic_write_yaml(relations_path, graph)
            grounding_errors = validate_input_root_grounding(graph)
    except Exception as exc:  # noqa: BLE001
        return _stage_fail("reduce_relation_parts", exc, debug_dir=debug_dir)
    _p_done()

    _p_start("validate_relation_graph")
    if grounding_errors and not allow_ungrounded:
        if not (graph.get("input_roots") or []):
            return {
                "ok": False,
                "error": "NO_INPUT_ROOTS",
                "grounding_errors": grounding_errors,
            }
    _p_done()

    _p_start("materialize_plan")
    try:
        plan = materialize_from_relations(graph, candidates, identity=ident)
    except Exception as exc:  # noqa: BLE001
        return _stage_fail("materialize_plan", exc, debug_dir=debug_dir)
    _p_done()

    _p_start("hydrate_evidence")
    try:
        plan = hydrate_materialized_plan(plan, candidates, candidates_sha256=cand_sha or snap_cand)
        for k in ("actor_id", "run_id", "workflow_id", "architecture"):
            if ident.get(k):
                plan[k] = ident[k]
        plan["confirmed_by"] = (
            "relation_graph_llm" if llm_n > 0 else "relation_graph_deterministic"
        )
        plan["candidates_sha256"] = cand_sha or snap_cand

        project_root = Path(repo_root)
        writer_pool = list(candidates.get("writer_candidates") or [])
        recv_pool = list(candidates.get("receiver_candidates") or [])
        from uo.scripts.extract_plan_io import _match_candidate

        for section, pool in (("writers", writer_pool), ("receivers", recv_pool)):
            for item in plan.get(section) or []:
                if isinstance(item, dict):
                    cand = _match_candidate(item, [c for c in pool if isinstance(c, dict)])
                    enrich_item_evidence_from_disk(
                        project_root,
                        item,
                        candidate=cand,
                        source_snapshot_hash=str(snap.get("source_snapshot_hash") or ""),
                    )
    except Exception as exc:  # noqa: BLE001
        return _stage_fail("hydrate_evidence", exc, debug_dir=debug_dir)
    _p_done()

    _p_start("validate_materialized_plan")
    try:
        plan = normalize_plan_from_candidates(plan, candidates)
        drop_invented_non_sink_roots(plan, candidates)
        auto_merge_high_confidence_aliases(plan, candidates)
        merge_receiver_bindings_into_plan(plan, candidates)
        errors = validate_extract_plan_against_candidates(
            plan, candidates, project_root=Path(repo_root)
        )
        structural = [
            e for e in errors if "missing" in e.lower() and "candidates" in e.lower()
        ]
    except Exception as exc:  # noqa: BLE001
        return _stage_fail("validate_materialized_plan", exc, debug_dir=debug_dir)
    _p_done()

    if check_only:
        return {
            "ok": not structural,
            "errors": errors,
            "grounding_errors": grounding_errors,
            "plan": plan,
            "graph": graph,
            "llm_required_count": llm_n,
        }
    if structural:
        return {
            "ok": False,
            "rejected_count": len(structural),
            "rejected": [{"reason": e} for e in structural],
            "errors": errors,
            "grounding_errors": grounding_errors,
        }

    aliases_rel = "extract_plan_aliases.yaml"
    bindings_rel = "receiver_bindings.yaml"
    relations_rel = "semantic_relations.yaml"

    _p_start("write_semantic_relations")
    try:
        ir.mkdir(parents=True, exist_ok=True)
        tmp_rel = ir / (relations_rel + ".tmp")
        write_yaml(tmp_rel, graph)
        rel_sha = file_sha256_bytes(tmp_rel.read_bytes())
    except Exception as exc:  # noqa: BLE001
        return _stage_fail("write_semantic_relations", exc, debug_dir=debug_dir)
    _p_done()

    _p_start("write_slim_extract_plan")
    try:
        slim, aliases_doc, bindings_doc = slim_extract_plan(
            plan,
            aliases_rel=aliases_rel,
            bindings_rel=bindings_rel,
            relations_rel=relations_rel,
            relations_sha=rel_sha,
        )
        # 禁止把 Relation 展开字段写入主计划。
        for key in RELATION_ONLY_KEYS:
            slim.pop(key, None)

        tmp_aliases = ir / (aliases_rel + ".tmp")
        tmp_bindings = ir / (bindings_rel + ".tmp")
        tmp_plan = ir / "extract_plan.yaml.tmp"
        write_yaml(tmp_aliases, aliases_doc)
        write_yaml(tmp_bindings, bindings_doc)
        a_sha = file_sha256_bytes(tmp_aliases.read_bytes())
        b_sha = file_sha256_bytes(tmp_bindings.read_bytes())
        slim2, _, _ = slim_extract_plan(
            plan,
            aliases_rel=aliases_rel,
            bindings_rel=bindings_rel,
            relations_rel=relations_rel,
            aliases_sha=a_sha,
            bindings_sha=b_sha,
            relations_sha=rel_sha,
        )
        for key in RELATION_ONLY_KEYS:
            slim2.pop(key, None)
        slim_errs = assert_canonical_plan_slim(slim2)
        if slim_errs:
            return {
                "ok": False,
                "error": "EXTRACT_PLAN_STAGE_FAILED",
                "stage": "write_slim_extract_plan",
                "errors": slim_errs,
                "message_zh": "canonical slim 校验失败",
            }
        write_yaml(tmp_plan, slim2)
    except Exception as exc:  # noqa: BLE001
        return _stage_fail("write_slim_extract_plan", exc, debug_dir=debug_dir)
    _p_done()

    _p_start("commit_canonical_artifacts")
    try:
        # 原子提交
        tmp_rel.replace(ir / relations_rel)
        tmp_aliases.replace(ir / aliases_rel)
        tmp_bindings.replace(ir / bindings_rel)
        tmp_plan.replace(ir / "extract_plan.yaml")
        write_yaml(ir / "semantic_observations.yaml", observations)
        atomic_write_yaml(staging / "semantic_relations.yaml", graph)
    except Exception as exc:  # noqa: BLE001
        return _stage_fail("commit_canonical_artifacts", exc, debug_dir=debug_dir)
    _p_done()

    return {
        "ok": True,
        "extract_plan_path": str(ir / "extract_plan.yaml"),
        "semantic_relations_path": str(ir / relations_rel),
        "writer_count": len(slim2.get("writers") or []),
        "receiver_count": len(slim2.get("receivers") or []),
        "binding_count": len((bindings_doc or {}).get("bindings") or {}),
        "alias_count": len((aliases_doc or {}).get("aliases") or {}),
        "grounding_errors": grounding_errors,
        "llm_required_count": llm_n,
        "unresolved_count": len(graph.get("unresolved") or []),
        "snapshot": snap,
    }


__all__ = [
    "prepare_semantic_relation_snapshot",
    "prepare_relation_extract_plan",
    "apply_semantic_extract_plan",
    "build_relation_artifacts",
]
