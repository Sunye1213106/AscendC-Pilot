# -*- coding: utf-8 -*-
"""Phase-level timing of extract_host_bundle (read-only w.r.t. src/tests)."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "engines" / "understand-operator" / "src"
sys.path.insert(0, str(SRC))

from uo_init import paths  # noqa: E402

DEFAULT_OPERATOR = os.environ.get("UO_OPERATOR", "attention/flash_attention_score_grad")
ARCH = os.environ.get("UO_ARCH", "arch35")


def tick(label: str, t0: float, acc: list) -> float:
    now = time.perf_counter()
    sec = now - t0
    acc.append((label, sec))
    print(f"  {sec:7.1f}s  {label}", flush=True)
    return now


def main() -> int:
    op = paths.op_dir(relative=DEFAULT_OPERATOR)
    cann = paths.cann_root()
    if op is None or cann is None:
        raise SystemExit(paths.explain())

    from uo_init.assemble_kb import extract_host_bundle
    from uo_init.branch_inventory import inventory_clang
    from uo_init.build_context import BuildContext
    from uo_init.controllability import ControllabilityBuilder, measure
    from uo_init.gaps import build_gap_report
    from uo_init.host_ir import build_host_ir
    from uo_init.op_spec import discover
    from uo_init.platform_ini import load_platform_profile
    from uo_init.registry_capable import parse_enums
    from uo_init.source_resolver import SourceResolver
    from uo_init.tpl_bind import bind_from_spec, merge_literal_encode_alts
    from uo_init.tpl_dsl import parse_file
    from uo_init.variable_model import apply_platform_profile, build_variable_model

    acc: list[tuple[str, float]] = []
    t = time.perf_counter()

    spec = discover(op, arch_dir=ARCH)
    t = tick("discover", t, acc)
    ctx = BuildContext.load(
        cann_root=str(cann),
        ops_root=str(op.parent.parent),
        op_dir=str(spec.op_dir),
        arch_dir=spec.arch_dir,
    )
    t = tick("BuildContext.load", t, acc)
    targets = [p for p in spec.host_targets if p.exists()]
    print(f"  (targets={len(targets)})", flush=True)

    ir = build_host_ir(list(targets), ctx=ctx, op_needle=spec.op_needle)
    t = tick("build_host_ir (all TUs)", t, acc)
    print(f"    writes={len(ir.writes)} summaries={len(ir.summaries)}", flush=True)

    resolver = SourceResolver(host_ir=ir)
    t = tick("SourceResolver", t, acc)

    schema = parse_file(spec.tiling_key_header) if spec.tiling_key_header else None
    t = tick("parse tpl schema", t, acc)

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
    t = tick("read headers + enums", t, acc)

    model = build_variable_model(
        opdef_path=spec.opdef,
        tpl_schema=schema,
        tpl_header=str(spec.tiling_key_header or ""),
        enums=enums,
        header_texts=list(header_texts) + cpp_texts,
    )
    t = tick("build_variable_model", t, acc)
    resolver.adopt(model)
    t = tick("resolver.adopt", t, acc)

    profile = load_platform_profile(str(cann), arch_dir=spec.arch_dir or ARCH)
    apply_platform_profile(model, profile)
    t = tick("platform profile", t, acc)

    nodes: list = []
    for target in targets:
        nodes.extend(
            inventory_clang(target, ctx, op_needle=spec.op_needle).production()
        )
    t = tick("inventory_clang sequential (4 TUs)", t, acc)
    print(f"    production nodes={len(nodes)}", flush=True)

    builder = ControllabilityBuilder(
        resolver, model, side="host", op_root=str(spec.op_dir)
    )
    analyses, records = builder.build(nodes)
    t = tick("ControllabilityBuilder.build", t, acc)
    print(f"    analyses={len(analyses)} records={len(records)}", flush=True)

    measure(analyses, records)
    build_gap_report(analyses)
    t = tick("measure + gap", t, acc)

    binding = bind_from_spec(spec, targets)
    binding = merge_literal_encode_alts(binding, ir)
    t = tick("tpl_bind", t, acc)

    total = sum(s for _, s in acc)
    print("\n=== summary ===")
    for label, sec in acc:
        pct = 100.0 * sec / total if total else 0
        print(f"  {sec:7.1f}s ({pct:5.1f}%)  {label}")
    print(f"  {total:7.1f}s  TOTAL")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
