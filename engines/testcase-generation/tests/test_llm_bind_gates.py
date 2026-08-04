"""Thin AST + LLM-gate mechanism tests (no FAG specialization)."""

from __future__ import annotations

from pathlib import Path

import pytest

from testcase_agent.binding_inventory import build_domain_review, build_binding_inventory, fingerprint_consumer
from testcase_agent.domain_policy import expand_enum_domain, shape_range_domain
from testcase_agent.lexicon_propose import propose_key_derivations_from_evidence
from testcase_agent.solve import TgSolveError, _require_domain_review, _require_nonempty_realize


def test_missing_csv_ref_not_auto_locked() -> None:
    proposed, gaps = propose_key_derivations_from_evidence(
        lexicon={"key_tokens": {}, "key_derivations": []},
        csv_columns=["B", "keep_prob"],
        sample_values={},
        snapshot_files={
            "contracts/testcase.yaml": {
                "key_determinants": {
                    "KEY_ISDROP": {
                        "role": "optional_presence",
                        "needs_binding": False,
                        "csv_determinants": [{"column": "drop_shape", "op": "present"}],
                    }
                }
            }
        },
    )
    assert not any(item.get("id") == "VAR_KEY_ISDROP" for item in proposed["key_derivations"])
    miss = [g for g in gaps if g.get("code") == "MISSING_CSV_REF"]
    assert miss
    assert "drop_shape" in (miss[0].get("missing_columns") or [])


def test_needs_binding_key_goes_unresolved() -> None:
    _, gaps = propose_key_derivations_from_evidence(
        lexicon={"key_tokens": {}, "key_derivations": []},
        csv_columns=["keep_prob", "B"],
        sample_values={},
        snapshot_files={
            "contracts/testcase.yaml": {
                "key_determinants": {
                    "KEY_ISDROP": {"role": "optional_presence", "csv_determinants": [], "needs_binding": True}
                }
            }
        },
    )
    assert any(g.get("code") == "UNBOUND_KEY" and "ISDROP" in str(g.get("variable_id")) for g in gaps)


def test_secondary_layout_does_not_get_input_layout_enums() -> None:
    primary = expand_enum_domain("Input_Layout", [])
    secondary = expand_enum_domain("PSE_layout", [])
    assert "BNSD" in primary and "TND" in primary
    assert secondary == [] or set(secondary).isdisjoint({"BNSD", "TND", "BSND", "BSH", "SBH"})


def test_pre_next_allows_negative_range() -> None:
    dom = shape_range_domain("Pre_Tockens", sample_ints=[])
    assert dom["kind"] == "range"
    assert dom["min"] < 0
    assert dom["max"] > 0


def test_fingerprint_torch_vs_aclnn(tmp_path: Path) -> None:
    root = tmp_path / "tools"
    root.mkdir()
    (root / "t.py").write_text("import torch\nx = torch.zeros(1)\n", encoding="utf-8")
    fp = fingerprint_consumer(root)
    assert fp["consumer_kind"] == "torch"
    (root / "a.py").write_text("aclnnFlashAttentionScore(x)\n", encoding="utf-8")
    fp2 = fingerprint_consumer(root)
    assert fp2["consumer_kind"] == "mixed"


def test_domain_review_gate_blocks_pending(tmp_path: Path) -> None:
    out = tmp_path / "op"
    real = out / "realization"
    real.mkdir(parents=True)
    from testcase_agent.io import write_yaml

    write_yaml(
        real / "domain_review.yaml",
        {"status": "pending", "pending_columns": ["PSE_layout", "B"], "columns": []},
    )
    write_yaml(real / "unresolved.yaml", {"binding_gaps": []})
    with pytest.raises(TgSolveError, match="DOMAIN_REVIEW_REQUIRED"):
        _require_domain_review(out)


