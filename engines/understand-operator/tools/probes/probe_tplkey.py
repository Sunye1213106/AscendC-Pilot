# -*- coding: utf-8 -*-
"""Decisive probe: recover the 19 positional args at the GET_TPL_TILING_KEY
call site, and cross-check them against the ASCENDC_TPL_ARGS_DECL schema
scraped textually from the kernel-side tiling-key header."""
import re
import sys
from clang import cindex

sys.path.insert(0, r"D:\PR-review\_cann")
from probe_clang import ARGS, FAG, parse  # noqa: E402

KEYHDR = FAG + r"\op_kernel\arch35\flash_attention_score_grad_template_tiling_key.h"


# ---------- side A: textual DSL scrape (kernel side) ----------
def scrape_decl(path):
    src = open(path, encoding="utf-8", errors="replace").read()
    src = re.sub(r"\\\r?\n", " ", src)          # join line continuations
    m = re.search(r"ASCENDC_TPL_ARGS_DECL\s*\(", src)
    if not m:
        return []
    i, depth = m.end() - 1, 0
    for j in range(m.end() - 1, len(src)):
        if src[j] == "(":
            depth += 1
        elif src[j] == ")":
            depth -= 1
            if depth == 0:
                body = src[m.end():j]
                break
    dims = []
    for dm in re.finditer(r"ASCENDC_TPL_(UINT|BOOL|DTYPE|FORMAT)_DECL\s*\(", body):
        k, depth = dm.end() - 1, 0
        for j in range(dm.end() - 1, len(body)):
            if body[j] == "(":
                depth += 1
            elif body[j] == ")":
                depth -= 1
                if depth == 0:
                    inner = body[dm.end():j]
                    break
        parts = [p.strip() for p in inner.split(",")]
        kind, name = dm.group(1), parts[0]
        if kind == "UINT":
            bwtok = parts[1]
            bw = int(re.match(r"ASCENDC_TPL_(\d+)_BW", bwtok).group(1))
            vals = parts[2:]                     # includes UI_LIST/UI_RANGE marker
        elif kind == "BOOL":
            bw, vals = 1, parts[1:]
        else:
            bw, vals = 8, parts[1:]
        dims.append({"name": name, "kind": kind, "bw": bw, "vals": vals})
    return dims


# ---------- side B: clang call-site args (host side) ----------
def find_key_call(path):
    tu = parse(path)
    hits = []
    for n in tu.cursor.walk_preorder():
        if n.kind != cindex.CursorKind.CALL_EXPR:
            continue
        if n.spelling != "FastEncodeTilingKeyDirect":
            continue
        f = n.location.file
        if f is None or "flash_attention_score_grad" not in f.name:
            continue
        # the {a,b,...} braced list may be wrapped (materialize/cast) nodes deep
        ilist = None
        stack = list(n.get_children())
        while stack:
            c = stack.pop(0)
            if c.kind == cindex.CursorKind.INIT_LIST_EXPR:
                ilist = c
                break
            stack.extend(c.get_children())
        args = []
        if ilist is not None:
            for a in ilist.get_children():
                args.append("".join(t.spelling for t in a.get_tokens()))
        hits.append((f.name.split("\\")[-1], n.location.line, args))
    return hits


if __name__ == "__main__":
    dims = scrape_decl(KEYHDR)
    print("=" * 78)
    print(f"A) kernel-side ASCENDC_TPL_ARGS_DECL -> {len(dims)} dims, "
          f"total bits = {sum(d['bw'] for d in dims)}")
    off = 0
    for i, d in enumerate(dims):
        print(f"   [{i:2}] bit{off:>2}..{off+d['bw']-1:<2} {d['bw']:>2}b "
              f"{d['kind']:<5} {d['name']:<22} vals={d['vals'][:5]}")
        off += d["bw"]

    print("=" * 78)
    tgt = FAG + r"\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp"
    hits = find_key_call(tgt)
    for fn, line, args in hits:
        print(f"B) host GET_TPL_TILING_KEY at {fn}:{line} -> arity {len(args)}")
        for i, a in enumerate(args):
            nm = dims[i]["name"] if i < len(dims) else "<OVERFLOW>"
            print(f"   [{i:2}] {nm:<22} <= {a}")

    print("=" * 78)
    if hits:
        n_host = len(hits[0][2])
        print(f"CHECK arity      host={n_host}  decl={len(dims)}  "
              f"{'OK' if n_host == len(dims) else 'MISMATCH'}")
    print(f"CHECK total bits {sum(d['bw'] for d in dims)} <= 64  "
          f"{'OK' if sum(d['bw'] for d in dims) <= 64 else 'OVERFLOW'}")
