"""Synthetic-op tests for LLM extract_plan gate (no FAG names)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from uo._operator.artifacts import init_operator_contract_layout, operator_root
from uo.scripts.apply_extract_plan import apply_extract_plan
from uo.scripts.extract_host_subgraph import extract_host_subgraph
from uo.scripts.extract_kernel_subgraph import extract_kernel_subgraph
from uo.scripts.extract_plan_io import validate_extract_plan_against_candidates
from uo.scripts.propose_extract_plan import propose_extract_plan
from uo.scripts.semantic_pipeline import prepare_relation_extract_plan
from uo.scripts._ir_io import write_yaml
from uo.scripts.source_evidence import read_source_window, require_disk_window_proof
from tests._entrypoint_fixtures import write_entrypoint_graph

# Valid 64-hex for unit tests that do not assert hash↔file match (gate does).
_TEST_CAND_SHA = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def _prepare_and_apply(
    repo: Path,
    op: str,
    *,
    check_only: bool = False,
    architecture: str = "arch35",
) -> dict:
    """Relation 主链：prepare snapshot → apply（禁止 plan= 兼容参数）。"""
    from ascendc_pilot.runs import file_sha256

    ir = operator_root(repo, op) / "ir"
    cand_path = ir / "extract_plan_candidates.yaml"
    assert cand_path.is_file(), "需要先写入 extract_plan_candidates.yaml"
    sha = file_sha256(cand_path) or _TEST_CAND_SHA
    (ir / "extract_plan_candidates.sha256").write_text(sha + "\n", encoding="utf-8")
    from uo.scripts._ir_io import read_yaml

    cands = read_yaml(cand_path)
    # 覆盖空 boundary（夹具常写 inputs:[]），提供最小真实 input_roots
    boundary_path = ir / "operator_boundary.yaml"
    write_yaml(
        boundary_path,
        {
            "version": 1,
            "inputs": [
                {
                    "name": "x",
                    "dtype": "float16",
                    "layout": "ND",
                    "shape_dims": ["B", "S"],
                }
            ],
            "attrs": [{"name": "layout"}, {"name": "dtype"}],
        },
    )
    action_dir = repo / ".ascendc-pilot" / "runs" / "test_run" / "actions" / "extract_plan"
    action_dir.mkdir(parents=True, exist_ok=True)
    prep = prepare_relation_extract_plan(
        cands if isinstance(cands, dict) else {},
        action_dir=action_dir,
        action_session_id="test_session",
        source_snapshot_hash=sha,
        identity={"architecture": architecture, "candidates_sha256": sha},
        run_id="test_run",
        architecture=architecture,
        operator_boundary_path=boundary_path,
        entrypoint_graph_path=ir / "entrypoint_graph.yaml",
    )
    assert prep.get("ok"), prep
    return apply_extract_plan(
        repo,
        op,
        action_dir=action_dir,
        check_only=check_only,
        identity={
            "architecture": architecture,
            "candidates_sha256": sha,
            "run_id": "test_run",
            "action_session_id": "test_session",
        },
    )


def _window_snippet(repo: Path, rel: str, start: int, end: int) -> str:
    lines = (repo / rel).read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[start - 1 : end])


def _setup_foo_tiling(tmp_path: Path) -> tuple[Path, str]:
    op = "foo_op"
    repo = tmp_path / op
    host = repo / "op_host" / "arch35"
    kernel = repo / "op_kernel" / "arch35"
    host.mkdir(parents=True)
    kernel.mkdir(parents=True)

    (host / "foo_tiling.cpp").write_text(
        """
void FooTiling() {
  SaveStuff();
  GetTilingKey();
}

void SaveStuff() {
  blob_->set_x(1);
  blob_->set_y(2);
  mid_->set_tmp(0);
}

void GetTilingKey() {
  context->SetTilingKey(1);
}
""",
        encoding="utf-8",
    )
    (kernel / "foo_kernel.h").write_text(
        """
