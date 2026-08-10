# -*- coding: utf-8 -*-
"""Probe: can vanilla libclang parse the AscendC kernel side on Windows?
Strategy: force-define bisheng address-space / function qualifiers to empty.
They carry no information we need for branch inventory or if-constexpr work."""
import collections
import sys
from clang import cindex
from uo_init import paths

DEFAULT_OPERATOR = "attention/flash_attention_score_grad"

_CANN = paths.cann_root()
_OPS = paths.ops_root()
_FAG = paths.op_dir(relative=DEFAULT_OPERATOR)
if _CANN is None or _OPS is None or _FAG is None:
    sys.exit(f"CANN packages or operator sources not available\n{paths.explain()}")

CANN = str(_CANN)
# Shims and the bisheng prelude ship with this repository, not with the toolkit.
COMPAT = str(paths.repo_root() / "engines" / "understand-operator" / "spec" / "compat")
OPS = str(_OPS)
FAG = str(_FAG)
KDIR = FAG + r"\op_kernel"
ASC = CANN + r"\cann-asc-devkit\x86_64-linux"

INCLUDES = [
    COMPAT,
    ASC + r"\asc\include",
    ASC + r"\asc\include\adv_api",
    ASC + r"\ascendc\include\highlevel_api",
    ASC + r"\ascendc\include\basic_api",
    ASC + r"\tikcpp\tikcfw",
    CANN + r"\cann-metadef\x86_64-linux\include",
    OPS + r"\common\include",
    KDIR,
    KDIR + r"\arch35",
    KDIR + r"\arch22",
]

# bisheng-only qualifiers: not macros in CANN, they are compiler keywords.
QUALS = ["__aicore__", "__gm__", "__ubuf__", "__cbuf__", "__ca__", "__cb__",
         "__cc__", "__fbuf__", "__global__", "__host_aicore__", "__sync_alias__",
         "__inout_pipe__", "__in_pipe__", "__out_pipe__", "__check_sync_alias__"]

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
        "-D__NPU_ARCH__=3510", "-D__DAV_C310__", "-D__CCE_AICORE__=310"]
ARGS += [f"-D{q}=" for q in QUALS]
ARGS += ["-isystem" + p for p in SYSINC]
ARGS += ["-I" + p for p in INCLUDES]


def run(path, label):
    print("=" * 74)
    print(f"[{label}] {path.split(chr(92))[-1]}")
    tu = cindex.Index.create().parse(
        path, args=ARGS,
        options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
    errs = [d for d in tu.diagnostics if d.severity >= 3]
    print(f"  errors: {len(errs)}")
    seen = set()
    for d in errs[:8]:
        loc = d.location
        fn = loc.file.name.split("\\")[-1] if loc.file else "?"
        k = (fn, d.spelling)
        if k in seen:
            continue
        seen.add(k)
        print(f"   [sev{d.severity}] {fn}:{loc.line}  {d.spelling}")
    if not tu.cursor:
        return
    # what did we actually recover?
    stats = collections.Counter()
    entries = []
    for n in tu.cursor.walk_preorder():
        f = n.location.file
        if f is None or "flash_attention_score_grad" not in f.name:
            continue
        if n.kind == cindex.CursorKind.IF_STMT:
            stats["if"] += 1
        elif n.kind == cindex.CursorKind.FUNCTION_DECL and n.is_definition():
            stats["func"] += 1
            if "flash_attention_score_grad" in (n.spelling or ""):
                entries.append((n.spelling, n.location.line))
        elif n.kind == cindex.CursorKind.CLASS_TEMPLATE:
            stats["class_tmpl"] += 1
        elif n.kind == cindex.CursorKind.FUNCTION_TEMPLATE:
            stats["func_tmpl"] += 1
    print(f"  recovered: {dict(stats)}")
    if entries:
        print(f"  kernel entries: {entries[:4]}")


if __name__ == "__main__":
    targets = {
        "arch35-entry": KDIR + r"\flash_attention_score_grad_apt.cpp",
        "arch22-entry": KDIR + r"\flash_attention_score_grad.cpp",
    }
    for k in (sys.argv[1:] or targets):
        run(targets[k], k)
