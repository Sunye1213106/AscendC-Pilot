import sys
from uo_init import paths
from uo_init.build_context import BuildContext
from uo_init.host_ir import build_host_ir
DEFAULT_OPERATOR = "attention/flash_attention_score_grad"
FAG = paths.op_dir(relative=DEFAULT_OPERATOR)
CANN = paths.cann_root()
OPS = paths.ops_root()
if FAG is None or CANN is None or OPS is None:
    sys.exit(f"CANN packages or operator sources not available\n{paths.explain()}")
ctx = BuildContext.load(cann_root=str(CANN), ops_root=str(OPS), op_dir=str(FAG))
ir = build_host_ir([FAG/"op_host"/"flash_attention_score_grad_tiling.cpp",
                    FAG/"op_host"/"arch35"/"flash_attention_score_grad_tiling_normal_regbase.cpp",
                    FAG/"op_host"/"arch35"/"flash_attention_score_grad_tiling_common_regbase.cpp"], ctx=ctx)
pb = ir.param_bindings()
lb = ir.locals_by_function()
for fn in ("AbsCeil","Gcd","CeilDivideBy","SliceVector","SupportTrans2BS2N2GD","IsNewDeter","GetSparseType","DoSplit","CalcleDeterParam"):
    s = ir.summaries.get(fn)
    print(f"\n== {fn}: params={s.params if s else None}")
    print("   actuals:", pb.get(fn))
    print("   assigns:", dict(list(s.assigns.items())[:8]) if s else None)
    print("   locals :", dict(list(s.locals.items())[:6]) if s else None)
    print("   returns:", s.returns[:3] if s else None)
callers = [(c.name, k, a) for c in ir.summaries.values() for k, a in c.calls if k in ("AbsCeil","Gcd","CeilDivideBy","SliceVector")]
print("\ncalls into numeric helpers:", callers[:8])