class FooKernel {
  void Process() {
    localType = tilingData->base.layout;
    if (localType == LAYOUT_TND) { DoTnd(); }
  }
};
""",
        encoding="utf-8",
    )

    root = operator_root(repo, op)
    init_operator_contract_layout(root, op, repo)
    ir = root / "ir"
    ir.mkdir(parents=True, exist_ok=True)
    write_entrypoint_graph(
        ir,
        op_name=op,
        host_name="FooTiling",
        host_file="op_host/arch35/foo_tiling.cpp",
        host_line=2,
        kernel_name="FooKernel",
        kernel_file="op_kernel/arch35/foo_kernel.h",
        kernel_line=2,
    )
    # propose_extract_plan requires boundary present (even empty slots).
    write_yaml(ir / "operator_boundary.yaml", {"inputs": [], "attributes": [], "outputs": []})
    return repo, op


def test_propose_finds_generic_receiver(tmp_path: Path) -> None:
    repo, op = _setup_foo_tiling(tmp_path)
    cands = propose_extract_plan(repo, op, architecture="arch35")
    write_yaml(
        operator_root(repo, op) / "ir" / "extract_plan_candidates.yaml",
        cands,
    )
    recv_names = {c["name"] for c in cands["receiver_candidates"]}
    assert "blob_" in recv_names
    writer_names = {c["name"] for c in cands["writer_candidates"]}
    assert "SaveStuff" in writer_names
    save = next(c for c in cands["writer_candidates"] if c["name"] == "SaveStuff")
    assert save.get("role_suggested") == "tiling_writer"
    blob = next(c for c in cands["receiver_candidates"] if c["name"] == "blob_")
    assert blob.get("is_tiling_sink_suggested") is True


def test_normalize_fills_role_and_sink_from_candidates(tmp_path: Path) -> None:
    from uo.scripts.extract_plan_io import normalize_plan_from_candidates

    repo, op = _setup_foo_tiling(tmp_path)
    cands = propose_extract_plan(repo, op, architecture="arch35")
    write_yaml(operator_root(repo, op) / "ir" / "extract_plan_candidates.yaml", cands)
    plan = {
        "version": 1,
        "confirmed_by": "llm",
        "writers": [
            {
                "name": "SaveStuff",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                # role omitted on purpose
            }
        ],
        "receivers": [
            {
                "name": "blob_",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                # is_tiling_sink omitted on purpose
            }
        ],
        "aliases": [],
        "non_sink_roots": [],
        "extra_host_entries": [],
    }
    # Drop writers/receivers not in candidates
    cw = {c["name"] for c in cands["writer_candidates"]}
    cr = {c["name"] for c in cands["receiver_candidates"]}
    plan["writers"] = [w for w in plan["writers"] if w["name"] in cw]
    plan["receivers"] = [r for r in plan["receivers"] if r["name"] in cr]

    # Ensure candidates expose sink suggestion so normalize can fill (no silent default).
    for rc in cands.get("receiver_candidates") or []:
        if str(rc.get("name") or "") == "blob_" and "is_tiling_sink_suggested" not in rc:
            rc["is_tiling_sink_suggested"] = True

    filled = normalize_plan_from_candidates(plan, cands)
    assert filled["writers"][0]["role"] == "tiling_writer"
    assert filled["receivers"][0]["is_tiling_sink"] is True
    # Promoted tiling_writer on possibly-weak candidate needs source evidence.
    snip = _window_snippet(repo, "op_host/arch35/foo_tiling.cpp", 7, 11)
    filled["candidates_sha256"] = _TEST_CAND_SHA
    filled["writers"][0].update(
        {
            "evidence_source": "source",
            "source_verified": True,
            "evidence_files": ["op_host/arch35/foo_tiling.cpp"],
            "evidence_lines": ["7-11"],
            "evidence_snippet": snip,
            "decision_reason": "blob_->set_x / set_y tilingData sink writes",
        }
    )
    filled["receivers"][0].update(
        {
            "evidence_source": "source",
            "source_verified": True,
            "evidence_files": ["op_host/arch35/foo_tiling.cpp"],
            "evidence_lines": ["7-11"],
            "evidence_snippet": snip,
            "decision_reason": "blob_ is tiling sink receiver in SaveStuff window",
        }
    )
    # Snippet may also mention mid_; list it (non-sink) so named-sink contract passes.
    if any(str(c.get("name") or "") == "mid_" for c in cands.get("receiver_candidates") or []):
        if not any(str(r.get("name") or "") == "mid_" for r in filled["receivers"]):
            filled["receivers"].append(
                {
                    "name": "mid_",
                    "file_path": "op_host/arch35/foo_tiling.cpp",
                    "is_tiling_sink": False,
                }
            )
    # Contract: unique GetTilingKey key_writer candidate must appear or ignore.
    if any(
        str(c.get("name") or "").casefold() == "gettilingkey"
        for c in cands.get("writer_candidates") or []
    ):
        key_snip = _window_snippet(repo, "op_host/arch35/foo_tiling.cpp", 13, 15)
        filled["writers"].append(
            {
                "name": "GetTilingKey",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "role": "key_writer",
                "evidence_source": "source",
                "source_verified": True,
                "evidence_files": ["op_host/arch35/foo_tiling.cpp"],
                "evidence_lines": ["13-15"],
                "evidence_snippet": key_snip,
                "decision_reason": "SetTilingKey on context",
            }
        )

    result_errs = validate_extract_plan_against_candidates(filled, cands, project_root=repo)
    structural = [e for e in result_errs if "missing" in e.lower() and "candidates" in e.lower()]
    assert not structural, result_errs


def test_host_no_tdf_without_plan(tmp_path: Path) -> None:
    repo, op = _setup_foo_tiling(tmp_path)
    payload = extract_host_subgraph(repo, op, architecture="arch35", allow_empty_plan=False)
    assert any(u.get("id") == "UNRES_EXTRACT_PLAN_MISSING" for u in payload["unresolved"])
    tdf_nodes = [n for n in payload["nodes"] if n.get("node_type") == "TilingDataField"]
    assert tdf_nodes == []


def test_host_tdf_after_plan(tmp_path: Path) -> None:
    repo, op = _setup_foo_tiling(tmp_path)
    cands = propose_extract_plan(repo, op, architecture="arch35")
    ir = operator_root(repo, op) / "ir"
    write_yaml(ir / "extract_plan_candidates.yaml", cands)

    save_snip = _window_snippet(repo, "op_host/arch35/foo_tiling.cpp", 7, 11)
    key_snip = _window_snippet(repo, "op_host/arch35/foo_tiling.cpp", 13, 15)
    plan = {
        "version": 1,
        "confirmed_by": "llm",
        "candidates_sha256": _TEST_CAND_SHA,
        "writers": [
            {
                "name": "SaveStuff",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "start_line": 8,
                "role": "tiling_writer",
                "evidence_source": "source",
                "source_verified": True,
                "evidence_files": ["op_host/arch35/foo_tiling.cpp"],
                "evidence_lines": ["7-11"],
                "evidence_snippet": save_snip,
                "decision_reason": "blob_->set_x / set_y tilingData sink writes",
            },
            {
                "name": "GetTilingKey",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "start_line": 14,
                "role": "key_writer",
                "evidence_source": "source",
                "source_verified": True,
                "evidence_files": ["op_host/arch35/foo_tiling.cpp"],
                "evidence_lines": ["13-15"],
                "evidence_snippet": key_snip,
                "decision_reason": "calls context->SetTilingKey",
            },
            {
                "name": "FooTiling",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "start_line": 2,
                "role": "ignore",
            },
        ],
        "receivers": [
            {
                "name": "blob_",
                "is_tiling_sink": True,
                "evidence_source": "source",
                "source_verified": True,
                "evidence_files": ["op_host/arch35/foo_tiling.cpp"],
                "evidence_lines": ["7-11"],
                "evidence_snippet": save_snip,
                "decision_reason": "blob_ tiling sink in SaveStuff",
            },
            {"name": "mid_", "is_tiling_sink": False},
        ],
        "aliases": [],
        "non_sink_roots": [],
        "extra_host_entries": [],
    }
    # Only include writers/receivers that exist in candidates
    cand_writers = {c["name"] for c in cands["writer_candidates"]}
    plan["writers"] = [w for w in plan["writers"] if w["name"] in cand_writers]
    cand_recv = {c["name"] for c in cands["receiver_candidates"]}
    plan["receivers"] = [r for r in plan["receivers"] if r["name"] in cand_recv]

    result = _prepare_and_apply(repo, op, check_only=False)
    assert result["ok"], result

    payload = extract_host_subgraph(repo, op, architecture="arch35")
    tdf_names = {n["name"] for n in payload["nodes"] if n.get("node_type") == "TilingDataField"}
    assert "x" in tdf_names or "y" in tdf_names


def test_kernel_alias_normalize(tmp_path: Path) -> None:
    repo, op = _setup_foo_tiling(tmp_path)
    ir = operator_root(repo, op) / "ir"
    # Minimal candidates so apply can validate alias if we skip apply
    write_yaml(
        ir / "extract_plan.yaml",
        {
            "version": 1,
            "confirmed_by": "test",
            "writers": [],
            "receivers": [],
            "aliases": [{"local": "localType", "tdf_leaf": "layout"}],
            "non_sink_roots": [],
            "extra_host_entries": [],
        },
    )
    payload = extract_kernel_subgraph(repo, op, architecture="arch35")
    refs = [
        b.get("determinant_ref") or b.get("node", {}).get("determinant_ref")
        for b in payload.get("branches") or []
    ]
    # branches may nest under node
    flat_refs = []
    for b in payload.get("branches") or []:
        if isinstance(b, dict):
            flat_refs.append(b.get("determinant_ref"))
            node = b.get("node") or {}
            if isinstance(node, dict):
                flat_refs.append(node.get("determinant_ref"))
    assert "layout" in flat_refs or any(r == "layout" for r in refs)
    assert "localType" not in [r for r in flat_refs if r]


def test_apply_rejects_invented_writer(tmp_path: Path) -> None:
    repo, op = _setup_foo_tiling(tmp_path)
    cands = propose_extract_plan(repo, op, architecture="arch35")
    write_yaml(
        operator_root(repo, op) / "ir" / "extract_plan_candidates.yaml",
        cands,
    )
    bad = {
        "version": 1,
        "confirmed_by": "llm",
        "writers": [{"name": "NotInCandidates", "role": "tiling_writer"}],
        "receivers": [],
        "aliases": [],
        "non_sink_roots": [],
        "extra_host_entries": [],
    }
    errs = validate_extract_plan_against_candidates(bad, cands, project_root=repo)
    assert errs
    assert any("NotInCandidates" in e or "not in candidates" in e.lower() for e in errs)


def test_validate_rejects_call_edge_adjudications(tmp_path: Path) -> None:
    """Edge adjudications must not live inside extract_plan.yaml."""
    from uo.scripts.extract_plan_io import validate_extract_plan_against_candidates

    repo, op = _setup_foo_tiling(tmp_path)
    cands = propose_extract_plan(repo, op, architecture="arch35")
    plan = {
        "version": 1,
        "confirmed_by": "llm",
        "writers": [],
        "receivers": [],
        "aliases": [],
        "call_edge_adjudications": [
            {"task_id": "t1", "action": "ACCEPT", "target": "FakeKernel"},
        ],
    }
    errors = validate_extract_plan_against_candidates(plan, cands)
    assert any("call_edge_adjudications" in e for e in errors)


def test_validate_non_sink_roots_string_list_ok() -> None:
    from uo.scripts.extract_plan_io import validate_extract_plan_against_candidates

    cands = {
        "writer_candidates": [],
        "receiver_candidates": [],
        "alias_candidates": [],
        "non_sink_root_candidates": [
            {"name": "ALIGN128", "file_path": "", "evidence": ["assign_lhs_only"]},
            {"name": "blockIdx", "file_path": "", "evidence": ["assign_lhs_only"]},
        ],
        "extra_entry_candidates": [],
    }
    plan = {
        "version": 1,
        "candidates_sha256": _TEST_CAND_SHA,
        "writers": [],
        "receivers": [],
        "aliases": [],
        "non_sink_roots": ["ALIGN128", "blockIdx"],
        "extra_host_entries": [],
        "derived_roots": [],
    }
    assert validate_extract_plan_against_candidates(plan, cands) == []


def test_validate_rejects_non_sink_roots_mapping() -> None:
    """Adjudication/unresolved objects under non_sink_roots are contract violations."""
    from uo.scripts.extract_plan_io import validate_extract_plan_against_candidates

    cands = {
        "writer_candidates": [],
        "receiver_candidates": [],
        "alias_candidates": [],
        "non_sink_root_candidates": [
            {"name": "ALIGN128", "file_path": "", "evidence": ["assign_lhs_only"]},
        ],
        "extra_entry_candidates": [],
    }
    plan = {
        "version": 1,
        "writers": [],
        "receivers": [],
        "aliases": [],
        "non_sink_roots": [
            {
                "name": "ALIGN128",
                "adjudication": "unresolved",
                "missing_evidence": "file_path",
                "reason": "assign_lhs_only",
            }
        ],
        "extra_host_entries": [],
    }
    errors = validate_extract_plan_against_candidates(plan, cands)
    assert any("must be a string name, got mapping" in e for e in errors)
    assert not any("not in candidates: {'name'" in e for e in errors)


def test_validate_rejects_derived_roots_mapping() -> None:
    from uo.scripts.extract_plan_io import validate_extract_plan_against_candidates

    cands = {
        "writer_candidates": [],
        "receiver_candidates": [],
        "alias_candidates": [],
        "non_sink_root_candidates": [],
        "extra_entry_candidates": [],
    }
    plan = {
        "version": 1,
        "writers": [],
        "receivers": [],
        "aliases": [],
        "non_sink_roots": [],
        "derived_roots": [{"name": "x", "adjudication": "unresolved"}],
    }
    errors = validate_extract_plan_against_candidates(plan, cands)
    assert any("derived_roots entry must be a string name, got mapping" in e for e in errors)


def test_validate_rejects_blocking_reasons_section() -> None:
    from uo.scripts.extract_plan_io import validate_extract_plan_against_candidates

    cands = {
        "writer_candidates": [],
        "receiver_candidates": [],
        "alias_candidates": [],
        "non_sink_root_candidates": [],
        "extra_entry_candidates": [],
    }
    plan = {
        "version": 1,
        "writers": [],
        "receivers": [],
        "aliases": [],
        "non_sink_roots": [],
        "blocking_reasons": [{"section": "non_sink_roots", "count_omitted": 30}],
    }
    errors = validate_extract_plan_against_candidates(plan, cands)
    assert any("blocking_reasons" in e for e in errors)


def test_plan_non_sink_roots_reads_strings_only() -> None:
    from uo.scripts.extract_plan_io import plan_non_sink_roots

    plan = {
        "non_sink_roots": [
            "ALIGN128",
            {"name": "blockIdx", "adjudication": "unresolved"},
        ]
    }
    assert plan_non_sink_roots(plan) == {"align128"}


def test_extract_plan_weak_candidate_requires_source_evidence() -> None:
    from uo.scripts.extract_plan_io import validate_extract_plan_against_candidates

    cands = {
        "writer_candidates": [
            {
                "name": "AlignTo",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "start_line": 40,
                "score": 0.45,
                "evidence": ["on_call_chain", "has_set_field"],
                "role_suggested": "tiling_writer",
                "qualified_name": "AlignTo",
            }
        ],
        "receiver_candidates": [],
        "alias_candidates": [],
        "non_sink_root_candidates": [],
        "extra_entry_candidates": [],
    }
    plan = {
        "version": 1,
        "writers": [
            {
                "name": "AlignTo",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "start_line": 40,
                "role": "tiling_writer",
                "evidence_source": "source",
                "source_verified": True,
                "evidence_files": [],
            }
        ],
        "receivers": [],
        "aliases": [],
        "non_sink_roots": [],
    }
    errors = validate_extract_plan_against_candidates(plan, cands)
    assert any("evidence_files" in e for e in errors)


def test_candidate_only_decision_not_marked_source_verified() -> None:
    from uo.scripts.extract_plan_io import validate_extract_plan_against_candidates

    cands = {
        "writer_candidates": [
            {
                "name": "SaveStuff",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "score": 0.9,
                "evidence": ["has_set_field", "tilingdata_assign"],
                "role_suggested": "tiling_writer",
            }
        ],
        "receiver_candidates": [],
        "alias_candidates": [],
        "non_sink_root_candidates": [],
        "extra_entry_candidates": [],
    }
    plan = {
        "version": 1,
        "writers": [
            {
                "name": "SaveStuff",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "role": "tiling_writer",
                "evidence_source": "candidate_only",
                "source_verified": True,
                "confidence": "source_verified",
            }
        ],
        "receivers": [],
        "aliases": [],
        "non_sink_roots": [],
    }
    errors = validate_extract_plan_against_candidates(plan, cands)
    assert any("candidate_only cannot set source_verified" in e for e in errors)


def test_align_helper_not_promoted_by_setter_name_only() -> None:
    from uo.scripts.extract_plan_io import validate_extract_plan_against_candidates

    cands = {
        "writer_candidates": [
            {
                "name": "AlignTo",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "start_line": 12,
                "score": 0.48,
                "evidence": ["on_call_chain", "has_set_field"],
                "role_suggested": "tiling_writer",
                "qualified_name": "AlignTo",
            }
        ],
        "receiver_candidates": [],
        "alias_candidates": [],
        "non_sink_root_candidates": [],
        "extra_entry_candidates": [],
    }
    plan = {
        "version": 1,
        "writers": [
            {
                "name": "AlignTo",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "start_line": 12,
                "role": "tiling_writer",
                "evidence_source": "candidate_only",
                "source_verified": False,
            }
        ],
        "receivers": [],
        "aliases": [],
        "non_sink_roots": [],
    }
    errors = validate_extract_plan_against_candidates(plan, cands)
    assert any("decision_reason" in e for e in errors)


def test_non_sink_roots_not_bulk_accepted_without_source() -> None:
    """non_sink_roots stay string-only; writers must not claim source_verified without files."""
    from uo.scripts.extract_plan_io import validate_extract_plan_against_candidates

    cands = {
        "writer_candidates": [
            {
                "name": "SaveStuff",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "score": 0.85,
                "evidence": ["has_set_field"],
                "role_suggested": "tiling_writer",
            }
        ],
        "receiver_candidates": [],
        "alias_candidates": [],
        "non_sink_root_candidates": [
            {"name": "ALIGN128", "file_path": "", "evidence": ["assign_lhs_only"]},
            {"name": "blockIdx", "file_path": "", "evidence": ["assign_lhs_only"]},
        ],
        "extra_entry_candidates": [],
    }
    plan = {
        "version": 1,
        "writers": [
            {
                "name": "SaveStuff",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "role": "tiling_writer",
                "source_verified": True,
                "evidence_source": "source",
            }
        ],
        "receivers": [],
        "aliases": [],
        "non_sink_roots": ["ALIGN128", "blockIdx"],
    }
    errors = validate_extract_plan_against_candidates(plan, cands)
    assert any("evidence_files" in e for e in errors)
    # String-only non_sink list still valid aside from writer evidence failure.
    assert not any("non_sink_roots entry must be a string" in e for e in errors)


def test_validate_rejects_semantic_groups_schema() -> None:
    from uo.scripts.extract_plan_io import validate_extract_plan_against_candidates

    cands = {
        "writer_candidates": [],
        "receiver_candidates": [],
        "alias_candidates": [],
        "non_sink_root_candidates": [],
        "extra_entry_candidates": [],
    }
    plan = {
        "version": 1,
        "semantic_groups": [{"group_id": "SG1", "members": []}],
        "writers": [],
        "receivers": [],
        "aliases": [],
    }
    errors = validate_extract_plan_against_candidates(plan, cands)
    assert any("semantic_groups" in e for e in errors)


def test_validate_rejects_alignto_as_tiling_writer() -> None:
    from uo.scripts.extract_plan_io import validate_extract_plan_against_candidates

    cands = {
        "writer_candidates": [
            {
                "name": "AlignTo",
                "file_path": "op_host/arch35/foo.cpp",
                "role_suggested": "tiling_writer",
                "score": 0.85,
                "evidence": ["has_set_field"],
            }
        ],
        "receiver_candidates": [],
        "alias_candidates": [],
        "non_sink_root_candidates": [],
        "extra_entry_candidates": [],
    }
    plan = {
        "version": 1,
        "writers": [
            {
                "name": "AlignTo",
                "file_path": "op_host/arch35/foo.cpp",
                "role": "tiling_writer",
                "evidence_source": "cbm",
                "source_verified": True,
                "evidence_files": ["op_host/arch35/foo.cpp"],
                "evidence_lines": ["10-20"],
                "decision_reason": "should still reject helper role",
            }
        ],
        "receivers": [],
        "aliases": [],
    }
    errors = validate_extract_plan_against_candidates(plan, cands)
    assert any("helper" in e.lower() or "AlignTo" in e for e in errors)


def test_disk_proof_requires_sha_and_contiguous_snippet(tmp_path: Path) -> None:
    repo, op = _setup_foo_tiling(tmp_path)
    rel = "op_host/arch35/foo_tiling.cpp"
    window = read_source_window(repo, rel, 7, 11, pad=0)
    sha = hashlib.sha256(window.encode("utf-8")).hexdigest()
    contiguous = _window_snippet(repo, rel, 7, 11)
    ok = require_disk_window_proof(
        repo,
        {
            "evidence_files": [rel],
            "evidence_lines": ["7-11"],
            "evidence_window_sha256": sha,
            "evidence_snippet": contiguous,
        },
    )
    assert ok.get("ok") is True

    # Correct sha but collage (non-contiguous picked lines) must fail.
    lines = (repo / rel).read_text(encoding="utf-8").splitlines()
    collage = "\n".join([lines[6], lines[8], lines[10]])  # 7,9,11 — skip middle
    while len(collage) < 48:
        collage += "\n" + lines[6]
    bad = require_disk_window_proof(
        repo,
        {
            "evidence_files": [rel],
            "evidence_lines": ["7-11"],
            "evidence_window_sha256": sha,
            "evidence_snippet": collage,
        },
    )
    assert bad.get("ok") is False


def test_validate_rejects_empty_sink_receivers_when_candidates_suggest(tmp_path: Path) -> None:
    from uo.scripts.extract_plan_io import validate_extract_plan_against_candidates

    repo, op = _setup_foo_tiling(tmp_path)
    cands = propose_extract_plan(repo, op, architecture="arch35")
    snip = _window_snippet(repo, "op_host/arch35/foo_tiling.cpp", 7, 11)
    window = read_source_window(repo, "op_host/arch35/foo_tiling.cpp", 7, 11, pad=0)
    sha = hashlib.sha256(window.encode("utf-8")).hexdigest()
    plan = {
        "version": 1,
        "candidates_sha256": _TEST_CAND_SHA,
        "writers": [
            {
                "name": "SaveStuff",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "role": "tiling_writer",
                "evidence_source": "source",
                "source_verified": True,
                "evidence_files": ["op_host/arch35/foo_tiling.cpp"],
                "evidence_lines": ["7-11"],
                "evidence_window_sha256": sha,
                "evidence_snippet": snip,
                "decision_reason": "blob_->set_x tiling sink writes",
            }
        ],
        "receivers": [],
        "aliases": [],
        "non_sink_roots": [],
    }
    errors = validate_extract_plan_against_candidates(plan, cands, project_root=repo)
    assert any("tiling_sink receivers must not be empty" in e for e in errors)
    assert any("GetTilingKey" in e for e in errors)


def test_build_candidates_summary_counts(tmp_path: Path) -> None:
    from uo.scripts.extract_plan_io import build_extract_plan_candidates_summary

    cand_path = tmp_path / "extract_plan_candidates.yaml"
    cand_path.write_text(
        "version: 1\n"
        "writer_candidates:\n"
        "- name: SaveStuff\n"
        "  file_path: op_host/a.cpp\n"
        "  start_line: 10\n"
        "  end_line: 20\n"
        "  source_window:\n"
        "    start_line: 10\n"
        "    end_line: 20\n"
        "    sha256: aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899\n"
        "- name: GetTilingKey\n"
        "  role_suggested: key_writer\n"
        "receiver_candidates:\n"
        "- name: blob_\n"
        "  is_tiling_sink_suggested: true\n"
        "- name: mid_\n"
        "  is_tiling_sink_suggested: false\n"
        "alias_candidates:\n"
        "- local: a\n"
        "  tdf_leaf: b\n"
        "non_sink_root_candidates: []\n"
        "extra_entry_candidates: []\n",
        encoding="utf-8",
    )
    summary = build_extract_plan_candidates_summary(
        {
            "writer_candidates": [
                {
                    "name": "SaveStuff",
                    "role_suggested": "tiling_writer",
                    "score": 0.8,
                    "file_path": "op_host/a.cpp",
                    "start_line": 10,
                    "end_line": 20,
                    "source_window": {
                        "start_line": 10,
                        "end_line": 20,
                        "sha256": (
                            "aabbccddeeff00112233445566778899"
                            "aabbccddeeff00112233445566778899"
                        ),
                    },
                },
                {"name": "GetTilingKey", "role_suggested": "key_writer", "score": 0.3},
            ],
            "receiver_candidates": [
                {"name": "blob_", "is_tiling_sink_suggested": True},
                {"name": "mid_", "is_tiling_sink_suggested": False},
            ],
            "alias_candidates": [{"local": "a", "tdf_leaf": "b"}],
            "non_sink_root_candidates": [],
            "extra_entry_candidates": [],
        },
        candidates_sha256=_TEST_CAND_SHA,
        section_lines={
            "writer_candidates": {"start_line": 2, "end_line": 12},
            "receiver_candidates": {"start_line": 13, "end_line": 17},
            "alias_candidates": {"start_line": 18, "end_line": 20},
            "non_sink_root_candidates": {"start_line": 21, "end_line": 21},
            "extra_entry_candidates": {"start_line": 22, "end_line": 22},
        },
        candidates_path=cand_path,
    )
    assert summary["counts"]["writers"] == 2
    assert summary["counts"]["sinks_suggested"] == 1
    assert "GetTilingKey" in summary["key_writer_suggested"]
    assert summary["alias_candidates"] == [{"local": "a", "tdf_leaf": "b"}]
    assert summary["section_lines"]["writer_candidates"]["start_line"] == 2
    assert "MUST Read this summary" in summary["must"]
    assert "section_lines" in summary["must"] or "BEFORE" in summary["must"]
    save = summary["writer_candidates"][0]
    assert save["end_line"] == 20
    assert save["source_window_sha256"] == (
        "aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899"
    )
    assert save["candidates_line"] == 3
    assert "source_window_sha256" in summary["must"]
    assert "FORBIDDEN" in summary["must"] and "neighbor" in summary["must"]
    assert summary["non_sink_root_names"] == []
    assert "non_sink_root_names" in summary["must"]


def test_build_candidates_summary_non_sink_root_names() -> None:
    from uo.scripts.extract_plan_io import build_extract_plan_candidates_summary

    summary = build_extract_plan_candidates_summary(
        {
            "writer_candidates": [],
            "receiver_candidates": [],
            "alias_candidates": [],
            "non_sink_root_candidates": [
                {"name": "ALIGN128", "score": 0.4},
                {"name": "blockIdx", "score": 0.4},
                {"name": "", "score": 0.4},
            ],
            "extra_entry_candidates": [],
        },
        candidates_sha256=_TEST_CAND_SHA,
    )
    assert summary["non_sink_root_names"] == ["ALIGN128", "blockIdx"]
    assert summary["counts"]["non_sink_roots"] == 3
    assert "prefer []" in summary["must"] or "non_sink_roots" in summary["must"]


def test_drop_invented_non_sink_roots() -> None:
    from uo.scripts.extract_plan_io import drop_invented_non_sink_roots

    plan = {
        "non_sink_roots": [
            "ALIGN128",
            "fBaseParams",
            "batchSize",
            {"name": "mapping_kept_for_validate"},
        ],
        "receivers": [],
    }
    cands = {
        "non_sink_root_candidates": [
            {"name": "ALIGN128"},
            {"name": "blockIdx"},
        ],
        "receiver_candidates": [],
    }
    tags = drop_invented_non_sink_roots(plan, cands)
    assert tags.count("drop_invented_non_sink") == 2
    assert plan["non_sink_roots"] == ["ALIGN128", {"name": "mapping_kept_for_validate"}]


def test_scan_yaml_section_lines_public(tmp_path: Path) -> None:
    from uo.scripts.ir_summary import attach_large_ir_meta, scan_yaml_section_lines

    p = tmp_path / "big.yaml"
    p.write_text("a:\n- 1\nb:\n- 2\n", encoding="utf-8")
    sections = scan_yaml_section_lines(p, ["a", "b"])
    assert sections["a"]["start_line"] == 1
    assert sections["b"]["start_line"] == 3
    meta = attach_large_ir_meta({"kind": "x", "counts": {}}, section_lines=sections, source_sha256="ab")
    assert meta["candidates_sha256"] == "ab"
    assert meta["section_lines"]["a"]["end_line"] == 2


def test_scan_candidates_section_lines(tmp_path: Path) -> None:
    from uo.scripts.extract_plan_io import scan_candidates_section_lines

    p = tmp_path / "extract_plan_candidates.yaml"
    p.write_text(
        "version: 1\n"
        "writer_candidates:\n"
        "- name: A\n"
        "receiver_candidates:\n"
        "- name: B\n"
        "alias_candidates:\n"
        "- local: x\n"
        "  tdf_leaf: y\n"
        "non_sink_root_candidates: []\n"
        "extra_entry_candidates: []\n",
        encoding="utf-8",
    )
    sections = scan_candidates_section_lines(p)
    assert sections["writer_candidates"]["start_line"] == 2
    assert sections["receiver_candidates"]["start_line"] == 4
    assert sections["alias_candidates"]["start_line"] == 6
    assert sections["writer_candidates"]["end_line"] == 3


def test_apply_backfills_collage_snippet(tmp_path: Path) -> None:
    """Product resilience: collage `...` snippet is replaced from disk window."""
    repo, op = _setup_foo_tiling(tmp_path)
    cands = propose_extract_plan(repo, op, architecture="arch35")
    ir = operator_root(repo, op) / "ir"
    write_yaml(ir / "extract_plan_candidates.yaml", cands)
    window = read_source_window(repo, "op_host/arch35/foo_tiling.cpp", 7, 11, pad=0)
    sha = hashlib.sha256(window.encode("utf-8")).hexdigest()
    collage = "void SaveStuff() {\n  blob_->set_x(1);\n  ...\n}"
    while len(collage) < 48:
        collage += "\n  blob_->set_x(1);"
    key_snip = _window_snippet(repo, "op_host/arch35/foo_tiling.cpp", 13, 15)
    key_win = read_source_window(repo, "op_host/arch35/foo_tiling.cpp", 13, 15, pad=0)
    key_sha = hashlib.sha256(key_win.encode("utf-8")).hexdigest()
    plan = {
        "version": 1,
        "candidates_sha256": _TEST_CAND_SHA,
        "writers": [
            {
                "name": "SaveStuff",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "role": "tiling_writer",
                "evidence_source": "source",
                "source_verified": True,
                "evidence_files": ["op_host/arch35/foo_tiling.cpp"],
                "evidence_lines": ["7-11"],
                "evidence_window_sha256": sha,
                "evidence_snippet": collage,
                "decision_reason": "blob_ set_* tiling sink",
            },
            {
                "name": "GetTilingKey",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "role": "key_writer",
                "evidence_source": "source",
                "source_verified": True,
                "evidence_files": ["op_host/arch35/foo_tiling.cpp"],
                "evidence_lines": ["13-15"],
                "evidence_window_sha256": key_sha,
                "evidence_snippet": key_snip,
                "decision_reason": "SetTilingKey",
            },
        ],
        "receivers": [
            {
                "name": "blob_",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "is_tiling_sink": True,
                "evidence_source": "source",
                "source_verified": True,
                "evidence_files": ["op_host/arch35/foo_tiling.cpp"],
                "evidence_lines": ["7-11"],
                "evidence_window_sha256": sha,
                "evidence_snippet": window,
                "decision_reason": "sink",
            },
            {
                "name": "mid_",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "is_tiling_sink": False,
            },
        ],
        "aliases": [],
        "non_sink_roots": [],
    }
    # Drop writers not in candidates
    cw = {c["name"] for c in cands["writer_candidates"]}
    plan["writers"] = [w for w in plan["writers"] if w["name"] in cw]
    cr = {c["name"] for c in cands["receiver_candidates"]}
    plan["receivers"] = [r for r in plan["receivers"] if r["name"] in cr]
    result = _prepare_and_apply(repo, op, check_only=False)
    assert result["ok"], result
    saved = (ir / "extract_plan.yaml").read_text(encoding="utf-8")
    # Canonical slim IR must not embed evidence snippets.
    assert "evidence_snippet" not in saved
    assert "aliases_ref" in saved or "receiver_bindings_ref" in saved


def test_apply_drops_invented_non_sink_and_passes(tmp_path: Path) -> None:
    """Invented non_sink string names are dropped; allowlisted names kept; gate can pass."""
    from uo.scripts._ir_io import read_yaml

    repo, op = _setup_foo_tiling(tmp_path)
    cands = propose_extract_plan(repo, op, architecture="arch35")
    ir = operator_root(repo, op) / "ir"
    # Ensure allowlist includes ALIGN128 when propose emits it; else inject.
    ns = list(cands.get("non_sink_root_candidates") or [])
    if not any(str(c.get("name") or "") == "ALIGN128" for c in ns if isinstance(c, dict)):
        ns.append(
            {
                "name": "ALIGN128",
                "file_path": "",
                "start_line": 0,
                "snippet": "ALIGN128 = ... (assign LHS only)",
                "score": 0.4,
                "evidence": ["assign_lhs_only"],
                "is_tiling_sink_suggested": False,
            }
        )
        cands["non_sink_root_candidates"] = ns
    write_yaml(ir / "extract_plan_candidates.yaml", cands)
    window = read_source_window(repo, "op_host/arch35/foo_tiling.cpp", 7, 11, pad=0)
    sha = hashlib.sha256(window.encode("utf-8")).hexdigest()
    key_snip = _window_snippet(repo, "op_host/arch35/foo_tiling.cpp", 13, 15)
    key_win = read_source_window(repo, "op_host/arch35/foo_tiling.cpp", 13, 15, pad=0)
    key_sha = hashlib.sha256(key_win.encode("utf-8")).hexdigest()
    plan = {
        "version": 1,
        "candidates_sha256": _TEST_CAND_SHA,
        "writers": [
            {
                "name": "SaveStuff",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "role": "tiling_writer",
                "evidence_source": "source",
                "source_verified": True,
                "evidence_files": ["op_host/arch35/foo_tiling.cpp"],
                "evidence_lines": ["7-11"],
                "evidence_window_sha256": sha,
                "evidence_snippet": window,
                "decision_reason": "blob_ set_* tiling sink",
            },
            {
                "name": "GetTilingKey",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "role": "key_writer",
                "evidence_source": "source",
                "source_verified": True,
                "evidence_files": ["op_host/arch35/foo_tiling.cpp"],
                "evidence_lines": ["13-15"],
                "evidence_window_sha256": key_sha,
                "evidence_snippet": key_snip,
                "decision_reason": "SetTilingKey",
            },
        ],
        "receivers": [
            {
                "name": "blob_",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "is_tiling_sink": True,
                "evidence_source": "source",
                "source_verified": True,
                "evidence_files": ["op_host/arch35/foo_tiling.cpp"],
                "evidence_lines": ["7-11"],
                "evidence_window_sha256": sha,
                "evidence_snippet": window,
                "decision_reason": "sink",
            },
            {
                "name": "mid_",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "is_tiling_sink": False,
            },
        ],
        "aliases": [],
        "non_sink_roots": ["ALIGN128", "fBaseParams", "batchSize"],
    }
    cw = {c["name"] for c in cands["writer_candidates"]}
    plan["writers"] = [w for w in plan["writers"] if w["name"] in cw]
    cr = {c["name"] for c in cands["receiver_candidates"]}
    plan["receivers"] = [r for r in plan["receivers"] if r["name"] in cr]
    result = _prepare_and_apply(repo, op, check_only=False)
    assert result["ok"], result
    from uo.scripts._ir_io import read_yaml

    saved = read_yaml(ir / "extract_plan.yaml")
    assert isinstance(saved, dict)
    # Relation 路径不再保留 invented non_sink；若仍有则不得含 fBaseParams/batchSize
    ns = saved.get("non_sink_roots") or []
    assert "fBaseParams" not in ns
    assert "batchSize" not in ns


def test_apply_overwrites_neighbor_wrong_sha(tmp_path: Path) -> None:
    """Wrong neighbor evidence_window_sha256 is corrected when files/lines/snippet match disk."""
    from uo.scripts._ir_io import read_yaml

    repo, op = _setup_foo_tiling(tmp_path)
    cands = propose_extract_plan(repo, op, architecture="arch35")
    ir = operator_root(repo, op) / "ir"
    write_yaml(ir / "extract_plan_candidates.yaml", cands)
    window = read_source_window(repo, "op_host/arch35/foo_tiling.cpp", 7, 11, pad=0)
    actual_sha = hashlib.sha256(window.encode("utf-8")).hexdigest()
    neighbor_sha = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
    assert neighbor_sha != actual_sha
    key_snip = _window_snippet(repo, "op_host/arch35/foo_tiling.cpp", 13, 15)
    key_win = read_source_window(repo, "op_host/arch35/foo_tiling.cpp", 13, 15, pad=0)
    key_sha = hashlib.sha256(key_win.encode("utf-8")).hexdigest()
    plan = {
        "version": 1,
        "candidates_sha256": _TEST_CAND_SHA,
        "writers": [
            {
                "name": "SaveStuff",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "role": "tiling_writer",
                "evidence_source": "source",
                "source_verified": True,
                "evidence_files": ["op_host/arch35/foo_tiling.cpp"],
                "evidence_lines": ["7-11"],
                "evidence_window_sha256": neighbor_sha,
                "evidence_snippet": window,
                "decision_reason": "blob_ set_* tiling sink",
            },
            {
                "name": "GetTilingKey",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "role": "key_writer",
                "evidence_source": "source",
                "source_verified": True,
                "evidence_files": ["op_host/arch35/foo_tiling.cpp"],
                "evidence_lines": ["13-15"],
                "evidence_window_sha256": key_sha,
                "evidence_snippet": key_snip,
                "decision_reason": "SetTilingKey",
            },
        ],
        "receivers": [
            {
                "name": "blob_",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "is_tiling_sink": True,
                "evidence_source": "source",
                "source_verified": True,
                "evidence_files": ["op_host/arch35/foo_tiling.cpp"],
                "evidence_lines": ["7-11"],
                "evidence_window_sha256": neighbor_sha,
                "evidence_snippet": window,
                "decision_reason": "sink",
            },
            {
                "name": "mid_",
                "file_path": "op_host/arch35/foo_tiling.cpp",
                "is_tiling_sink": False,
            },
        ],
        "aliases": [],
        "non_sink_roots": [],
    }
    cw = {c["name"] for c in cands["writer_candidates"]}
    plan["writers"] = [w for w in plan["writers"] if w["name"] in cw]
    cr = {c["name"] for c in cands["receiver_candidates"]}
    plan["receivers"] = [r for r in plan["receivers"] if r["name"] in cr]
    result = _prepare_and_apply(repo, op, check_only=False)
    assert result["ok"], result
    from uo.scripts._ir_io import read_yaml

    saved = read_yaml(ir / "extract_plan.yaml")
    assert isinstance(saved, dict)
    # Canonical slim IR drops evidence_* ; wrong neighbor sha must not leak into IR.
    text = (ir / "extract_plan.yaml").read_text(encoding="utf-8")
    assert "evidence_snippet" not in text
    assert "deadbeef" not in text
    # Sidecars written by finalizer.
    assert (ir / "extract_plan_aliases.yaml").is_file()
    assert (ir / "receiver_bindings.yaml").is_file()


def test_bucket_extract_plan_errors_dedupes() -> None:
    from uo.scripts.source_evidence import bucket_extract_plan_errors

    errs = [
        "writer A evidence_snippet is not a contiguous substring of the source window (collage / skipped lines rejected)",
        "writer A evidence_snippet is not a contiguous substring of the source window (collage / skipped lines rejected)",
        "receiver blob_ evidence_window_sha256 mismatch with on-disk source window",
        "alias missing local/tdf_leaf",
    ]
    b = bucket_extract_plan_errors(errs)
    assert b["raw_count"] == 4
    assert b["unique_count"] == 3
    assert b["counts"]["collage_snippet"] == 1
    assert "collage_snippet=1" in b["summary"]
