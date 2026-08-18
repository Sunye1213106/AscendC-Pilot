from pathlib import Path

import pytest

from testcase_agent import init_status


def test_fingerprint_hint_never_defaults_arch35(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(init_status, "_product_uo_root", lambda *args, **kwargs: None)

    import ascendc_pilot.paths as paths

    def unresolved(_root: Path) -> Path:
        raise ValueError("ARCHITECTURE_AMBIGUOUS")

    monkeypatch.setattr(paths, "uo_product_root", unresolved)

    with pytest.raises(init_status.InitGateError) as excinfo:
        init_status._fingerprint_hint(tmp_path, "demo_op")

    err = excinfo.value
    assert err.ask == "architecture_required"
    assert err.payload["reason_code"] == "ARCHITECTURE_UNRESOLVED"
    assert "arch35" not in str(err.payload)
