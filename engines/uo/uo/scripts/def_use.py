"""Lightweight def-use / guarded assignment provenance (not full SSA)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from uo.scripts.semantic_identity import mint_def_identity, mint_edge_id

ASSIGN_RE = re.compile(
    r"(?P<lhs>(?:[A-Za-z_][A-Za-z0-9_]*\.)+[A-Za-z_][A-Za-z0-9_]*|[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<rhs>[^;]+);",
)
IF_RE = re.compile(r"\bif\s*\((?P<cond>[^)]*)\)\s*\{")
GET_DIM_RE = re.compile(
    r"(?P<obj>[A-Za-z_][A-Za-z0-9_]*)\s*(?:->|\.)\s*Get(?:Storage)?Shape\s*\(\s*\)\s*(?:->|\.)\s*GetDim\s*\(\s*(?P<dim>\d+)\s*\)"
)


@dataclass
class DefRecord:
    def_id: str
    name: str
    object_identity: str
    scope_id: str
    guard: str
    rhs_expr: str
    source_nodes: list[str] = field(default_factory=list)
    locator: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "def_id": self.def_id,
            "symbol_identity": self.name,
            "object_identity": self.object_identity,
            "scope_id": self.scope_id,
            "guard": self.guard,
            "rhs_expr": self.rhs_expr,
            "source_nodes": self.source_nodes,
            "locator": self.locator,
        }


def extract_def_use_from_text(
    text: str,
    *,
    file_path: str,
    scope_symbol: str,
    start_line: int = 1,
) -> dict[str, Any]:
    """Extract guarded definitions and flows from a function body."""
    definitions: list[DefRecord] = []
    flows: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    ordinals: dict[str, int] = {}

    # Build simple if-region map: line -> active guard (best-effort brace scan).
    guards_by_line = _guards_by_line(text, start_line=start_line)
    lines = text.splitlines()
    for offset, line in enumerate(lines):
        line_no = start_line + offset
        for match in ASSIGN_RE.finditer(line):
            lhs = match.group("lhs").strip()
            rhs = match.group("rhs").strip()
            guard = guards_by_line.get(line_no, "true")
            obj, field = _split_lhs(lhs)
            key = f"{obj}.{field}" if obj else field
            ordinals[key] = ordinals.get(key, 0) + 1
            def_id = mint_def_identity(
                name=field,
                scope_symbol=scope_symbol,
                file_path=file_path,
                ordinal=ordinals[key],
                object_identity=obj,
                guard=guard,
            )
            sources = _rhs_sources(rhs)
            rec = DefRecord(
                def_id=def_id,
                name=field,
                object_identity=obj or scope_symbol,
                scope_id=scope_symbol,
                guard=guard,
                rhs_expr=rhs,
                source_nodes=sources,
                locator={"file_path": file_path, "start_line": line_no, "end_line": line_no},
            )
            definitions.append(rec)
            for src in sources:
                flows.append(
                    {
                        "id": mint_edge_id("derives", src, def_id, guard),
                        "type": "derives",
                        "from": src,
                        "to": def_id,
                        "guard": guard,
                        "confidence": "verified" if not src.startswith("unresolved:") else "candidate",
                    }
                )
            # Field write flow
            if obj:
                flows.append(
                    {
                        "id": mint_edge_id("writes", def_id, f"{obj}.{field}", guard),
                        "type": "writes",
                        "from": def_id,
                        "to": f"{obj}.{field}",
                        "guard": guard,
                        "confidence": "verified",
                    }
                )

    # Detect obvious pointer alias ambiguity
    if re.search(r"\bauto\s*\*\s*[A-Za-z_]", text) or re.search(r"\bstd::shared_ptr\b", text):
        unresolved.append(
            {
                "severity": "informational",
                "code": "pointer_alias_unresolved",
                "related_symbols": [scope_symbol],
                "candidate_files": [file_path],
                "evidence_present": ["pointer_or_shared_ptr"],
                "evidence_missing": ["points_to_analysis"],
                "reason": "pointer aliasing not modeled; dataflow may be incomplete",
            }
        )

    return {
        "definitions": [d.as_dict() for d in definitions],
        "uses": [],
        "flows": flows,
        "unresolved": unresolved,
    }


def bind_argument_parameter(
    *,
    caller_expr: str,
    callee_param: str,
    call_guard: str = "true",
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | dict[str, Any]:
    """Create arg→param binding edge when evidence exists; else unresolved."""
    if not evidence:
        return {
            "severity": "degraded",
            "code": "argument_parameter_unbound",
            "related_symbols": [caller_expr, callee_param],
            "candidate_files": [],
            "evidence_present": [],
            "evidence_missing": ["callsite_binding_evidence"],
            "reason": "cannot bind argument to parameter without callsite evidence",
        }
    return {
        "id": mint_edge_id("binds_arg", caller_expr, callee_param, call_guard),
        "type": "binds_arg",
        "from": caller_expr,
        "to": callee_param,
        "guard": call_guard,
        "confidence": "verified",
        "evidence": evidence,
    }


def _split_lhs(lhs: str) -> tuple[str, str]:
    if "." in lhs:
        obj, field = lhs.rsplit(".", 1)
        return obj, field
    return "", lhs


def _rhs_sources(rhs: str) -> list[str]:
    sources: list[str] = []
    for match in GET_DIM_RE.finditer(rhs):
        sources.append(f"input_shape:{match.group('obj')}.dim[{match.group('dim')}]")
    for match in re.finditer(r"GetAttr(?:Pointer)?\s*\(\s*[\"']([^\"']+)[\"']", rhs):
        sources.append(f"attribute:{match.group(1)}")
    for match in re.finditer(r"GetOptionalInputShape\s*\(\s*(\d+)\s*\)", rhs):
        sources.append(f"input_slot[{match.group(1)}].optional_shape")
    # bare identifiers as candidate sources (not verified input mapping)
    for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", rhs):
        name = match.group(1)
        if name in {"true", "false", "return", "if", "else", "const", "int", "uint32_t", "int64_t", "bool", "auto"}:
            continue
        if name not in {s.split(":")[-1].split(".")[0] for s in sources}:
            sources.append(f"local:{name}")
    return sources[:8]


def _guards_by_line(text: str, *, start_line: int = 1) -> dict[int, str]:
    """Best-effort: map lines inside `if (cond) { ... }` to guard string."""
    result: dict[int, str] = {}
    lines = text.splitlines()
    stack: list[tuple[str, int]] = []  # (guard, brace_depth_at_push)
    depth = 0
    for offset, line in enumerate(lines):
        line_no = start_line + offset
        for match in IF_RE.finditer(line):
            cond = re.sub(r"\s+", " ", match.group("cond")).strip()
            stack.append((cond or "true", depth))
        # track braces
        depth += line.count("{") - line.count("}")
        while stack and depth < stack[-1][1] + 1 and "{" not in line:
            # closed
            stack.pop()
        # After processing line braces more carefully:
        if stack:
            # compose nested guards
            guards = [g for g, _ in stack]
            result[line_no] = " && ".join(f"({g})" for g in guards)
        # pop when depth falls below push depth
        while stack and depth <= stack[-1][1]:
            stack.pop()
    return result
