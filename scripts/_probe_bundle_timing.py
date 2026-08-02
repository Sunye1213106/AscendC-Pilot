# -*- coding: utf-8 -*-
"""Temporary probe: where does extract_host_bundle spend time?

Read-only w.r.t. src/ and tests/. Does NOT write fag_bundle.pkl.

    python scripts/_probe_bundle_timing.py --info
    python scripts/_probe_bundle_timing.py --tu all
    python scripts/_probe_bundle_timing.py --tu 0 --walk-modes host_ir,inventory
    python scripts/_probe_bundle_timing.py --fast-phases
"""
from __future__ import annotations

import argparse
import os
import pickle
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "engines" / "understand-operator" / "src"
sys.path.insert(0, str(SRC))

from uo_init import paths  # noqa: E402

DEFAULT_OPERATOR = os.environ.get("UO_OPERATOR", "attention/flash_attention_score_grad")
ARCH = os.environ.get("UO_ARCH", "arch35")


def _setup():
    op = paths.op_dir(relative=DEFAULT_OPERATOR)
    cann = paths.cann_root()
    if op is None or cann is None:
        raise SystemExit(paths.explain())
    from uo_init.build_context import BuildContext
    from uo_init.op_spec import discover

    spec = discover(op, arch_dir=ARCH)
    ctx = BuildContext.load(
        cann_root=str(cann),
        ops_root=str(op.parent.parent),
        op_dir=str(spec.op_dir),
        arch_dir=spec.arch_dir,
    )
    targets = [p for p in spec.host_targets if p.exists()]
    return op, cann, spec, ctx, targets


