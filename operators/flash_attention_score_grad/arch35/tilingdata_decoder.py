# -*- coding: utf-8 -*-
"""FlashAttentionScoreGrad arch35 runtime TilingData decoder.

The replay driver intentionally emits opaque ``###TD`` bytes. This operator
adapter derives the ABI layout from the *current* arch35 headers with libclang
and BuildContext, then decodes only primitive leaves. TG's generic branch
runtime knows nothing about FAG struct names or template variants.
"""

from __future__ import annotations

import os
import struct
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

ARCH = "arch35"
TOP = "FlashAttentionScoreGradTilingDataUs1s2Bbn2gs1s2Regbase"
NS = "optiling::fag"
HEADER_REL = f"op_kernel/{ARCH}/flash_attention_score_grad_tiling_data_regbase.h"

# Concrete instantiations observed in the arch35 host dispatch. They remain in
# the operator package, never in the generic TG engine. Layout offsets are not
# stored here; clang computes them from the current checkout at runtime.
VARIANTS: dict[str, tuple[int, int, int, int]] = {
    "FFFF": (0, 0, 0, 0),
    "FFTF": (0, 0, 1, 0),
    "FFTT": (0, 0, 1, 1),
    "TFFF": (1, 0, 0, 0),
    "TFTF": (1, 0, 1, 0),
    "TTTF": (1, 1, 1, 0),
    "TTTT": (1, 1, 1, 1),
}
PLAIN = {"EMPTY": "FlashAttentionScoreGradEmptyTensorTilingDataRegbase"}

# branch_eval parameter spellings that are not TilingData leaves.
_PARAM_TO_DIM = {
    "T1": "IsDrop",
    "T2": "IsPse",
    "T3": "IsAttenMask",
    "T4": "IsRegbase",
    "T5": "IsDeterministic",
    "T6": "IsTnd",
    "T7": "IsDNoEqual",
    "T8": "IsTndSwizzle",
    "T9": "IsBn2",
    "T10": "IsBn2MultiBlk",
    "T11": "IsNzOut",
    "T12": "HasRope",
    "T13": "DeterType",
}
_ENUMS = {
    "NORMAL_TENSOR": 0,
    "EMPTY_TENSOR": 1,
    "BASE16": 16,
    "BLOCK_CUBE": 16,
    "BLOCK_SIZE": 32,
    "BASE256": 256,
    "SELECT_SPACE": 1024,
}


def _scalar_code(tname: str) -> str | None:
    t = tname.replace("const ", "").strip()
    return {
        "int64_t": "q",
        "long": "q",
        "long long": "q",
        "uint64_t": "Q",
        "unsigned long": "Q",
        "unsigned long long": "Q",
        "int32_t": "i",
        "int": "i",
        "uint32_t": "I",
        "unsigned int": "I",
        "int16_t": "h",
        "uint16_t": "H",
        "int8_t": "b",
        "uint8_t": "B",
        "unsigned char": "B",
        "char": "b",
        "bool": "?",
        "float": "f",
        "double": "d",
    }.get(t)


def _operator_root() -> Path:
    for name in ("ASCENDC_PROJECT_ROOT", "UO_OP_DIR"):
        raw = os.environ.get(name)
        if raw:
            root = Path(raw).expanduser().resolve()
            if (root / HEADER_REL).is_file():
                return root
    # Same fallback UO itself uses in the FAG development checkout.
    from uo_init import paths

    return Path(paths.op_dir(relative="attention/flash_attention_score_grad")).resolve()


def _walk(t: Any, prefix: str, base: int, out: list[dict[str, Any]]) -> None:
    t = t.get_canonical()
    for field in t.get_fields():
        name, ft = field.spelling, field.type
        off = base + t.get_offset(name) // 8
        n_elem = ft.get_array_size()
        elem = (ft.get_array_element_type() if n_elem > 0 else ft).get_canonical()
        nested = list(elem.get_fields())
        if n_elem <= 0 and nested:
            _walk(elem, f"{prefix}{name}.", off, out)
            continue
        elem_size = int(elem.get_size())
        out.append(
            {
                "path": f"{prefix}{name}",
                "offset": int(off),
                "size": int(ft.get_size()),
                "elem_size": elem_size,
                "type": elem.spelling,
                "count": int(n_elem if n_elem > 0 else 1),
                "code": _scalar_code(elem.spelling),
            }
        )


