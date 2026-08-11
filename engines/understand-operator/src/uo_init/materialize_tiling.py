# -*- coding: utf-8 -*-
"""Materialize TPL key space, template blocks and coverage into the KB.

This is the new-contract producer for TG L1/L2. Empty shells must not be marked
``extracted``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from uo_init.ids import named_id, slug
from uo_init.kb_model import (
    CONTROLLABLE_ROOTS,
    STATUS_EXTRACTED,
    STATUS_PARTIAL,
    Domain,
    Evidence,
    KnowledgeBase,
    Node,
)
from uo_init.tpl_bind import BindingResult
from uo_init.tpl_dsl import TplSchema, expand_legal_instances, parse_file
from uo_init.variable_model import VariableModel

KEY_REACHABLE = "reachable"
KEY_UNREACHABLE = "unreachable"
KEY_UNKNOWN = "unknown"
KEY_UNDERIVABLE = "underivable"
LAYER_TEMPLATE = "template"
LAYER_NOT_COMPUTED = "not_computed"

REASON_OK = "OK"
REASON_BIND_INCOMPLETE = "BIND_INCOMPLETE"
REASON_NOT_INPUT_DERIVABLE = "NOT_INPUT_DERIVABLE"
REASON_PREDICATE_UNRESOLVED = "PREDICATE_UNRESOLVED"
REASON_REALIZATION_MISSING = "REALIZATION_MISSING"
REASON_DOMAIN_OPEN = "DOMAIN_OPEN"
REASON_HOST_ENCODE_CONFLICT = "HOST_ENCODE_CONFLICT"
REASON_HOST_UNREACHABLE = "HOST_UNREACHABLE"
REASON_HOST_UNKNOWN = "HOST_UNKNOWN"

REASON_CODES = frozenset(
    {
        REASON_OK,
        REASON_BIND_INCOMPLETE,
        REASON_NOT_INPUT_DERIVABLE,
        REASON_PREDICATE_UNRESOLVED,
        REASON_REALIZATION_MISSING,
        REASON_DOMAIN_OPEN,
        REASON_HOST_ENCODE_CONFLICT,
        REASON_HOST_UNREACHABLE,
        REASON_HOST_UNKNOWN,
    }
)


@dataclass
class TemplateBlock:
    id: str
    name: str
    fixed_fields: dict[str, str]
    field_domains: dict[str, list[str]]
    product_count: int
    sel_group_index: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "fixed_fields": dict(self.fixed_fields),
            "field_domains": {k: list(v) for k, v in self.field_domains.items()},
            "product_count": self.product_count,
            "sel_group_index": self.sel_group_index,
        }


@dataclass
class LegalKeyRow:
    index: int
    tiling_key: int
    tiling_key_hex: str
    dims: dict[str, str]
    sel_group_id: str
    reason_code: str = REASON_OK
    #: Default is the weakest status, not the strongest. A row that nobody
    #: classified must not read as "a host run produces this".
    status: str = KEY_UNKNOWN
    detail: str = ""
    blocker_ids: list[str] = field(default_factory=list)
    #: Which check produced the status.
    layer: str = LAYER_TEMPLATE

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "index": self.index,
            "tiling_key": self.tiling_key,
            "tiling_key_hex": self.tiling_key_hex,
            "dims": dict(self.dims),
            "sel_group_id": self.sel_group_id,
            "reason_code": self.reason_code,
            "status": self.status,
            "detail": self.detail,
            "blocker_ids": list(self.blocker_ids),
            "layer": self.layer,
        }
        return out


def _sel_domain(sel: dict[str, Any]) -> list[str]:
    vals = list(sel.get("vals") or [])
    if vals and ("UI_LIST" in str(vals[0]) or "UI_RANGE" in str(vals[0])):
        return [str(v) for v in vals[1:]]
    return [str(v) for v in vals]


def build_template_blocks(schema: TplSchema) -> list[TemplateBlock]:
    blocks: list[TemplateBlock] = []
    for gi, group in enumerate(schema.selections):
        fixed: dict[str, str] = {}
        domains: dict[str, list[str]] = {}
        product = 1
        for sel in group:
            name = str(sel["name"])
            domain = _sel_domain(sel)
            if not domain:
                continue
            if len(domain) == 1:
                fixed[name] = domain[0]
            else:
                domains[name] = domain
                product *= len(domain)
        if not fixed and not domains:
            continue
        if product < 1:
            product = 1
        bid = named_id("TemplateBinding", f"sel{gi}")
        blocks.append(
            TemplateBlock(
                id=bid,
                name=f"ARGS_SEL_{gi}",
                fixed_fields=fixed,
                field_domains=domains,
                product_count=product,
                sel_group_index=gi,
            )
        )
    return blocks


def expand_legal_with_groups(schema: TplSchema) -> list[tuple[int, dict[str, str]]]:
    """Return (sel_group_index, dims) for every legal instance."""
    import itertools

    out: list[tuple[int, dict[str, str]]] = []
    for gi, group in enumerate(schema.selections):
        axes: list[tuple[str, list[str]]] = []
        for sel in group:
            axes.append((str(sel["name"]), _sel_domain(sel)))
        if not axes:
            continue
        names = [a[0] for a in axes]
        for combo in itertools.product(*[a[1] for a in axes]):
            out.append((gi, dict(zip(names, combo))))
    return out


def _bind_complete(binding: BindingResult | None, schema: TplSchema) -> tuple[bool, str]:
    if binding is None:
        return False, "tpl_bind missing"
    if not binding.bindings:
        return False, "tpl_bind empty"
    bound = {b.decl.name for b in binding.bindings}
    missing = [d.name for d in schema.dims if d.name not in bound]
    if missing:
        return False, "unbound dims: " + ",".join(missing[:8])
    return True, ""


def _legal_key_status(
    dims: dict[str, str],
    schema: TplSchema,
    *,
    bind_ok: bool,
    bind_detail: str,
) -> tuple[str, str, str, str]:
    """Return (status, reason_code, detail, layer) for a legal key row."""

    if not bind_ok:
        return KEY_UNDERIVABLE, REASON_NOT_INPUT_DERIVABLE, bind_detail, LAYER_TEMPLATE
    for dim in schema.dims:
        val = dims.get(dim.name)
        if val is None:
            return KEY_UNDERIVABLE, REASON_NOT_INPUT_DERIVABLE, f"missing {dim.name}", LAYER_TEMPLATE
        if str(val) not in [str(x) for x in dim.value_domain]:
            return (
                KEY_UNDERIVABLE,
                REASON_NOT_INPUT_DERIVABLE,
                f"{dim.name}={val} not in domain",
                LAYER_TEMPLATE,
            )
    return (
        KEY_UNKNOWN,
        REASON_HOST_UNKNOWN,
        "host reachability is not computed by UO; TG closes it with replay or reviewed evidence",
        LAYER_NOT_COMPUTED,
    )


def build_legal_key_rows(
    schema: TplSchema,
    *,
    binding: BindingResult | None = None,
    blocker_ids: Iterable[str] = (),
) -> list[LegalKeyRow]:
    blockers = list(blocker_ids)
    bind_ok, bind_detail = _bind_complete(binding, schema)
    rows: list[LegalKeyRow] = []
    for idx, (gi, dims) in enumerate(expand_legal_with_groups(schema)):
        full = {d.name: str(dims.get(d.name, d.value_domain[0])) for d in schema.dims}
        key = schema.encode_tiling_key(full)
        status, reason, detail, layer = _legal_key_status(
            full,
            schema=schema,
            bind_ok=bind_ok,
            bind_detail=bind_detail,
        )
        rows.append(
            LegalKeyRow(
                index=idx,
                tiling_key=key,
                tiling_key_hex=f"0x{key:016x}",
                dims=full,
                sel_group_id=named_id("TemplateBinding", f"sel{gi}"),
                reason_code=reason,
                status=status,
                detail=detail,
                blocker_ids=blockers if reason == REASON_PREDICATE_UNRESOLVED else [],
                layer=layer,
            )
        )
    return rows

def materialize_into_kb(
    kb: KnowledgeBase,
    *,
    schema: TplSchema | None,
    var_model: VariableModel | None = None,
    binding: BindingResult | None = None,
    derivation: Any | None = None,
    header_path: str = "",
) -> dict[str, Any]:
    """Add KEY/VAR/KTPL nodes + domains; stash contract payloads in kb.notes.

    `derivation` is the per-dimension `HostDerivation`. Without it no dimension
    can be called input-derivable: having a host expression bound to a key field
    says the encode site was found, not that a test case can steer it.
    """
    if schema is None or not schema.dims:
        kb.notes["tiling_materialize"] = {"ok": False, "reason": "no_tpl_schema"}
        return {"ok": False, "reason": "no_tpl_schema"}

    ev = Evidence.at(header_path or "<tpl>", 1, snippet="ASCENDC_TPL_ARGS_DECL")
    field_order = [d.name for d in schema.dims]
    dimensions: list[dict[str, Any]] = []
    key_field_obligations: dict[str, Any] = {}
    derived_fields = derivation.by_name() if derivation is not None else {}

    for dim in schema.dims:
        kid = named_id("TilingKeyDim", dim.name)
        domain_vals = [str(v) for v in dim.value_domain]
        kb.add_domain(
            Domain(
                var_id=kid,
                value_type="enum" if dim.kind != "BOOL" else "bool",
                values=domain_vals,
                completeness="closed",
                source="tpl_decl",
            )
        )
        kb.add_node(
            Node(
                id=kid,
                kind="TilingKeyDim",
                name=dim.name,
                layer="tiling",
                status=STATUS_EXTRACTED,
                confidence=1.0,
                evidence=[ev],
                data={
                    "bit_lo": dim.bit_lo,
                    "bit_hi": dim.bit_hi,
                    "bw": dim.bw,
                    "kind": dim.kind,
                    "domain": domain_vals,
                },
            )
        )
        fld = derived_fields.get(dim.name)
        dimensions.append(
            {
                "id": kid,
                "name": dim.name,
                "values": domain_vals,
                "bit_lo": dim.bit_lo,
                "bit_hi": dim.bit_hi,
                "bw": dim.bw,
                "kind": dim.kind,
                "completeness": "closed",
                "exactness": getattr(fld, "exactness", "") if fld else "",
                "input_closure": getattr(fld, "input_closure", "") if fld else "",
                "input_derivable": bool(getattr(fld, "input_derivable", False)) if fld else False,
            }
        )
        key_field_obligations[dim.name] = {
            "id": kid,
            "values": domain_vals,
            "independent": True,
            "completeness": "closed",
        }

    if var_model is not None:
        for spec in var_model.variables.values():
            if spec.var_id in kb.nodes:
                continue
            kb.add_domain(spec.domain)
            kb.add_node(
                Node(
                    id=spec.var_id,
                    kind="Variable",
                    name=spec.name,
                    layer="tiling",
                    status=STATUS_EXTRACTED,
                    confidence=1.0,
                    evidence=list(spec.evidence) or [ev],
                    data={
                        "value_type": spec.value_type,
                        "origin": spec.origin,
                        "description": spec.description,
                    },
                )
            )

    blocks = build_template_blocks(schema)
    for block in blocks:
        kb.add_node(
            Node(
                id=block.id,
                kind="TemplateBinding",
                name=block.name,
                layer="tiling",
                status=STATUS_EXTRACTED,
                confidence=1.0,
                evidence=[ev],
                data={
                    "fixed_fields": block.fixed_fields,
                    "field_domains": block.field_domains,
                    "product_count": block.product_count,
                    "sel_group_index": block.sel_group_index,
                },
            )
        )

    bind_edges: list[dict[str, Any]] = []
    if binding is not None:
        for b in binding.bindings:
            kid = named_id("TilingKeyDim", b.decl.name)
            bind_edges.append(
                {
                    "kind": "binds",
                    "src": kid,
                    "host_expr": b.host_expr,
                    "nttp": b.nttp_name,
                    "index": b.index,
                }
            )

    blocker_ids = sorted(kb.blockers.keys())
    legal_rows = build_legal_key_rows(
        schema,
        binding=binding,
        blocker_ids=blocker_ids,
    )

    # Host-derived realization: binding maps each key dim to a host expression.
    # Do not claim tpl_identity (that short-circuited K6).
    input_realization: dict[str, Any] = {}
    realization_mode = "host_derivation" if binding and binding.bindings else "unbound"
    if binding and binding.bindings:
        for b in binding.bindings:
            rid = f"IR_{slug(b.decl.name)}"
            fld = derived_fields.get(b.decl.name)
            input_realization[rid] = {
                "id": rid,
                "key_pattern": {b.decl.name: "*"},
                "host_expr": b.host_expr,
                "csv_hints": {b.decl.name: f"HOST.{b.decl.name}"},
                "source": "host_encode_binding",
                # Was hardcoded True for every bound dimension. A binding only
                # locates the encode site; whether the input reaches it is the
                # derivation's answer.
                "input_derivable": bool(getattr(fld, "input_derivable", False)) if fld else False,
                "input_closure": getattr(fld, "input_closure", "") if fld else "",
            }
    else:
        for dim in schema.dims:
            rid = f"IR_{slug(dim.name)}"
            input_realization[rid] = {
                "id": rid,
                "key_pattern": {dim.name: "*"},
                "csv_hints": {dim.name: f"KEY.{dim.name}"},
                "source": "tpl_dim_unbound",
                "input_derivable": False,
            }

    relations = []
    for node in kb.iter_nodes():
        if node.kind != "Predicate":
            continue
        expr = (node.data or {}).get("expr")
        if not expr:
            continue
        relations.append(
            {
                "id": node.id,
                "branch_id": (node.data or {}).get("branch_id"),
                "target_value": (node.data or {}).get("target_value"),
                "input_controllable": (node.data or {}).get("input_controllable"),
                "expr": expr,
                "status": node.status,
            }
        )

    contract = {
        "ok": True,
        "field_order": field_order,
        "dimensions": dimensions,
        "template_blocks": [b.to_dict() for b in blocks],
        "args_sel_count": len(blocks),
        "legal_key_count": len(legal_rows),
        "key_field_obligations": key_field_obligations,
        "family_obligations": [{"id": "COV_FAM_DEFAULT", "family_id": "FAM_DEFAULT"}],
        "input_realization": input_realization,
        "input_realization_mode": realization_mode,
        "relations": relations,
        "bind_edges": bind_edges,
        "legal_keys": [r.to_dict() for r in legal_rows],
        "key_status_counts": {
            "reachable": sum(1 for r in legal_rows if r.status == KEY_REACHABLE),
            "unreachable": sum(1 for r in legal_rows if r.status == KEY_UNREACHABLE),
            "unknown": sum(1 for r in legal_rows if r.status == KEY_UNKNOWN),
            "underivable": sum(1 for r in legal_rows if r.status == KEY_UNDERIVABLE),
        },
        "host_reachability": {
            "status": "not_computed",
            "policy": "tg_replay_or_reviewed_exclusion",
            "reason": "UO no longer runs symbolic host reachability",
        },
        "summary": {
            "template_block_count": len(blocks),
            "expanded_key_count": len(legal_rows),
            "ktpl_instance_count": len(blocks),
            "key_dimension_count": len(dimensions),
            # UO enumerates keys the template can spell; TG closes host
            # reachability through replay or reviewed evidence.
            "template_admissible": len(legal_rows),
            "host_reachable": 0,
            "host_unreachable": 0,
        },
    }
    kb.notes["tiling_materialize"] = contract
    return {
        "ok": True,
        "legal_key_count": len(legal_rows),
        "template_block_count": len(blocks),
        "dimension_count": len(dimensions),
    }


def write_legal_key_index(uo_root: Path, legal_keys: list[dict[str, Any]]) -> Path:
    path = uo_root / "tiling" / "legal_key_index.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in legal_keys:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    return path


def write_key_index(uo_root: Path, fields: list[dict[str, Any]]) -> Path:
    """Lightweight closure-facing index (~8% of derive payload).

    Carries def_sites / status / exactness / value_leaves / input_roots.
    """
    import yaml

    root = Path(uo_root)
    rows = []
    for f in fields or []:
        if not isinstance(f, dict):
            continue
        rows.append({
            "name": f.get("name"),
            "index": f.get("index"),
            "status": f.get("status"),
            "exactness": f.get("exactness"),
            "value_leaves": list(f.get("value_leaves") or []),
            "input_roots": list(f.get("input_roots") or []),
            "def_sites": list(f.get("def_sites") or []),
            "free_vars": list(f.get("free_vars") or []),
        })
    path = root / "tiling" / "key_index.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {"schema": "uo-key-index/v1", "fields": rows},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def load_schema_from_notes_or_header(
    kb: KnowledgeBase, header: str | Path | None
) -> TplSchema | None:
    if header and Path(header).is_file():
        return parse_file(header)
    return None

