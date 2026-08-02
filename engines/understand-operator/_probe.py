# -*- coding: utf-8 -*-
import sys
from pathlib import Path

from uo_init import paths
from uo_init.build_context import BuildContext
from uo_init.host_ir import build_host_ir

DEFAULT_OPERATOR = "attention/flash_attention_score_grad"

FAG = paths.op_dir(relative=DEFAULT_OPERATOR)
CANN = paths.cann_root()
OPS = paths.ops_root()
if FAG is None or CANN is None or OPS is None:
    sys.exit(f"CANN packages or operator sources not available\n{paths.explain()}")

ctx = BuildContext.load(
    cann_root=str(CANN),
    ops_root=str(OPS),
    op_dir=str(FAG),
)
targets = [
    FAG / "op_host" / "flash_attention_score_grad_tiling.cpp",
    FAG / "op_host" / "arch35" / "flash_attention_score_grad_tiling_normal_regbase.cpp",
    FAG / "op_host" / "arch35" / "flash_attention_score_grad_tiling_common_regbase.cpp",
]
ir = build_host_ir(list(targets), ctx=ctx)

print("### summary keys sample")
keys = sorted(ir.summaries)
print(len(keys), keys[:25])
for probe in ("IsEmptyOutput", "DoBn2s2Sparse", "SupportTrans2BS2N2GD", "AbsCeil", "Gcd"):
    hits = [k for k in keys if k.endswith(probe)]
    s = ir.summaries.get(probe)
    print(f"  {probe}: keys={hits} params={s.params if s else None} returns={(s.returns[:2] if s else None)}")

print("\n### writes to .queryType")
for w in ir.writes:
    if w.path.endswith(".queryType"):
        print(f"  {Path(w.file).name}:{w.line} fn={w.function} {w.path} = {w.rhs[:100]}")

print("\n### param bindings")
pb = ir.param_bindings()
print("callees with bindings:", len(pb))
for k in list(pb)[:10]:
    print("  ", k, {p: v[:2] for p, v in pb[k].items()})

print("\n### call sites recorded")
tot = sum(len(s.calls) for s in ir.summaries.values())
print("total calls:", tot)
for s in list(ir.summaries.values())[:3]:
    print("  ", s.name, s.calls[:3])

print("\n### bare-name local assignments present as writes?")
bare = [w for w in ir.writes if "." not in w.path][:10]
print(len(bare), [(w.path, w.rhs[:40]) for w in bare])
