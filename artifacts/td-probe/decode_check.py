# -*- coding: utf-8 -*-
"""End-to-end check: clang's layout against the bytes the host actually wrote.

The case replayed was b=2 s1=1024 s2=1024 n2=2 g=2 d=128 FLOAT16 BSND, so the
decode is checkable against the input rather than against itself.
"""

from __future__ import annotations

import base64
import json
import os
import struct
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
VARIANTS = {
    "FFFF": (0, 0, 0, 0), "FFTF": (0, 0, 1, 0), "FFTT": (0, 0, 1, 1),
    "TFFF": (1, 0, 0, 0), "TFTF": (1, 0, 1, 0), "TTTF": (1, 1, 1, 0),
    "TTTT": (1, 1, 1, 1),
}

def scalar_code(tname: str, size: int) -> str | None:
    """`struct` code for a scalar leaf, or None when it is not decodable."""
    t = tname.replace("const ", "").strip()
    table = {
        "int64_t": "q", "long": "q", "long long": "q",
        "uint64_t": "Q", "unsigned long": "Q", "unsigned long long": "Q",
        "int32_t": "i", "int": "i",
        "uint32_t": "I", "unsigned int": "I",
        "int16_t": "h", "uint16_t": "H",
        "int8_t": "b", "uint8_t": "B", "unsigned char": "B", "char": "b",
        "bool": "?", "float": "f", "double": "d",
    }
    return table.get(t)


op_dir = paths.op_dir(relative="attention/flash_attention_score_grad")
header = Path(op_dir) / HEADER_REL
ctx = BuildContext.load(op_dir=str(op_dir), arch_dir=ARCH)
args = ctx.kernel_args()

#: Non-template tiling data structs the entry also dispatches onto. The empty
#: tensor path has its own struct entirely, and leaving it out reported every
#: branch on that path as undecided.
PLAIN = {"EMPTY": "FlashAttentionScoreGradEmptyTensorTilingDataRegbase"}

names = list(VARIANTS)
src = ["#include <type_traits>", "#include <cstdint>", "#include <cstddef>",
       f'#include "{header.as_posix()}"', "namespace uo_probe {"]
for i, n in enumerate(names):
    targs = ", ".join("true" if x else "false" for x in VARIANTS[n])
    src.append(f"using V{i} = {NS}::{TOP}<{targs}>;")
    src.append(f"V{i} inst{i};")
for j, (n, cls) in enumerate(PLAIN.items()):
    names.append(n)
    src.append(f"using V{len(VARIANTS) + j} = {NS}::{cls};")
    src.append(f"V{len(VARIANTS) + j} inst{len(VARIANTS) + j};")
src.append("}")


def walk(t, prefix: str, base: int, out: list) -> None:
    t = t.get_canonical()
    for f in t.get_fields():
        name, ft = f.spelling, f.type
        off = base + t.get_offset(name) // 8
        n_elem = ft.get_array_size()
        # Canonical first: the conditional members arrive as
        # `std::conditional<...>::type`, whose declaration is the typedef and
        # not the record, so an uncanonicalised check calls them scalars and
        # silently drops every field they carry.
        base_t = (ft.get_array_element_type() if n_elem > 0 else ft).get_canonical()
        if n_elem <= 0 and list(base_t.get_fields()):
            walk(base_t, f"{prefix}{name}.", off, out)
        else:
            out.append({
                "path": f"{prefix}{name}", "offset": off,
                "size": ft.get_size(), "type": base_t.spelling,
                "count": n_elem if n_elem > 0 else 1,
                "code": scalar_code(base_t.spelling, base_t.get_size()),
            })


layouts: dict[str, dict] = {}
with tempfile.TemporaryDirectory() as td:
    path = Path(td) / "uo_td_layout_probe.cpp"
    path.write_text("\n".join(src) + "\n", encoding="utf-8")
    tu = cindex.Index.create().parse(str(path), args=args)
    errs = [d for d in tu.diagnostics if d.severity >= cindex.Diagnostic.Error]
    if errs:
        for d in errs[:4]:
            print("DIAG:", d.spelling, d.location)
        raise SystemExit("layout probe did not compile")
    for cur in tu.cursor.walk_preorder():
        if cur.kind != cindex.CursorKind.VAR_DECL:
            continue
        if not cur.spelling.startswith("inst"):
            continue
        i = int(cur.spelling[4:])
        rows: list = []
        walk(cur.type, "", 0, rows)
        # A conditional member that resolved to nullptr_t carries no fields, so
        # every branch reading it is absent from this variant rather than merely
        # unobserved. Recording which members those are is what lets a reader
        # tell "not reachable here" from "not yet covered".
        absent = [f["path"] for f in rows if not f["code"]]
        layouts[names[i]] = {"size": cur.type.get_size(), "fields": rows,
                             "absent_members": absent}

out = Path(__file__).parent / "layout.json"
out.write_text(json.dumps(layouts, indent=1), encoding="utf-8")
print(f"wrote {out} ({len(layouts)} variants)")
for n, lay in layouts.items():
    unk = [f["path"] for f in lay["fields"] if not f["code"]]
    print(f"  {n}: size={lay['size']} leaves={len(lay['fields'])}"
          + (f" UNDECODABLE={unk}" if unk else ""))

# --- decode the real bytes -------------------------------------------------
td_b64 = os.environ.get("TD_B64", "")
if not td_b64:
    print("\nset TD_B64 to the driver's ###TD payload to decode")
    raise SystemExit(0)

raw = base64.b64decode(td_b64)
lay = layouts["FFFF"]
print(f"\nbytes={len(raw)} layout FFFF size={lay['size']} "
      f"match={len(raw) == lay['size']}")

want = {"coreNum": 32, "b": 2, "n2": 2, "g": 2, "s1": 1024, "s2": 1024,
        "d": 128, "d1": 128, "keepProb": 1.0, "layout": 1}
for f in lay["fields"]:
    leaf = f["path"].rsplit(".", 1)[-1]
    if leaf not in want or f["count"] != 1 or not f["code"]:
        continue
    got = struct.unpack_from("<" + f["code"], raw, f["offset"])[0]
    mark = "OK " if abs(float(got) - float(want[leaf])) < 1e-6 else "BAD"
    print(f"  {mark} {f['path']:44s} = {got}  (expect {want[leaf]})")
