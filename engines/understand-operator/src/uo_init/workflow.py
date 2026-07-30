# -*- coding: utf-8 -*-
"""Single-shot closure report for one operator (diagnostic entrypoint).

The Pilot workflow drives the phased pipeline in `pilot_engines`; this module
stays as the one-command way to see where an operator stands without going
through the harness.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from uo_init.anchors import build_anchors_yaml
from uo_init.branch_inventory import inventory_clang
from uo_init.build_context import BuildContext
from uo_init.harness import count_legal_instances, pairwise_coverage, sample_instances
from uo_init.host_ir import build_host_ir
from uo_init.lineage import Lineage, build_lineages, run_gates
from uo_init.op_spec import OpSpec, discover
from uo_init.registry_capable import build_arch35_competition
from uo_init.source_resolver import SourceResolver
from uo_init.tpl_dsl import parse_file


def run_operator_report(
    *,
    op_dir: str,
    cann_root: str | None = None,
    ops_root: str | None = None,
    arch_dir: str | None = None,
    spec: OpSpec | None = None,
) -> dict[str, Any]:
    spec = spec or discover(op_dir, arch_dir=arch_dir)
    ctx = BuildContext.load(
        cann_root=cann_root,
        ops_root=ops_root,
        op_dir=str(spec.op_dir),
        arch_dir=spec.arch_dir,
    )

    anchors = build_anchors_yaml(
        spec.opdef,
        spec.host_root,
        spec.kernel_entry,
        op_name=spec.op_name,
        entry_name=spec.op_snake,
    )
    schema = parse_file(spec.tiling_key_header)
    comp = build_arch35_competition(spec.host_root, op_name=spec.op_name)

    targets = [p for p in spec.host_targets if p.exists()]
    ir = build_host_ir(list(targets), ctx=ctx)
    resolver = SourceResolver(host_ir=ir)
    func_locals = ir.locals_by_function()
    func_params = ir.params_by_function()
    param_actuals = ir.param_bindings()

    lineages: list[Lineage] = []
    per_file: dict[str, dict[str, Any]] = {}
    for t in targets:
        inv = inventory_clang(t, ctx)
        lins = build_lineages(
            inv,
            resolver,
            func_locals=func_locals,
            func_params=func_params,
            param_actuals=param_actuals,
        )
        sub = run_gates(lineages=lins, template_ok=0, schema_ok=True)
        per_file[t.name] = {
            "nodes": len(inv.nodes),
            "universes": {
                u: len(inv.by_universe(u))
                for u in ("PRODUCTION", "LIBRARY_INTERNAL", "VALIDATION_ONLY")
            },
            "closed": sub.branch_closed,
            "open": sub.branch_open,
            "closure": sub.deterministic_closure,
            "roots": sub.root_histogram,
            "reasons": sub.reason_histogram,
        }
        lineages.extend(lins)

    # Registry selection is closed only when every competing predicate resolves.
    registry_roots = sorted({r for p in comp.preds.values() for r in p.roots})
    for name, pred in comp.preds.items():
        lineages.append(
            Lineage(
                node_id=f"registry:{name}",
                root_kind=pred.roots[0] if pred.roots else "UNKNOWN",
                expression=f"IsCapable({name})",
                roots=pred.roots,
                reason_code=None if pred.roots else "NO_ROOTS_RESOLVED",
                file=pred.file,
                line=pred.line,
            )
        )

    gates = run_gates(lineages=lineages, template_ok=len(schema.selections), schema_ok=True)
    sample = sample_instances(schema, strategy="pairwise")
    return {
        "op_spec": spec.to_dict(),
        "tpl_dims": len(schema.dims),
        "tpl_total_bits": schema.total_bits,
        "tpl_sel_groups": len(schema.selections),
        "tpl_legal_instances": count_legal_instances(schema),
        "harness_sample": {
            "strategy": "pairwise",
            "instances": len(sample),
            "coverage": pairwise_coverage(schema, sample),
        },
        "registry_order": [
            {"priority": r["priority"], "class": r["class"]} for r in comp.ordered
        ],
        "registry_roots": registry_roots,
        "anchors_inputs": len(anchors["opdef"]["inputs"]),
        "anchors_outputs": len(anchors["opdef"]["outputs"]),
        "anchors_attrs": len(anchors["opdef"]["attrs"]),
        "host_ir": {
            "backend": ir.backend,
            "writes": len(ir.writes),
            "functions": len(ir.summaries),
        },
        "denominator_note": "BranchInventory PRODUCTION universe, clang AST backend",
        "per_file": per_file,
        "deterministic_closure": gates.deterministic_closure,
        "open_reasons": gates.reasons,
        "open_reason_histogram": gates.reason_histogram,
        "root_histogram": gates.root_histogram,
        "gates": {
            "branch_closed": gates.branch_closed,
            "branch_open": gates.branch_open,
            "branch_total": gates.total,
            "template_closed": gates.template_closed,
            "schema_closed": gates.schema_closed,
        },
        "build_context": {"cann_root": ctx.cann_root, "compat_root": ctx.compat_root},
    }


def main(argv: list[str] | None = None) -> None:
    import argparse

    ap = argparse.ArgumentParser(prog="uo-init")
    ap.add_argument("--op-dir", required=True)
    ap.add_argument("--cann-root", default=None)
    ap.add_argument("--ops-root", default=None)
    ap.add_argument("--arch-dir", default=None)
    ap.add_argument("-o", "--output", default=None)
    args = ap.parse_args(argv)
    rep = run_operator_report(
        op_dir=args.op_dir,
        cann_root=args.cann_root,
        ops_root=args.ops_root,
        arch_dir=args.arch_dir,
    )
    text = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
