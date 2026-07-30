# -*- coding: utf-8 -*-
"""Measure kernel-side parse quality: how many errors remain, and crucially
whether any of them land in FAG's own sources rather than CANN headers."""
import collections
import probe_kernel as P
from clang import cindex

EXTRA = [
    r"D:\PR-review\_cann\pkg\cann-asc-devkit\x86_64-linux\asc\include\basic_api",
    r"D:\PR-review\_cann\pkg\cann-asc-devkit\x86_64-linux\asc\impl\basic_api",
    r"D:\PR-review\_cann\pkg\cann-asc-devkit\x86_64-linux\asc",
]
PRELUDE = r"D:\PR-review\_cann\compat\bisheng_prelude.h"
QUALS2 = ["__simd_callee__", "__simd__", "__vec_callee__"]


def run(label, target, prelude=True):
    args = list(P.ARGS) + ["-I" + p for p in EXTRA] + [f"-D{q}=" for q in QUALS2]
    if prelude:
        args += ["-include", PRELUDE]
    tu = cindex.Index.create().parse(target, args=args)

    errs = []
    for d in tu.diagnostics:
        if d.severity < 3:
            continue
        loc = d.location
        fn = loc.file.name if loc.file else "?"
        errs.append((fn, loc.line, d.spelling))          # materialise now

    in_fag = [e for e in errs if "flash_attention_score_grad" in e[0]]
    st = collections.Counter()
    for n in tu.cursor.walk_preorder():
        f = n.location.file
        if f is None or "flash_attention_score_grad" not in f.name:
            continue
        k = n.kind
        if k == cindex.CursorKind.IF_STMT:
            st["if"] += 1
        elif k == cindex.CursorKind.CLASS_TEMPLATE:
            st["class_tmpl"] += 1
        elif k == cindex.CursorKind.FUNCTION_TEMPLATE:
            st["func_tmpl"] += 1
        elif k == cindex.CursorKind.FUNCTION_DECL and n.is_definition():
            st["func"] += 1
        elif k == cindex.CursorKind.CLASS_DECL and n.is_definition():
            st["class"] += 1

    print("=" * 74)
    print(f"[{label}]")
    print(f"  errors total = {len(errs)}   of which inside FAG sources = {len(in_fag)}")
    print(f"  recovered from FAG sources: {dict(st)}")
    where = collections.Counter(e[0].split("\\")[-1] for e in errs)
    print("  error hotspots:")
    for f, n in where.most_common(6):
        print(f"     {n:>4}  {f}")
    if in_fag:
        print("  !! errors in FAG code:")
        for f, ln, s in in_fag[:8]:
            print(f"     {f.split(chr(92))[-1]}:{ln}  {s}")
    return len(errs), len(in_fag)


if __name__ == "__main__":
    run("arch35 entry (apt.cpp)", P.KDIR + r"\flash_attention_score_grad_apt.cpp")
    run("arch22 entry", P.KDIR + r"\flash_attention_score_grad.cpp")
