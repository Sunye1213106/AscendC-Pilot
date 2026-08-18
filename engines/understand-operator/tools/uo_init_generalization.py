# -*- coding: utf-8 -*-
"""Architecture-safe entrypoint for the UO generalization harness.

The retained implementation is loaded as data so this small shim can remove
its historical arch35 default without duplicating the large experiment driver.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

_IMPL = Path(__file__).with_suffix(".legacy")
_ns: dict[str, Any] = {
    "__name__": "uo_init_generalization_impl",
    "__file__": str(_IMPL),
    "__package__": None,
}
exec(compile(_IMPL.read_text(encoding="utf-8"), str(_IMPL), "exec"), _ns)


def _pick_arch(op: Path) -> str | None:
    """Use an architecture that exists in source; never invent one."""
    archs = _ns["_list_archs"](op)
    if archs:
        return max(archs, key=_ns["_arch_sort_key"])
    return None


# Functions defined in the retained implementation resolve globals from ``_ns``.
# Patch that namespace first, then re-export its public/testing surface.
_ns["_pick_arch"] = _pick_arch
for _name, _value in _ns.items():
    if not _name.startswith("__"):
        globals()[_name] = _value

# Keep the patched function visible even if the retained module had its own.
globals()["_pick_arch"] = _pick_arch

if __name__ == "__main__":
    raise SystemExit(_ns["main"]())
