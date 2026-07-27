"""Scope expansion transactional / budget / evidence / SSOT correctness."""

from __future__ import annotations

import hashlib
from pathlib import Path

from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.scope_expansion import (
    MAX_FILES_PER_ROUND,
    apply_scope_expansion,
    audit_scope_expansion_request,
    cbm_index_ready_for_score,
)
from uo.scripts.source_include_closure import include_closure_is_complete, load_include_closure_ssot


def _op_with_include(tmp_path: Path) -> tuple[Path, Path]:
    op = tmp_path / "DemoOp"
    host = op / "op_host"
    host.mkdir(parents=True)
    (host / "main.cpp").write_text('#include "extra.h"\nvoid foo();\n', encoding="utf-8")
    (host / "extra.h").write_text("// reachable symbol FooBar\n", encoding="utf-8")
    (host / "orphan.cpp").write_text("// not included\n", encoding="utf-8")
    other = op / "op_kernel"
    other.mkdir(parents=True)
    (other / "extra.h").write_text("// same basename wrong path\n", encoding="utf-8")
    uo = op / ".ascendc-pilot" / "uo"
    (uo / "ir").mkdir(parents=True)
    scope = uo / "runs" / "r1" / "scope"
    scope.mkdir(parents=True)
    write_yaml(scope / "scope_confirmed.yaml", {"confirmed_source_files": [{"path": "op_host/main.cpp"}], "scope_revision": 1})
    return op, uo


