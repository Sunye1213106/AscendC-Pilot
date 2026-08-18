"""Host replay construction failure must fail closed (no analyze)."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.actions import tg_product
from ascendc_pilot.paths import ensure_agent_layout


def test_replay_round_wsl_unavailable_is_not_ok(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root, arch="arch35")

    monkeypatch.setattr(tg_product, "_live_replay", lambda ctx: True)
    monkeypatch.setattr(tg_product.products, "load_init", lambda tg: {"table_kind": "csv"})
    monkeypatch.setattr(tg_product.products, "cases_path", lambda tg, kind: root / "cases.csv")
    monkeypatch.setattr(
        tg_product,
        "_read_cases",
        lambda path: (["Testcase_Name"], [{"Testcase_Name": "c0"}]),
    )
    monkeypatch.setattr(tg_product, "_tg", lambda project_root, ctx: root)

    class Boom:
        def __init__(self) -> None:
            raise RuntimeError("REPLAY_BOOTSTRAP_FAILED:WSL_UNAVAILABLE:no distro")

    monkeypatch.setattr(
        "testcase_agent.closure.oracle.HostOracle",
        Boom,
        raising=False,
    )

    # Import path used inside run_replay_round.
    import testcase_agent.closure.oracle as oracle_mod

    monkeypatch.setattr(oracle_mod, "HostOracle", Boom)

    result = tg_product.run_replay_round(
        root,
        {"run_id": "r1", "workflow_id": "tg-solve", "action_id": "replay_round"},
    )
    assert result["ok"] is False
    assert result["error"] == "WSL_UNAVAILABLE"
    assert result["reason_code"] == "WSL_UNAVAILABLE"
    assert "WSL" in str(result.get("message_zh") or "")
    assert result.get("replayed") is False


def test_replay_bootstrap_failure_parses_cann_code() -> None:
    code, zh = tg_product._replay_bootstrap_failure(
        RuntimeError("REPLAY_BOOTSTRAP_FAILED:CANN_ENV_NOT_FOUND:missing pkg")
    )
    assert code == "CANN_ENV_NOT_FOUND"
    assert "CANN" in zh
