"""Provenance-based classification: TilingKey vs TilingData vs unbound symbols."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

IDENT_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")
CPP_KEYWORDS = frozenset(
    {
        "if",
        "else",
        "return",
        "true",
        "false",
        "nullptr",
        "this",
        "const",
        "constexpr",
        "static_cast",
        "unlikely",
        "likely",
        "and",
        "or",
        "not",
        "template",
        "typename",
        "class",
        "struct",
        "using",
        "namespace",
        "uint32_t",
        "uint16_t",
        "uint8_t",
        "int",
        "bool",
        "void",
        "auto",
        "sizeof",
    }
)


@dataclass(frozen=True)
class KeyDimensionEntry:
    name: str
    key_id: str
    values: list[Any]


def norm_symbol(name: str) -> str:
    return "".join(ch for ch in str(name or "") if ch.isalnum()).casefold()


def load_key_dimension_index(tilingkey_space: dict[str, Any] | None) -> dict[str, KeyDimensionEntry]:
    """Map normalized symbol -> KeyDimensionEntry from tilingkey_space.dimensions."""
    out: dict[str, KeyDimensionEntry] = {}
    if not isinstance(tilingkey_space, dict):
        return out
    for dim in tilingkey_space.get("dimensions") or []:
        if not isinstance(dim, dict):
            continue
        name = str(dim.get("name") or "").strip()
        if not name:
            continue
        norm = norm_symbol(name)
        entry = KeyDimensionEntry(
            name=name,
            key_id=f"KEY_{name}",
            values=list(dim.get("values") or []),
        )
        out[norm] = entry
        # Allow IS_DROP <-> IsDrop style aliases without name-based trust.
        upper = name.upper()
        if upper.startswith("IS"):
            out.setdefault(norm_symbol(upper), entry)
            if len(name) > 2 and name[2].isupper():
                snake = f"IS_{name[2:]}"
                out.setdefault(norm_symbol(snake), entry)
        if name.startswith("IS_"):
            camel = "Is" + name[3:].title().replace("_", "")
            out.setdefault(norm_symbol(camel), entry)
    return out


def bind_symbol_to_key(symbol: str, key_index: dict[str, KeyDimensionEntry]) -> KeyDimensionEntry | None:
    if not symbol or not key_index:
        return None
    return key_index.get(norm_symbol(symbol))


def iter_condition_symbols(cond: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for match in IDENT_RE.finditer(cond or ""):
        sym = match.group(1)
        if sym in CPP_KEYWORDS or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return out


def classify_compile_determinant(
    cond: str,
    key_index: dict[str, KeyDimensionEntry],
) -> tuple[str, str, list[Any] | None]:
    """Classify if constexpr condition is driven by a known TilingKey dimension."""
    for sym in iter_condition_symbols(cond):
        hit = bind_symbol_to_key(sym, key_index)
        if hit is not None:
            domain: list[Any] = [0, 1] if hit.values else [False, True]
            return "TilingKey", hit.name, domain
    if any(tok in (cond or "").lower() for tok in ("true", "false")):
        return "UnboundTemplateSymbol", cond[:120], [False, True]
    return "UnboundTemplateSymbol", cond[:120], None


def is_key_symbol(symbol: str, key_index: dict[str, KeyDimensionEntry]) -> bool:
    return bind_symbol_to_key(symbol, key_index) is not None


def load_tilingkey_space(uo_root: Any, repo_root: Any, op_name: str, architecture: str = "arch35") -> dict[str, Any]:
    """Load ir/tilingkey_space.yaml or extract on demand."""
    from pathlib import Path

    from uo.scripts._ir_io import read_yaml
    from uo.scripts.extract_tilingkey_space import extract_tilingkey_space

    uo_path = Path(uo_root)
    ir_path = uo_path / "ir" / "tilingkey_space.yaml"
    if ir_path.is_file():
        doc = read_yaml(ir_path)
        if isinstance(doc, dict) and doc.get("dimensions"):
            return doc
    return extract_tilingkey_space(Path(repo_root), op_name, architecture=architecture)
