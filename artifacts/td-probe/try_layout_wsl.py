# -*- coding: utf-8 -*-
"""WSL run of the layout probe: libclang there has a real include path."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path("/mnt/d/PR-review/AscendC-Pilot")
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from clang import cindex  # noqa: E402

HEADER = Path("/mnt/d/PR-review/TEST/ops-transformer/attention"
              "/flash_attention_score_grad/op_kernel/arch35"
              "/flash_attention_score_grad_tiling_data_regbase.h")

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


def walk(t, prefix: str, base: int, out: list) -> None:
    """Flatten nested records into (path, offset, size, type) rows."""
    for f in t.get_fields():
        name = f.spelling
        ft = f.type
        off = base + t.get_offset(name) // 8
        decl = ft.get_declaration()
        nested = (decl is not None
                  and decl.kind in (cindex.CursorKind.STRUCT_DECL,
                                    cindex.CursorKind.CLASS_DECL)
                  and list(ft.get_fields()))
        if nested:
            walk(ft, f"{prefix}{name}.", off, out)
        else:
            out.append((f"{prefix}{name}", off, ft.get_size(), ft.spelling))


src = probe_source()
with tempfile.TemporaryDirectory() as td:
    path = Path(td) / "probe.cpp"
    path.write_text(src, encoding="utf-8")
    idx = cindex.Index.create()
    tu = idx.parse(str(path), args=["-std=c++17", "-x", "c++"])
    errs = [d for d in tu.diagnostics
            if d.severity >= cindex.Diagnostic.Error]
    for d in errs[:5]:
        print("DIAG:", d.spelling, d.location)

    for cur in tu.cursor.walk_preorder():
        if cur.kind != cindex.CursorKind.VAR_DECL:
            continue
        if not cur.spelling.startswith("inst"):
            continue
        t = cur.type
        rows: list = []
        walk(t, "", 0, rows)
        print(f"\n== {cur.spelling} size={t.get_size()} fields={len(rows)} ==")
        for name, off, size, tname in rows[:6]:
            print(f"   {name:44s} off={off:6d} size={size:5d} {tname}")
        if rows:
            print(f"   ... last: {rows[-1][0]} off={rows[-1][1]}")
