from __future__ import annotations

from pathlib import Path

from ascendc_pilot.actions.fast_tg_engines import (
    _cache_valid,
    _write_receipt,
    invoke_fast_tg_engine,
)


def _seed_contract(project: Path, consumer: Path) -> None:
    tg = project / ".ascendc-pilot" / "tg"
    files = {
        tg / "snapshot" / "understand_contract.json": "{}",
        tg / "realization" / "consumer_evidence.yaml": "version: 1\n",
        tg / "realization" / "consumer_schema.yaml": "version: 1\n",
        tg / "realization" / "realization_map.yaml": "version: 1\n",
        tg / "realization" / "binding_inventory.yaml": "version: 1\n",
        tg / "realization" / "domain_review.yaml": "status: confirmed\n",
        tg / "contract" / "testcase.yaml": "version: 1\n",
    }
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    consumer.mkdir(parents=True, exist_ok=True)
    (consumer / "runner.py").write_text("print('ok')\n", encoding="utf-8")


def test_contract_receipt_invalidates_on_consumer_change(tmp_path: Path) -> None:
    consumer = tmp_path / "tests"
    _seed_contract(tmp_path, consumer)
    _write_receipt(tmp_path, consumer)
    valid, _, _ = _cache_valid(tmp_path, consumer)
    assert valid is True

    (consumer / "runner.py").write_text("print('changed')\n", encoding="utf-8")
    valid, _, _ = _cache_valid(tmp_path, consumer)
    assert valid is False


def test_contract_build_skips_when_fingerprint_is_fresh(tmp_path: Path) -> None:
    consumer = tmp_path / "tests"
    _seed_contract(tmp_path, consumer)
    _write_receipt(tmp_path, consumer)
    calls = []

    def fallback(*args, **kwargs):
        calls.append((args, kwargs))
        return {"ok": False}

    out = invoke_fast_tg_engine(
        tmp_path,
        "tg-init",
        "contract_build",
        ctx={"csv_consumer_root": str(consumer)},
        fallback=fallback,
    )
    assert out["ok"] is True
    assert out["cache_hit"] is True
    assert out["contract_rebuilt"] is False
    assert calls == []


def test_contract_receipt_invalidates_on_output_corruption(tmp_path: Path) -> None:
    consumer = tmp_path / "tests"
    _seed_contract(tmp_path, consumer)
    _write_receipt(tmp_path, consumer)
    target = tmp_path / ".ascendc-pilot" / "tg" / "realization" / "realization_map.yaml"
    target.write_text("broken: true\n", encoding="utf-8")
    valid, _, _ = _cache_valid(tmp_path, consumer)
    assert valid is False
