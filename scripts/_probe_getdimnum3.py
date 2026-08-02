# -*- coding: utf-8 -*-
"""Map each GETDIMNUM field back to source tensors + domain evidence."""
from __future__ import annotations

import json
import pickle
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "engines" / "common"))

d = json.loads((ROOT / ".probe_cache" / "fag_derive.json").read_text(encoding="utf-8"))
fields = {f["name"]: f for f in d["host_derivation"]["fields"]}
targets = [
    "SplitAxis",
    "IsPse",
    "IsAttenMask",
    "DTemplateNum",
    "IsBn2MultiBlk",
    "IsDNoEqual",
    "IsRope",
    "IsNzOut",
    "IsTndSwizzle",
]

# Walk value_expr for GETDIMNUM occurrences with nearby OPT vars
def walk(node, path="$"):
    if isinstance(node, dict):
        if node.get("var") == "VAR_SHAPE_GETDIMNUM":
            yield path, node
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{path}[{i}]")


def nearby_context(expr_str: str, window=400):
    hits = []
    for m in re.finditer("VAR_SHAPE_GETDIMNUM", expr_str):
        lo = max(0, m.start() - window)
        hi = min(len(expr_str), m.end() + window)
        hits.append(expr_str[lo:hi])
    return hits


print("======== PER-FIELD SOURCE EVIDENCE ========")
for name in targets:
    f = fields[name]
    print(f"\n### {name}")
    print(" host_expr:", f.get("host_expr"))
    # def sites
    for site in (f.get("def_sites") or [])[:6]:
        print(f" def_site: {site.get('function')}:{site.get('line')} rhs={str(site.get('rhs'))[:80]}")
        for g in site.get("guards") or []:
            if "DimNum" in g or "GetDim" in g or "Shape" in g:
                print("   guard:", g[:160])
    for rec in f.get("implicit_defaults") or []:
        g = rec.get("guard") or ""
        if "DimNum" in g or "GetDim" in g:
            print(f" implicit: {rec.get('function')}:{rec.get('line')} guard={g}")
    # context around GETDIMNUM in value_expr
    ve = json.dumps(f.get("value_expr"), ensure_ascii=False)
    ctxs = nearby_context(ve, 250)
    print(f" GETDIMNUM occurrences in value_expr: {len(ctxs)}")
    # unique nearby OPT / SHAPE tokens
    tokens = set()
    for c in ctxs:
        tokens |= set(re.findall(r"VAR_(?:OPT|SHAPE)_[A-Z0-9_]+", c))
    print(" nearby vars:", sorted(tokens))


# Domain source
print("\n\n======== DOMAIN lo=1 SOURCE ========")
from uo_init.variable_model import VariableModel
import inspect
from uo_init import variable_model as vm

src = inspect.getsource(vm.VariableModel.declare_on_demand)
print(src)

b = pickle.load(open(ROOT / ".probe_cache" / "fag_bundle.pkl", "rb"))
s = b["var_model"].get("VAR_SHAPE_GETDIMNUM")
print("spec:", s.var_id, s.domain, s.identity_merged, s.origin)

# Compare VAR_SHAPE_PSE_SHIFT domain
for vid in ["VAR_SHAPE_PSE_SHIFT", "VAR_SHAPE_ATTEN_MASK", "VAR_SHAPE_QUERY", "VAR_SHAPE_QUERY_D2"]:
    sp = b["var_model"].get(vid)
    if sp:
        print(vid, "lo", sp.domain.lo, "hi", sp.domain.hi, "merged", sp.identity_merged)

# FAG GetDimNum == 0 sites in arch35
print("\n\n======== FAG arch35 GetDimNum == 0 ========")
arch35 = Path(
    r"D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35"
)
pat = re.compile(r"GetDimNum\s*\(\s*\)\s*==\s*0|GetDimNum\s*\(\s*\)\s*!=\s*0")
for p in sorted(arch35.glob("*.cpp")):
    text = p.read_text(encoding="utf-8", errors="replace")
    for i, line in enumerate(text.splitlines(), 1):
        if "GetDimNum" in line:
            print(f"{p.name}:{i}: {line.strip()[:160]}")
