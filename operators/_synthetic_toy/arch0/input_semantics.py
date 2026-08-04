# -*- coding: utf-8 -*-
"""Minimal InputSemantics for Phase-5 second-operator smoke."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence

LAYOUTS = ("FLAT",)
ATTEN_MASKS = ("none",)
PSE_SHAPES = ("none",)
DT = {"FLOAT": 0, "FLOAT16": 1}
IN_ORDER = ["x"]
OUT_ORDER = ["y"]
FIXED_DT: dict[str, int] = {}
ROPE_D = 0
PSE_ALIBI_S = 0
ROPE_TOTAL_D = 0


@dataclass
class Case:
    layout: str = "FLAT"
    dtype: str = "FLOAT"
    n: int = 4

    def normalised(self) -> "Case":
        if self.layout not in LAYOUTS:
            raise ValueError(f"unknown layout {self.layout!r}")
        if self.dtype not in DT:
            raise ValueError(f"unknown dtype {self.dtype!r}")
        if self.n < 1:
            raise ValueError("n must be positive")
        return replace(self)


def dtype_of(case: Case, name: str, main: int) -> int:
    del name, main
    return DT[case.dtype]


def shapes(case: Case) -> tuple[Mapping[str, Sequence[int]], Mapping[str, Sequence[int]]]:
    c = case.normalised()
    return {"x": [c.n]}, {"y": [c.n]}


_shapes = shapes


def describe(case: Case) -> Mapping[str, Any]:
    c = case.normalised()
    return {"layout": c.layout, "dtype": c.dtype, "n": c.n}


class _ToySemantics:
    @property
    def in_order(self) -> Sequence[str]:
        return IN_ORDER

    @property
    def out_order(self) -> Sequence[str]:
        return OUT_ORDER

    def shapes(self, case: Any):
        return shapes(case)

    def dtype_of(self, case: Any, name: str, main: int) -> int:
        return dtype_of(case, name, main)

    def normalize(self, case: Any) -> Any:
        return case.normalised()

    def describe(self, case: Any) -> Mapping[str, Any]:
        return describe(case)

    def enums(self) -> Mapping[str, Sequence[Any]]:
        return {"layout": LAYOUTS, "dtype": tuple(DT), "atten_mask": ATTEN_MASKS}

    def knob_schema(self) -> Mapping[str, Mapping[str, Any]]:
        return {
            "layout": {"kind": "categorical", "domain": list(LAYOUTS), "mutable": True},
            "dtype": {"kind": "categorical", "domain": list(DT), "mutable": True},
            "n": {"kind": "numeric", "mutable": True, "default": 4},
        }

    def from_knobs(self, knobs: Mapping[str, Any]) -> Case:
        return Case(
            layout=str(knobs.get("layout", "FLAT")),
            dtype=str(knobs.get("dtype", "FLOAT")),
            n=int(knobs.get("n", 4)),
        )

    def knobs_of(self, case: Any) -> Mapping[str, Any]:
        return describe(case)

    def repair(self, case: Any) -> Any:
        return case.normalised()


SEMANTICS = _ToySemantics()
