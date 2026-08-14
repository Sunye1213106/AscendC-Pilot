# -*- coding: utf-8 -*-
"""CANN Reg / VF compute API spellings loaded from installed headers.

Member-call catalog stays small; these names are free/Reg vector APIs declared
under ``basic_api/reg_compute/kernel_reg_compute_*.h``. Spellings such as
``FusedExpSub`` are older LocalTensor aliases of the same operations.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_FN_RE = re.compile(
    r"__simd_callee__\s+inline\s+void\s+([A-Za-z_]\w*)\s*\("
)
_LEVEL2_RE = re.compile(
    r"__aicore__\s+inline\s+void\s+([A-Za-z_]\w*)\s*\("
)

# Older Level-2 names still used in operators; map onto the current Reg spelling.
VF_ALIASES: dict[str, str] = {
    "FusedExpSub": "ExpSub",
    "FusedMulDstAdd": "MulDstAdd",
}

# Spellings that also exist as project scalar/logic helpers. Never prove from
# the name alone — need a Reg/vector call shape (see kernel_root_trace).
AMBIGUOUS_VF_ROOTS: frozenset[str] = frozenset({"Min", "Max", "Or", "And", "Xor", "Not"})


def _header_roots(cann: Path) -> list[Path]:
    rels = (
        Path("cann-asc-devkit/x86_64-linux/asc/include/basic_api/reg_compute"),
        Path("cann-asc-devkit/x86_64-linux/asc/include/basic_api"),
        Path("cann-asc-devkit/x86_64-linux/ascendc/include/basic_api/interface/reg_compute"),
        Path("cann-asc-devkit/x86_64-linux/include/ascendc/basic_api/interface/reg_compute"),
        Path("cann-asc-devkit/x86_64-linux/tikcpp/tikcfw/interface/reg_compute"),
        Path("cann-asc-devkit/x86_64-linux/tikcpp/tikcfw/interface"),
    )
    out: list[Path] = []
    seen: set[Path] = set()
    for rel in rels:
        d = cann / rel
        if d.is_dir() and d not in seen:
            seen.add(d)
            out.append(d)
    return out


def _scan_file(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    names = set(_FN_RE.findall(text))
    stem = path.name.lower()
    if "reg_compute" in stem or "vec_binary" in stem or "vec_fused" in stem or "vec_unary" in stem:
        names.update(_LEVEL2_RE.findall(text))
    return {n for n in names if n and n[0].isupper()}


def _scan_dir(folder: Path) -> set[str]:
    names: set[str] = set()
    for pattern in ("kernel_reg_compute_*.h", "kernel_operator_vec_*_intf.h"):
        for path in folder.glob(pattern):
            names.update(_scan_file(path))
    return names


@lru_cache(maxsize=1)
def cann_vf_api_names() -> frozenset[str]:
    """Declared Reg/VF compute APIs plus known Fused* aliases."""
    from uo_init.paths import cann_root

    names: set[str] = set(VF_ALIASES)
    names.update(VF_ALIASES.values())
    root = cann_root()
    if root is not None:
        for folder in _header_roots(root):
            names.update(_scan_dir(folder))
    # Always keep the fused spellings used by current ops even if headers differ.
    names.update({"ExpSub", "MulDstAdd", "AbsSub", "MulsCast", "Or", "And", "Xor"})
    return frozenset(n for n in names if n and n[0].isupper())


def vf_root_spelling(callee: str) -> str:
    short = str(callee or "").split("::")[-1]
    return VF_ALIASES.get(short, short)


def is_cann_vf_api(callee: str) -> bool:
    short = vf_root_spelling(callee)
    return short in cann_vf_api_names()


def is_ambiguous_vf_name(callee: str) -> bool:
    return vf_root_spelling(callee) in AMBIGUOUS_VF_ROOTS
