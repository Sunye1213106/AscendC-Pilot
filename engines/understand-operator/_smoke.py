# -*- coding: utf-8 -*-
"""Temporary end-to-end smoke check; removed in the cleanup step."""
from __future__ import annotations

import sys
from pathlib import Path

from uo_init import paths
from uo_init.branch_inventory import inventory_clang
from uo_init.build_context import BuildContext
from uo_init.controllability import ControllabilityBuilder, measure
from uo_init.gaps import build_gap_report
from uo_init.host_ir import build_host_ir
from uo_init.op_spec import discover
from uo_init.registry_capable import parse_enums
from uo_init.source_resolver import SourceResolver
from uo_init.tpl_dsl import parse_file
from uo_init.variable_model import build_variable_model, infer_bounds_from_guards

DEFAULT_OPERATOR = "attention/flash_attention_score_grad"

FAG = paths.op_dir(relative=DEFAULT_OPERATOR)
CANN = paths.cann_root()
OPS = paths.ops_root()


def main() -> None:
    if FAG is None or CANN is None or OPS is None:
        print(
            f"CANN packages or operator sources not available\n{paths.explain()}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    spec = discover(FAG)
    ctx = BuildContext.load(
        cann_root=str(CANN),
        ops_root=str(OPS),
        op_dir=str(spec.op_dir),
        arch_dir=spec.arch_dir,
    )
    targets = [p for p in spec.host_targets if p.exists()]
    print("targets:", [p.name for p in targets])

    ir = build_host_ir(list(targets), ctx=ctx)
    print("host ir:", ir.backend, len(ir.writes), "writes", len(ir.summaries), "funcs")

    enums: dict = {}
    for h in list((spec.host_root / spec.arch_dir).glob("*.h")) + list(
        spec.host_root.glob("*.h")
    ):
        enums.update(parse_enums(h.read_text(encoding="utf-8", errors="replace")))
    schema = parse_file(spec.tiling_key_header)
    model = build_variable_model(
        opdef_path=spec.opdef,
        tpl_schema=schema,
        tpl_header=str(spec.tiling_key_header),
        enums=enums,
    )
    print("variables:", len(model.variables), "enums:", len(enums))

    resolver = SourceResolver(host_ir=ir)
    builder = ControllabilityBuilder(
        resolver, model, side="host", op_root=str(spec.op_dir)
    )
    nodes = []
    for t in targets:
        inv = inventory_clang(t, ctx, op_needle=spec.op_needle)
        nodes.extend(inv.production())
    print("production nodes:", len(nodes))

    bounds = infer_bounds_from_guards(model, nodes, resolver)
    print("bounds inferred from validation branches:", len(bounds), bounds[:5])

    analyses, records = builder.build(nodes)
    m = measure(analyses, records)
    d = m.to_dict()
    for k in (
        "total_nodes",
        "closed_nodes",
        "partial_nodes",
        "open_nodes",
        "controllable_nodes",
        "source_closure",
        "input_controllability",
        "predicate_normalization",
    ):
        print(f"  {k}: {d[k]}")
    print("  reasons:", d["reason_histogram"])

    gap = build_gap_report(analyses)
    print("open nodes:", gap.open_node_count, "blockers:", gap.blocker_count,
          "nodes/blocker:", gap.compression)
    for b in gap.blockers[:12]:
        print(f"   {b.reason_code:28s} x{len(b.affected_nodes):4d}  {b.text[:60]}")


if __name__ == "__main__":
    main()
