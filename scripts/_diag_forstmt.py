"""What `_loop_header` reads off real loop shapes.

libclang omits absent header clauses rather than leaving a hole, so this
checks which shapes yield an init/step and which correctly report None.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

SRC = """
void f(int n) {
    int acc = 0;
    for (unsigned int coreId = 0; coreId < 36; coreId++) { acc += coreId; }
    for (int i = 10; i > 0; i--) { acc += i; }
    for (int i = 0, j = 1; i < n; i += 2) { acc += i + j; }
    for (int i = 0; i < n; i += 4) { acc += i; }
    for (int i = 5; i < n; ++i) { acc += i; }
    for (int i = n; i > 0; i -= 2) { acc += i; }
    int k = 0;
    for (; k < n; ++k) { acc += k; }
    for (k = 0; k < n; k++) { acc += k; }
    for (;;) { break; }
    while (k < n) { k++; }
}
"""


def main() -> int:
    from clang import cindex

    from uo_init.clang_walk import _loop_header, _text_of

    path = ROOT / ".probe_cache" / "_forstmt.cpp"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SRC, encoding="utf-8")
    tu = cindex.TranslationUnit.from_source(str(path), args=["-std=c++17"])

    def visit(cur):
        if cur.kind.name in ("FOR_STMT", "WHILE_STMT"):
            kind = "for" if cur.kind.name == "FOR_STMT" else "while"
            kids = list(cur.get_children())
            cond, ind, init, step = _loop_header(kids, kind)
            print(
                f"L{cur.location.line:<3} {_text_of(cur, 10)[:44]:<46} "
                f"cond={_text_of(cond, 8) if cond is not None else None!r:<12} "
                f"ind={ind} init={init} step={step}"
            )
        for ch in cur.get_children():
            visit(ch)

    visit(tu.cursor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
