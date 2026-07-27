"""Tests for extract_plan autofill, receiver binding, score canonicalize, shards, ownership."""
from __future__ import annotations

from pathlib import Path

from ascendc_pilot.ownership import (
    ACTION_FINALIZER_WRITE_PATHS,
    ACTION_PRODUCER_WRITE_PATHS,
    action_finalizer_write_paths,
    action_producer_write_paths,
    path_matches_patterns,
    shard_producer_write_paths,
)
from uo.scripts.extract_plan_autofill import (
    auto_merge_high_confidence_aliases,
    detect_alias_conflicts,
    stamp_candidate_ids,
    validate_tri_state_coverage,
)
from uo.scripts.receiver_binding import (
    extract_receiver_bindings_from_text,
    owner_identity_string,
)
from uo.scripts.score_canonicalize import (
    bridge_obligation_id,
    candidate_content_hash,
    canonicalize_score_items,
)
from uo.scripts.semantic_patch_shards import (
    plan_semantic_batches,
    reduce_semantic_parts,
    validate_part,
    write_semantic_batches,
)
from uo.scripts.extract_plan_io import PROMOTED_WRITER_ROLES, WRITER_ROLES, CHAIN_ROLES


def test_key_dimension_source_roles() -> None:
    assert "key_dimension_source" in WRITER_ROLES
    assert "key_dimension_source" in CHAIN_ROLES
    assert "key_dimension_source" not in PROMOTED_WRITER_ROLES


def test_stamp_candidate_ids_stable() -> None:
    cands = {
        "alias_candidates": [
            {
                "local": "x",
                "tdf_leaf": "b",
                "file_path": "a.cpp",
                "start_line": 10,
                "score": 0.85,
                "evidence": ["kernel_tdf_assign"],
            }
        ]
    }
    stamp_candidate_ids(cands)
    cid1 = cands["alias_candidates"][0]["candidate_id"]
    stamp_candidate_ids(cands)
    assert cid1 == cands["alias_candidates"][0]["candidate_id"]
    assert cid1.startswith("CAND_")


def test_alias_auto_fill_and_conflict_deferred() -> None:
    cands = {
        "alias_candidates": [
            {
                "candidate_id": "CAND_a1",
                "local": "foo",
                "tdf_leaf": "b",
                "score": 0.85,
                "evidence": ["kernel_tdf_assign"],
            },
            {
                "candidate_id": "CAND_a2",
                "local": "bar",
                "tdf_leaf": "c",
                "score": 0.9,
                "evidence": ["tdf_assign"],
            },
            {
                "candidate_id": "CAND_c1",
                "local": "dup",
                "tdf_leaf": "x",
                "score": 0.85,
                "evidence": ["kernel_tdf_assign"],
            },
            {
                "candidate_id": "CAND_c2",
                "local": "dup",
                "tdf_leaf": "y",
                "score": 0.85,
                "evidence": ["kernel_tdf_assign"],
            },
        ]
    }
    assert "dup" in detect_alias_conflicts(cands["alias_candidates"])
    plan: dict = {"aliases": [], "accepted_candidates": [], "deferred_candidates": [], "rejected_candidates": []}
    report = auto_merge_high_confidence_aliases(plan, cands)
    locals_accepted = {a["local"] for a in plan["aliases"]}
    assert "foo" in locals_accepted and "bar" in locals_accepted
    assert "dup" not in locals_accepted
    deferred_ids = {d["candidate_id"] for d in plan["deferred_candidates"]}
    assert "CAND_c1" in deferred_ids or "CAND_c2" in deferred_ids
    assert report["accepted"]
    errs = validate_tri_state_coverage(plan, cands)
    assert not errs


def test_receiver_binding_from_assign_and_macro_body() -> None:
    text = """
    FagTilingWithTemplateFFFF *tilingData = this->context_->GetTilingData<FagTilingWithTemplateFFFF>();
    s1s2BNGS1S2BaseParams_ = &tilingData->s1s2BNGS1S2BaseParams;
    preTilingData_ = &tilingData->preTilingData;
    FlashAttentionScoreGradS1S2BNGS1S2BaseParamsRegbase *s1s2BNGS1S2BaseParams_ = nullptr;
    """
    bindings = extract_receiver_bindings_from_text(text, file_path="op_host/x.cpp")
    by_recv = {b["receiver"]: b for b in bindings}
    assert "s1s2BNGS1S2BaseParams_" in by_recv
    b = by_recv["s1s2BNGS1S2BaseParams_"]
    assert b["nested_field"] == "s1s2BNGS1S2BaseParams"
    assert "FagTilingWithTemplateFFFF" in (b.get("root_tiling_types") or [])
    ident = owner_identity_string(b.get("canonical_owner_key"))
    assert "s1s2bngs1s2baseparams" in ident.casefold()
    assert "fagtilingwithtemplateffff" in ident.casefold()