@lru_cache(maxsize=1)
def _layouts() -> dict[str, dict[str, Any]]:
    from clang import cindex
    from uo_init.build_context import BuildContext

    op_root = _operator_root()
    header = op_root / HEADER_REL
    if not header.is_file():
        raise RuntimeError(f"FAG_TD_HEADER_MISSING:{header}")
    ctx = BuildContext.load(op_dir=str(op_root), arch_dir=ARCH)
    args = ctx.kernel_args()

    names = list(VARIANTS)
    src = [
        "#include <type_traits>",
        "#include <cstdint>",
        "#include <cstddef>",
        f'#include "{header.as_posix()}"',
        "namespace uo_probe {",
    ]
    for i, name in enumerate(names):
        targs = ", ".join("true" if x else "false" for x in VARIANTS[name])
        src.append(f"using V{i} = {NS}::{TOP}<{targs}>;")
        src.append(f"V{i} inst{i};")
    for j, (name, cls) in enumerate(PLAIN.items()):
        idx = len(VARIANTS) + j
        names.append(name)
        src.append(f"using V{idx} = {NS}::{cls};")
        src.append(f"V{idx} inst{idx};")
    src.append("}")

    layouts: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "uo_td_layout_probe.cpp"
        path.write_text("\n".join(src) + "\n", encoding="utf-8")
        tu = cindex.Index.create().parse(str(path), args=args)
        errors = [
            d for d in tu.diagnostics
            if d.severity >= cindex.Diagnostic.Error
        ]
        if errors:
            text = " | ".join(str(d.spelling) for d in errors[:4])
            raise RuntimeError(f"FAG_TD_LAYOUT_COMPILE_FAILED:{text}")
        for cur in tu.cursor.walk_preorder():
            if cur.kind != cindex.CursorKind.VAR_DECL or not cur.spelling.startswith("inst"):
                continue
            idx = int(cur.spelling[4:])
            rows: list[dict[str, Any]] = []
            _walk(cur.type, "", 0, rows)
            undecodable = [r["path"] for r in rows if not r.get("code")]
            layouts[names[idx]] = {
                "size": int(cur.type.get_size()),
                "fields": rows,
                # Conditional nullptr/opaque leaves are absent from useful
                # runtime observation for this specialization.
                "absent_members": undecodable,
            }
    if not layouts:
        raise RuntimeError("FAG_TD_LAYOUT_EMPTY")
    return layouts


def _pick_layout(raw: bytes) -> tuple[str, dict[str, Any]]:
    matches = [(name, layout) for name, layout in _layouts().items() if int(layout["size"]) == len(raw)]
    if not matches:
        sizes = sorted({int(x["size"]) for x in _layouts().values()})
        raise RuntimeError(f"FAG_TD_SIZE_UNKNOWN:{len(raw)}:known={sizes}")
    # Equal-size specializations have the same primitive ABI for the bytes we
    # can safely decode; choosing deterministically keeps evidence reproducible.
    return sorted(matches, key=lambda item: item[0])[0]


def decode(raw: bytes, dims: dict[str, Any] | None = None) -> dict[str, Any]:
    """Decode primitive TilingData leaves from one replay observation."""
    del dims
    name, layout = _pick_layout(raw)
    fields: dict[str, Any] = {}
    present: set[str] = set()
    owner: dict[str, str] = {}
    for row in layout["fields"]:
        code = row.get("code")
        if not code:
            continue
        count = int(row.get("count") or 1)
        offset = int(row.get("offset") or 0)
        elem_size = int(row.get("elem_size") or 0)
        path = str(row.get("path") or "")
        if not path or elem_size <= 0:
            continue
        try:
            if count == 1:
                value: Any = struct.unpack_from("<" + str(code), raw, offset)[0]
            else:
                value = [
                    struct.unpack_from("<" + str(code), raw, offset + i * elem_size)[0]
                    for i in range(count)
                ]
        except (struct.error, IndexError):
            continue
        fields[path] = value
        leaf = path.rsplit(".", 1)[-1]
        fields.setdefault(leaf, value)
        present.add(path)
        present.add(leaf)
        if "." in path:
            owner[leaf] = path.rsplit(".", 1)[0]
    return {
        "layout": name,
        "fields": fields,
        "present_leaves": sorted(present),
        "absent_members": list(layout.get("absent_members") or []),
        "owner": owner,
        "layout_size": int(layout["size"]),
    }


def eval_context(dims: dict[str, Any] | None = None) -> dict[str, Any]:
    """Operator spellings needed by the generic branch expression evaluator."""
    del dims
    return {
        "param_to_dim": dict(_PARAM_TO_DIM),
        "enums": dict(_ENUMS),
    }


def selfcheck() -> dict[str, Any]:
    """Compile layouts without requiring a replay observation."""
    layouts = _layouts()
    return {
        "ok": bool(layouts),
        "variants": len(layouts),
        "sizes": {name: int(doc["size"]) for name, doc in sorted(layouts.items())},
    }


__all__ = ["decode", "eval_context", "selfcheck"]
