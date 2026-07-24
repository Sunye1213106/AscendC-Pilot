"""Unified semantic identity for UO layered IR.

Semantic IDs deliberately exclude start_line so formatting / comment shifts do not
change node identity. Locators carry line ranges and content hashes separately.

This module is the single minting path for extract/plan/export scripts. It does
not depend on the (currently empty) entity_types spec used by the legacy facts
pipeline in ``uo._operator.identity``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from uo.scripts.arch_path import architecture_of_path, path_family_of

IDENTITY_VERSION = 3

SpecializationKind = str  # primary|partial|explicit|instance|none


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _norm_path(rel: str) -> str:
    return str(rel or "").replace("\\", "/").lstrip("./")


def _hash_key(*parts: str, length: int = 16) -> str:
    material = "\0".join(_clean(p) for p in parts)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:length].upper()


@dataclass(frozen=True)
class Locator:
    file_path: str
    start_line: int = 0
    end_line: int = 0
    source_hash: str = ""
    snippet_hash: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "start_line": int(self.start_line or 0),
            "end_line": int(self.end_line or 0),
            "source_hash": self.source_hash,
            "snippet_hash": self.snippet_hash,
        }


@dataclass(frozen=True)
class SemanticIdentity:
    kind: str
    identity_version: int
    identity_key: str
    stable_id: str
    qualified_name: str
    normalized_signature: str
    class_or_namespace: str
    template_arity_or_signature: str
    specialization_kind: SpecializationKind
    architecture: str
    template_family: str
    path_family: str
    repo_relative_path: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "identity_version": self.identity_version,
            "kind": self.kind,
            "identity_key": self.identity_key,
            "stable_id": self.stable_id,
            "qualified_name": self.qualified_name,
            "normalized_signature": self.normalized_signature,
            "class_or_namespace": self.class_or_namespace,
            "template_arity_or_signature": self.template_arity_or_signature,
            "specialization_kind": self.specialization_kind,
            "architecture": self.architecture,
            "template_family": self.template_family,
            "path_family": self.path_family,
            "repo_relative_path": self.repo_relative_path,
        }


def snippet_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def source_file_hash(path: Path) -> str:
    if not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def make_locator(
    file_path: str,
    *,
    start_line: int = 0,
    end_line: int = 0,
    source_hash: str = "",
    text: str = "",
) -> Locator:
    return Locator(
        file_path=_norm_path(file_path),
        start_line=int(start_line or 0),
        end_line=int(end_line or start_line or 0),
        source_hash=source_hash,
        snippet_hash=snippet_hash(text) if text else "",
    )


def normalize_cxx_signature(signature: str) -> str:
    """Public alias for signature normalization used in identity material."""
    return _normalize_signature(signature)


def parse_template_arity(text_near_decl: str) -> str:
    """Extract normalized contents of the first balanced ``<...>`` template list."""
    text = text_near_decl or ""
    start = text.find("<")
    if start < 0:
        return ""
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
            if depth == 0:
                inner = text[start + 1 : i]
                return _clean(re.sub(r"\s*,\s*", ",", inner))
    return ""


def infer_specialization_kind(header_text: str) -> SpecializationKind:
    """Heuristic C++ template specialization class (generic, not op-specific)."""
    text = _clean(header_text)
    if not text:
        return "none"
    if re.search(r"\btemplate\s*<>\s*(?:class|struct|typename|\w|\{|<)", text):
        return "explicit"
    if re.search(r"\btemplate\s*>\s*(?:class|struct|typename|\w|<|\{)", text):
        return "explicit"
    if re.search(r"\btemplate\s*<", text):
        # partial: template params then class Name< fixed args >
        if re.search(
            r"\btemplate\s*<[^>]+>\s*(?:class|struct)\s+\w+\s*<",
            text,
        ):
            return "partial"
        return "primary"
    if re.search(r"\b(?:class|struct)\s+\w+\s*<[^>]+>", text):
        return "instance"
    if re.search(r"\w+\s*<[^>]+>\s*::\s*\w+", text):
        return "instance"
    return "none"


def mint_scoped_node_id(
    prefix: str,
    owning_identity_key: str,
    file: str,
    line: int,
    extra: str = "",
) -> str:
    """Stable scoped id for branches/loops under an owning function identity."""
    key = _hash_key(_clean(owning_identity_key), _norm_path(file), str(int(line or 0)), extra)
    p = _clean(prefix).upper().rstrip("_")
    return f"{p}_{key}"


def mint_method_identity(
    *,
    name: str,
    file_path: str,
    class_or_namespace: str,
    qualified_name: str = "",
    signature: str = "",
    template_arity_or_signature: str = "",
    specialization_kind: SpecializationKind = "none",
    architecture: str = "",
    template_family: str = "",
    path_family: str = "",
    prefix: str = "SYM",
) -> SemanticIdentity:
    cls = _clean(class_or_namespace)
    if not cls:
        raise ValueError("mint_method_identity requires class_or_namespace")
    qn = _clean(qualified_name) or f"{cls}::{_clean(name)}"
    sk = _clean(specialization_kind) or "none"
    if sk not in {"primary", "partial", "explicit", "instance", "none"}:
        sk = "none"
    return mint_symbol_identity(
        kind="method",
        name=name,
        file_path=file_path,
        qualified_name=qn,
        signature=signature,
        class_or_namespace=cls,
        template_arity_or_signature=template_arity_or_signature,
        specialization_kind=sk,
        architecture=architecture,
        template_family=template_family,
        path_family=path_family,
        prefix=prefix,
    )


def mint_symbol_identity(
    *,
    kind: str,
    name: str,
    file_path: str,
    qualified_name: str = "",
    signature: str = "",
    class_or_namespace: str = "",
    template_arity_or_signature: str = "",
    specialization_kind: SpecializationKind = "none",
    architecture: str = "",
    template_family: str = "",
    path_family: str = "",
    prefix: str = "SYM",
) -> SemanticIdentity:
    """Mint a line-independent semantic identity for a symbol-like entity."""
    rel = _norm_path(file_path)
    qn = _clean(qualified_name) or f"{rel}::{_clean(name)}"
    arch = _clean(architecture) or architecture_of_path(rel)
    family = _clean(path_family) or path_family_of(rel)
    sig = _normalize_signature(signature)
    cls = _clean(class_or_namespace)
    tpl = _clean(template_arity_or_signature)
    sk = _clean(specialization_kind) or "none"
    if sk not in {"primary", "partial", "explicit", "instance", "none"}:
        sk = "none"
    tpl_family = _clean(template_family) or "unknown"
    identity_key = _hash_key(
        kind,
        rel,
        qn,
        sig,
        cls,
        tpl,
        sk,
        arch,
        tpl_family,
        family,
    )
    stable = f"{prefix}_{_clean(kind).upper()}_{identity_key}"
    return SemanticIdentity(
        kind=_clean(kind) or "symbol",
        identity_version=IDENTITY_VERSION,
        identity_key=identity_key,
        stable_id=stable,
        qualified_name=qn,
        normalized_signature=sig,
        class_or_namespace=cls,
        template_arity_or_signature=tpl,
        specialization_kind=sk,
        architecture=arch,
        template_family=tpl_family,
        path_family=family,
        repo_relative_path=rel,
    )


def mint_field_identity(
    *,
    owning_type: str,
    field_path: str,
    file_path: str = "",
    architecture: str = "",
    template_family: str = "",
    path_family: str = "",
) -> SemanticIdentity:
    owning = _clean(owning_type) or "UnknownType"
    field = _clean(field_path)
    rel = _norm_path(file_path)
    return mint_symbol_identity(
        kind="struct_field",
        name=field.split(".")[-1],
        file_path=rel or f"type/{owning}",
        qualified_name=f"{owning}::{field}",
        class_or_namespace=owning,
        signature=field,
        architecture=architecture,
        template_family=template_family,
        path_family=path_family,
        prefix="TDF",
    )


def mint_def_identity(
    *,
    name: str,
    scope_symbol: str,
    file_path: str,
    ordinal: int,
    object_identity: str = "",
    guard: str = "true",
) -> str:
    """Stable id for a variable definition version (def-use)."""
    return "DEF_" + _hash_key(
        _norm_path(file_path),
        _clean(scope_symbol),
        _clean(object_identity),
        _clean(name),
        str(int(ordinal)),
        _clean(guard) or "true",
    )


def mint_edge_id(edge_type: str, source_id: str, target_id: str, qualifier: str = "") -> str:
    return "EDGE_" + _hash_key(edge_type, source_id, target_id, qualifier)


def _normalize_signature(signature: str) -> str:
    text = _clean(signature)
    if not text:
        return ""
    text = re.sub(r"\s*,\s*", ",", text)
    text = re.sub(r"\s*\(\s*", "(", text)
    text = re.sub(r"\s*\)\s*", ")", text)
    return text
