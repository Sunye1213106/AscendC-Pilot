# -*- coding: utf-8 -*-
"""Temporary: what is actually missing when parsing the kernel TU."""
from __future__ import annotations

import collections
import re

from clang import cindex

from uo_init.build_context import BuildContext
from uo_init.op_spec import discover

FAG = r"d:\PR-review\TEST\ops-transformer\attention\flash_attention_score_grad"
CANN = r"d:\PR-review\_cann\pkg"
OPS = r"d:\PR-review\TEST\ops-transformer"

spec = discover(FAG)
ctx = BuildContext.load(cann_root=CANN, ops_root=OPS, op_dir=str(spec.op_dir), arch_dir=spec.arch_dir)
args = ctx.kernel_args("DT_FLOAT16")
tu = cindex.Index.create().parse(
    str(spec.kernel_entry), args=args,
    options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
errs = [d for d in tu.diagnostics if d.severity >= 3]
print("errors:", len(errs))
kinds = collections.Counter()
idents = collections.Counter()
files = collections.Counter()
for d in errs:
    msg = d.spelling
    files[(d.location.file.name.split("\\")[-1] if d.location.file else "?")] += 1
    key = re.sub(r"'[^']*'", "'X'", msg)
    kinds[key] += 1
    for m in re.finditer(r"'([^']+)'", msg):
        idents[m.group(1)] += 1
print("\ntop messages:")
for k, v in kinds.most_common(12):
    print(f"  {v:4d}  {k[:100]}")
print("\ntop identifiers:")
for k, v in idents.most_common():
    print(f"  {v:4d}  {k}")
print("\ntop files:")
for k, v in files.most_common(8):
    print(f"  {v:4d}  {k}")
print("\nfirst diagnostics:")
for d in errs[:240]:
    print(f"{d.location.file}:{d.location.line}:{d.location.column}: {d.spelling}")

op_nodes = []
op_kinds = collections.Counter()
for node in tu.cursor.walk_preorder():
    location_file = node.location.file
    if location_file is None:
        continue
    location_name = location_file.name.replace("\\", "/")
    if "flash_attention_score_grad" not in location_name:
        continue
    op_kinds[node.kind.name] += 1
    if node.kind in {
        cindex.CursorKind.FUNCTION_DECL,
        cindex.CursorKind.FUNCTION_TEMPLATE,
        cindex.CursorKind.CLASS_DECL,
        cindex.CursorKind.CLASS_TEMPLATE,
        cindex.CursorKind.IF_STMT,
        cindex.CursorKind.SWITCH_STMT,
        cindex.CursorKind.CONDITIONAL_OPERATOR,
    }:
        op_nodes.append(
            (node.kind.name, node.spelling, location_name, node.location.line)
        )
print("\noperator AST kinds:")
for kind, count in op_kinds.most_common():
    print(f"  {count:6d}  {kind}")
print("\noperator structural nodes:")
for item in op_nodes:
    print(item)