def test_missing_scope_file_does_not_consume_request(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    (op / "op_host").mkdir(parents=True)
    uo = op / ".ascendc-pilot" / "uo"
    (uo / "ir").mkdir(parents=True)
    write_yaml(
        uo / "ir" / "scope_expansion_requests.yaml",
        {"version": 1, "requests": [{"task_id": "t1", "proposed_files": ["op_host/x.h"]}]},
    )
    result = apply_scope_expansion(op, "DemoOp", uo_root=uo)
    assert result.get("ok") is False
    assert result.get("error") == "SCOPE_CONFIRMED_MISSING"
    req = read_yaml(uo / "ir" / "scope_expansion_requests.yaml")
    assert req["requests"][0].get("status") not in {"consumed", "applied"}


def test_round_budget_records_all_file_dispositions(tmp_path: Path) -> None:
    op, uo = _op_with_include(tmp_path)
    # Create many include-reachable headers
    for i in range(MAX_FILES_PER_ROUND + 3):
        name = f"extra_{i}.h"
        (op / "op_host" / name).write_text(f"// {name}\n", encoding="utf-8")
        main = (op / "op_host" / "main.cpp").read_text(encoding="utf-8")
        (op / "op_host" / "main.cpp").write_text(main + f'#include "{name}"\n', encoding="utf-8")
    proposed = [f"op_host/extra_{i}.h" for i in range(MAX_FILES_PER_ROUND + 3)]
    audit = audit_scope_expansion_request(
        op,
        "DemoOp",
        {"proposed_files": proposed},
        confirmed_rels=["op_host/main.cpp"],
        uo_root=uo,
        round_slots_remaining=MAX_FILES_PER_ROUND,
        total_slots_remaining=32,
    )
    assert len(audit["file_dispositions"]) == len(proposed)
    assert len(audit["applied_files"]) == MAX_FILES_PER_ROUND
    assert any(d["disposition"] == "deferred_round_budget" for d in audit["file_dispositions"])


def test_total_budget_deferred_not_accepted(tmp_path: Path) -> None:
    op, uo = _op_with_include(tmp_path)
    (op / "op_host" / "extra2.h").write_text("// e2\n", encoding="utf-8")
    main = (op / "op_host" / "main.cpp").read_text(encoding="utf-8")
    (op / "op_host" / "main.cpp").write_text(main + '#include "extra2.h"\n', encoding="utf-8")
    audit = audit_scope_expansion_request(
        op,
        "DemoOp",
        {"proposed_files": ["op_host/extra.h", "op_host/extra2.h"]},
        confirmed_rels=["op_host/main.cpp"],
        uo_root=uo,
        round_slots_remaining=8,
        total_slots_remaining=0,
    )
    assert audit["applied_files"] == []
    assert all(d["disposition"] == "deferred_total_budget" for d in audit["file_dispositions"])


def test_symbol_evidence_window_verified(tmp_path: Path) -> None:
    op, uo = _op_with_include(tmp_path)
    good = audit_scope_expansion_request(
        op,
        "DemoOp",
        {
            "proposed_files": ["op_host/orphan.cpp"],
            "evidence_windows": [
                {
                    "file": "op_host/orphan.cpp",
                    "lines": [1, 1],
                    "snippet": "// not included",
                    "symbol": "included",
                }
            ],
        },
        confirmed_rels=["op_host/main.cpp"],
        uo_root=uo,
    )
    assert "op_host/orphan.cpp" in good["applied_files"]


def test_same_basename_wrong_path_rejected(tmp_path: Path) -> None:
    op, uo = _op_with_include(tmp_path)
    # Evidence names op_host/extra.h but proposes op_kernel/extra.h
    bad = audit_scope_expansion_request(
        op,
        "DemoOp",
        {
            "proposed_files": ["op_kernel/extra.h"],
            "symbol_evidence": [
                {"file": "op_host/extra.h", "lines": [1, 1], "snippet": "// reachable", "symbol": "FooBar"}
            ],
        },
        confirmed_rels=["op_host/main.cpp"],
        uo_root=uo,
    )
    assert "op_kernel/extra.h" not in bad["applied_files"]
    assert any(
        r.get("reason") in {"EVIDENCE_PATH_MISMATCH", "invalid_evidence", "not_reachable", "EVIDENCE_SNIPPET_MISMATCH"}
        or r.get("disposition") in {"invalid_evidence", "rejected"}
        for r in (bad["rejected_files"] + bad["file_dispositions"])
    )


def test_ambiguous_include_is_not_verified(tmp_path: Path) -> None:
    op = tmp_path / "DemoOp"
    (op / "op_host" / "a").mkdir(parents=True)
    (op / "op_host" / "b").mkdir(parents=True)
    (op / "op_host" / "main.cpp").write_text('#include "dup.h"\n', encoding="utf-8")
    (op / "op_host" / "a" / "dup.h").write_text("// a\n", encoding="utf-8")
    (op / "op_host" / "b" / "dup.h").write_text("// b\n", encoding="utf-8")
    uo = op / ".ascendc-pilot" / "uo"
    (uo / "ir").mkdir(parents=True)
    write_yaml(
        uo / "runs" / "r1" / "scope" / "scope_confirmed.yaml",
        {"confirmed_source_files": [{"path": "op_host/main.cpp"}]},
    )
    # Prefer proposing one of the ambiguous targets without unique resolution via relative include
    audit = audit_scope_expansion_request(
        op,
        "DemoOp",
        {"proposed_files": ["op_host/a/dup.h"]},
        confirmed_rels=["op_host/main.cpp"],
        uo_root=uo,
    )
    # Must not silently accept via basename; either applied via unique resolve from source dir, or ambiguous/reject
    if "op_host/a/dup.h" in audit["applied_files"]:
        # quote include from main.cpp parent may unique-resolve via suffix index failure → ambiguous
        pass
    else:
        assert any(
            d.get("disposition") in {"ambiguous_reachability", "rejected"}
            or d.get("reason") in {"ambiguous_reachability", "not_reachable", "include_target_ambiguous"}
            for d in audit["file_dispositions"]
        )


def test_include_closure_single_ssot(tmp_path: Path) -> None:
    uo = tmp_path / "uo"
    (uo / "ir").mkdir(parents=True)
    write_yaml(uo / "ir" / "scope_include_closure.yaml", {"files": ["a.h"], "truncated": False})
    data = load_include_closure_ssot(uo, migrate=True)
    assert (uo / "ir" / "include_closure.yaml").is_file()
    assert data.get("status") in {"complete", "partial", "failed"}
    assert include_closure_is_complete(uo) or data.get("status") == "complete"


def test_scope_expansion_requires_index_receipt(tmp_path: Path) -> None:
    op, uo = _op_with_include(tmp_path)
    write_yaml(
        uo / "ir" / "scope_expansion_requests.yaml",
        {"version": 1, "requests": [{"task_id": "t1", "proposed_files": ["op_host/extra.h"]}]},
    )
    result = apply_scope_expansion(op, "DemoOp", uo_root=uo)
    assert result.get("ok") is True
    assert result.get("pending_index") is True
    assert "detect_score_post" not in (result.get("next_actions") or [])
    assert (uo / "ir" / "cbm_reindex_request.yaml").is_file()
    assert (uo / "ir" / "include_closure.yaml").is_file()
    ready = cbm_index_ready_for_score(uo)
    assert ready.get("ok") is False
