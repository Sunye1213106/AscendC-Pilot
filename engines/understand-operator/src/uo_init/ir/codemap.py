# -*- coding: utf-8 -*-
"""In-memory AscendC CodeMap — single graph for Host/Kernel/Tiling/compile-time."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

from uo_init.ir.entity import Entity, EntityKind
from uo_init.ir.relation import Relation, RelationKind


def _is_truncated_kernel_branch(cond: str) -> bool:
    text = str(cond or "").strip()
    if not text:
        return False
    if "..." in text:
        return True
    if text.count("<") != text.count(">"):
        return True
    return len(text) > 80 and "<" in text


def _ingest_host_checks(cm: "CodeMap", host_ir: Any, ordinals: dict[tuple[str, str, str], int]) -> None:
    """Mint locatable Host BRANCH nodes for OP_CHECK / VALIDATION_ONLY controls."""
    from uo_init.ids import branch_id

    for node in getattr(host_ir, "controls", None) or []:
        universe = str(getattr(node, "universe", "") or "")
        snippet = str(getattr(node, "snippet", "") or "")
        cond = str(getattr(node, "condition", "") or "")
        haystack = f"{snippet} {cond}"
        if universe != "VALIDATION_ONLY" and "OP_CHECK" not in haystack and "OPS_CHECK" not in haystack:
            continue
        file = str(getattr(node, "file", "") or "")
        line = int(getattr(node, "line", 0) or 0)
        if not file or line <= 0:
            continue
        fn_name = str(getattr(node, "function", "") or "")
        guard = (cond or snippet).strip()[:120]
        if not guard:
            continue
        okey = (file, fn_name or "_check", guard)
        ordinal = ordinals.get(okey, 0)
        ordinals[okey] = ordinal + 1
        eid = branch_id(
            side="host",
            file=file,
            function=fn_name or "_check",
            guard=guard,
            ordinal=ordinal,
        )
        cm.upsert(
            EntityKind.BRANCH,
            guard,
            eid=eid,
            attrs={
                "layer": "host",
                "predicate": guard,
                "branch_kind": "host_check",
                "function": fn_name,
                "universe": universe or "VALIDATION_ONLY",
            },
            file=file,
            line=line,
            status="confirmed",
        )


# Legacy KB kind → CodeMap entity kind.
_KB_KIND_MAP: dict[str, EntityKind] = {
    "Variable": EntityKind.VARIABLE,
    "Field": EntityKind.FIELD,
    "Function": EntityKind.FUNCTION,
    "Method": EntityKind.METHOD,
    "File": EntityKind.FILE,
    "Type": EntityKind.TYPE,
    "Input": EntityKind.INPUT,
    "Output": EntityKind.OUTPUT,
    "Macro": EntityKind.MACRO,
    "CompileDefine": EntityKind.COMPILE_VAR,
    "CompileVar": EntityKind.COMPILE_VAR,
    "Template": EntityKind.TEMPLATE,
    "TemplateArg": EntityKind.TEMPLATE_ARG,
    "TemplateInstance": EntityKind.TEMPLATE_INSTANCE,
    "Branch": EntityKind.BRANCH,
    "Ctrl": EntityKind.BRANCH,
    "Predicate": EntityKind.PREDICATE,
    "TilingKey": EntityKind.TILING_KEY,
    "TilingKeyDim": EntityKind.TILING_KEY,
    "TilingField": EntityKind.TILING_FIELD,
    "TilingDataField": EntityKind.TILING_FIELD,
    "Kernel": EntityKind.KERNEL,
    "KernelBranch": EntityKind.BRANCH,
    "Arch": EntityKind.ARCH,
    "Architecture": EntityKind.ARCH,
    "BuildVariant": EntityKind.BUILD_VARIANT,
    "Operation": EntityKind.OPERATION,
    "Buffer": EntityKind.BUFFER,
    "Register": EntityKind.REGISTER,
    "Pipe": EntityKind.PIPE,
    "Event": EntityKind.EVENT,
    "Queue": EntityKind.QUEUE,
}

_KB_EDGE_MAP: dict[str, RelationKind] = {
    "DECLARES": RelationKind.DECLARES,
    "DEFINES": RelationKind.DEFINES,
    "REFERENCES": RelationKind.REFERENCES,
    "CALLS": RelationKind.CALLS,
    "READS": RelationKind.READS,
    "WRITES": RelationKind.WRITES,
    "DERIVES": RelationKind.DERIVES,
    "FLOWS_TO": RelationKind.FLOWS_TO,
    "CONTROLS": RelationKind.CONTROLS,
    "EXPANDS_TO": RelationKind.EXPANDS_TO,
    "GUARDED_BY": RelationKind.GUARDED_BY,
    "BINDS": RelationKind.BINDS,
    "INSTANTIATES": RelationKind.INSTANTIATES,
    "SPECIALIZES": RelationKind.SPECIALIZES,
    "SELECTS": RelationKind.SELECTS,
    "LAUNCHES": RelationKind.LAUNCHES,
    "AVAILABLE_ON": RelationKind.AVAILABLE_ON,
    "ACTIVE_UNDER": RelationKind.ACTIVE_UNDER,
    "SAVES": RelationKind.SAVES,
    "RESTORES": RelationKind.RESTORES,
    "CONTAINS": RelationKind.CONTAINS,
    "RETURNS": RelationKind.RETURNS,
    "ALIASES": RelationKind.ALIASES,
    "WRAPS": RelationKind.WRAPS,
    "ROOTED_AT": RelationKind.ROOTED_AT,
    "PRECEDES": RelationKind.PRECEDES,
    "SIGNALS": RelationKind.SIGNALS,
    "AWAITS": RelationKind.AWAITS,
    # Legacy KB edge names.
    "writes": RelationKind.WRITES,
    "reads": RelationKind.READS,
    "calls": RelationKind.CALLS,
    "controls": RelationKind.CONTROLS,
    "derives": RelationKind.DERIVES,
    "flows_to": RelationKind.FLOWS_TO,
    "selects": RelationKind.SELECTS,
    "binds": RelationKind.BINDS,
    "instantiates": RelationKind.INSTANTIATES,
    "guarded_by": RelationKind.GUARDED_BY,
}


def _eid(kind: str, name: str, *extra: str) -> str:
    raw = "|".join([kind, name, *extra])
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"E_{kind}_{digest}"


def _rid(kind: str, src: str, dst: str) -> str:
    raw = f"{kind}|{src}|{dst}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"R_{kind}_{digest}"


@dataclass
class CodeMap:
    """Unified operator CodeMap (Host + Kernel + compile-time overlay)."""

    op_name: str = ""
    architecture: str = ""
    entities: dict[str, Entity] = field(default_factory=dict)
    relations: dict[str, Relation] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    # -- mutation ----------------------------------------------------------
    def add_entity(self, entity: Entity) -> Entity:
        existing = self.entities.get(entity.id)
        if existing is None:
            self.entities[entity.id] = entity
            return entity
        existing.attrs.update(entity.attrs)
        if entity.name and not existing.name:
            existing.name = entity.name
        if entity.file and not existing.file:
            existing.file = entity.file
            existing.line_start = entity.line_start
            existing.line_end = entity.line_end
        settled = str(existing.attrs.get("root_status") or "")
        if settled in {"REACHED", "PROJECT", "BUILTIN"}:
            existing.status = "extracted"
            existing.confidence = max(float(existing.confidence or 0.0), float(entity.confidence or 0.0))
        elif str(entity.status or "") == "extracted" and str(existing.status or "").lower() in {
            "partial",
            "unresolved",
            "unknown",
            "not_extracted",
            "",
        }:
            existing.status = "extracted"
            existing.confidence = max(float(existing.confidence or 0.0), float(entity.confidence or 0.0))
        return existing

    def upsert(
        self,
        kind: EntityKind | str,
        name: str,
        *,
        eid: str | None = None,
        attrs: dict[str, Any] | None = None,
        file: str = "",
        line: int = 0,
        status: str = "extracted",
        confidence: float = 1.0,
    ) -> Entity:
        kind_name = kind.value if isinstance(kind, EntityKind) else str(kind)
        attrs_doc = dict(attrs or {})

        # A selected source Kernel is first materialised from its verified
        # __global__ signature, then the generic body scanner sees the same
        # definition as a free FUNCTION.  Forking those identities moves CALLS
        # and READS off the actual Kernel and makes entry reachability false.
        # Reuse only the exact, source-verified same-name Kernel case; ordinary
        # same-name functions remain distinct entities.
        if (
            eid is not None
            and kind_name == EntityKind.FUNCTION.value
            and attrs_doc.get("provenance") == "source_kernel_definition"
        ):
            kernels = [
                ent
                for ent in self.by_name(name, kind=EntityKind.KERNEL)
                if ent.attrs.get("source_signature") is True
                or ent.attrs.get("provenance") == "source_kernel_signature"
            ]
            if len(kernels) == 1:
                entity = kernels[0]
                entity.attrs.update(attrs_doc)
                if file:
                    entity.file = file
                    entity.line_start = int(line)
                    entity.line_end = int(line)
                entity.status = status
                entity.confidence = confidence
                return entity

        entity_id = eid or _eid(kind_name, name)
        return self.add_entity(
            Entity(
                id=entity_id,
                kind=kind,
                name=name,
                attrs=attrs_doc,
                file=file,
                line_start=int(line),
                line_end=int(line),
                status=status,
                confidence=confidence,
            )
        )

    def link(
        self,
        kind: RelationKind | str,
        src: str,
        dst: str,
        *,
        attrs: dict[str, Any] | None = None,
        status: str = "extracted",
        confidence: float = 1.0,
    ) -> Relation:
        kind_name = kind.value if isinstance(kind, RelationKind) else str(kind)
        rid = _rid(kind_name, src, dst)
        rel = Relation(
            id=rid,
            kind=kind,
            src=src,
            dst=dst,
            attrs=dict(attrs or {}),
            status=status,
            confidence=confidence,
        )
        self.relations.setdefault(rid, rel)
        return self.relations[rid]

    # -- query helpers -----------------------------------------------------
    def by_kind(self, kind: EntityKind | str) -> list[Entity]:
        name = kind.value if isinstance(kind, EntityKind) else str(kind)
        return [e for e in self.entities.values() if e.kind_name() == name]

    def by_name(self, name: str, *, kind: EntityKind | str | None = None) -> list[Entity]:
        kn = None
        if kind is not None:
            kn = kind.value if isinstance(kind, EntityKind) else str(kind)
        out: list[Entity] = []
        for e in self.entities.values():
            if e.name != name:
                continue
            if kn is not None and e.kind_name() != kn:
                continue
            out.append(e)
        return out

    def neighbors(
        self,
        entity_id: str,
        *,
        kind: RelationKind | str | None = None,
        direction: str = "out",
    ) -> list[tuple[Relation, Entity]]:
        kn = None
        if kind is not None:
            kn = kind.value if isinstance(kind, RelationKind) else str(kind)
        hits: list[tuple[Relation, Entity]] = []
        for rel in self.relations.values():
            if kn is not None and rel.kind_name() != kn:
                continue
            if direction in ("out", "both") and rel.src == entity_id:
                dst = self.entities.get(rel.dst)
                if dst is not None:
                    hits.append((rel, dst))
            if direction in ("in", "both") and rel.dst == entity_id:
                src = self.entities.get(rel.src)
                if src is not None:
                    hits.append((rel, src))
        return hits

    def find_path(
        self,
        start_id: str,
        *,
        end_kinds: Iterable[str] | None = None,
        end_id: str | None = None,
        max_depth: int = 32,
    ) -> list[str]:
        """BFS path of entity ids from start to end_id or first end_kind."""
        ends = {str(k) for k in (end_kinds or ())}
        adj: dict[str, list[str]] = defaultdict(list)
        for rel in self.relations.values():
            adj[rel.src].append(rel.dst)

        prev: dict[str, str | None] = {start_id: None}
        q: deque[str] = deque([start_id])
        found: str | None = None
        while q:
            cur = q.popleft()
            ent = self.entities.get(cur)
            if end_id and cur == end_id:
                found = cur
                break
            if ends and ent is not None and ent.kind_name() in ends:
                found = cur
                break
            if len(prev) > 1 and (len(prev) // 2) > max_depth * 64:
                break
            depth = 0
            walk = cur
            while prev.get(walk) is not None:
                depth += 1
                walk = prev[walk]  # type: ignore[assignment]
                if depth > max_depth:
                    break
            if depth > max_depth:
                continue
            for nxt in adj.get(cur, ()):
                if nxt in prev:
                    continue
                prev[nxt] = cur
                q.append(nxt)
        if found is None:
            return []
        path: list[str] = []
        cur2: str | None = found
        while cur2 is not None:
            path.append(cur2)
            cur2 = prev.get(cur2)
        path.reverse()
        return path

    def host_kernel_path_exists(self) -> bool:
        inputs = self.by_kind(EntityKind.INPUT)
        if not inputs:
            # Fallback: VARIABLE named like inputs also count for adapters.
            inputs = [e for e in self.entities.values() if e.kind_name() in {"INPUT", "VARIABLE"}]
        for inp in inputs[:32]:
            # Prefer a full path to KERNEL; fall back to key/instance reachability.
            to_kernel = self.find_path(inp.id, end_kinds={"KERNEL"})
            if len(to_kernel) >= 2:
                return True
            path = self.find_path(
                inp.id,
                end_kinds={"TILING_KEY", "TEMPLATE_INSTANCE"},
            )
            if len(path) >= 2 and (
                self.by_kind(EntityKind.KERNEL)
                or self.by_kind(EntityKind.TEMPLATE_INSTANCE)
            ):
                return True
        kernels = self.by_kind(EntityKind.KERNEL)
        keys = self.by_kind(EntityKind.TILING_KEY)
        return bool(kernels) and (bool(keys) or bool(self.by_kind(EntityKind.TEMPLATE_INSTANCE)))

    def summary(self) -> dict[str, Any]:
        by_kind: dict[str, int] = defaultdict(int)
        for e in self.entities.values():
            by_kind[e.kind_name()] += 1
        by_rel: dict[str, int] = defaultdict(int)
        for r in self.relations.values():
            by_rel[r.kind_name()] += 1
        return {
            "op_name": self.op_name,
            "architecture": self.architecture,
            "entity_count": len(self.entities),
            "relation_count": len(self.relations),
            "entities_by_kind": dict(sorted(by_kind.items())),
            "relations_by_kind": dict(sorted(by_rel.items())),
            "has_host": bool(
                self.by_kind(EntityKind.FUNCTION)
                or self.by_kind(EntityKind.VARIABLE)
                or self.by_kind(EntityKind.FIELD)
            ),
            "has_kernel": bool(self.by_kind(EntityKind.KERNEL)),
            "has_host_kernel_path": self.host_kernel_path_exists(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "codemap/v1",
            "op_name": self.op_name,
            "architecture": self.architecture,
            "meta": dict(self.meta),
            "entities": [e.to_dict() for e in self.entities.values()],
            "relations": [r.to_dict() for r in self.relations.values()],
            "summary": self.summary(),
        }

    # -- adapters from legacy IR -------------------------------------------
    @classmethod
    def from_host_ir(
        cls,
        host_ir: Any,
        *,
        op_name: str = "",
        architecture: str = "",
        codemap: "CodeMap | None" = None,
    ) -> "CodeMap":
        cm = codemap or cls(op_name=op_name, architecture=architecture)
        if op_name:
            cm.op_name = op_name
        if architecture:
            cm.architecture = architecture

        for name, summary in (getattr(host_ir, "summaries", None) or {}).items():
            fn = cm.upsert(
                EntityKind.FUNCTION,
                str(name),
                attrs={"layer": "host"},
                file=str(getattr(summary, "file", "") or ""),
                line=int(getattr(summary, "line", 0) or 0),
            )
            for callee, _args in getattr(summary, "calls", None) or []:
                other = cm.upsert(EntityKind.FUNCTION, str(callee), attrs={"layer": "host"})
                cm.link(RelationKind.CALLS, fn.id, other.id)
            for w in getattr(summary, "writes", None) or []:
                field_e = cm.upsert(EntityKind.FIELD, str(w), attrs={"layer": "host"})
                cm.link(RelationKind.WRITES, fn.id, field_e.id)
            for r in getattr(summary, "reads", None) or []:
                var_e = cm.upsert(EntityKind.VARIABLE, str(r), attrs={"layer": "host"})
                cm.link(RelationKind.READS, fn.id, var_e.id)

        from uo_init.ids import branch_id

        host_branch_ordinals: dict[tuple[str, str, str], int] = {}
        for ev in getattr(host_ir, "writes", None) or []:
            path = str(getattr(ev, "path", "") or "")
            if not path:
                continue
            ev_file = str(getattr(ev, "file", "") or "")
            ev_line = int(getattr(ev, "line", 0) or 0)
            fn_name = str(getattr(ev, "function", "") or "")
            guards = list((ev.guards() if hasattr(ev, "guards") else []) or [])
            field_attrs: dict[str, Any] = {
                "layer": "host",
                "rhs": getattr(ev, "rhs", ""),
            }
            if guards and (not ev_file or ev_line <= 0):
                # Keep short guard text on the write site when we cannot mint a
                # located Host BRANCH (span is required for test/dev locate).
                field_attrs["guards"] = [str(g)[:120] for g in guards]
            field_e = cm.upsert(
                EntityKind.FIELD,
                path,
                attrs=field_attrs,
                file=ev_file,
                line=ev_line,
            )
            if fn_name:
                fn = cm.upsert(
                    EntityKind.FUNCTION,
                    fn_name,
                    attrs={"layer": "host"},
                    file=ev_file,
                    line=ev_line,
                )
                cm.link(RelationKind.WRITES, fn.id, field_e.id)
            if not ev_file or ev_line <= 0:
                continue
            for guard in guards:
                gtext = str(guard or "").strip()
                if not gtext:
                    continue
                okey = (ev_file, fn_name, gtext)
                ordinal = host_branch_ordinals.get(okey, 0)
                host_branch_ordinals[okey] = ordinal + 1
                eid = branch_id(
                    side="host",
                    file=ev_file,
                    function=fn_name,
                    guard=gtext,
                    ordinal=ordinal,
                )
                br = cm.upsert(
                    EntityKind.BRANCH,
                    gtext[:120],
                    eid=eid,
                    attrs={
                        "layer": "host",
                        "predicate": gtext,
                        "branch_kind": "host_guard",
                        "function": fn_name,
                    },
                    file=ev_file,
                    line=ev_line,
                    status="confirmed",
                )
                cm.link(RelationKind.GUARDED_BY, field_e.id, br.id)
                cm.link(RelationKind.CONTROLS, br.id, field_e.id)

        for site in getattr(host_ir, "call_sites", None) or []:
            caller = cm.upsert(
                EntityKind.FUNCTION,
                str(getattr(site, "caller", "") or ""),
                attrs={"layer": "host"},
                file=str(getattr(site, "file", "") or ""),
                line=int(getattr(site, "line", 0) or 0),
            )
            callee = cm.upsert(
                EntityKind.FUNCTION,
                str(getattr(site, "callee", "") or ""),
                attrs={"layer": "host"},
            )
            if caller.name and callee.name:
                cm.link(RelationKind.CALLS, caller.id, callee.id)

        _ingest_host_checks(cm, host_ir, host_branch_ordinals)

        cm.meta["host_backend"] = str(getattr(host_ir, "backend", "") or "")
        return cm

    @classmethod
    def from_kernel_ir(
        cls,
        kernel_ir: Any,
        *,
        op_name: str = "",
        architecture: str = "",
        codemap: "CodeMap | None" = None,
        op_root: str = "",
    ) -> "CodeMap":
        cm = codemap or cls(op_name=op_name, architecture=architecture)
        if architecture:
            arch = cm.upsert(EntityKind.ARCH, architecture, attrs={"layer": "arch"})
        else:
            arch = None

        # Prefer already-verified KERNEL entities (source signature / tiling
        # closure). Never mint a span-less dummy KERNEL from the op name alone.
        verified_kernels = [
            e
            for e in cm.by_kind(EntityKind.KERNEL)
            if e.attrs.get("source_signature")
            or e.attrs.get("source_definition")
            or str(e.attrs.get("provenance") or "").startswith("source_kernel")
            or (e.file and int(e.line_start or 0) > 0)
        ]
        variants = list(getattr(kernel_ir, "variants", None) or [])
        for kernel in verified_kernels:
            if variants:
                existing = list(kernel.attrs.get("variants") or [])
                for v in variants:
                    if v not in existing:
                        existing.append(v)
                kernel.attrs["variants"] = existing
            if arch is not None:
                cm.link(RelationKind.AVAILABLE_ON, kernel.id, arch.id)

        mint = getattr(kernel_ir, "mint_ids", None)
        if callable(mint):
            mint(op_root or "")

        for br in getattr(kernel_ir, "branches", None) or []:
            bid = str(getattr(br, "id", "") or "").strip()
            cond = str(getattr(br, "condition", "") or "")
            br_file = str(getattr(br, "file", "") or "")
            br_line = int(getattr(br, "line", 0) or 0)
            if not bid or not br_file or br_line <= 0:
                continue
            if _is_truncated_kernel_branch(cond):
                continue
            ident = re.search(r"\b(IS_[A-Z0-9_]+|[A-Z][A-Z0-9_]{2,})\b", cond)
            name = ident.group(1) if ident else (cond[:120] or bid)
            branch = cm.upsert(
                EntityKind.BRANCH,
                name,
                eid=bid,
                attrs={
                    "layer": "kernel",
                    "condition": cond[:200],
                    "dimensions": list(getattr(br, "dimensions", None) or []),
                    "variants": list(getattr(br, "variants", None) or []),
                    "function": str(getattr(br, "function", "") or ""),
                },
                file=br_file,
                line=br_line,
                status="confirmed",
            )
            for kernel in verified_kernels:
                cm.link(RelationKind.CONTROLS, branch.id, kernel.id)
            for dim in getattr(br, "dimensions", None) or []:
                key = cm.upsert(EntityKind.TILING_KEY, str(dim), attrs={"layer": "tiling"})
                cm.link(RelationKind.SELECTS, key.id, branch.id)
                for kernel in verified_kernels:
                    cm.link(
                        RelationKind.SELECTS,
                        key.id,
                        kernel.id,
                        attrs={"provenance": "kernel_branch_dimension"},
                    )
        cm.meta["kernel_ir_variants"] = variants
        return cm

    @classmethod
    def from_tiling_data_ir(
        cls,
        tiling_ir: Any,
        *,
        op_name: str = "",
        architecture: str = "",
        codemap: "CodeMap | None" = None,
    ) -> "CodeMap":
        cm = codemap or cls(op_name=op_name, architecture=architecture)
        structs = getattr(tiling_ir, "structs", None) or {}
        # TilingDataIR may expose .fields or iterate structs.
        fields: list[Any] = list(getattr(tiling_ir, "fields", None) or [])
        if not fields and isinstance(structs, dict):
            for st in structs.values():
                fields.extend(getattr(st, "fields", None) or [])
        for f in fields:
            name = str(getattr(f, "name", "") or "")
            if not name:
                continue
            cm.upsert(
                EntityKind.TILING_FIELD,
                name,
                attrs={
                    "layer": "tiling",
                    "ctype": str(getattr(f, "ctype", "") or ""),
                    "struct": str(getattr(f, "struct", "") or ""),
                },
                file=str(getattr(f, "file", "") or ""),
                line=int(getattr(f, "line", 0) or 0),
            )
        return cm

    @classmethod
    def from_kb(
        cls,
        kb: Any,
        *,
        codemap: "CodeMap | None" = None,
    ) -> "CodeMap":
        cm = codemap or cls(
            op_name=str(getattr(kb, "op_name", "") or ""),
            architecture=str(getattr(kb, "architecture", "") or ""),
        )
        for node in (getattr(kb, "nodes", None) or {}).values():
            kind_raw = str(getattr(node, "kind", "") or "OTHER")
            kind = _KB_KIND_MAP.get(kind_raw, EntityKind.OTHER)
            ev0 = (getattr(node, "evidence", None) or [None])[0]
            cm.add_entity(
                Entity(
                    id=str(node.id),
                    kind=kind,
                    name=str(getattr(node, "name", "") or ""),
                    attrs={
                        "layer": str(getattr(node, "layer", "") or ""),
                        "legacy_kind": kind_raw,
                        **dict(getattr(node, "data", None) or {}),
                    },
                    file=str(getattr(ev0, "file", "") or "") if ev0 else "",
                    line_start=int(getattr(ev0, "line_start", 0) or 0) if ev0 else 0,
                    line_end=int(getattr(ev0, "line_end", 0) or 0) if ev0 else 0,
                    status=str(getattr(node, "status", "extracted") or "extracted"),
                    confidence=float(getattr(node, "confidence", 1.0) or 1.0),
                )
            )
        for edge in (getattr(kb, "edges", None) or {}).values():
            kind_raw = str(getattr(edge, "kind", "") or "OTHER")
            kind = _KB_EDGE_MAP.get(kind_raw, RelationKind.OTHER)
            cm.link(
                kind,
                str(edge.src),
                str(edge.dst),
                attrs={"legacy_kind": kind_raw, **dict(getattr(edge, "data", None) or {})},
                status=str(getattr(edge, "status", "extracted") or "extracted"),
                confidence=float(getattr(edge, "confidence", 1.0) or 1.0),
            )
        return cm

    @classmethod
    def assemble(
        cls,
        *,
        op_name: str = "",
        architecture: str = "",
        host_ir: Any = None,
        kernel_ir: Any = None,
        tiling_ir: Any = None,
        kb: Any = None,
        inputs: Iterable[str] | None = None,
        key_fields: Iterable[dict[str, Any]] | None = None,
    ) -> "CodeMap":
        """Build a CodeMap from available legacy IR pieces."""
        cm = cls(op_name=op_name, architecture=architecture)
        if architecture:
            arch = cm.upsert(EntityKind.ARCH, architecture)
            bv = cm.upsert(
                EntityKind.BUILD_VARIANT,
                architecture,
                attrs={"architecture": architecture},
            )
            cm.link(RelationKind.ACTIVE_UNDER, arch.id, bv.id)

        for inp in inputs or ():
            name = str(inp)
            if name:
                cm.upsert(EntityKind.INPUT, name, attrs={"layer": "api"})

        if host_ir is not None:
            cls.from_host_ir(host_ir, op_name=op_name, architecture=architecture, codemap=cm)
        if tiling_ir is not None:
            cls.from_tiling_data_ir(
                tiling_ir, op_name=op_name, architecture=architecture, codemap=cm
            )
        if kernel_ir is not None:
            cls.from_kernel_ir(
                kernel_ir, op_name=op_name, architecture=architecture, codemap=cm
            )
        if kb is not None:
            cls.from_kb(kb, codemap=cm)

        # Input-rooted derivation rows → DERIVES / SELECTS backbone.
        for row in key_fields or ():
            if not isinstance(row, dict):
                continue
            key_name = str(row.get("name") or row.get("field") or row.get("dim") or "")
            if not key_name:
                continue
            key_e = cm.upsert(EntityKind.TILING_KEY, key_name, attrs={"layer": "tiling"})
            for root in row.get("input_roots") or row.get("roots") or []:
                root_name = str(root)
                if not root_name:
                    continue
                known_inputs = {e.name for e in cm.by_kind(EntityKind.INPUT)}
                kind = EntityKind.VARIABLE
                if root_name in known_inputs:
                    kind = EntityKind.INPUT
                elif root_name.isupper() and "_" in root_name:
                    kind = EntityKind.INPUT
                elif root_name.startswith("INPUT_") or root_name.startswith("ATTR_"):
                    kind = EntityKind.INPUT
                root_e = cm.upsert(kind, root_name, attrs={"layer": "api"})
                cm.link(RelationKind.DERIVES, root_e.id, key_e.id)
                cm.link(RelationKind.FLOWS_TO, root_e.id, key_e.id)
            for kernel in cm.by_kind(EntityKind.KERNEL):
                cm.link(RelationKind.SELECTS, key_e.id, kernel.id)

        # Ensure tiling fields written by host connect toward keys when names match.
        for field_e in cm.by_kind(EntityKind.FIELD):
            for key_e in cm.by_kind(EntityKind.TILING_KEY):
                if field_e.name and (
                    field_e.name == key_e.name
                    or field_e.name.endswith("." + key_e.name)
                    or key_e.name in field_e.name
                ):
                    cm.link(RelationKind.FLOWS_TO, field_e.id, key_e.id)

        return cm
