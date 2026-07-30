# -*- coding: utf-8 -*-
"""libclang feasibility probe: parse FAG op_host on native Windows.
Read-only; does not modify operator sources."""
import collections
import sys
from clang import cindex

CANN = r"D:\PR-review\_cann\pkg"
COMPAT = r"D:\PR-review\_cann\compat"
OPS = r"D:\PR-review\TEST\ops-transformer"
FAG = OPS + r"\attention\flash_attention_score_grad"

INCLUDES = [
    COMPAT,
    CANN + r"\cann-metadef\x86_64-linux\include",
    CANN + r"\cann-metadef\x86_64-linux\pkg_inc",
    CANN + r"\cann-asc-devkit\x86_64-linux\asc\include",
    CANN + r"\cann-asc-devkit\x86_64-linux\ascendc\include\highlevel_api",
    CANN + r"\cann-opbase\x86_64-linux\include",
    CANN + r"\cann-opbase\x86_64-linux\include\op_common",
    CANN + r"\cann-opbase\x86_64-linux\pkg_inc",
    CANN + r"\cann-ge-compiler\x86_64-linux\include",
    CANN + r"\cann-npu-runtime\x86_64-linux\include",
    CANN + r"\cann-npu-runtime\x86_64-linux\pkg_inc\base",
    OPS + r"\common\include",
    FAG + r"\op_host",
    FAG + r"\op_host\arch35",
]

BS = CANN + r"\bisheng\tools"
GXX = BS + r"\hcc\aarch64-target-linux-gnu"
SYSINC = [
    GXX + r"\include\c++\7.3.0",
    GXX + r"\include\c++\7.3.0\aarch64-target-linux-gnu",
    GXX + r"\include\c++\7.3.0\backward",
    BS + r"\bisheng_compiler\lib\clang\15.0.5\include",
    GXX + r"\sys-include",
    GXX + r"\include",
]

ARGS = ["-x", "c++", "-std=c++17", "--target=aarch64-linux-gnu",
        "-nostdinc", "-nostdinc++", "-ferror-limit=0", "-Wno-everything",
        "-DNO_OPERATOR_IMPL"]
ARGS += ["-isystem" + p for p in SYSINC]
ARGS += ["-I" + p for p in INCLUDES]

TARGETS = {
    "opdef": FAG + r"\op_host\flash_attention_score_grad_def.cpp",
    "entry": FAG + r"\op_host\flash_attention_score_grad_tiling.cpp",
    "regbase": FAG + r"\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp",
    "common35": FAG + r"\op_host\arch35\flash_attention_score_grad_tiling_common_regbase.cpp",
}


def parse(path):
    idx = cindex.Index.create()
    return idx.parse(path, args=ARGS,
                     options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)


def diags(tu):
    out = []
    for d in tu.diagnostics:
        if d.severity >= 3:
            loc = d.location
            fn = loc.file.name.split("\\")[-1] if loc.file else "?"
            out.append(f"[sev{d.severity}] {fn}:{loc.line}  {d.spelling}")
    return out


def in_fag(n):
    try:
        return n.location.file is not None and "flash_attention_score_grad" in n.location.file.name
    except Exception:
        return False


def member_path(n):
    """Reconstruct a.b.c from a MEMBER_REF_EXPR chain, marking implicit this."""
    parts = []
    cur = n
    while cur is not None:
        k = cur.kind
        if k == cindex.CursorKind.MEMBER_REF_EXPR:
            parts.append(cur.spelling)
            ch = list(cur.get_children())
            cur = ch[0] if ch else None
            if cur is None:
                parts.append("this")
        elif k == cindex.CursorKind.DECL_REF_EXPR:
            parts.append(cur.spelling)
            cur = None
        elif k == cindex.CursorKind.CXX_THIS_EXPR:
            parts.append("this")
            cur = None
        elif k == cindex.CursorKind.ARRAY_SUBSCRIPT_EXPR:
            ch = list(cur.get_children())
            cur = ch[0] if ch else None
        else:
            ch = list(cur.get_children())
            cur = ch[0] if ch else None
    return ".".join(reversed([p for p in parts if p]))


def analyze(tag, path):
    print("=" * 72)
    print(f"[{tag}]  {path.split(chr(92))[-1]}")
    tu = parse(path)
    ds = diags(tu)
    print(f"  diagnostics(>=error): {len(ds)}")
    for d in ds[:5]:
        print("   ", d)

    writes = []
    single = []
    branches = collections.Counter()
    tplkey_calls = []

    for n in tu.cursor.walk_preorder():
        if not in_fag(n):
            continue
        k = n.kind
        if k in (cindex.CursorKind.IF_STMT, cindex.CursorKind.SWITCH_STMT,
                 cindex.CursorKind.FOR_STMT, cindex.CursorKind.WHILE_STMT,
                 cindex.CursorKind.CONDITIONAL_OPERATOR):
            branches[k.name] += 1
        if k == cindex.CursorKind.BINARY_OPERATOR:
            toks = [t.spelling for t in n.get_tokens()]
            if "=" in toks:
                ch = list(n.get_children())
                if ch and ch[0].kind == cindex.CursorKind.MEMBER_REF_EXPR:
                    p = member_path(ch[0])
                    (writes if p.count(".") >= 1 else single).append(p)
        if k == cindex.CursorKind.CALL_EXPR and "TilingKey" in (n.spelling or ""):
            tplkey_calls.append((n.spelling, n.location.line))

    total = len(writes) + len(single)
    print(f"  branch nodes: {dict(branches)}  total={sum(branches.values())}")
    print(f"  field writes in FAG src: {total}  resolved-path={len(writes)}  bare={len(single)}")
    uniq = sorted(set(writes))
    print(f"  distinct write paths: {len(uniq)}")
    for w in uniq[:12]:
        print("     ", w)
    key_fields = [w for w in uniq if any(s in w for s in
                  ("isNzOut", "Swizzle", "TemplateNum", "splitAxis", "isTnd", "Dtype", "deter"))]
    print(f"  TilingKey-related writes: {key_fields[:10]}")
    if tplkey_calls:
        print(f"  TilingKey calls: {tplkey_calls[:5]}")
    return len(ds), total, len(writes)


if __name__ == "__main__":
    which = sys.argv[1:] or list(TARGETS)
    for t in which:
        try:
            analyze(t, TARGETS[t])
        except Exception as e:
            print(f"[{t}] EXCEPTION {type(e).__name__}: {e}")
