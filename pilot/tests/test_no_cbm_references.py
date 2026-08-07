from __future__ import annotations

import importlib.util
from pathlib import Path


def test_cbm_negative_gate() -> None:
    repo = Path(__file__).resolve().parents[2]
    script = repo / "scripts" / "check_no_cbm.py"
    spec = importlib.util.spec_from_file_location("check_no_cbm", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.find_violations(repo) == []
