"""Live eval must skip without a model/product and must not fake pass@k."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def test_live_cases_are_fixed_and_about_twenty() -> None:
    from evals.live.run import load_cases

    cases = load_cases(REPO)
    assert 18 <= len(cases) <= 24
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids))
    assert any("uo_query" in i or "oa_" in i for i in ids)


def test_live_eval_skips_without_model(monkeypatch) -> None:
    from evals.live.run import evaluate_live

    monkeypatch.delenv("ASCENDC_PILOT_LIVE_EVAL", raising=False)
    monkeypatch.delenv("ASCENDC_LIVE_EVAL_CMD", raising=False)
    doc = evaluate_live(REPO)
    assert doc["skipped"] is True
    assert doc["skip_reason"] == "no_model"
    assert doc["pass@k"] is None
    assert doc["pass@1"] is None
    assert doc["pass^k"] is None
    assert doc["pass_rate"] is None
    assert doc["ok"] is True
    assert all(r.get("skipped") for r in doc["runs"])


def test_live_eval_skips_without_product_when_enabled(monkeypatch, tmp_path: Path) -> None:
    from evals.live.run import evaluate_live

    monkeypatch.setenv("ASCENDC_PILOT_LIVE_EVAL", "1")
    monkeypatch.setenv("ASCENDC_LIVE_EVAL_CMD", "python -c pass")
    monkeypatch.setenv("ASCENDC_LIVE_PRODUCT", str(tmp_path))
    doc = evaluate_live(REPO, skill="uo-query")
    assert doc["skipped"] is True
    assert doc["skip_reason"] == "no_product"
    assert doc["pass@k"] is None
