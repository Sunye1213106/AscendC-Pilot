# -*- coding: utf-8 -*-
"""Minimal 4-key CodeMap product for TG/CE runtime-closure tests."""

from __future__ import annotations

import sys
from pathlib import Path


def write_synthetic_uo(
    project_root: Path,
    *,
    op_name: str = "_synthetic_toy",
    architecture: str = "arch0",
) -> Path:
    """Write a CodeMap whose canonical TPL facts rebuild a 4-key D."""
    uo_src = Path(__file__).resolve().parents[2] / "engines" / "understand-operator" / "src"
    if uo_src.is_dir() and str(uo_src) not in sys.path:
        sys.path.insert(0, str(uo_src))

    from uo_init.ir.codemap import CodeMap
    from uo_init.ir.entity import Entity, EntityKind
    from uo_init.store.writer import write_codemap

    cm = CodeMap(op_name=op_name, architecture=architecture)
    cm.add_entity(Entity(id=f"ARCH_{architecture}", kind=EntityKind.ARCH, name=architecture))
    shift = 0
    dims = (("DimA", ["0", "1"]), ("DimB", ["0", "1"]))
    for order, (name, domain) in enumerate(dims):
        bw = 1
        cm.add_entity(
            Entity(
                id=f"TK_{name}",
                kind=EntityKind.TILING_KEY,
                name=name,
                attrs={
                    "source_declared": True,
                    "decl_kind": "UINT",
                    "kind_tpl": "UINT",
                    "bit_width": bw,
                    "bw": bw,
                    "bit_offset": shift,
                    "bit_lo": shift,
                    "bit_hi": shift + bw - 1,
                    "decl_order": order,
                    "allowed_values": list(domain),
                    "value_domain": list(domain),
                    "provenance": "source_tpl_args_decl",
                },
                file=f"op_kernel/{architecture}/{op_name}_template_tiling_key.h",
                status="confirmed",
            )
        )
        shift += bw
    cm.add_entity(
        Entity(
            id="TPL_SEL_0",
            kind=EntityKind.TEMPLATE,
            name="ARGS_SEL_0",
            attrs={
                "tpl_role": "args_sel_group",
                "sel_group_index": 0,
                "fixed_fields": {},
                "field_domains": {name: list(domain) for name, domain in dims},
                "product_count": 4,
                "provenance": "source_tpl_args_sel",
            },
            file=f"op_kernel/{architecture}/{op_name}_template_tiling_key.h",
            status="confirmed",
        )
    )
    product = (
        project_root
        / ".ascendc-pilot"
        / architecture
        / "uo"
        / f"{op_name}.{architecture}.uo"
    )
    write_codemap(cm, product, meta={"fingerprint": "fp-toy"})
    return product
