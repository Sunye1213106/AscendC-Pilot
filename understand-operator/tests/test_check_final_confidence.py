"""Tests for final confidence gate."""

from __future__ import annotations

from pathlib import Path

from uo.scripts._ir_io import write_yaml
from uo.scripts.check_final_confidence import check_final_confidence


def _uo(tmp_path: Path) -> Path:
    uo = tmp_path / ".understand-operator" / "demo"
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
    payload = check_final_confidence(uo, write_skeleton=False)
    assert payload["status"] == "pass"
    assert payload["need_llm_count"] == 0


def test_unsolved_without_report_fails_and_writes_skeleton(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(
        uo / "ir" / "input_derivable.yaml",
        {"keys": {"KEY_X": {"input_derivable": "unsolved", "confidence": "low", "reason": "缺边"}}},
    )
    payload = check_final_confidence(uo, write_skeleton=True)
    assert payload["status"] == "fail"
    report = uo / "summary" / "confidence_report.md"
    assert report.is_file()
    assert "KEY_X" in report.read_text(encoding="utf-8")
    assert "TODO" in report.read_text(encoding="utf-8")


def test_filled_report_allows_reported(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(
        uo / "ir" / "input_derivable.yaml",
        {"keys": {"KEY_X": {"input_derivable": "unsolved", "confidence": "low"}}},
    )
    (uo / "summary").mkdir(parents=True, exist_ok=True)
    (uo / "summary" / "confidence_report.md").write_text(
        "# 置信度未达 high 说明\n\n## 未达 high 的项\n\n"
        "### KEY_X\n- 状态：unsolved\n- 原因：证据不足，optional 未实例化，暂无法 high 闭合\n"
        "- 建议：人工确认后再补边\n",
        encoding="utf-8",
    )
    payload = check_final_confidence(uo, write_skeleton=False)
    assert payload["status"] == "reported"


def test_closed_without_high_hard_fails(tmp_path: Path) -> None:
    uo = _uo(tmp_path)
    write_yaml(
        uo / "ir" / "input_derivable.yaml",
        {"keys": {"KEY_Y": {"input_derivable": True, "confidence": "medium"}}},
    )
    payload = check_final_confidence(uo, write_skeleton=True)
    assert payload["status"] == "fail"
    assert payload["closed_without_high"]
