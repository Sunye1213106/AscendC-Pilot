# -*- coding: utf-8 -*-
"""Whether a clang diagnostic belongs to the operator tree (not CANN / family 3rd)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

# tikcfw and asc/include/basic_api both ship Atomic*Impl. libclang sees both
# copies; bisheng does not. Counted as operator errors when the TU is the
# diagnostic location, and can be fatal — neither is an operator defect.
_CANN_ATOMIC_REDEF_RE = re.compile(
    r"redefinition of 'Atomic\w+'"
)
_CANN_VECTOR_TYPE_RE = re.compile(
    r"unknown type name '(?:u?int|u?long|float|half|bfloat)\d+'"
)
_CANN_SIMT_BUILTIN_RE = re.compile(
    r"use of undeclared identifier 'warpSize'"
)


def is_libclang_cann_residual(spelling: str) -> bool:
    """True for known CANN dual-include residuals under vanilla clang."""
    text = str(spelling or "")
    return bool(
        _CANN_ATOMIC_REDEF_RE.search(text)
        or _CANN_VECTOR_TYPE_RE.search(text)
        or _CANN_SIMT_BUILTIN_RE.search(text)
    )


def score_tu_diagnostics(
    diagnostics: Iterable[Any],
    tu_path: str,
    op_dir: str,
) -> dict[str, Any]:
    """Error / fatal / operator-error counts, ignoring CANN libclang residuals."""
    errors = 0
    fatals = 0
    op_errors = 0
    op_fatals = 0
    samples: list[str] = []
    for d in diagnostics:
        try:
            sev = int(d.severity)
        except Exception:  # noqa: BLE001
            continue
        if sev < 3:
            continue
        try:
            spelling = str(d.spelling or "")
        except Exception:  # noqa: BLE001
            spelling = ""
        if is_libclang_cann_residual(spelling):
            continue
        errors += 1
        if sev >= 4:
            fatals += 1
        loc_file = ""
        try:
            if d.location.file is not None:
                loc_file = str(d.location.file.name)
        except Exception:  # noqa: BLE001
            loc_file = ""
        if diagnostic_in_operator(loc_file, op_dir, tu_path):
            op_errors += 1
            if sev >= 4:
                op_fatals += 1
        if len(samples) < 5:
            samples.append(spelling[:200])
    relevant = op_errors if fatals == 0 else op_errors + fatals
    return {
        "error_count": errors,
        "fatal_count": fatals,
        "operator_error_count": op_errors,
        "operator_fatal_count": op_fatals,
        "probe_relevant_errors": relevant,
        "samples": samples,
    }


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
