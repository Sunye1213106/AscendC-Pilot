# -*- coding: utf-8 -*-
"""BranchInventory: control-node enumeration independent of sinks.

The clang backend is authoritative. The text scanner is kept only as a fallback
for files that cannot be parsed, and it under-counts by construction, so it
must never be used to compute a closure rate. Per-operator baselines belong to
the test suite, not here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from uo_init.clang_walk import CtrlNode, PathCond, classify_universe, walk_file

UNIVERSE = {
    "PRODUCTION",
    "LIBRARY_INTERNAL",
    "HARDWARE_INTERNAL",
    "VALIDATION_ONLY",
    "DEAD_AFTER_CONST_EVAL",
    "UNREACHABLE_TEMPLATE_INSTANCE",
}

# Operator kernels dispatch through an `INVOKE_<OP>_<VARIANT>` macro. clang
# expands these away, so they are recovered textually; the operator tag varies
# per operator, hence no fixed prefix.
INVOKE_MACRO_RE = re.compile(r"\bINVOKE_[A-Z][A-Z0-9_]{2,}\b")

ControlNode = CtrlNode

# Approximate text-level control keywords (clang preferred when available)
CTRL_PATTERNS = [
    ("if_constexpr", re.compile(r"\bif\s+constexpr\b")),
    ("if", re.compile(r"\bif\s*\(")),
    ("switch", re.compile(r"\bswitch\s*\(")),
    ("for", re.compile(r"\bfor\s*\(")),
    ("while", re.compile(r"\bwhile\s*\(")),
    ("ternary", re.compile(r"\?[^;]+\s*:")),
]


@dataclass
class BranchInventory:
    nodes: list[ControlNode] = field(default_factory=list)
    backend: str = "text"
    macro_idioms: int = 0

    def ids(self) -> set[str]:
        return {n.id for n in self.nodes}

    def count_by_file(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for n in self.nodes:
            out[n.file] = out.get(n.file, 0) + 1
        return out

    def count_by_kind(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for n in self.nodes:
            out[n.kind] = out.get(n.kind, 0) + 1
        return out

    def by_universe(self, universe: str) -> list[ControlNode]:
        return [n for n in self.nodes if n.universe == universe]

    def production(self) -> list[ControlNode]:
        return self.by_universe("PRODUCTION")

    def denominator(self, universe: str = "PRODUCTION") -> int:
        """Closure-rate denominator. Only meaningful on the clang backend."""
        if self.backend != "clang":
            raise ValueError(
                "denominator requires the clang backend; the text scanner under-counts"
            )
        return len(self.by_universe(universe))


def _stable_id(file: str, line: int, kind: str, ordinal: int) -> str:
    return f"{file}:{line}:{kind}:{ordinal}"


def inventory_text(path: str | Path, *, keep_invoke: bool = True) -> BranchInventory:
    """Fallback scanner. Records at most one node per line; do not use as denominator."""
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    rel = str(path).replace("\\", "/")
    nodes: list[ControlNode] = []
    ordinals: dict[str, int] = {}
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        for kind, pat in CTRL_PATTERNS:
            if kind == "if" and re.search(r"\bif\s+constexpr\b", line):
                continue  # counted as if_constexpr
            if pat.search(line):
                ord_ = ordinals.get(kind, 0)
                ordinals[kind] = ord_ + 1
                nodes.append(
                    ControlNode(
                        id=_stable_id(rel, i, kind, ord_),
                        kind=kind,
                        file=rel,
                        line=i,
                        snippet=stripped[:120],
                        universe="PRODUCTION",
                    )
                )
                break
    if keep_invoke:
        nodes.extend(_invoke_nodes(text, rel, ordinals))
    return BranchInventory(nodes=nodes, backend="text")


def _invoke_nodes(text: str, rel: str, ordinals: dict[str, int]) -> list[ControlNode]:
    """Macro dispatch sites are control nodes even though clang expands them away."""
    out: list[ControlNode] = []
    for m in INVOKE_MACRO_RE.finditer(text):
        line = text[: m.start()].count("\n") + 1
        kind = "macro_dispatch"
        ord_ = ordinals.get(kind, 0)
        ordinals[kind] = ord_ + 1
        out.append(
            ControlNode(
                id=_stable_id(rel, line, kind, ord_),
                kind=kind,
                file=rel,
                line=line,
                snippet=m.group(0),
                universe="PRODUCTION",
            )
        )
    return out


def inventory_paths(paths: Iterable[str | Path]) -> BranchInventory:
    all_nodes: list[ControlNode] = []
    for p in paths:
        all_nodes.extend(inventory_text(p).nodes)
    return BranchInventory(nodes=all_nodes, backend="text")


def inventory_clang(
    path: str | Path,
    ctx,
    *,
    side: str = "host",
    dtype_variant: str | None = "DT_FLOAT16",
    op_needle: str = "",
    keep_invoke: bool = True,
) -> BranchInventory:
    """Authoritative inventory: one node per AST control construct."""
    res = walk_file(
        path,
        ctx,
        side=side,
        dtype_variant=dtype_variant,
        op_needle=op_needle,
        collect_writes=False,
    )
    nodes = list(res.controls)
    if keep_invoke:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        nodes.extend(_invoke_nodes(text, str(path).replace("\\", "/"), {}))
    return BranchInventory(nodes=nodes, backend="clang", macro_idioms=res.macro_idioms)


def inventory_clang_paths(
    paths: Iterable[str | Path],
    ctx,
    **kwargs,
) -> BranchInventory:
    nodes: list[ControlNode] = []
    idioms = 0
    for p in paths:
        inv = inventory_clang(p, ctx, **kwargs)
        nodes.extend(inv.nodes)
        idioms += inv.macro_idioms
    # de-duplicate: headers shared across TUs yield identical stable ids
    seen: dict[str, ControlNode] = {}
    for n in nodes:
        seen.setdefault(n.id, n)
    return BranchInventory(nodes=list(seen.values()), backend="clang", macro_idioms=idioms)


def assert_no_sink_pruning(inv: BranchInventory, source_text: str | None = None) -> None:
    """Nodes must never be dropped for failing to reach an output sink.

    Concretely: every macro dispatch site present in the source must survive
    into the inventory, because those are exactly the nodes a sink-reachability
    filter would delete first.
    """
    if source_text is None:
        return
    expected = {m.group(0) for m in INVOKE_MACRO_RE.finditer(source_text)}
    if not expected:
        return
    present = {n.snippet for n in inv.nodes if n.kind == "macro_dispatch"}
    missing = expected - present
    if missing:
        raise AssertionError(f"sink pruning removed macro dispatch nodes: {sorted(missing)}")


def label_universe(node: ControlNode, *, is_library: bool = False, op_root: str = "") -> ControlNode:
    node.universe = "LIBRARY_INTERNAL" if is_library else classify_universe(node, op_root=op_root)
    if node.universe not in UNIVERSE:
        raise ValueError(f"bad universe {node.universe}")
    return node
