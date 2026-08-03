# -*- coding: utf-8 -*-
"""Re-export of the active operator's input semantics.

The rules live in the operator package. This module exists so the dozens of
call sites that already say `from replay import inputs as I` keep working
while they migrate, and so the engine still has one place to ask "what is
the Case for this run?".

Once every caller imports from the package (or through the adapter), this
file shrinks to a loader and nothing else.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE = (_ROOT / "operators" / "flash_attention_score_grad"
            / "arch35" / "input_semantics.py")


def _load() -> Any:
    name = "uo_operator_input_semantics"
    if name in sys.modules:
        return sys.modules[name]
    if not _PACKAGE.is_file():
        raise ImportError(
            f"no input semantics at {_PACKAGE}; the operator package is "
            f"incomplete")
    spec = importlib.util.spec_from_file_location(name, _PACKAGE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_mod = _load()

# Re-export every public name the rest of the tree still imports.
LAYOUTS = _mod.LAYOUTS
ATTEN_MASKS = _mod.ATTEN_MASKS
PSE_SHAPES = _mod.PSE_SHAPES
DT = _mod.DT
IN_ORDER = _mod.IN_ORDER
OUT_ORDER = _mod.OUT_ORDER
FIXED_DT = _mod.FIXED_DT
ROPE_D = _mod.ROPE_D
PSE_ALIBI_S = _mod.PSE_ALIBI_S
ROPE_TOTAL_D = _mod.ROPE_TOTAL_D
Case = _mod.Case
dtype_of = _mod.dtype_of
shapes = _mod.shapes
_shapes = _mod._shapes
describe = _mod.describe
SEMANTICS = _mod.SEMANTICS


def to_csv_line(c: Case, case_id: str) -> str:
    """Render the case in the replay driver's input format.

    Stays here rather than in the operator package because it goes through
    the adapter, which is still on the engine side of the P2 boundary.
    """
    from .adapter import ADAPTER

    return ADAPTER.materialize(c, case_id).serialize_for_host()