def test_binding_review_gate_blocks_unbound(tmp_path: Path) -> None:
    out = tmp_path / "op"
    real = out / "realization"
    real.mkdir(parents=True)
    from testcase_agent.io import write_yaml

    write_yaml(real / "domain_review.yaml", {"status": "confirmed", "pending_columns": [], "columns": []})
    write_yaml(
        real / "unresolved.yaml",
        {
            "binding_gaps": [
                {"code": "UNBOUND_KEY", "variable_id": "VAR_KEY_ISDROP", "message": "needs bind"},
            ]
        },
    )
    write_yaml(real / "binding_lexicon.yaml", {"key_derivations": []})
    with pytest.raises(TgSolveError, match="BINDING_REVIEW_REQUIRED"):
        _require_domain_review(out)


def test_binding_review_passes_when_locked(tmp_path: Path) -> None:
    out = tmp_path / "op"
    real = out / "realization"
    real.mkdir(parents=True)
    from testcase_agent.io import write_yaml

    write_yaml(real / "domain_review.yaml", {"status": "confirmed", "pending_columns": [], "columns": []})
    write_yaml(
        real / "unresolved.yaml",
        {"binding_gaps": [{"code": "UNBOUND_KEY", "variable_id": "VAR_KEY_ISDROP"}]},
    )
    write_yaml(
        real / "binding_lexicon.yaml",
        {
            "key_derivations": [
                {
                    "id": "VAR_KEY_ISDROP",
                    "locked": True,
                    "expr": {"op": "eq", "var": "VAR_CSV_keep_prob", "value": 1},
                }
            ]
        },
    )
    _require_domain_review(out)  # no raise


def test_inventory_marks_thin_and_consumer_kind(tmp_path: Path) -> None:
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "run.py").write_text("import torch\n", encoding="utf-8")
    schema = {
        "columns": ["B", "PSE_layout"],
        "fields": [
            {"name": "B", "role": "solver_input", "domain": {"kind": "range", "min": 1, "max": 8}},
            {"name": "PSE_layout", "role": "layout_secondary", "domain": ["_"]},
        ],
    }
    inv = build_binding_inventory(
        schema=schema,
        lexicon={"key_derivations": []},
        snapshot_files={
            "tiling/key_space.yaml": {
                "fields": [
                    {
                        "id": "KEY_ISDROP",
                        "needs_binding": True,
                        "csv_determinants": [],
                        "input_derivable": True,
                    }
                ]
            }
        },
        consumer_root=tools,
        binding_gaps=[],
    )
    assert inv["consumer_kind"] == "torch"
    assert any(t["column"] == "PSE_layout" for t in inv["thin_domains"])
    assert "KEY_ISDROP" in inv["needs_binding_keys"]
    review = build_domain_review(schema=schema, inventory=inv)
    assert review["status"] == "pending"
    assert "PSE_layout" in review["pending_columns"] or "B" in review["pending_columns"]


def test_realize_empty_fails() -> None:
    with pytest.raises(TgSolveError, match="REALIZE_EMPTY"):
        _require_nonempty_realize({"realized_count": 0, "selected_count": 3, "blocked_count": 3})
    _require_nonempty_realize({"realized_count": 0, "selected_count": 0, "blocked_count": 0})
    _require_nonempty_realize({"realized_count": 2, "selected_count": 2, "blocked_count": 0})


def test_load_dict_store_not_treated_as_csv_column(tmp_path: Path) -> None:
    from testcase_agent.consumer_evidence import build_consumer_evidence

    root = tmp_path / "tools"
    root.mkdir()
    (root / "x.py").write_text(
        'load_dict = {}\nload_dict["structural_only"] = 1\nrow["B"]\nget_column_index(t, "S1")\n',
        encoding="utf-8",
    )
    evidence = build_consumer_evidence(root, snapshot={}, obligations_doc={"obligations": []}, out_root=tmp_path)
    assert "B" in evidence["field_accesses"] or "S1" in evidence["field_accesses"]
    assert "structural_only" not in evidence["field_accesses"]
