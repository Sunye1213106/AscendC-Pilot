"""Regression: finalize must compare index_meta.op_name to the operator package, not KB dir name 'uo'."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from uo.scripts.finalize_scope import _validation_errors


def _scope_docs(op_name: str) -> dict:
    return {
        "context": {"op_name": op_name, "project_root": f"/tmp/{op_name}"},
        "installed_skill_check": {
            "skill_present": True,
            "consistent": True,
            "installed_skill_root": "skills/workflows/uo-init",
        },
        "scope_scan": {},
        "semantic_enrichment": {"status": "complete", "cbm_queries": [{"tool": "search", "query": "x", "result": {}}]},
        "scope_review": {},
        "scope_confirmed": {},
    }


def test_op_name_match_uses_package_not_uo_dirname(tmp_path: Path) -> None:
    repo = tmp_path / "flash_attention_score_grad"
    repo.mkdir()
    uo = repo / ".ascendc-pilot" / "uo"
    cbm = uo / "cbm"
    cbm.mkdir(parents=True)
    (cbm / "index_meta.json").write_text(
        json.dumps(
            {
                "repo_root": str(repo.resolve()),
                "op_name": "flash_attention_score_grad",
                "cbm_project": "flash_attention_score_grad-scope",
                "indexed_via": "mcp",
                "indexed_at": "2026-07-24T00:00:00+00:00",
                "project_confirmed": True,
            }
        ),
        encoding="utf-8",
    )
    # Other validators may still fail; assert the old uo_root.name bug is gone.
    errors = _validation_errors(
        repo.resolve(),
        uo,
        _scope_docs("flash_attention_score_grad"),
        op_name="flash_attention_score_grad",
    )
    assert not any("op_name does not match" in e for e in errors)
    assert uo.name == "uo"  # KB dirname is always uo; must not drive the check


def test_op_name_mismatch_still_reported(tmp_path: Path) -> None:
    repo = tmp_path / "flash_attention_score_grad"
    repo.mkdir()
    uo = repo / ".ascendc-pilot" / "uo"
    cbm = uo / "cbm"
    cbm.mkdir(parents=True)
    (cbm / "index_meta.json").write_text(
        json.dumps(
            {
                "repo_root": str(repo.resolve()),
                "op_name": "wrong_op",
                "cbm_project": "wrong_op-scope",
                "indexed_via": "mcp",
                "indexed_at": "2026-07-24T00:00:00+00:00",
                "project_confirmed": True,
            }
        ),
        encoding="utf-8",
    )
    errors = _validation_errors(
        repo.resolve(),
        uo,
        _scope_docs("flash_attention_score_grad"),
        op_name="flash_attention_score_grad",
    )
    assert any("op_name does not match" in e for e in errors)
    assert any("wrong_op" in e and "flash_attention_score_grad" in e for e in errors)


def test_scope_confirmed_operator_is_op_name_not_uo(tmp_path: Path) -> None:
    from uo.scripts.finalize_scope import _scope_confirmed_from_review

    uo = tmp_path / ".ascendc-pilot" / "uo"
    uo.mkdir(parents=True)
    (uo / "manifest.yaml").write_text(
        yaml.safe_dump({"current_run_id": "UO_RUN_TEST"}, sort_keys=False),
        encoding="utf-8",
    )
    confirmed = _scope_confirmed_from_review(
        uo,
        "UO_RUN_TEST",
        {"confirmed_file_list": [{"path": "a.cpp", "role": "host"}]},
        operator="flash_attention_score_grad",
    )
    assert confirmed["operator"] == "flash_attention_score_grad"
    assert confirmed["operator"] != "uo"
