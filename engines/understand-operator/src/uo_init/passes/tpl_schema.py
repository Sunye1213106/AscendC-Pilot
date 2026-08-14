# -*- coding: utf-8 -*-
"""TplSchemaPass — ASCENDC_TPL ARGS_DECL + ARGS_SEL into CodeMap + TG D blobs.

Stores selection groups as TEMPLATE entities (not one entity per legal key).
Legal packed-key space D goes into ``context['tg_views']`` view blobs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.materialize_tiling import (
    build_template_blocks,
    expand_legal_with_groups,
)
from uo_init.tpl_dsl import TplSchema, parse_file


def run(codemap: CodeMap, *, context: dict[str, Any] | None = None) -> CodeMap:
    ctx = context if context is not None else {}
    schema, header = _resolve_schema(codemap, ctx)
    if schema is None or not schema.dims:
        codemap.meta["tpl_schema_pass"] = "v1-missing"
        return codemap

    header_ref = _portable_header_ref(header, ctx)
    _upsert_dims(codemap, schema, header_ref)
    _upsert_sel_groups(codemap, schema, header_ref)
    views = _build_tpl_views(schema, header_ref)
    existing = ctx.get("tg_views")
    if not isinstance(existing, dict):
        existing = {}
    existing.update(views)
    ctx["tg_views"] = existing
    ctx["tpl_schema"] = schema

    codemap.meta["tpl_schema_pass"] = "v1"
    codemap.meta["tpl_schema"] = {
        "op_tag": schema.op_tag,
        "dim_count": len(schema.dims),
        "args_sel_group_count": len(schema.selections),
        "legal_key_count": int(views["tiling/exhaustive_key_space.yaml"]["legal_key_count"]),
        "header": header_ref,
    }
    codemap.meta["args_sel_group_count"] = len(schema.selections)
    codemap.meta["legal_key_count"] = int(
        views["tiling/exhaustive_key_space.yaml"]["legal_key_count"]
    )
    return codemap


def _resolve_schema(
    codemap: CodeMap, ctx: dict[str, Any]
) -> tuple[TplSchema | None, Path | None]:
    header = _find_header(codemap, ctx)
    if header is not None and header.is_file():
        try:
            return parse_file(header), header
        except Exception as exc:  # noqa: BLE001
            codemap.meta["tpl_schema_parse_error"] = str(exc)[:240]
            return None, header

    dsl = str(ctx.get("tiling_key_dsl") or "")
    if dsl.strip():
        from uo_init.tpl_dsl import parse_args_decl, parse_args_sel

        schema = parse_args_decl(dsl)
        schema.selections = parse_args_sel(dsl)
        return schema, None
    return None, None


def _portable_header_ref(header: Path | None, ctx: dict[str, Any]) -> str:
    """Return a machine-independent source reference for a discovered TPL header.

    UO products are portable artifacts.  Absolute build-machine paths must not
    leak into entity ``file`` fields, TG views or metadata because downstream
    source freshness checks resolve evidence relative to the operator checkout.
    The canonical in-tree form matches the other source passes:
    ``<operator>/op_kernel/...``.
    """
    if header is None:
        return ""
    resolved = header.expanduser().resolve()
    op_root = str(ctx.get("op_root") or "").strip()
    if op_root:
        root = Path(op_root).expanduser().resolve()
        try:
            return resolved.relative_to(root.parent).as_posix()
        except ValueError:
            pass
    # An explicitly supplied external header is unusual but still must not make
    # a committed .uo host-specific.  Preserve a stable basename rather than an
    # absolute path; parse-time resolution has already happened above.
    return resolved.name


def _find_header(codemap: CodeMap, ctx: dict[str, Any]) -> Path | None:
    explicit = ctx.get("tiling_key_header") or ctx.get("tpl_header")
    if explicit:
        p = Path(str(explicit)).expanduser()
        if p.is_file():
            return p.resolve()

    op_root = str(ctx.get("op_root") or "").strip()
    if op_root:
        root = Path(op_root).expanduser().resolve()
        arch = str(ctx.get("architecture") or codemap.architecture or "")
        try:
            from uo_init.source_layout import select_tpl_decl_header

            hit = select_tpl_decl_header(root, arch)
            if hit is not None and hit.is_file():
                return hit.resolve()
        except Exception:
            pass
        try:
            from uo_init.op_spec import discover

            spec = discover(root, arch_dir=arch or None)
            if spec.tiling_key_header and Path(spec.tiling_key_header).is_file():
                return Path(spec.tiling_key_header).resolve()
        except Exception:
            pass
        # Fallback glob under op_kernel
        hits = sorted(root.glob("op_kernel/**/*template_tiling_key.h"))
        arch = str(codemap.architecture or "")
        if arch:
            prefer = [h for h in hits if arch in h.as_posix()]
            if prefer:
                return prefer[0].resolve()
        if hits:
            return hits[0].resolve()

    for ent in codemap.by_kind(EntityKind.FILE):
        name = str(ent.name or "").replace("\\", "/")
        if name.endswith("template_tiling_key.h") and op_root:
            # FILE names are often op-relative with op folder prefix
            root = Path(op_root).expanduser().resolve()
            cand = root / Path(name).name
            if cand.is_file():
                return cand.resolve()
            # strip leading "<op>/"
            parts = name.split("/", 1)
            if len(parts) == 2:
                cand = root / parts[1]
                if cand.is_file():
                    return cand.resolve()
            for hit in root.glob(f"**/{Path(name).name}"):
                return hit.resolve()
    return None


def _upsert_dims(codemap: CodeMap, schema: TplSchema, header_ref: str) -> None:
    shift = 0
    for order, dim in enumerate(schema.dims):
        domain = [str(v) for v in dim.value_domain]
        bit_lo = int(dim.bit_lo or shift)
        bit_hi = int(dim.bit_hi or (bit_lo + max(int(dim.bw), 1) - 1))
        if not dim.bit_hi and not dim.bit_lo:
            bit_lo = shift
            bit_hi = shift + max(int(dim.bw), 1) - 1
        codemap.upsert(
            EntityKind.TILING_KEY,
            dim.name,
            attrs={
                "layer": "tiling",
                "source_declared": True,
                "decl_kind": dim.kind,
                "kind_tpl": dim.kind,
                "bit_width": int(dim.bw),
                "bw": int(dim.bw),
                "bit_offset": bit_lo,
                "bit_lo": bit_lo,
                "bit_hi": bit_hi,
                "bit_end": bit_hi,
                "decl_order": order,
                "allowed_values": domain,
                "value_domain": domain,
                "provenance": "source_tpl_args_decl",
            },
            file=header_ref,
            status="confirmed",
        )
        shift += max(int(dim.bw), 1)


def _upsert_sel_groups(codemap: CodeMap, schema: TplSchema, header_ref: str) -> None:
    blocks = build_template_blocks(schema)
    for block in blocks:
        tpl = codemap.upsert(
            EntityKind.TEMPLATE,
            block.name,
            attrs={
                "layer": "template",
                "tpl_role": "args_sel_group",
                "sel_group_index": block.sel_group_index,
                "fixed_fields": dict(block.fixed_fields),
                "field_domains": {k: list(v) for k, v in block.field_domains.items()},
                "product_count": int(block.product_count),
                "provenance": "source_tpl_args_sel",
            },
            file=header_ref,
            status="confirmed",
        )
        for dim_name in list(block.fixed_fields) + list(block.field_domains):
            keys = codemap.by_name(dim_name, kind=EntityKind.TILING_KEY)
            if not keys:
                continue
            codemap.link(
                RelationKind.BINDS,
                tpl.id,
                keys[0].id,
                attrs={
                    "provenance": "source_tpl_args_sel",
                    "sel_group_index": block.sel_group_index,
                    "fixed": dim_name in block.fixed_fields,
                },
                status="confirmed",
            )


def _build_tpl_views(schema: TplSchema, header_ref: str) -> dict[str, Any]:
    blocks = [b.to_dict() for b in build_template_blocks(schema)]
    fallback = {d.name: (list(d.value_domain) or ["0"])[0] for d in schema.dims}
    rows: list[dict[str, Any]] = []
    for idx, (gi, dims) in enumerate(expand_legal_with_groups(schema)):
        full = {name: str(dims.get(name, fallback[name])) for name in fallback}
        try:
            key = int(schema.encode_tiling_key(full))
        except (ValueError, KeyError):
            continue
        rows.append(
            {
                "index": idx,
                "tiling_key": key,
                "tiling_key_hex": f"0x{key:016x}",
                "dims": full,
                "sel_group_id": f"ARGS_SEL_{gi}",
                "status": "template_admissible",
            }
        )

    dims_doc = [
        {
            "name": d.name,
            "kind": d.kind,
            "bw": int(d.bw),
            "bit_lo": int(d.bit_lo),
            "bit_hi": int(d.bit_hi),
            "value_domain": [str(v) for v in d.value_domain],
        }
        for d in schema.dims
    ]
    selections = []
    for gi, group in enumerate(schema.selections):
        selections.append(
            {
                "sel_group_index": gi,
                "sels": [
                    {
                        "name": str(s.get("name")),
                        "kind": str(s.get("kind")),
                        "vals": list(s.get("vals") or []),
                    }
                    for s in group
                ],
            }
        )

    return {
        "tiling/tpl_schema.yaml": {
            "schema": "uo-tpl-schema/v1",
            "op_tag": schema.op_tag,
            "header": header_ref,
            "dims": dims_doc,
            "selections": selections,
        },
        "tiling/template_blocks.yaml": {
            "schema": "uo-template-blocks/v1",
            "blocks": blocks,
            "count": len(blocks),
        },
        "tiling/exhaustive_key_space.yaml": {
            "schema": "uo-exhaustive-key-space/v1",
            "legal_key_count": len(rows),
            "legal_key_index": "tiling/legal_key_index.jsonl",
            "template_blocks": blocks,
            "header": header_ref,
            "status": "template_admissible",
        },
        "tiling/legal_key_index.jsonl": {
            "schema": "uo-legal-key-index/v1",
            "count": len(rows),
            "rows": rows,
        },
    }
