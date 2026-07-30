# -*- coding: utf-8 -*-
"""CANN context accessor → root symbol binding model."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from uo_init.expr_ir import Call, Const, Expr, Ref, Unknown


DEFAULT_MODEL = {
    "GetAttrs.GetAttrPointer": {
        "pattern": r"GetAttrs\(\)->GetAttrPointer<[^>]+>\(\s*(?:static_cast<size_t>\()?AttrIndex::(\w+)",
        "root": "ATTRIBUTE",
        "name_from": "attr_index",
    },
    "GetInputDesc.GetDataType": {
        "pattern": r"GetInputDesc\(\s*(?:static_cast<size_t>\()?InputIndex::(\w+)",
        "root": "INPUT_DTYPE",
    },
    "GetStorageShape.GetDim": {
        "pattern": r"GetStorageShape\(\)\.GetDim\(\s*(\d+)\s*\)",
        "root": "INPUT_SHAPE",
        "dim": True,
    },
    "GetOptionalInputTensor": {
        "pattern": r"GetOptionalInputTensor\(\s*(?:static_cast<size_t>\()?InputIndex::(\w+)",
        "root": "OPTIONAL_INPUT_PRESENCE",
    },
}


@dataclass
class AccessorHit:
    root_kind: str
    name: str
    dim: int | None = None
    expr: Expr | None = None


def load_model(path: str | Path | None = None) -> dict[str, Any]:
    if path and Path(path).exists():
        return yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return DEFAULT_MODEL


def map_attr_index(enum_src: str, index_name: str) -> str:
    """Map AttrIndex::FOO to snake attribute name via enum order / comments — best effort."""
    # Convert TND_SOFTMAX_IN -> tnd_softmax_in style
    return index_name.lower()


def bind_expression(code: str, model: dict | None = None) -> Expr:
    model = model or DEFAULT_MODEL
    for _name, spec in model.items():
        m = re.search(spec["pattern"], code)
        if not m:
            continue
        root = spec["root"]
        if root == "ATTRIBUTE":
            attr = map_attr_index("", m.group(1))
            return Ref(f"Attr[{attr}]")
        if root == "INPUT_DTYPE":
            return Ref(f"InputDType[{m.group(1).lower()}]")
        if root == "INPUT_SHAPE" and spec.get("dim"):
            return Call("InputShapeDim", (Const(int(m.group(1))),))
        if root == "OPTIONAL_INPUT_PRESENCE":
            return Ref(f"OptionalPresence[{m.group(1).lower()}]")
    return Unknown("unmapped_accessor")


def layout_axis_scenes(code: str) -> list[dict[str, Any]]:
    """Path-sensitive axis derivation from strcmp(layout,\"TND\") style guards."""
    scenes = []
    if re.search(r'strcmp\s*\([^,]+,\s*"TND"\s*\)\s*==\s*0', code):
        scenes.append(
            {
                "guard": 'layout == "TND"',
                "axes": ["t1", "t2", "n1", "d"],
                "seq_lists": ["actual_seq_qlen", "actual_seq_kvlen"],
            }
        )
        scenes.append(
            {
                "guard": 'layout != "TND"',
                "axes": ["b", "s1", "s2", "n1", "d"],
                "seq_lists": [],
            }
        )
    return scenes


def count_getdim(src: str) -> int:
    return len(re.findall(r"GetStorageShape\(\)\.GetDim\s*\(|GetDim\s*\(", src))