def _tu_bytes(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def cmd_info(spec, ctx, targets, cann) -> None:
    args = ctx.host_args()
    print("=== bundle build context ===")
    print(f"  operator     : {spec.op_dir}")
    print(f"  arch_dir     : {spec.arch_dir}")
    print(f"  cann_root    : {cann}")
    print(f"  slim marker  : {paths.slim_status(Path(cann)) or 'n/a (full tree)'}")
    print(f"  host TUs     : {len(targets)}")
    print(f"  -I paths     : {len([a for a in args if a == '-I'])}")
    print(f"  -D defines   : {len([a for a in args if a.startswith('-D')])}")
    print(f"  total args   : {len(args)}")
    print()
    print(f"{'idx':>3}  {'bytes':>8}  path")
    for i, p in enumerate(targets):
        rel = p.relative_to(spec.op_dir) if p.is_relative_to(spec.op_dir) else p
        print(f"{i:>3}  {_tu_bytes(p):>8}  {rel}")


def _parse_only(path: Path, ctx):
    from clang import cindex

    t0 = time.perf_counter()
    idx = cindex.Index.create()
    tu = idx.parse(
        str(path),
        args=ctx.host_args(),
        options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
    )
    t_parse = time.perf_counter() - t0
    diags = sum(1 for d in tu.diagnostics if d.severity >= 3)
    return tu, t_parse, diags


def _walk_parsed(tu, path: Path, ctx, *, collect_writes: bool, op_needle: str):
    from uo_init.clang_walk import _Walker, _framework_headers, _norm
    from clang import cindex

    t0 = time.perf_counter()
    op_root = ctx.op_dir or ""
    w = _Walker(
        op_needle,
        op_root=op_root,
        collect_writes=collect_writes,
        side="host",
        frame_files=frozenset(_framework_headers(tu.cursor, op_needle, op_root)),
    )
    for child in tu.cursor.get_children():
        w.walk(child, [], "")
    t_walk = time.perf_counter() - t0
    return w, t_walk


def _ast_stats(tu, op_needle: str) -> dict:
    from clang import cindex

    total = 0
    in_op = 0
    files: Counter[str] = Counter()
    for n in tu.cursor.walk_preorder():
        total += 1
        f = n.location.file
        if f is not None:
            fn = f.name.replace("\\", "/")
            files[fn] += 1
            if op_needle in fn:
                in_op += 1
    top_files = files.most_common(8)
    return {
        "ast_nodes": total,
        "ast_nodes_in_op": in_op,
        "unique_files": len(files),
        "top_files": top_files,
    }


def cmd_tu(targets, ctx, spec, indices, modes) -> None:
    op_needle = spec.op_needle
    print(f"=== per-TU timing (modes={modes}) ===")
    print(f"{'idx':>3}  {'parse':>7}  {'walk':>7}  {'mode':<10}  {'ast':>8}  {'in_op':>7}  {'files':>5}  path")
    totals = Counter()
    for i in indices:
        path = targets[i]
        rel = path.name
        for mode in modes:
            collect = mode == "host_ir"
            tu, t_parse, diags = _parse_only(path, ctx)
            w, t_walk = _walk_parsed(
                tu, path, ctx, collect_writes=collect, op_needle=op_needle
            )
            stats = _ast_stats(tu, op_needle)
            totals["parse"] += t_parse
            totals["walk"] += t_walk
            totals["modes"] += 1
            print(
                f"{i:>3}  {t_parse:>7.1f}s  {t_walk:>7.1f}s  {mode:<10}  "
                f"{stats['ast_nodes']:>8}  {stats['ast_nodes_in_op']:>7}  "
                f"{stats['unique_files']:>5}  {rel}  (err={diags}, "
                f"ctrl={len(w.controls)}, writes={len(w.writes)})"
            )
            if stats["top_files"]:
                print("       top AST files:")
                for fn, cnt in stats["top_files"][:5]:
                    tag = "OP" if op_needle in fn else "CANN"
                    print(f"         {cnt:>7}  [{tag}]  {Path(fn).name}")

    n_tus = len(targets)
    per_mode_parse = totals["parse"] / max(1, totals["modes"])
    per_mode_walk = totals["walk"] / max(1, totals["modes"])
    # Full bundle does host_ir + inventory for each TU (2 modes).
    extrap_parse = per_mode_parse * n_tus * 2
    extrap_walk = per_mode_walk * n_tus * 2
    print()
    print("=== extrapolation (if all TUs × 2 passes match sampled) ===")
    print(f"  measured parse sum : {totals['parse']:.1f}s over {totals['modes']} runs")
    print(f"  measured walk sum  : {totals['walk']:.1f}s")
    print(f"  -> all {n_tus} TUs × 2 passes: parse ~{extrap_parse:.0f}s, walk ~{extrap_walk:.0f}s")
    print(f"  -> combined clang  ~{extrap_parse + extrap_walk:.0f}s (vs reported bundle ~367s)")


def cmd_fast_phases(spec, ctx, targets, cann) -> None:
    """Time non-clang phases using one inventory result if cached, else minimal."""
    from uo_init.host_ir import build_host_ir
    from uo_init.source_resolver import SourceResolver
    from uo_init.tpl_dsl import parse_file
    from uo_init.registry_capable import parse_enums
    from uo_init.variable_model import apply_platform_profile, build_variable_model
    from uo_init.platform_ini import load_platform_profile
    from uo_init.tpl_bind import bind_from_spec, merge_literal_encode_alts
    from uo_init.controllability import ControllabilityBuilder, measure
    from uo_init.gaps import build_gap_report

    phases: list[tuple[str, float]] = []

    t0 = time.perf_counter()
    schema = parse_file(spec.tiling_key_header) if spec.tiling_key_header else None
    phases.append(("parse tpl schema (text)", time.perf_counter() - t0))

    t0 = time.perf_counter()
    header_paths: list[Path] = []
    for h in list((spec.host_root / (spec.arch_dir or ".")).glob("*.h")) + list(
        spec.host_root.glob("*.h")
    ):
        header_paths.append(h)
    kernel_arch = spec.op_dir / "op_kernel" / (spec.arch_dir or ".")
    if kernel_arch.is_dir():
        header_paths.extend(kernel_arch.glob("*.h"))
    ops = Path(ctx.ops_root) if ctx.ops_root else None
    if ops and ops.is_dir():
        common_host = ops / "common" / "include" / "op_host"
        if common_host.is_dir():
            header_paths.extend(common_host.glob("*.h"))
    cpp_texts: list[str] = []
    for cpp in list((spec.host_root / (spec.arch_dir or ".")).glob("*.cpp")) + list(
        spec.host_root.glob("*.cpp")
    ):
        if cpp.is_file():
            cpp_texts.append(cpp.read_text(encoding="utf-8", errors="replace"))
    seen: set[Path] = set()
    enums: dict = {}
    header_texts: list[str] = []
    for h in header_paths:
        key = h.resolve()
        if key in seen or not h.is_file():
            continue
        seen.add(key)
        text = h.read_text(encoding="utf-8", errors="replace")
        header_texts.append(text)
        enums.update(parse_enums(text))
    phases.append(("read headers + parse_enums", time.perf_counter() - t0))

    t0 = time.perf_counter()
    model = build_variable_model(
        opdef_path=spec.opdef,
        tpl_schema=schema,
        tpl_header=str(spec.tiling_key_header or ""),
        enums=enums,
        header_texts=list(header_texts) + cpp_texts,
    )
    phases.append(("build_variable_model", time.perf_counter() - t0))

    t0 = time.perf_counter()
    profile = load_platform_profile(cann, arch_dir=spec.arch_dir or ARCH)
    apply_platform_profile(model, profile)
    phases.append(("platform profile", time.perf_counter() - t0))

    bundle_path = ROOT / ".probe_cache" / "fag_bundle.pkl"
    nodes = None
    ir = None
    if bundle_path.is_file():
        with bundle_path.open("rb") as fh:
            cached = pickle.load(fh)
        ir = cached.get("host_ir")
        resolver = cached.get("resolver")
        if ir is not None and resolver is not None:
            from uo_init.branch_inventory import inventory_clang

            # Re-inventory one TU only to get node count shape without full rebuild
            t_inv = time.perf_counter()
            sample = inventory_clang(
                targets[0], ctx, op_needle=spec.op_needle
            ).production()
            phases.append(("inventory_clang sample TU", time.perf_counter() - t_inv))
            nodes = sample

    if nodes is not None and ir is not None:
        resolver = SourceResolver(host_ir=ir)
        resolver.adopt(model)
        builder = ControllabilityBuilder(
            resolver, model, side="host", op_root=str(spec.op_dir)
        )
        t0 = time.perf_counter()
        analyses, records = builder.build(nodes)
        phases.append(("ControllabilityBuilder.build (cached nodes)", time.perf_counter() - t0))
        t0 = time.perf_counter()
        measure(analyses, records)
        build_gap_report(analyses)
        phases.append(("measure + gap", time.perf_counter() - t0))

        t0 = time.perf_counter()
        binding = bind_from_spec(spec, targets)
        binding = merge_literal_encode_alts(binding, ir)
        phases.append(("tpl_bind", time.perf_counter() - t0))

    print("=== fast / post-clang phases ===")
    for name, sec in phases:
        print(f"  {sec:>6.2f}s  {name}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--info", action="store_true")
    ap.add_argument("--tu", default="", help="TU index, 'all', or comma list")
    ap.add_argument(
        "--walk-modes",
        default="host_ir,inventory",
        help="host_ir (=collect_writes) and/or inventory (=controls only)",
    )
    ap.add_argument("--fast-phases", action="store_true")
    args = ap.parse_args()

    op, cann, spec, ctx, targets = _setup()
    if not targets:
        raise SystemExit("no host targets")

    if args.info or (not args.tu and not args.fast_phases):
        cmd_info(spec, ctx, targets, cann)

    if args.tu:
        modes = [m.strip() for m in args.walk_modes.split(",") if m.strip()]
        if args.tu.strip().lower() == "all":
            indices = list(range(len(targets)))
        else:
            indices = [int(x.strip()) for x in args.tu.split(",")]
        cmd_tu(targets, ctx, spec, indices, modes)

    if args.fast_phases:
        cmd_fast_phases(spec, ctx, targets, str(cann))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
