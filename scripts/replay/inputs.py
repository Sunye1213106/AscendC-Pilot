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
_MOD_NAME = "uo_operator_input_semantics"
_mod: Any | None = None
_loaded_from: Path | None = None

_EXPORTS = (
    "LAYOUTS",
    "ATTEN_MASKS",
    "PSE_SHAPES",
    "DT",
    "IN_ORDER",
    "OUT_ORDER",
    "FIXED_DT",
    "ROPE_D",
    "PSE_ALIBI_S",
    "ROPE_TOTAL_D",
    "Case",
    "dtype_of",
    "shapes",
    "_shapes",
    "describe",
    "construct_case",
    "construct_reasons",
    "SEMANTICS",
)


def _semantics_path() -> Path:
    from .package_data import package_file

    return package_file("input_semantics.py")


def _load(path: Path | None = None) -> Any:
    global _mod, _loaded_from
    target = path or _semantics_path()
    if _mod is not None and _loaded_from == target:
        return _mod
    if _MOD_NAME in sys.modules:
        del sys.modules[_MOD_NAME]
    if not target.is_file():
        raise ImportError(
            "LOCAL_CAPABILITY_REQUIRED interface=case_builder "
            f"detail=no input semantics at {target}; place implementation under "
            "<op>/.ascendc-pilot/<arch>/local/case-builder/ or a tests/fixtures package"
        )
    spec = importlib.util.spec_from_file_location(_MOD_NAME, target)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_MOD_NAME] = mod
    spec.loader.exec_module(mod)
    _mod = mod
    _loaded_from = target
    return mod


def reload() -> Any:
    """Drop the cached semantics module (tests switching UO_OPERATOR)."""
    global _mod, _loaded_from
    _mod = None
    _loaded_from = None
    if _MOD_NAME in sys.modules:
        del sys.modules[_MOD_NAME]
    from . import package_data

    package_data.clear_caches()
    return _load()


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        return getattr(_load(), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS) | {"reload", "to_csv_line"})


def to_csv_line(c: Any, case_id: str) -> str:
    """Render the case in the replay driver's input format.

    Stays here rather than in the operator package because it goes through
    the adapter, which is still on the engine side of the P2 boundary.
    """
    from .adapter import ADAPTER

    return ADAPTER.materialize(c, case_id).serialize_for_host()
