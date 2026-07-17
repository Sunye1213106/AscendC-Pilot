from __future__ import annotations

from pathlib import Path

from uo.scripts.extract_golden import extract_golden


def test_extract_golden_fag_rich_metadata() -> None:
    repo = Path(r"d:\PR-review\TEST\FAG_test")
    if not (repo / "flash_attention_score_grad" / "tests" / "pytest" / "cpu_impl.py").exists():
        return
    payload = extract_golden(repo, "flash_attention_score_grad")
    assert payload["status"] == "ok"
    golden = payload["golden"]
    assert golden["function"] == "attentionScoreWithGrad"
    assert golden["start_line"] == 30
    assert golden["end_line"] >= 300
    assert "CalculationContext" in golden["signature"]
    assert "B" in golden["input_case_keys"]
    assert "sparse_mode" in golden["input_case_keys"]
    assert "DataGen" in golden["direct_calls"]
    assert "tforward" in golden["direct_calls"]
    assert "tbackward" in golden["direct_calls"]
    assert set(golden["outputs"]) >= {"dq", "dk", "dv"}
    assert any(h["name"] == "DataGen" for h in golden["helpers"])
    assert payload["nodes"]
    assert payload["edges"]
