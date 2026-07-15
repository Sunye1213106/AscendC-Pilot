from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from understand_operator._operator.document_store import DocumentStore
from understand_operator._operator.catalog import CatalogMatchError, match_catalog_entry
from understand_operator._operator.spec import load_spec


@dataclass
class RegistryConflict:
    code: str
    existing_id: str
    incoming_id: str
    key: str


class RegistryConflictError(ValueError):
    def __init__(self, conflict: RegistryConflict) -> None:
        super().__init__(f"{conflict.code}: {conflict.key}: {conflict.existing_id} != {conflict.incoming_id}")
        self.conflict = conflict


@dataclass
class FactRegistry:
    facts_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    canonical_to_id: dict[str, str] = field(default_factory=dict)
    identity_to_ids: dict[str, set[str]] = field(default_factory=dict)
    symbol_to_ids: dict[str, set[str]] = field(default_factory=dict)
    symbol_kind_to_ids: dict[str, set[str]] = field(default_factory=dict)
    declaration_to_id: dict[str, str] = field(default_factory=dict)
    tilingdata_field_to_id: dict[str, str] = field(default_factory=dict)
    operator_io_to_id: dict[str, str] = field(default_factory=dict)
    conflicts: list[RegistryConflict] = field(default_factory=list)

    def add(self, fact: dict[str, Any]) -> None:
        fact_id = fact.get("id")
        if not isinstance(fact_id, str) or not fact_id:
            return
        self.facts_by_id[fact_id] = fact
        identity = fact.get("identity") if isinstance(fact.get("identity"), dict) else {}
        canonical = identity.get("canonical_key")
        normalized = identity.get("normalized") if isinstance(identity.get("normalized"), dict) else {}
        if isinstance(canonical, str) and canonical:
            self._put_unique(self.canonical_to_id, canonical, fact_id, "IDENTITY_DUPLICATE")
        kind = str(fact.get("kind") or "")
        if normalized:
            self.identity_to_ids.setdefault(_identity_key(kind, normalized), set()).add(fact_id)
        qualified_symbol = normalized.get("qualified_symbol") or normalized.get("qualified_entry_symbol")
        signature = normalized.get("signature")
        if qualified_symbol:
            self.symbol_to_ids.setdefault(str(qualified_symbol), set()).add(fact_id)
            self.symbol_kind_to_ids.setdefault(f"{kind}\0{qualified_symbol}", set()).add(fact_id)
            if signature is not None:
                self.symbol_to_ids.setdefault(f"{qualified_symbol}\0{signature}", set()).add(fact_id)
                self.symbol_kind_to_ids.setdefault(f"{kind}\0{qualified_symbol}\0{signature}", set()).add(fact_id)
        if {"source_file", "scope_symbol", "source_name", "declaration_span"} <= set(normalized):
            span = normalized.get("declaration_span") if isinstance(normalized.get("declaration_span"), dict) else {}
            key = "\0".join(str(normalized.get(name) or "") for name in ("source_file", "scope_symbol", "source_name")) + f"\0{span.get('start_line')}\0{span.get('end_line')}"
            self._put_unique(self.declaration_to_id, key, fact_id, "IDENTITY_DUPLICATE")
        struct_name = normalized.get("qualified_struct_name")
        field_name = normalized.get("field_name")
        if struct_name and field_name:
            self._put_unique(self.tilingdata_field_to_id, f"{struct_name}\0{field_name}", fact_id, "IDENTITY_DUPLICATE")
        if {"operator_name", "direction", "index"} <= set(normalized):
            self._put_unique(self.operator_io_to_id, f"{normalized.get('operator_name')}\0{normalized.get('direction')}\0{normalized.get('index')}", fact_id, "IDENTITY_DUPLICATE")

    def _put_unique(self, mapping: dict[str, str], key: str, fact_id: str, code: str) -> None:
        existing = mapping.get(key)
        if existing and existing != fact_id:
            self.conflicts.append(RegistryConflict(code, existing, fact_id, key))
            return
        mapping[key] = fact_id

    def find_canonical(self, canonical_key: str) -> str | None:
        return self.canonical_to_id.get(canonical_key)

    def kind_of(self, fact_id: str) -> str | None:
        fact = self.facts_by_id.get(fact_id)
        kind = fact.get("kind") if isinstance(fact, dict) else None
        return str(kind) if isinstance(kind, str) and kind else None

    def find_symbol(self, symbol: str, signature: str | None = None) -> tuple[str, ...]:
        key = f"{symbol}\0{signature}" if signature is not None else symbol
        return tuple(sorted(self.symbol_to_ids.get(key) or ()))

    def find_symbol_kind(self, kind: str, symbol: str, signature: str | None = None) -> tuple[str, ...]:
        compatible = _compatible_symbol_kinds(kind)
        found: set[str] = set()
        for one_kind in compatible:
            key = f"{one_kind}\0{symbol}\0{signature}" if signature is not None else f"{one_kind}\0{symbol}"
            found.update(self.symbol_kind_to_ids.get(key) or ())
        return tuple(sorted(found))

    def to_cache(self) -> dict[str, Any]:
        return {
            "version": 1,
            "facts_by_id": sorted(self.facts_by_id),
            "canonical_to_id": dict(sorted(self.canonical_to_id.items())),
            "identity_to_ids": {key: sorted(value) for key, value in sorted(self.identity_to_ids.items())},
            "symbol_to_ids": {key: sorted(value) for key, value in sorted(self.symbol_to_ids.items())},
            "symbol_kind_to_ids": {key: sorted(value) for key, value in sorted(self.symbol_kind_to_ids.items())},
            "declaration_to_id": dict(sorted(self.declaration_to_id.items())),
            "tilingdata_field_to_id": dict(sorted(self.tilingdata_field_to_id.items())),
            "operator_io_to_id": dict(sorted(self.operator_io_to_id.items())),
            "conflicts": [conflict.__dict__ for conflict in self.conflicts],
        }


def build_fact_registry(uo_root: Path) -> FactRegistry:
    registry = FactRegistry()
    for fact in iter_formal_facts(uo_root):
        registry.add(fact)
    return registry


def iter_formal_facts(uo_root: Path) -> list[dict[str, Any]]:
    if yaml is None or not uo_root.exists():
        return []
    spec = load_spec()
    store = DocumentStore(uo_root)
    result: list[dict[str, Any]] = []
    facts_root = uo_root / "facts"
    if not facts_root.exists():
        return result
    for path in sorted(facts_root.rglob("*.yaml")):
        rel = path.relative_to(uo_root).as_posix()
        try:
            match = match_catalog_entry(spec, rel)
        except CatalogMatchError:
            continue
        if not match or not str(match.pattern).startswith("facts/"):
            continue
        try:
            doc = store.read(rel).data
        except Exception:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(doc, dict):
            continue
        for _, unit in _document_units(doc):
            for item in unit.get("items") or []:
                if isinstance(item, dict):
                    result.append(item)
    return result


def write_registry_cache(uo_root: Path, registry: FactRegistry) -> None:
    path = uo_root / "indexes" / "entity_registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(registry.to_cache(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _document_units(doc: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    sections = doc.get("sections")
    if isinstance(sections, dict):
        return [(str(name), value) for name, value in sections.items() if isinstance(value, dict)]
    return [("", doc)]


def _identity_key(kind: str, normalized: dict[str, Any]) -> str:
    return json.dumps({"kind": kind, "identity": normalized}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _compatible_symbol_kinds(kind: str) -> set[str]:
    if kind == "function":
        return {"function", "host_function", "kernel_function", "kernel_method", "helper_function"}
    return {kind}
