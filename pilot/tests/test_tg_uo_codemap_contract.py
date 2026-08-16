# -*- coding: utf-8 -*-
"""Optional FA CodeMap product regression. CI uses synthetic 4-key handoff instead."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml


REPO = Path(__file__).resolve().parents[2]
FAG_UO = REPO / "artifacts" / "fa-pr13" / "flash_attention_score_grad.arch35.uo"


@pytest.mark.skipif(
    not FAG_UO.is_file(),
    reason="optional local FA CodeMap artifact is not checked in (see .gitignore artifacts/ *.uo)",
)
def test_flashattention_product_only_uo_to_tg(tmp_path: Path, monkeypatch) -> None:

    monkeypatch.setenv("UO_OPERATOR", "flash_attention_score_grad")
    monkeypatch.setenv("UO_ARCH", "arch35")
    monkeypatch.setenv("ASCENDC_PROJECT_ROOT", str(tmp_path))

    (tmp_path / "op_host").mkdir()
    (tmp_path / "op_kernel").mkdir()
    uo_dir = tmp_path / ".ascendc-pilot" / "uo"
    uo_dir.mkdir(parents=True)
    product = uo_dir / "flash_attention_score_grad.arch35.uo"
    shutil.copy2(FAG_UO, product)

    # Upgrade missing TG projections from CodeMap entities without source/TPL.
    # Existing D must survive the atomic rewrite.
    from uo_init.tg_projection import backfill_from_source, load_tg_view

    filled = backfill_from_source(
        tmp_path,
        uo_path=product,
        op_name="flash_attention_score_grad",
        architecture="arch35",
    )
    assert filled.get("ok") is True, filled
    assert filled.get("tpl_rerun") is False, filled
    assert int(filled.get("legal_key_count") or 0) == 8705

    kernel = load_tg_view(product, "views/kernel.yaml") or {}
    tilingdata = load_tg_view(product, "views/tilingdata.yaml") or {}
    assert isinstance(kernel, dict) and isinstance(kernel.get("branches"), list)
    assert isinstance(tilingdata, dict) and isinstance(tilingdata.get("structs"), list)
    assert len(kernel.get("branches") or []) > 0, "FA CodeMap must establish kernel branch domain"
    assert sum(len((s or {}).get("fields") or []) for s in (tilingdata.get("structs") or [])) > 0, (
        "FA CodeMap must establish TilingData field domain"
    )

    from ascendc_pilot.paths import ensure_agent_layout, tg_root
    from ascendc_pilot.actions.engines import (
        _run_tg_kb_check,
        _run_tg_contract_build,
        _run_tg_semantic_bind,
    )

    ensure_agent_layout(tmp_path, arch="arch35")
    legacy_uo = tmp_path / ".ascendc-pilot" / "arch35" / "uo"
    # An empty mount point is tolerated; no YAML/DB/cache authority may exist.
    assert not legacy_uo.exists() or not any(p.is_file() for p in legacy_uo.rglob("*"))
    assert product.is_file()

    ctx = {
        "op_name": "flash_attention_score_grad",
        "architecture": "arch35",
        "mode": "tilingkey_full_coverage",
        "level": "L0",
    }
    kb = _run_tg_kb_check(tmp_path, ctx)
    assert kb.get("ok") is True, kb
    ready = Path(kb.get("receipt_path") or "")
    assert ready.is_file(), kb
    assert "receipts" in ready.as_posix()

    contract = _run_tg_contract_build(tmp_path, ctx)
    assert contract.get("ok") is True, contract
    payload = contract.get("payload") or {}
    assert int((payload.get("declared_set") or {}).get("count") or 0) == 8705

    bind = _run_tg_semantic_bind(tmp_path, ctx)
    assert bind.get("ok") is True, bind
    inv_path = Path(bind.get("inventory_path") or "")
    assert inv_path.is_file()
    inv = yaml.safe_load(inv_path.read_text(encoding="utf-8"))
    assert int(inv.get("field_count") or 0) > 0

    # TG must not quietly regenerate the old UO YAML tree as a side effect.
    assert not legacy_uo.exists() or not any(p.is_file() for p in legacy_uo.rglob("*"))
