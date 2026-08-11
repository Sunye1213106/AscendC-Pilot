# -*- coding: utf-8 -*-
"""tilingkey_full_coverage must not require a CSV consumer root."""

from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.paths import ensure_agent_layout, tg_root, uo_root


def test_is_tilingkey_full_detects_mode():
    from ascendc_pilot.actions.engines import _is_tilingkey_full

    assert _is_tilingkey_full({"mode": "tilingkey_full_coverage"})
    assert _is_tilingkey_full({"mode": "tilingkey_full"})
    # csv_consumer stack was removed; unknown/legacy modes are not full-TK.
    assert not _is_tilingkey_full({"mode": "csv_consumer"})


def test_init_intent_defaults_to_tilingkey(tmp_path: Path):
    from ascendc_pilot.actions.engines import _run_tg_init_intent

    ensure_agent_layout(tmp_path)
    (uo_root(tmp_path) / "manifest.yaml").write_text(
        "op_name: demo\narchitecture: arch35\n", encoding="utf-8"
    )
    out = _run_tg_init_intent(tmp_path, {"op_name": "demo"})
    assert out["ok"] is True
    assert out["mode"] == "tilingkey_full_coverage"
    path = tg_root(tmp_path) / "init" / "init_intent.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["schema"] == "tg-init-intent/v1"
    assert doc["mode"] == "tilingkey_full_coverage"


def test_plan_scope_without_consumer(tmp_path: Path):
    from ascendc_pilot.actions.engines import _run_tg_init_intent, _run_tg_plan_scope

    ensure_agent_layout(tmp_path)
    (uo_root(tmp_path) / "manifest.yaml").write_text(
        "op_name: demo\narchitecture: arch35\n", encoding="utf-8"
    )
    assert _run_tg_init_intent(tmp_path, {"op_name": "demo"})["ok"]
    out = _run_tg_plan_scope(tmp_path, {"op_name": "demo"})
    assert out["ok"] is True
    assert out["mode"] == "tilingkey_full_coverage"
    assert "csv_consumer_root" not in out


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
