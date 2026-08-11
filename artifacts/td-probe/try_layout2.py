# -*- coding: utf-8 -*-
"""Record layout via libclang, using UO's own build context for the flags.

The check that matters is the last line: the size clang computes for a variant
has to equal the byte count the host handed back at replay. If they agree the
layout is the same one the running tiling wrote, and every field offset below
it can be trusted.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from clang import cindex  # noqa: E402
from uo_init import paths  # noqa: E402
from uo_init.build_context import BuildContext  # noqa: E402

ARCH = "arch35"
TOP = "FlashAttentionScoreGradTilingDataUs1s2Bbn2gs1s2Regbase"
NS = "optiling::fag"
HEADER_REL = f"op_kernel/{ARCH}/flash_attention_score_grad_tiling_data_regbase.h"
VARIANTS = [(0, 0, 0, 0), (0, 0, 1, 0), (0, 0, 1, 1), (1, 0, 0, 0),
            (1, 0, 1, 0), (1, 1, 1, 0), (1, 1, 1, 1)]

op_dir = paths.op_dir(relative="attention/flash_attention_score_grad")
if op_dir is None:
    raise SystemExit(f"cannot locate operator\n{paths.explain()}")
header = Path(op_dir) / HEADER_REL

ctx = BuildContext.load(op_dir=str(op_dir), arch_dir=ARCH)
args = ctx.kernel_args()
target = os.environ.get("UO_LAYOUT_TARGET")
if target:
    args = [a for a in args if not a.startswith("--target=")] + [f"--target={target}"]
print("target:", [a for a in args if a.startswith("--target=")])


def probe_source() -> str:
    # The header uses std::conditional without including <type_traits>; it gets
    # it transitively in the real build. Naming it here keeps the probe from
    # depending on which other header happened to be pulled in first.
    lines = ["#include <type_traits>", "#include <cstdint>", "#include <cstddef>",
             f'#include "{header.as_posix()}"', "namespace uo_probe {"]
    for i, v in enumerate(VARIANTS):
        targs = ", ".join("true" if x else "false" for x in v)
        lines.append(f"using V{i} = {NS}::{TOP}<{targs}>;")
        lines.append(f"V{i} inst{i};")
    lines.append("}")
    return "\n".join(lines) + "\n"


def walk(t, prefix: str, base: int, out: list) -> None:
    t = t.get_canonical()
    for f in t.get_fields():
        name, ft = f.spelling, f.type
        off = base + t.get_offset(name) // 8
        elem = ft.get_array_element_type() if ft.get_array_size() > 0 else None
        decl = (elem or ft).get_declaration()
        is_record = decl is not None and decl.kind in (
            cindex.CursorKind.STRUCT_DECL, cindex.CursorKind.CLASS_DECL)
        if is_record and list((elem or ft).get_fields()) and elem is None:
            walk(ft, f"{prefix}{name}.", off, out)
        else:
            out.append((f"{prefix}{name}", off, ft.get_size(), ft.spelling,
                        ft.get_array_size()))


with tempfile.TemporaryDirectory() as td:
    path = Path(td) / "uo_td_layout_probe.cpp"
    path.write_text(probe_source(), encoding="utf-8")
    tu = cindex.Index.create().parse(str(path), args=args)
    errs = [d for d in tu.diagnostics if d.severity >= cindex.Diagnostic.Error]
    print(f"errors: {len(errs)}")
    for d in errs[:4]:
        print("  DIAG:", d.spelling, d.location)

    for cur in tu.cursor.walk_preorder():
        if cur.kind != cindex.CursorKind.VAR_DECL:
            continue
        if not cur.spelling.startswith("inst"):
            continue
        i = int(cur.spelling[4:])
        t = cur.type
        rows: list = []
        walk(t, "", 0, rows)
        print(f"\n== {VARIANTS[i]} size={t.get_size()} leaves={len(rows)} ==")
        for name, off, size, tname, n in rows[:5]:
            print(f"   {name:46s} off={off:6d} size={size:5d} {tname}")
        if rows:
            print(f"   ... {rows[-1][0]} off={rows[-1][1]} size={rows[-1][2]}")
