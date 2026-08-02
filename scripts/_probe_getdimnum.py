# -*- coding: utf-8 -*-
"""Temporary probe: GetDimNum vs GetDim resolution paths."""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "engines" / "common"))

from uo_init.cpp_expr import parse_expr
from uo_init.expr_ir import Call, Ref, Const
from uo_init.source_resolver import SourceResolver, CALL_ROOTS, _match, _call_name, _DIM_ACCESSOR_RE
from uo_init.variable_model import VariableModel, slug


class _Model:
    def __init__(self, constants, operands):
        self.named_constants = dict(constants)
        self._operands = dict(operands)

    def operand_names(self):
        return {k: list(v) for k, v in self._operands.items()}


def dump_expr(e, indent=0):
    pad = "  " * indent
    if isinstance(e, Call):
        print(f"{pad}Call(func={e.func!r}, nargs={len(e.args)})")
        for a in e.args:
            dump_expr(a, indent + 1)
    elif isinstance(e, Ref):
        print(f"{pad}Ref({e.symbol!r})")
    elif isinstance(e, Const):
        print(f"{pad}Const({e.value!r})")
    else:
        print(f"{pad}{type(e).__name__}({e!r})")


def show_resolve(label, expr, r: SourceResolver):
    print("\n====", label, "====")
    print("EXPR:", expr)
    try:
        tree = parse_expr(expr)
        dump_expr(tree)
    except Exception as ex:
        print("parse failed:", ex)
    res = r.resolve(expr)
    for i, a in enumerate(res.atoms):
        print(
            f"atom[{i}]: root={a.root} symbol={a.symbol!r} index={a.index} "
            f"reason={a.reason} text={a.text!r} via={a.via}"
        )
        vid = None
        if a.root:
            # mimic var_id_for
            sym = slug(a.symbol or "")
            if a.root == "INPUT_SHAPE":
                vid = f"VAR_SHAPE_{sym}_D{a.index}" if a.index is not None else f"VAR_SHAPE_{sym}"
            else:
                vid = f"VAR_{a.root}_{sym}"
        print("  -> var_id guess:", vid)


def main():
    r = SourceResolver()
    r.adopt(
        _Model(
            {
                "QUERY_INPUT_INDEX": 0,
                "KEY_INPUT_INDEX": 1,
                "PSE_SHIFT": 5,
                "DIM_2": 2,
            },
            {
                "input": ["query", "key", "value", "dy", "pse_shift", "atten_mask"],
                "output": ["dq", "dk", "dv"],
            },
        )
    )

    cases = [
        ("GetDim chain", "ctx->GetInputShape(QUERY_INPUT_INDEX)->GetStorageShape().GetDim(DIM_2)"),
        ("GetDimNum chain", "ctx->GetInputShape(QUERY_INPUT_INDEX)->GetStorageShape().GetDimNum()"),
        ("GetDimNum on local", "queryShape.GetDimNum()"),
        ("GetDimNum arrow local", "queryShape->GetStorageShape().GetDimNum()"),
        ("optional GetDimNum", "pseShape->GetStorageShape().GetDimNum()"),
        ("bare storage GetDimNum", "storageShape.GetDimNum()"),
        ("GetDimNum == 0", "pseShape->GetStorageShape().GetDimNum() == 0"),
        ("queryRope GetDimNum", "queryRopeShape->GetDimNum() != 0"),
    ]
    for label, expr in cases:
        show_resolve(label, expr, r)

    # with bindings like FAG locals
    r2 = r.scoped(
        bindings={
            "queryShape": "ctx->GetInputShape(QUERY_INPUT_INDEX)",
            "pseShape": "ctx->GetOptionalInputShape(5)",
            "storageShape": "ctx->GetOptionalInputShape(5)->GetStorageShape()",
            "queryRopeShape": "ctx->GetOptionalInputShape(10)->GetStorageShape()",
        }
    )
    print("\n\n######## WITH BINDINGS ########")
    for label, expr in [
        ("bound queryShape.GetDimNum", "queryShape->GetStorageShape().GetDimNum()"),
        ("bound pse GetDimNum==0", "pseShape->GetStorageShape().GetDimNum() == 0"),
        ("bound storageShape.GetDimNum", "storageShape.GetDimNum()"),
        ("bound queryRopeShape->GetDimNum", "queryRopeShape->GetDimNum() != 0"),
        ("bound queryShape.GetDim", "queryShape->GetStorageShape().GetDim(DIM_2)"),
    ]:
        show_resolve(label, expr, r2)

    # Inspect CALL_ROOTS match for GetDimNum / GetStorageShape
    print("\nCALL_ROOTS GetDimNum:", _match(CALL_ROOTS, "GetDimNum"))
    print("CALL_ROOTS GetStorageShape:", _match(CALL_ROOTS, "GetStorageShape"))
    print("DIM_ACCESSOR GetDimNum?", bool(_DIM_ACCESSOR_RE.match("GetDimNum")))
    print("DIM_ACCESSOR GetDim?", bool(_DIM_ACCESSOR_RE.match("GetDim")))

    # From derive cache: find evidence of which expressions mention GETDIMNUM
    derive = json.loads((ROOT / ".probe_cache" / "fag_derive.json").read_text(encoding="utf-8"))
    fields = derive["host_derivation"]["fields"]
    target = [
        "SplitAxis",
        "IsPse",
        "IsAttenMask",
        "DTemplateNum",
        "IsBn2MultiBlk",
        "IsDNoEqual",
        "IsRope",
        "IsNzOut",
        "IsTndSwizzle",
    ]
    print("\n\n######## FIELD ATOMS / SOURCES ########")
    for f in fields:
        if f["name"] not in target:
            continue
        print(f"\n--- {f['name']} ---")
        # print keys that might help
        for k in ("atoms", "value_atoms", "sources", "source_atoms", "guards", "evidence", "raw_sources"):
            if k in f:
                v = f[k]
                s = json.dumps(v, ensure_ascii=False)
                print(f"  {k}: {s[:800]}")
        # variables related
        vs = [v for v in (f.get("variables") or []) if "GETDIMNUM" in v or "DIMNUM" in v or "SHAPE" in v]
        print("  shape-ish vars:", vs[:20])


if __name__ == "__main__":
    main()
