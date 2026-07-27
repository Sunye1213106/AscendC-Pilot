"""Scope expansion roots, reachability, recovery sequencing."""

from __future__ import annotations

from pathlib import Path

from uo.scripts.scope_expansion import apply_scope_expansion, audit_scope_expansion_request
from uo.scripts.source_path_resolve import resolve_scoped_source_path
from uo.scripts._ir_io import write_yaml


def test_sibling_operator_rejected(tmp_path: Path) -> None:
    repo = tmp_path / "attention"
    op = repo / "DemoOp"
    other = repo / "OtherOp"
    (op / "op_host").mkdir(parents=True)
    (other / "op_host").mkdir(parents=True)
    (other / "op_host" / "x.cpp").write_text("// sibling\n", encoding="utf-8")
    result = resolve_scoped_source_path(
        op, "OtherOp/op_host/x.cpp", "DemoOp", repository_root=repo
    )
    assert result["ok"] is False


def test_scope_expansion_requires_reachability(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    host = op / "op_host"
    host.mkdir(parents=True)
    (host / "main.cpp").write_text('#include "extra.h"\n', encoding="utf-8")
    (host / "extra.h").write_text("// reachable\n", encoding="utf-8")
    (host / "orphan.cpp").write_text("// not included\n", encoding="utf-8")
    uo = op / ".ascendc-pilot" / "uo"
    scope = uo / "runs" / "r1" / "scope"
    scope.mkdir(parents=True)
    write_yaml(scope / "scope_confirmed.yaml", {"confirmed_source_files": [{"path": "op_host/main.cpp"}]})
    # orphan without include/evidence -> reject
    bad = audit_scope_expansion_request(
        op,
        "DemoOp",
        {"proposed_files": ["op_host/orphan.cpp"]},
        confirmed_rels=["op_host/main.cpp"],
        uo_root=uo,
    )
    assert bad["ok"] is False
    assert any(r.get("reason") == "not_reachable" for r in bad["rejected_files"])
    # include-reachable -> accept
    good = audit_scope_expansion_request(
        op,
        "DemoOp",
        {"proposed_files": ["op_host/extra.h"]},
        confirmed_rels=["op_host/main.cpp"],
        uo_root=uo,
    )
    assert good["ok"] is True
    assert "op_host/extra.h" in good["accepted_files"]


def test_apply_updates_snapshot_and_consumes_requests(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    host = op / "op_host"
    host.mkdir(parents=True)
    (host / "main.cpp").write_text('#include "extra.h"\n', encoding="utf-8")
    (host / "extra.h").write_text("// ok\n", encoding="utf-8")
    uo = op / ".ascendc-pilot" / "uo"
    (uo / "ir").mkdir(parents=True)
    scope = uo / "runs" / "r1" / "scope"
    scope.mkdir(parents=True)
    write_yaml(scope / "scope_confirmed.yaml", {"confirmed_source_files": [{"path": "op_host/main.cpp"}]})
    write_yaml(
        uo / "ir" / "scope_expansion_requests.yaml",
        {"version": 1, "requests": [{"task_id": "t1", "proposed_files": ["op_host/extra.h"]}]},
    )
    result = apply_scope_expansion(op, "DemoOp", uo_root=uo)
    assert result.get("ok") is True
    assert result.get("new_files")
    assert (scope / "scope_snapshot.yaml").is_file()
    assert result.get("source_snapshot_hash")
    req = __import__("uo.scripts._ir_io", fromlist=["read_yaml"]).read_yaml(
        uo / "ir" / "scope_expansion_requests.yaml"
    )
    assert req["requests"][0].get("status") == "consumed"


def test_recovery_scope_sequencing() -> None:
    from ascendc_pilot.recovery import (
        SCOPE_EXPANSION_REWORK,
        SEMANTIC_PATCH_REWORK,
        recoveries_for_task_routes,
    )

    only_adj = recoveries_for_task_routes(
        [{"effective_task_type": "evidence_enrichment", "triage_category": "incomplete_scope_candidate"}]
    )
    assert SEMANTIC_PATCH_REWORK in only_adj["reason_codes"]
    assert SCOPE_EXPANSION_REWORK not in only_adj["reason_codes"]

    only_apply = recoveries_for_task_routes(
        [
            {
                "effective_task_type": "evidence_enrichment",
                "triage_category": "incomplete_scope_candidate",
                "pending_scope_expansion": True,
            }
        ]
    )
    assert SCOPE_EXPANSION_REWORK in only_apply["reason_codes"]
    assert SEMANTIC_PATCH_REWORK not in only_apply["reason_codes"]
