# -*- coding: utf-8 -*-
"""Which kernel code each TilingKey dimension selects.

The kernel is one template parameterised by the key, and every dimension of
the key switches code in or out through `if constexpr`. Reading those branches
gives the map from a dimension to the code it decides -- which is what
"a change here affects what?" needs, and what a test aimed at one dimension
has to cover.

Deliberately read *before* instantiation. Once instantiated, `IS_ROPE` has
folded to `true` and the branch it guarded is either there or gone, with
nothing left saying which dimension decided it. Uninstantiated the condition
still names the parameter, which is the whole point. It also keeps the cost to
one parse per dtype variant rather than one per instantiation, of which there
are hundreds.

The dtype variants are parsed separately because the dtype macro is a
preprocessor value, not a template parameter: different values compile
different code, so a single parse sees only a third of the kernel.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

IDENT_RE = re.compile(r"\b[A-Za-z_]\w*\b")
CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*[(<]")
QUALIFIER_RE = re.compile(r"\b([A-Za-z_]\w*)\s*::")


@dataclass
class KernelBranch:
    """One `if constexpr`, and what decides it."""

    condition: str
    file: str
    line: int
    function: str = ""
    #: TilingKey dimensions the condition names outright.
    dimensions: list[str] = field(default_factory=list)
    #: Names built from a dimension rather than being one, such as a
    #: `constexpr bool` derived from it.
    derived: list[str] = field(default_factory=list)
    #: Everything else the condition mentions.
    symbols: list[str] = field(default_factory=list)
    #: Which dtype variants compile this branch.
    variants: list[str] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, int, str]:
        return (self.file, self.line, self.condition)


@dataclass
class KernelIR:
    """The kernel's compile-time branching, indexed by what decides it."""

    branches: list[KernelBranch] = field(default_factory=list)
    variants: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def touching(self, dimension: str) -> list[KernelBranch]:
        return [
            b
            for b in self.branches
            if dimension in b.dimensions or dimension in b.derived
        ]

    def by_dimension(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for b in self.branches:
            for d in (*b.dimensions, *b.derived):
                counts[d] = counts.get(d, 0) + 1
        return counts

    def variant_only(self) -> list[KernelBranch]:
        """Branches that only some dtype variants compile at all."""
        return [b for b in self.branches if len(b.variants) < len(self.variants)]

    def silent_dimensions(self, dimensions: list[str]) -> list[str]:
        """Dimensions no branch was found for.

        Either the dimension decides nothing at compile time, or the inner
        template renamed it on the way down -- `DeterType` arrives as
        `DETER_SPARSE_TYPE`. Reported rather than guessed at: matching on how
        similar two names look would attach branches to the wrong dimension,
        and a wrong answer here is worse than a missing one.
        """
        seen = self.by_dimension()
        return [d for d in dimensions if not seen.get(d)]

    def unmapped_symbols(self, limit: int = 0) -> list[tuple[str, int]]:
        """Names the conditions turn on that reached no dimension, commonest
        first. Where a renamed dimension shows up."""
        counts: dict[str, int] = {}
        for b in self.branches:
            for s in b.symbols:
                counts[s] = counts.get(s, 0) + 1
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        return ranked[:limit] if limit else ranked

    def to_dict(self) -> dict:
        return {
            "variants": list(self.variants),
            "branches": len(self.branches),
            "by_dimension": self.by_dimension(),
            "variant_only": len(self.variant_only()),
            "notes": list(self.notes),
            "detail": [
                {
                    "condition": b.condition,
                    "file": Path(b.file).name,
                    "line": b.line,
                    "function": b.function,
                    "dimensions": list(b.dimensions),
                    "derived": list(b.derived),
                    "variants": list(b.variants),
                }
                for b in self.branches
            ],
        }


def _squash(name: str) -> str:
    return name.replace("_", "").lower()


class _Dimensions:
    """Matches a kernel parameter name to the key dimension it carries.

    The two sides spell the same idea differently -- `IS_ROPE` against
    `IsRope`, `SPLIT_AXIS` against `SplitAxis` -- so the separators and case go
    before comparing. A name that merely starts with a dimension, such as a
    `constexpr bool OUTDTYPE_IS_B16` computed from `OUTDTYPE`, is reported
    separately: it is evidence about that dimension without being it.
    """

    def __init__(self, names: list[str]) -> None:
        self._exact = {_squash(n): n for n in names}
        # Longest first, so `OUTDTYPE_IS_B16` prefers `OutDType` over `Out`.
        self._prefixes = sorted(self._exact.items(), key=lambda kv: -len(kv[0]))

    def classify(self, ident: str) -> tuple[str | None, str | None]:
        squashed = _squash(ident)
        hit = self._exact.get(squashed)
        if hit:
            return hit, None
        for prefix, name in self._prefixes:
            if len(prefix) >= 4 and squashed.startswith(prefix):
                return None, name
        return None, None


def _classify(condition: str, dims: _Dimensions) -> tuple[list, list, list]:
    syntax = set(CALL_RE.findall(condition)) | set(QUALIFIER_RE.findall(condition))
    exact: list[str] = []
    derived: list[str] = []
    others: list[str] = []
    for ident in IDENT_RE.findall(condition):
        if ident in syntax:
            continue
        hit, near = dims.classify(ident)
        if hit is not None:
            if hit not in exact:
                exact.append(hit)
        elif near is not None:
            if near not in derived:
                derived.append(near)
        elif ident not in others:
            others.append(ident)
    return exact, derived, others


def build_kernel_ir(spec, ctx, *, dimensions: list[str] | None = None) -> KernelIR:
    """Parse the kernel entry once per dtype variant and index its branches."""
    from uo_init.clang_walk import walk_file

    ir = KernelIR()
    entries = [
        Path(p)
        for p in (getattr(spec, "kernel_targets", None) or [spec.kernel_entry])
        if p and Path(p).is_file()
    ]
    if not entries:
        ir.notes.append("no_kernel_entry")
        return ir

    variants = list((ctx.dtype_variants() or {}).get("values") or []) or [None]
    ir.variants = [v or "default" for v in variants]
    dims = _Dimensions(list(dimensions or ()))

    found: dict[tuple[str, int, str], KernelBranch] = {}
    for entry in entries:
        for variant in variants:
            res = walk_file(
                entry,
                ctx,
                side="kernel",
                dtype_variant=variant,
                op_needle=getattr(spec, "op_needle", ""),
                scope=getattr(spec, "scope", None),
                collect_writes=False,
            )
            label = variant or "default"
            for node in res.controls:
                if node.kind != "if_constexpr":
                    continue
                condition = (node.condition or "").strip()
                if not condition:
                    continue
                key = (node.file, node.line, condition)
                branch = found.get(key)
                if branch is None:
                    exact, derived, others = _classify(condition, dims)
                    branch = KernelBranch(
                        condition=condition,
                        file=node.file,
                        line=node.line,
                        function=getattr(node, "function", "") or "",
                        dimensions=exact,
                        derived=derived,
                        symbols=others,
                    )
                    found[key] = branch
                if label not in branch.variants:
                    branch.variants.append(label)

    ir.branches = sorted(found.values(), key=lambda b: (b.file, b.line))
    named = sum(1 for b in ir.branches if b.dimensions or b.derived)
    ir.notes.append(
        f"entries={len(entries)} variants={len(variants)} "
        f"branches={len(ir.branches)} dimension_driven={named}"
    )
    silent = ir.silent_dimensions(list(dimensions or ()))
    if silent:
        ir.notes.append("no_branch_found_for: " + ", ".join(silent))
    return ir
