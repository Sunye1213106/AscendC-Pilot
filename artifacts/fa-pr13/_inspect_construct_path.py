import os
from pathlib import Path

os.environ["ASCENDC_PROJECT_ROOT"] = (
    "/work/ops-transformer/attention/flash_attention_score_grad"
)
os.environ["UO_OPERATOR"] = "flash_attention_score_grad"
os.environ["UO_ARCH"] = "arch35"

from testcase_agent.closure import workspace as W
from testcase_agent.closure import construct as C
from uo_init.store.reader import find_uo_product
from uo_init.tg_projection import legal_key_rows

I = W.replay_inputs()
print("inputs_mod", getattr(I, "__file__", type(I)))
print("has_construct_case", hasattr(I, "construct_case"))
print("has_from_knobs", hasattr(getattr(I, "SEMANTICS", None), "from_knobs"))

p = find_uo_product(
    Path(os.environ["ASCENDC_PROJECT_ROOT"]),
    op_name="flash_attention_score_grad",
    architecture="arch35",
)
row = legal_key_rows(p)[0]
t = {str(k): str(v) for k, v in (row.get("dims") or {}).items()}
coded = C._codemap_build(t, seed=0)
hints = C._hints_build(t, seed=0)
hooked = list(I.construct_case(t) or []) if hasattr(I, "construct_case") else None
print("key", row.get("tiling_key"))
print(
    "hooked_n",
    None if hooked is None else len(hooked),
    "type",
    type(hooked[0]).__name__ if hooked else None,
)
print("codemap_n", len(coded), "traces", len(C.last_traces() or []))
if C.last_traces():
    print("trace0", C.last_traces()[0])
print("hints_n", len(hints))
if hooked:
    c0 = hooked[0]
    print("case_attrs", [a for a in dir(c0) if not a.startswith("_")][:40])
    for attr in ("tiling_key", "key", "knobs", "shape", "dtype", "inputs", "case"):
        if hasattr(c0, attr):
            print(attr, getattr(c0, attr))
    print("repr", repr(c0)[:500])
