# -*- coding: utf-8 -*-
"""Implications between key dimensions, read off the tiling source.

These are deductions, not observations: each one names the line that forces it.
That matters because "the search never produced this" and "the host cannot
produce this" are different claims, and only the second one closes a gap.

Every entry is (name, predicate, reason). The predicate returns False when the
instance violates the implication, i.e. when the host could not have produced it.
"""

from __future__ import annotations

from typing import Callable

SRC_COMMON = "flash_attention_score_grad_tiling_common_regbase.cpp"
SRC_NORMAL = "flash_attention_score_grad_tiling_normal_regbase.cpp"

Rule = tuple[str, Callable[[dict], bool], str]


def _i(inst: dict, name: str) -> int:
    return int(inst[name])


RULES: list[Rule] = [
    (
        "rope forces D=192",
        lambda d: _i(d, "IsRope") != 1 or _i(d, "DTemplateNum") == 192,
        f"GetDTemplateType returns NUM192 as its first branch when hasRope "
        f"({SRC_COMMON}:849-852), so no other D template can accompany rope",
    ),
    (
        "swizzle forces non-deterministic",
        lambda d: _i(d, "IsTndSwizzle") != 1 or _i(d, "DeterType") == 0,
        f"templateSupportCond's deterministic branch ends in `&& false` "
        f"({SRC_NORMAL}:453-455), leaving only the !isDeterministic branch",
    ),
    (
        "swizzle forces the BN2S2 split",
        lambda d: _i(d, "IsTndSwizzle") != 1 or _i(d, "SplitAxis") == 5,
        f"the only live branch of templateSupportCond requires "
        f"splitAxis == BN2S2 ({SRC_NORMAL}:456)",
    ),
    (
        "swizzle forces TND",
        lambda d: _i(d, "IsTndSwizzle") != 1 or _i(d, "IsTnd") == 1,
        f"isTndSwizzle conjoins layoutType == INPUT_FORMAT_TND "
        f"({SRC_NORMAL}:461)",
    ),
    (
        "causal/band determinism needs a mask",
        lambda d: _i(d, "DeterType") not in (3, 4) or _i(d, "IsAttenMask") == 1,
        f"DETER_CAUSAL and DETER_BAND both require isSparse, and "
        f"SetSparseParams returns false as soon as attenMask is empty "
        f"({SRC_COMMON}:1545-1549)",
    ),
    (
        "NZ out needs 64 < D < 128",
        lambda d: _i(d, "IsNzOut") != 1 or _i(d, "DTemplateNum") == 128,
        f"isNzOut requires d > 64 and d < 128, which GetDTemplateType maps to "
        f"the 128 template ({SRC_NORMAL}:446-447, {SRC_COMMON}:856-858)",
    ),
    (
        "NZ out excludes float and quantised dtypes",
        lambda d: _i(d, "IsNzOut") != 1 or _i(d, "InputDType") in (2, 3),
        f"isNzOut excludes DT_FLOAT, FP8 and HIFLOAT8 ({SRC_NORMAL}:448-449); "
        f"only BF16 and FP16 remain",
    ),
    (
        "NZ out excludes DETER_OLD",
        lambda d: _i(d, "IsNzOut") != 1 or _i(d, "DeterType") != 1,
        f"isNzOut requires deterSparseType != DETER_OLD ({SRC_NORMAL}:450)",
    ),
    (
        "input and output dtype agree",
        lambda d: _i(d, "InputDType") == _i(d, "OutDType"),
        f"outDtype is assigned from inputDtype with no branch "
        f"({SRC_COMMON}:1182)",
    ),
]


def violated(inst: dict) -> list[tuple[str, str]]:
    """Rules this declared instance breaks, i.e. why the host cannot emit it."""
    out = []
    for name, ok, reason in RULES:
        try:
            if not ok(inst):
                out.append((name, reason))
        except (KeyError, ValueError):
            continue
    return out
