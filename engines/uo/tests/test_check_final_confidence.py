"""Tests for final confidence gate."""

from __future__ import annotations

from pathlib import Path

from uo.scripts._ir_io import write_yaml
from uo.scripts.check_final_confidence import check_final_confidence


def _uo(tmp_path: Path) -> Path:
    uo = tmp_path / ".ascendc-agent" / "uo"
    (uo / "ir").mkdir(parents=True)
    (uo / "checks").mkdir(parents=True)
    (uo / "summary").mkdir(parents=True)
    return uo


def test_all_high_passes(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(
        uo / "ir" / "input_derivable.yaml",
        {
            "keys": {
                "KEY_A": {"input_derivable": True, "confidence": "high"},
                "KEY_B": {"input_derivable": False, "confidence": "high", "not_input_derivable": True},
            }
        },
    )
    payload = check_final_confidence(uo, write_report=False)
    assert payload["status"] == "pass"
    assert payload["need_llm_count"] == 0


def test_unsolved_deterministic_report_no_todo(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(
        uo / "ir" / "input_derivable.yaml",
        {
            "keys": {
                "KEY_X": {
                    "input_derivable": "unsolved",
                    "confidence": "low",
                    "reason": "宿主边缺失，无法接到 Host 输入根",
                    "attempted": "已跑 classify_input_derivable",
                    "suggestion": "补边或标 not_input_derivable",
                }
            }
        },
    )
    write_yaml(
        uo / "ir" / "key_triage.yaml",
        {"keys": [{"id": "KEY_X", "complexity": "simple"}]},
    )
    write_yaml(uo / "checks" / "human_accept_reported.yaml", {"accepted": True})
    payload = check_final_confidence(uo, write_report=True)
    report = uo / "summary" / "confidence_report.md"
    assert report.is_file()
    text = report.read_text(encoding="utf-8")
    assert "KEY_X" in text
    assert "TODO" not in text
    assert "宿主边缺失" in text
    assert payload.get("harness", {}).get("deterministic_report") is True
    assert payload["status"] == "reported"


def test_filled_report_allows_reported(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(
        uo / "ir" / "input_derivable.yaml",
        {
            "keys": {
                "KEY_X": {
                    "input_derivable": "unsolved",
                    "confidence": "low",
                    "reason": "证据不足，optional 未实例化，暂无法 high 闭合",
                    "suggestion": "人工确认后再补边",
                }
            }
        },
    )
    write_yaml(
        uo / "ir" / "key_triage.yaml",
        {"keys": [{"id": "KEY_X", "complexity": "simple"}]},
    )
    write_yaml(uo / "checks" / "human_accept_reported.yaml", {"accepted": True})
    payload = check_final_confidence(uo, write_report=True)
    assert payload["status"] == "reported"
    assert "TODO" not in (uo / "summary" / "confidence_report.md").read_text(encoding="utf-8")


def test_reported_without_triage_fails(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(
        uo / "ir" / "input_derivable.yaml",
        {
            "keys": {
                "KEY_X": {
                    "input_derivable": "unsolved",
                    "confidence": "low",
                    "reason": "故意缺 triage",
                }
            }
        },
    )
    payload = check_final_confidence(uo, write_report=True)
    assert payload["status"] == "fail"
    assert payload.get("harness", {}).get("triage_fail") is True


def test_closed_without_high_hard_fails(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(
        uo / "ir" / "input_derivable.yaml",
        {"keys": {"KEY_Y": {"input_derivable": True, "confidence": "medium", "reason": "置信度不够"}}},
    )
    payload = check_final_confidence(uo, write_report=True)
    assert payload["status"] == "fail"
    assert payload["closed_without_high"]
    assert "TODO" not in (uo / "summary" / "confidence_report.md").read_text(encoding="utf-8")
