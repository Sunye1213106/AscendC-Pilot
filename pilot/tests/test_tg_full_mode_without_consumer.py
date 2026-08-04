# -*- coding: utf-8 -*-
"""tilingkey_full_coverage must not require a CSV consumer root."""

from __future__ import annotations

from pathlib import Path

import yaml


def test_require_consumer_optional_under_tilingkey_mode():
    from ascendc_pilot.actions.engines import (
        _is_tilingkey_full,
        _require_consumer_root,
    )

    assert _is_tilingkey_full({"mode": "tilingkey_full_coverage"})
    assert _require_consumer_root({"mode": "tilingkey_full_coverage"}) is None
    try:
        _require_consumer_root({"mode": "csv_consumer"})
        raised = False
    except RuntimeError as exc:
        raised = "TEST_SCRIPT_ROOT_REQUIRED" in str(exc)
    assert raised


def test_init_intent_defaults_to_tilingkey(tmp_path: Path):
    from ascendc_pilot.actions.engines import _run_tg_init_intent

    (tmp_path / ".ascendc-pilot" / "uo").mkdir(parents=True)
    (tmp_path / ".ascendc-pilot" / "uo" / "manifest.yaml").write_text(
        "op_name: demo\narchitecture: arch35\n", encoding="utf-8"
    )
    out = _run_tg_init_intent(tmp_path, {"op_name": "demo"})
    assert out["ok"] is True
    assert out["mode"] == "tilingkey_full_coverage"
    path = tmp_path / ".ascendc-pilot" / "tg" / "init" / "init_intent.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["schema"] == "tg-init-intent/v1"
    assert doc["mode"] == "tilingkey_full_coverage"


def test_plan_scope_without_consumer(tmp_path: Path):
    from ascendc_pilot.actions.engines import _run_tg_init_intent, _run_tg_plan_scope

    (tmp_path / ".ascendc-pilot" / "uo").mkdir(parents=True)
    (tmp_path / ".ascendc-pilot" / "uo" / "manifest.yaml").write_text(
        "op_name: demo\narchitecture: arch35\n", encoding="utf-8"
    )
    assert _run_tg_init_intent(tmp_path, {"op_name": "demo"})["ok"]
    out = _run_tg_plan_scope(tmp_path, {"op_name": "demo"})
    assert out["ok"] is True
    assert out["mode"] == "tilingkey_full_coverage"
    assert out["csv_consumer_root"] == ""


def test_candidate_human_rule_cannot_enter_E():
    """SOUND_GRADES only — a bare human rule must not shrink E."""
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    scripts = str(root / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from replay.rule_engine import Rule, RuleBook, SOUND_GRADES

    book = RuleBook(
        rules=(
            Rule(kind="combo", grade="human", label="BAD", when={"IsDrop": "1"}),
            Rule(
                kind="combo",
                grade="source_lemma",
                label="OK",
                when={"IsRope": "1", "DTemplateNum": "64"},
            ),
        )
    )
    inst = {"IsDrop": "1", "IsRope": "0", "DTemplateNum": "128"}
    assert book.excluded_by(inst) == ["BAD"]
    assert book.excluded_by_sound(inst) == []
    assert "human" not in SOUND_GRADES
    inst2 = {"IsDrop": "0", "IsRope": "1", "DTemplateNum": "64"}
    assert book.excluded_by_sound(inst2) == ["OK"]