def test_canonicalize_merges_gap_kinds() -> None:
    items = [
        {
            "disposition": "llm_task",
            "severity": "blocking",
            "object_type": "tilingdata_bridge",
            "target_id": "bridge_gap:unknown_type:b",
            "owning_type": "Params",
            "field_path": "b",
            "architecture": "arch35",
            "candidates": [],
        },
        {
            "disposition": "llm_task",
            "severity": "blocking",
            "object_type": "tilingdata_bridge",
            "target_id": "bridge_gap:missing_producer:b",
            "owning_type": "Params",
            "field_path": "b",
            "architecture": "arch35",
            "candidates": [{"id": "h1", "file_path": "a.cpp", "start_line": 1}],
        },
    ]
    out = canonicalize_score_items(items, architecture="arch35", source_snapshot_hash="snap1")
    bridge = [x for x in out if x.get("object_type") == "tilingdata_bridge"]
    assert len(bridge) == 1
    assert set(bridge[0].get("gap_kinds") or []) >= {"unknown_type", "missing_producer"}
    assert bridge[0].get("stable_task_id_override", "").startswith("TASK_")
    obl = bridge_obligation_id(
        owner_identity="Params",
        field_path="b",
        architecture="arch35",
    )
    assert bridge[0]["obligation_id"] == obl


def test_candidate_content_hash_changes_with_snippet() -> None:
    a = {"candidate_id": "C1", "file_path": "a.cpp", "start_line": 1, "snippet": "aaa"}
    b = {"candidate_id": "C1", "file_path": "a.cpp", "start_line": 1, "snippet": "bbb"}
    assert candidate_content_hash(a) != candidate_content_hash(b)


def test_semantic_batches_and_reduce(tmp_path: Path) -> None:
    tasks = [
        {
            "task_id": f"TASK_{i:03d}",
            "status": "open",
            "severity": "blocking",
            "eligible_for_adjudication": True,
            "route": "uo-semantic-resolve",
            "object_type": "tilingdata_bridge",
            "normalized_owner_identity": f"Owner{i // 4}",
        }
        for i in range(10)
    ]
    # also a degraded that must be excluded
    tasks.append(
        {
            "task_id": "TASK_DEG",
            "status": "open",
            "severity": "degraded",
            "eligible_for_adjudication": True,
            "route": "uo-semantic-resolve",
            "object_type": "tilingdata_bridge",
        }
    )
    man = plan_semantic_batches(
        tasks,
        action_session_id="AS1",
        source_snapshot_hash="SNAP",
        max_per_shard=4,
    )
    assert man["shard_count"] >= 2
    for sh in man["shards"]:
        assert int(sh["task_count"]) <= 4
        assert "TASK_DEG" not in sh["task_ids"]
    by_id = {t["task_id"]: t for t in tasks}
    write_semantic_batches(tmp_path, man, by_id)
    # write parts
    for sh in man["shards"]:
        sid = sh["shard_id"]
        part = {
            "run_id": "R1",
            "action_session_id": "AS1",
            "shard_id": sid,
            "task_ids": sh["task_ids"],
            "source_snapshot_hash": "SNAP",
            "candidate_set_hash": "x",
            "patches": [{"task_id": tid, "action": "inspect_candidates"} for tid in sh["task_ids"]],
        }
        assert not validate_part(part, shard=sh, manifest=man)
        from uo.scripts._ir_io import write_yaml

        write_yaml(tmp_path / "parts" / f"part_{sid}.yaml", part)
    reduced = reduce_semantic_parts(tmp_path, manifest=man)
    assert reduced["ok"] is True
    assert len(reduced["patches"]) == 10


def test_producer_cannot_match_finalizer_paths() -> None:
    prod = action_producer_write_paths("uo-init", "extract_plan", run_id="RUN1")
    fin = action_finalizer_write_paths("uo-init", "extract_plan", run_id="RUN1")
    assert any("staging" in p for p in prod)
    assert any(p.endswith("extract_plan.yaml") for p in fin)
    # Producer patterns must not authorize canonical IR write.
    assert not path_matches_patterns("uo/ir/extract_plan.yaml", prod)
    assert path_matches_patterns("uo/ir/extract_plan.yaml", fin)

    shard_writes = shard_producer_write_paths(
        "uo-init", "adjudicate_llm_tasks", run_id="RUN1", shard_id="bridge_000"
    )
    assert any("part_bridge_000.yaml" in p for p in shard_writes)
    assert not path_matches_patterns(
        "runs/RUN1/actions/adjudicate_llm_tasks/parts/part_bridge_001.yaml",
        shard_writes,
    )
    assert not path_matches_patterns("uo/ir/semantic_patches.yaml", shard_writes)
    assert "extract_plan" in (ACTION_PRODUCER_WRITE_PATHS.get("uo-init") or {})
    assert "extract_plan" in (ACTION_FINALIZER_WRITE_PATHS.get("uo-init") or {})


def test_io_slot_unique_auto_accept() -> None:
    from uo.scripts.evidence_score import score_io_slot

    slot = {
        "name": "query",
        "slot": 0,
        "direction": "input",
        "evidence": [{"file_path": "def.cpp", "snippet": "INPUT(query)"}],
        "host_accessors": [],
        "schema_unique": True,
        "declaration_unique": True,
    }
    result = score_io_slot(slot)
    assert result.get("disposition") == "auto_accept"
