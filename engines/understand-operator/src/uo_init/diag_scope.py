# -*- coding: utf-8 -*-
"""Whether a clang diagnostic belongs to the operator tree (not CANN / family 3rd)."""
from __future__ import annotations

from pathlib import Path


def diagnostic_in_operator(loc_file: str, op_dir: str, tu_path: str) -> bool:
    """True when the diagnostic file resolves under ``op_dir`` (or is the TU).

    Relative includes such as ``op_kernel/arch22/../../../../3rd/...`` keep the
    operator directory in the *lexical* path. Resolve first so family ``3rd/``
    and CANN headers are not counted as operator sources.
    """
    loc = str(loc_file or "").strip()
    if not loc:
        return False
    try:
        resolved = Path(loc).resolve()
    except (OSError, RuntimeError):
        return False
    tu = str(tu_path or "").strip()
    if tu:
        try:
            if resolved == Path(tu).resolve():
                return True
        except (OSError, RuntimeError):
            pass
    root_s = str(op_dir or "").strip()
    if not root_s:
        return False
    try:
        root = Path(root_s).resolve()
    except (OSError, RuntimeError):
        return False
    if resolved == root:
        return True
    return root in resolved.parents
