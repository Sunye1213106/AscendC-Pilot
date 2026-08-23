from pathlib import Path
import importlib.util
import shutil
import yaml

src = Path(
    r"D:/TEST/pr_workspace/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-9851/"
    r"attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/"
    r"RUN_20260822_160048_c23c9341/actions/bind_init/parts/bind.yaml"
)
dst = Path(__file__).with_name("bind.yaml")
shutil.copy2(src, dst)
spec = importlib.util.spec_from_file_location(
    "g",
    Path(__file__).resolve().parents[1] / "grade_live_bind.py",
)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)
g = mod.grade(src)
passed = sum(1 for v in g.values() if v)
failed = [k for k, v in g.items() if not v]
print(f"{passed}/{len(g)}")
for k, v in g.items():
    mark = "PASS" if v else "FAIL"
    print(f"  {mark} {k}")
if failed:
    print("FAILED:", ", ".join(failed))
doc = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
print("---key mapping---")
for name in [
    "D",
    "D_V",
    "N1",
    "prefix",
    "inner_drop",
    "is_deter",
    "eod",
    "Dtype",
    "seqlens_list_q",
    "seqlens_list_kv",
    "cu_seqlens_q",
    "Drop_Out_Possibility",
    "is_sink",
    "rope",
    "same_as_input",
    "out_dtype",
]:
    row = (doc.get("mapping") or {}).get(name) or {}
    dom = (doc.get("domains") or {}).get(name) or {}
    print(
        name,
        "role=",
        row.get("role"),
        "uo=",
        row.get("uo_id"),
        "op=",
        dom.get("operator"),
        "cmp=",
        dom.get("compare"),
    )
