# -*- coding: utf-8 -*-
"""Operator TD decoder must import without a CANN checkout; clang work is lazy."""
from __future__ import annotations

import importlib.util
from pathlib import Path


def _module():
    repo = Path(__file__).resolve().parents[3]
    path = repo / "operators" / "flash_attention_score_grad" / "arch35" / "tilingdata_decoder.py"
    spec = importlib.util.spec_from_file_location("test_fag_tilingdata_decoder", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_decoder_import_is_lazy() -> None:
    mod = _module()
    assert callable(mod.decode)
    assert callable(mod.selfcheck)
    assert mod._layouts.cache_info().currsize == 0


def test_decoder_eval_context_and_scalar_codes() -> None:
    mod = _module()
    ctx = mod.eval_context({})
    assert ctx["param_to_dim"]["T13"] == "DeterType"
    assert ctx["enums"]["BLOCK_SIZE"] == 32
    assert mod._scalar_code("uint32_t") == "I"
    assert mod._scalar_code("float") == "f"
