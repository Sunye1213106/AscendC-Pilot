# -*- coding: utf-8 -*-
"""What does the walker see in a guarded-return chain?"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

SAMPLES = {
    "lone": """
int pick(int a) {
    if (a > 1) { return 7; }
    return 9;
}
""",
    "two": """
int pick(int a, int b) {
    if (a > 1) { return 1; }
    else if (b > 2) { return 2; }
    return 3;
}
""",
    "three": """
int pick(int a, int b, int c) {
    if (a > 1) { return 1; }
    else if (b > 2) { return 2; }
    else if (c > 3) { return 3; }
    return 4;
}
""",
}


def main() -> int:
    from clang import cindex

    from uo_init.clang_walk import (
        _else_if_chain,
        _exit_statement,
        _file_of,
        _guard_clause_negations,
        _text_of,
        COND_TOKENS,
    )

    for name, source in SAMPLES.items():
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.cpp"
            path.write_text(source, encoding="utf-8")
            tu = cindex.Index.create().parse(str(path), args=["-std=c++17"])
            print(f"\n=== {name}")
            for d in tu.diagnostics:
                print(f"  diag: {d.severity} {d.spelling}")
            stack = list(tu.cursor.get_children())
            node = None
            while stack:
                cur = stack.pop(0)
                if cur.kind.name == "IF_STMT":
                    node = cur
                    break
                stack = list(cur.get_children()) + stack
            if node is None:
                print("  no IF_STMT found")
                continue
            print(f"  outer if at line {node.location.line}")
            print(f"  file_of = {_file_of(node)}")
            links, tail = _else_if_chain(node)
            print(f"  links={len(links)} tail={tail.kind.name if tail else None}")
            for cond, then in links:
                text = _text_of(cond, COND_TOKENS)
                leaves = _exit_statement(then)
                print(
                    f"    cond={text!r:22} line={cond.location.line} "
                    f"then={then.kind.name} exits={leaves.kind.name if leaves else None}"
                )
            got = _guard_clause_negations(node)
            print(f"  -> {[(c.pretty(), c.kind) for c in got]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
