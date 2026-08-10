# -*- coding: utf-8 -*-
"""tg-init full mode reads CodeMap .uo view_blobs only."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml


FAG_UO = Path(
    r"d:\PR-review\AscendC-Pilot\artifacts\fa-pr13\flash_attention_score_grad.arch35.uo"
)
FAG_OP = Path(r"d:\PR-review\TEST\ops-transformer\attention\flash_attention_score_grad")
FAG_HEADER = (
    FAG_OP / "op_kernel" / "arch35" / "flash_attention_score_grad_template_tiling_key.h"
)


@pytest.mark.skipif(not FAG_UO.is_file() or not FAG_HEADER.is_file(), reason="FAG fixtures missing")
def test_tg_contract_from_codemap_uo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("UO_OPERATOR", "flash_attention_score_grad")
    monkeypatch.setenv("UO_ARCH", "arch35")
    monkeypatch.setenv("ASCENDC_PROJECT_ROOT", str(tmp_path))

    (tmp_path / "op_host").mkdir()
    (tmp_path / "op_kernel").mkdir()
    uo_dir = tmp_path / ".ascendc-pilot" / "uo"
    uo_dir.mkdir(parents=True)
    product = uo_dir / "flash_attention_score_grad.arch35.uo"
    shutil.copy2(FAG_UO, product)

    from uo_init.tg_projection import backfill_from_source

    filled = backfill_from_source(
        tmp_path,
        uo_path=product,
        tiling_key_header=FAG_HEADER,
        op_name="flash_attention_score_grad",
        architecture="arch35",
    )
    assert filled.get("ok") is True
    assert int(filled.get("legal_key_count") or 0) == 8705

    from ascendc_pilot.paths import ensure_agent_layout
    from ascendc_pilot.actions.engines import (
        _run_tg_kb_check,
        _run_tg_contract_build,
        _run_tg_semantic_bind,
    )

    ensure_agent_layout(tmp_path, arch="arch35")
    # Migration must not move the CodeMap product out of .ascendc-pilot/uo/
    assert product.is_file()

    ctx = {
        "op_name": "flash_attention_score_grad",
        "architecture": "arch35",
        "mode": "tilingkey_full_coverage",
        "level": "L0",
    }
    kb = _run_tg_kb_check(tmp_path, ctx)
    assert kb.get("ok") is True, kb
    from ascendc_pilot.paths import tg_root

    assert (tg_root(tmp_path, arch="arch35") / "init" / "uo_ready.yaml").is_file()

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
