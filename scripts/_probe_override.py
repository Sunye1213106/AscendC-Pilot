# -*- coding: utf-8 -*-
"""Which override edges does libclang actually hand us?"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "engines" / "common"))


def main() -> int:
    from clang import cindex

    from uo_init import paths
    from uo_init.build_context import BuildContext
    from uo_init.clang_walk import _file_of, _in_scope, _require_clang
    from uo_init.op_spec import discover

    _require_clang()
    op = paths.op_dir(
        relative=os.environ.get("UO_OPERATOR", "attention/flash_attention_score_grad")
    )
    spec = discover(op, arch_dir="arch35")
    ctx = BuildContext.load(
        cann_root=str(paths.cann_root()),
        ops_root=str(paths.ops_root()),
        op_dir=str(spec.op_dir),
        arch_dir=spec.arch_dir,
    )
    from uo_init.clang_walk import _framework_headers

    needle, root = spec.op_needle, str(spec.op_dir)
    for target in [p for p in spec.host_targets if p.exists()]:
        print(f"\n=== {target.name}")
        idx = cindex.Index.create()
        tu = idx.parse(
            str(target),
            args=ctx.host_args(),
            options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
        )
        frame = _framework_headers(tu.cursor, needle, root)
        print(f"  framework headers: {sorted(frame) or '(none)'}")

        specs = []
        stack = list(tu.cursor.get_children())
        while stack:
            node = stack.pop()
            try:
                kind = node.kind.name
            except Exception:
                continue
            where = _file_of(node)
            if where is None or not _in_scope(where, needle, root):
                continue
            if kind == "CXX_BASE_SPECIFIER":
                specs.append((node.spelling, where, node.location.line))
            stack.extend(node.get_children())
        print(f"  in-scope base specifiers: {len(specs)}")
        for name, where, line in specs[:8]:
            print(f"      {name}  @ {Path(where).name}:{line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
