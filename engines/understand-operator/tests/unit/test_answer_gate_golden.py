# -*- coding: utf-8 -*-
"""The answer-equivalence golden is a tracked oracle, not an artifacts dump."""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from uo_answer_gate import DEFAULT_GOLDEN, compare  # noqa: E402


def test_default_golden_exists_in_clean_tree() -> None:
    assert DEFAULT_GOLDEN.is_file(), DEFAULT_GOLDEN
    assert "tests" in DEFAULT_GOLDEN.parts
    assert "baselines" in DEFAULT_GOLDEN.parts
    assert "artifacts" not in DEFAULT_GOLDEN.parts
    payload = json.loads(DEFAULT_GOLDEN.read_text(encoding="utf-8"))
    answers = payload.get("answers") or {}
    assert isinstance(answers, dict) and answers


def test_compare_diffs_tiny_fixture_without_running_queries() -> None:
    gold = {"answers": {"Q1": {"ok": True, "span": "a.cpp:1"}}}
    same = compare(gold, {"answers": {"Q1": {"ok": True, "span": "a.cpp:1"}}})
    assert same == []
    changed = compare(gold, {"answers": {"Q1": {"ok": True, "span": "a.cpp:2"}}})
    assert changed
    missing = compare(gold, {"answers": {}})
    assert any("MISSING" in row for row in missing)
