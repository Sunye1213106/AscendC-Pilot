# -*- coding: utf-8 -*-
"""Which variable a scoped accessor chain resolves to, from the encode scope.

Reproduces the table in the GetDimNum investigation: leaves are tagged with the
function they were read in (as `_expand_surface` does), then lowered by a
`_ValueNormalizer` whose own resolver is the encode function's — exactly the
situation a derived key field puts them in.
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "engines" / "common"))

from uo_init.cpp_expr import parse_expr  # noqa: E402
from uo_init.derive_key_fields import KeyFieldDeriver, _ValueNormalizer  # noqa: E402

ENCODE_FN = "GetTilingKey"

CASES = [
    ("GetTilingKey", "context_->GetInputShape(QUERY_IDX)->GetStorageShape().GetDim(2)"),
    ("GetShapeAttrsInfo", "queryShape->GetStorageShape().GetDim(2)"),
    (
        "GetTilingKey",
        "context_->GetOptionalInputShape(static_cast<size_t>(InputIndex::PSE_SHIFT))"
        "->GetStorageShape().GetDimNum()",
    ),
    ("ProcessPseInfo", "pseShape->GetStorageShape().GetDimNum()"),
    ("ProcessSparseModeInfo", "attenMaskShape->GetStorageShape().GetDimNum()"),
    ("GetShapeAttrsInfo", "queryRopeShape->GetDimNum()"),
    ("GetShapeAttrsInfo", "keyRopeShape->GetDimNum()"),
    ("IsSameShape", "aShape->GetStorageShape().GetDimNum()"),
    ("IsSameShape", "bShape->GetStorageShape().GetDimNum()"),
]


def main() -> None:
    bundle = pickle.load((ROOT / ".probe_cache" / "fag_bundle.pkl").open("rb"))
    deriver = KeyFieldDeriver(
        host_ir=bundle["host_ir"],
        resolver=bundle["resolver"],
        var_model=bundle["var_model"],
    )
    norm = _ValueNormalizer(
        deriver._scope(ENCODE_FN),
        bundle["var_model"],
        scope_for=deriver._scope,
        host_ir=bundle["host_ir"],
    )
    width = max(len(expr) for _, expr in CASES)
    for scope, expr in CASES:
        tagged = deriver._expand_surface(parse_expr(expr), scope, 0)
        try:
            got = norm._leaf(tagged)
        except Exception as exc:  # noqa: BLE001 - probe reports the failure
            got = f"{type(exc).__name__}: {exc}"
        print(f"[{scope:<22}] {expr:<{width}} -> {got}")

    print("\n---- domains ----")
    model = bundle["var_model"]
    for vid in sorted(v for v in model.variables if v.startswith("VAR_SHAPE_")):
        spec = model.get(vid)
        print(f"  {vid:<34} lo={spec.domain.lo} hi={spec.domain.hi} merged={spec.identity_merged}")


if __name__ == "__main__":
    main()
