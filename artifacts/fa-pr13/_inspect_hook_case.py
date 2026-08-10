import os
from pathlib import Path

os.environ["ASCENDC_PROJECT_ROOT"] = (
    "/work/ops-transformer/attention/flash_attention_score_grad"
)
os.environ["UO_OPERATOR"] = "flash_attention_score_grad"
os.environ["UO_ARCH"] = "arch35"

from testcase_agent.closure import workspace as W
from uo_init.store.reader import find_uo_product
from uo_init.tg_projection import legal_key_rows

I = W.replay_inputs()
p = find_uo_product(
    Path(os.environ["ASCENDC_PROJECT_ROOT"]),
    op_name="flash_attention_score_grad",
    architecture="arch35",
)
rows = legal_key_rows(p)
print("D", len(rows))
print("construct_case", I.construct_case)
# sample a few diverse rows
for idx in (0, 100, 1000, len(rows) // 2, len(rows) - 1):
    row = rows[idx]
    t = {str(k): str(v) for k, v in (row.get("dims") or {}).items()}
    cases = list(I.construct_case(t) or [])
    c0 = cases[0] if cases else None
    print("---", idx, "key", row.get("tiling_key"), "n", len(cases))
    if c0 is None:
        continue
    print("type", type(c0).__name__, "module", type(c0).__module__)
    print("repr", repr(c0)[:300])
    for attr in (
        "tiling_key",
        "expected_key",
        "key",
        "knobs",
        "shape",
        "dtype",
        "b",
        "n",
        "s",
        "d",
        "name",
    ):
        if hasattr(c0, attr):
            print(attr, getattr(c0, attr))
    if isinstance(c0, dict):
        print("dict_keys", list(c0.keys())[:20])
