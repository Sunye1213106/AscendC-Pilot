# -*- coding: utf-8 -*-
"""libclang translation-unit helpers for host/kernel parsing."""
from __future__ import annotations

import collections
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from uo_init.build_context import BuildContext

try:
    from clang import cindex
except ImportError:  # pragma: no cover
    cindex = None  # type: ignore


@dataclass
class ParseResult:
    path: str
    args: list[str]
    diagnostics: list[tuple[int, str, str]] = field(default_factory=list)
    nested_writes: list[str] = field(default_factory=list)
    branches: dict[str, int] = field(default_factory=dict)
    tu: object | None = None

    @property
    def error_count(self) -> int:
        return sum(1 for sev, _, _ in self.diagnostics if sev >= 3)

    def errors_in_paths(self, needles: Iterable[str]) -> int:
        n = 0
        for sev, fn, _ in self.diagnostics:
            if sev < 3:
                continue
            if any(x in fn.replace("\\", "/") for x in needles):
                n += 1
        return n


def _require_clang():
    if cindex is None:
        raise RuntimeError("libclang not installed")


def parse_path(path: str, args: list[str]) -> ParseResult:
    _require_clang()
    idx = cindex.Index.create()
    tu = idx.parse(
        path,
        args=args,
        options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
    )
    diags = []
    for d in tu.diagnostics:
        fn = d.location.file.name if d.location.file else "?"
        diags.append((int(d.severity), fn, d.spelling))
    return ParseResult(path=path, args=args, diagnostics=diags, tu=tu)


def _in_analysis_scope(
    node,
    needle: str = "",
    *,
    scope=None,
    op_root: str = "",
) -> bool:
    """True when a cursor belongs to operator-owned or shared analysis sources.

    Prefer a scanned/Clang-enriched ScopeSet: shared ``common/`` headers carry
    no operator name, so a bare ``op_needle`` substring drops them and loses
    semantics. Fall back to needle / op_root / sibling ``common/`` when no
    scope was supplied (legacy callers).
    """
    try:
        f = node.location.file
        if f is None:
            return False
        path = f.name.replace("\\", "/")
    except Exception:
        return False
    if scope is not None:
        return scope.contains(path)
    if needle and needle in path:
        return True
    if op_root:
        root = str(op_root).replace("\\", "/")
        if path.startswith(root) or root in path:
            return True
        # Sibling domain common: <workspace>/common/... next to the operator.
        try:
            sibling_common = (Path(op_root).resolve().parent / "common").as_posix()
            if path.startswith(sibling_common) or f"/{sibling_common}/" in f"/{path}/":
                return True
        except Exception:
            pass
        inner_common = f"{root.rstrip('/')}/common/"
        if inner_common in path or path.startswith(inner_common):
            return True
    return False


def _in_op(node, needle: str) -> bool:
    """Legacy needle-only check; prefer :func:`_in_analysis_scope`."""
    return _in_analysis_scope(node, needle)


def _member_path(n) -> str:
    parts: list[str] = []
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
        else:
            ch = list(cur.get_children())
            cur = ch[0] if ch else None
    return ".".join(reversed([p for p in parts if p]))


def analyze_host(
    path: str,
    ctx: BuildContext,
    op_needle: str,
    *,
    scope=None,
) -> ParseResult:
    res = parse_path(path, ctx.host_args())
    if res.tu is None:
        return res
    op_root = getattr(ctx, "op_dir", "") or ""
    writes: list[str] = []
    branches: collections.Counter = collections.Counter()
    for n in res.tu.cursor.walk_preorder():
        if not _in_analysis_scope(n, op_needle, scope=scope, op_root=op_root):
            continue
        k = n.kind
        if k in (
            cindex.CursorKind.IF_STMT,
            cindex.CursorKind.SWITCH_STMT,
            cindex.CursorKind.FOR_STMT,
            cindex.CursorKind.WHILE_STMT,
            cindex.CursorKind.CONDITIONAL_OPERATOR,
        ):
            branches[k.name] += 1
        if k == cindex.CursorKind.BINARY_OPERATOR:
            toks = [t.spelling for t in n.get_tokens()]
            if "=" in toks:
                ch = list(n.get_children())
                if ch and ch[0].kind == cindex.CursorKind.MEMBER_REF_EXPR:
                    p = _member_path(ch[0])
                    if p.count(".") >= 1:
                        writes.append(p)
    res.nested_writes = writes
    res.branches = dict(branches)
    return res


def analyze_kernel(
    path: str,
    ctx: BuildContext,
    op_needle: str,
    dtype_variant: str | None = "DT_FLOAT16",
    *,
    scope=None,
) -> ParseResult:
    res = parse_path(
        path, ctx.kernel_args(dtype_variant=dtype_variant, source_path=path)
    )
    if res.tu is None:
        return res
    op_root = getattr(ctx, "op_dir", "") or ""
    branches: collections.Counter = collections.Counter()
    for node in res.tu.cursor.walk_preorder():
        if not _in_analysis_scope(node, op_needle, scope=scope, op_root=op_root):
            continue
        if node.kind in (
            cindex.CursorKind.IF_STMT,
            cindex.CursorKind.SWITCH_STMT,
            cindex.CursorKind.FOR_STMT,
            cindex.CursorKind.WHILE_STMT,
            cindex.CursorKind.CONDITIONAL_OPERATOR,
        ):
            branches[node.kind.name] += 1
    res.branches = dict(branches)
    return res


def find_tiling_key_args(path: str, ctx: BuildContext | None = None) -> list[str]:
    _require_clang()
    if ctx is None:
        # build minimal context from defaults
        ctx = BuildContext.load()
        # guess op_dir from path
        p = Path(path)
        parts = list(p.parts)
        if "op_host" in parts:
            i = parts.index("op_host")
            ctx.op_dir = str(Path(*parts[:i])).replace("\\", "/")
            if i + 1 < len(parts) and parts[i + 1].startswith("arch"):
                ctx.arch_dir = parts[i + 1]
    res = parse_path(path, ctx.host_args())
    args_out: list[str] = []
    for n in res.tu.cursor.walk_preorder():
        if n.kind != cindex.CursorKind.CALL_EXPR:
            continue
        if n.spelling != "FastEncodeTilingKeyDirect":
            continue
        f = n.location.file
        if f is None:
            continue
        ilist = None
        stack = list(n.get_children())
        while stack:
            c = stack.pop(0)
            if c.kind == cindex.CursorKind.INIT_LIST_EXPR:
                ilist = c
                break
            stack.extend(c.get_children())
        if ilist is None:
            continue
        args_out = ["".join(t.spelling for t in a.get_tokens()) for a in ilist.get_children()]
        if args_out:
            return args_out
    return args_out


def find_method_line(path: str, ctx: BuildContext, method: str, class_hint: str = "") -> list[int]:
    res = parse_path(path, ctx.host_args())
    lines = []
    for n in res.tu.cursor.walk_preorder():
        if n.kind == cindex.CursorKind.CXX_METHOD and n.spelling == method and n.is_definition():
            parent = n.semantic_parent.spelling if n.semantic_parent else ""
            if class_hint and class_hint not in parent:
                continue
            lines.append(n.location.line)
    return lines
