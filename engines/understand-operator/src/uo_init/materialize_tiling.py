# -*- coding: utf-8 -*-
"""Materialize TPL key space, template blocks, coverage and reachability into the KB.

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

REASON_OK = "OK"
REASON_BIND_INCOMPLETE = "BIND_INCOMPLETE"
REASON_NOT_INPUT_DERIVABLE = "NOT_INPUT_DERIVABLE"
REASON_PREDICATE_UNRESOLVED = "PREDICATE_UNRESOLVED"
REASON_REALIZATION_MISSING = "REALIZATION_MISSING"
REASON_DOMAIN_OPEN = "DOMAIN_OPEN"
REASON_HOST_ENCODE_CONFLICT = "HOST_ENCODE_CONFLICT"
REASON_Z3_UNSAT = "Z3_UNSAT"
REASON_Z3_UNKNOWN = "Z3_UNKNOWN"

REASON_CODES = frozenset(
    {
        REASON_OK,
        REASON_BIND_INCOMPLETE,
        REASON_NOT_INPUT_DERIVABLE,
        REASON_PREDICATE_UNRESOLVED,
        REASON_REALIZATION_MISSING,
        REASON_DOMAIN_OPEN,
        REASON_HOST_ENCODE_CONFLICT,
        REASON_Z3_UNSAT,
        REASON_Z3_UNKNOWN,
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
    status: str = "reachable"
    detail: str = ""
    blocker_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "tiling_key": self.tiling_key,
            "tiling_key_hex": self.tiling_key_hex,
            "dims": dict(self.dims),
            "sel_group_id": self.sel_group_id,
            "reason_code": self.reason_code,
            "status": self.status,
            "detail": self.detail,
            "blocker_ids": list(self.blocker_ids),
        }


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


def _hard_invariants(dims: dict[str, str]) -> list[tuple[str, bool]]:
    """Cheap source-level invariants (no full field DAG required).

    Returns list of (detail, ok). False means the key is unreachable.
    """
    checks: list[tuple[str, bool]] = []
    reg = str(dims.get("IsRegbase", ""))
    # arch35 regbase path always ENABLE / 1
    if reg and reg not in ("1", "ENABLE", "OptionEnum::ENABLE", "True"):
        checks.append((f"IsRegbase={reg} not ENABLE", False))
    else:
        checks.append(("IsRegbase ENABLE", True))
    # OutDType ≡ InputDType on arch35
    out_v, in_v = dims.get("OutDType"), dims.get("InputDType")
    if out_v is not None and in_v is not None and str(out_v) != str(in_v):
        checks.append((f"OutDType={out_v} != InputDType={in_v}", False))
    else:
        checks.append(("OutDType==InputDType", True))
    # Empty path is a separate encode site; normal ARGS_SEL keep IsEmptyTensor=0
    empty = str(dims.get("IsEmptyTensor", "0"))
    if empty in ("1", "TILING_KEY_1", "True", "ENABLE"):
        # Allow only if other dims are mostly zeroed (template empty block).
        nonzero = [
            n
            for n, v in dims.items()
            if n not in ("IsEmptyTensor", "IsRegbase") and str(v) not in ("0", "DISABLE", "False")
        ]
        if len(nonzero) > 3:
            checks.append(("IsEmptyTensor=1 with rich dims", False))
        else:
            checks.append(("IsEmptyTensor empty-block", True))
    return checks


def z3_check_key_dims(dims: dict[str, str], *, full: bool = False) -> tuple[str, str, str]:
    """Return (status, reason_code, detail) using hard invariants + optional z3.

    Status: reachable | unreachable | unknown

    Full per-key z3 encoding is opt-in (`full=True` or env ``UO_KEY_Z3_FULL=1``)
    because the ARGS_SEL product is thousands of keys; hard invariants cover the
    structural conflicts (OutDType≡InputDType, IsRegbase, empty-path).
    """
    import os

    hard = _hard_invariants(dims)
    bad = [d for d, ok in hard if not ok]
    if bad:
        return "unreachable", REASON_Z3_UNSAT, "; ".join(bad)
    do_full = full or os.environ.get("UO_KEY_Z3_FULL") == "1"
    if not do_full:
        return "reachable", REASON_OK, "invariants_ok"
    try:
        import z3  # type: ignore
    except ImportError:
        return "reachable", REASON_OK, "invariants_ok;z3_unavailable"

    s = z3.Solver()
    s.set(timeout=200)
    syms: dict[str, Any] = {}
    for name, val in dims.items():
        if name in (
            "IsRegbase",
            "IsEmptyTensor",
            "IsDrop",
            "IsPse",
            "IsAttenMask",
            "IsTnd",
            "IsNEqual",
            "IsBn2MultiBlk",
            "IsDNoEqual",
            "IsRope",
            "IsNzOut",
            "IsTndSwizzle",
        ):
            syms[name] = z3.Bool(name)
            truth = str(val) in ("1", "True", "ENABLE", "TILING_KEY_1", "NORMAL_TENSOR")
            if str(val) in ("0", "False", "DISABLE", "EMPTY_TENSOR"):
                truth = False
            s.add(syms[name] == truth)
        else:
            raw = str(val).split("::")[-1]
            try:
                iv = int(raw) if raw.lstrip("-").isdigit() else None
            except ValueError:
                iv = None
            if iv is not None:
                syms[name] = z3.Int(name)
                s.add(syms[name] == iv)
    if "OutDType" in syms and "InputDType" in syms:
        s.add(syms["OutDType"] == syms["InputDType"])
    if "IsRegbase" in syms:
        s.add(syms["IsRegbase"] == True)  # noqa: E712
    r = s.check()
    if r == z3.unsat:
        return "unreachable", REASON_Z3_UNSAT, "z3_unsat"
    if r == z3.unknown:
        return "unknown", REASON_Z3_UNKNOWN, "z3_unknown"
    return "reachable", REASON_OK, "z3_sat"


def classify_key_reachability(
    *,
    dims: dict[str, str],
    schema: TplSchema,
    binding: BindingResult | None,
    blocker_ids: list[str],
    input_controllable_fraction: float,
    use_z3: bool = True,
) -> tuple[str, str, str]:
    """Return (status, reason_code, detail)."""
    ok_bind, bind_detail = _bind_complete(binding, schema)
    if not ok_bind:
        return "underivable", REASON_BIND_INCOMPLETE, bind_detail
    for dim in schema.dims:
        val = dims.get(dim.name)
        if val is None:
            return "underivable", REASON_HOST_ENCODE_CONFLICT, f"missing {dim.name}"
        if str(val) not in [str(x) for x in dim.value_domain]:
            return (
                "underivable",
                REASON_HOST_ENCODE_CONFLICT,
                f"{dim.name}={val} not in domain",
            )
    if input_controllable_fraction <= 0.0:
        return (
            "underivable",
            REASON_NOT_INPUT_DERIVABLE,
            "no input_controllable host predicates",
        )
    if use_z3:
        status, reason, detail = z3_check_key_dims(dims)
        if blocker_ids and status == "reachable":
            detail = (detail + f"; open_blockers={len(blocker_ids)}").strip("; ")
        return status, reason, detail
    detail = ""
    if blocker_ids:
        detail = f"open_blockers={len(blocker_ids)}"
    return "reachable", REASON_OK, detail


def build_legal_key_rows(
    schema: TplSchema,
    *,
    binding: BindingResult | None = None,
    blocker_ids: Iterable[str] = (),
    input_controllable_fraction: float = 0.0,
    use_z3: bool = True,
) -> list[LegalKeyRow]:
    blockers = list(blocker_ids)
    rows: list[LegalKeyRow] = []
    for idx, (gi, dims) in enumerate(expand_legal_with_groups(schema)):
        full = {d.name: str(dims.get(d.name, d.value_domain[0])) for d in schema.dims}
        key = schema.encode_tiling_key(full)
        status, reason, detail = classify_key_reachability(
            dims=full,
            schema=schema,
            binding=binding,
            blocker_ids=blockers,
            input_controllable_fraction=input_controllable_fraction,
            use_z3=use_z3,
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
            )
        )
    return rows


def materialize_into_kb(
    kb: KnowledgeBase,
    *,
    schema: TplSchema | None,
    var_model: VariableModel | None = None,
    binding: BindingResult | None = None,
    header_path: str = "",
) -> dict[str, Any]:
    """Add KEY/VAR/KTPL nodes + domains; stash contract payloads in kb.notes."""
    if schema is None or not schema.dims:
        kb.notes["tiling_materialize"] = {"ok": False, "reason": "no_tpl_schema"}
        return {"ok": False, "reason": "no_tpl_schema"}

    ev = Evidence.at(header_path or "<tpl>", 1, snippet="ASCENDC_TPL_ARGS_DECL")
    field_order = [d.name for d in schema.dims]
    dimensions: list[dict[str, Any]] = []
    key_field_obligations: dict[str, Any] = {}

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

    quality = kb.notes.get("quality") if isinstance(kb.notes.get("quality"), dict) else {}
    ic = float(quality.get("input_controllability") or 0.0)
    blocker_ids = sorted(kb.blockers.keys())
    legal_rows = build_legal_key_rows(
        schema,
        binding=binding,
        blocker_ids=blocker_ids,
        input_controllable_fraction=ic,
    )

    # Host-derived realization: binding maps each key dim to a host expression.
    # Do not claim tpl_identity (that short-circuited K6).
    input_realization: dict[str, Any] = {}
    realization_mode = "host_derivation" if binding and binding.bindings else "unbound"
    if binding and binding.bindings:
        for b in binding.bindings:
            rid = f"IR_{slug(b.decl.name)}"
            input_realization[rid] = {
                "id": rid,
                "key_pattern": {b.decl.name: "*"},
                "host_expr": b.host_expr,
                "csv_hints": {b.decl.name: f"HOST.{b.decl.name}"},
                "source": "host_encode_binding",
                "input_derivable": True,
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
        smt = (node.data or {}).get("smt")
        if not smt:
            continue
        relations.append(
            {
                "id": node.id,
                "branch_id": (node.data or {}).get("branch_id"),
                "target_value": (node.data or {}).get("target_value"),
                "input_controllable": (node.data or {}).get("input_controllable"),
                "expr": smt,
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
            "reachable": sum(1 for r in legal_rows if r.status == "reachable"),
            "unreachable": sum(1 for r in legal_rows if r.status == "unreachable"),
            "unknown": sum(1 for r in legal_rows if r.status == "unknown"),
            "underivable": sum(1 for r in legal_rows if r.status == "underivable"),
        },
        "summary": {
            "template_block_count": len(blocks),
            "expanded_key_count": len(legal_rows),
            "ktpl_instance_count": len(blocks),
            "key_dimension_count": len(dimensions),
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


def load_schema_from_notes_or_header(
    kb: KnowledgeBase, header: str | Path | None
) -> TplSchema | None:
    if header and Path(header).is_file():
        return parse_file(header)
    return None
