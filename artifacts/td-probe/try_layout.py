# -*- coding: utf-8 -*-
"""Check that libclang will hand over a record layout for the instantiated
tiling data. If it does, the layout is the compiler's own answer and UO can
record it instead of anybody re-deriving C++ padding rules.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from clang import cindex  # noqa: E402

HEADER = (ROOT.parent / "TEST" / "ops-transformer" / "attention"
          / "flash_attention_score_grad" / "op_kernel" / "arch35"
          / "flash_attention_score_grad_tiling_data_regbase.h")

TOP = "FlashAttentionScoreGradTilingDataUs1s2Bbn2gs1s2Regbase"
VARIANTS = [(0, 0, 0, 0), (0, 0, 1, 0), (0, 0, 1, 1), (1, 0, 0, 0),
            (1, 0, 1, 0), (1, 1, 1, 0), (1, 1, 1, 1)]


def probe_source() -> str:
    lines = ["#include <cstdint>", "#include <type_traits>", "#include <cstddef>",
             f'#include "{HEADER.as_posix()}"', "namespace uo_probe {"]
    for i, v in enumerate(VARIANTS):
        args = ", ".join("true" if x else "false" for x in v)
        lines.append(f"using V{i} = optiling::fag::{TOP}<{args}>;")
        lines.append(f"V{i} inst{i};")
    lines.append("}")
    return "\n".join(lines) + "\n"


src = probe_source()
with tempfile.TemporaryDirectory() as td:
    path = Path(td) / "probe.cpp"
    path.write_text(src, encoding="utf-8")
    idx = cindex.Index.create()
    tu = idx.parse(str(path), args=["-std=c++17", "-x", "c++"])
    for d in tu.diagnostics:
        if d.severity >= cindex.Diagnostic.Error:
            print("DIAG:", d.spelling, d.location)

    found = 0
    for cur in tu.cursor.walk_preorder():
        if cur.kind != cindex.CursorKind.VAR_DECL:
            continue
        if not cur.spelling.startswith("inst"):
            continue
        t = cur.type
        print(f"\n== {cur.spelling}: {t.spelling}  size={t.get_size()} ==")
        found += 1
        for f in t.get_fields():
            off = t.get_offset(f.spelling)
            ft = f.type
            print(f"   {f.spelling:28s} off={off // 8:6d} "
                  f"size={ft.get_size():6d} type={ft.spelling}")
    print(f"\nvariants with layout: {found}/{len(VARIANTS)}")
