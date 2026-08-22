# Grade d4-bind-accuracy Composer outputs.

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "iteration-1" / "d4-bind-accuracy"


def _field(text: str, col: str, key: str) -> str:
    m = re.search(rf"{re.escape(col)}:\s*\{{[^}}]*\b{key}:\s*([^,}}]+)", text)
    if not m:
        return ""
    return m.group(1).strip().strip("'\"")


def grade(text: str) -> dict[str, bool]:
    d_uo = _field(text, "D", "uo_id").lower()
    inner_role = _field(text, "inner_drop", "role").lower()
    inner_uo = _field(text, "inner_drop", "uo_id")
    inner_dom_op = _field(text, "inner_drop", "operator")
    eod_role = _field(text, "eod", "role").lower()
    eod_uo = _field(text, "eod", "uo_id")
    seq_op = _field(text, "seqlens_list_q", "operator")
    seq_uo = _field(text, "seqlens_list_q", "uo_id")
    prefix_uo = _field(text, "prefix", "uo_id")
    d_op = _field(text, "D", "operator")
    verify = ""
    vm = re.search(r"verify:\s*(.+)", text)
    if vm:
        verify = vm.group(1).lower()
    plan = ""
    pm = re.search(r"plan_tools:([\s\S]*?)\nmapping:", text)
    if pm:
        plan = pm.group(1).lower()
    return {
        "D_binds_head_dim": d_uo in {"d", "d1"} and "scale" not in d_uo,
        "inner_drop_feature_header": inner_role == "feature" and "drop" in inner_uo.lower(),
        "eod_feature": eod_role == "feature",
        "seqlens_not_istnd": "istnd" not in seq_op.lower() and "istnd" not in seq_uo.lower(),
        "prefix_uo_filled": bool(prefix_uo) and prefix_uo not in {"''", '""', "~"},
        "eod_not_borrow_neighbor": eod_uo.lower() not in {"b", "actualseqqlen", "s1", "d"},
        "inner_drop_domain_empty": inner_role != "feature" or inner_dom_op in {"", "''", '""', "~"},
        "verify_inspect_yaml": "inspect yaml" in verify or "inspect yaml" in plan,
        "plan_header_first": "tiling" in plan or "头文件" in plan or "header" in plan,
        "plan_not_eight_queries": not re.search(r"8\s*(identifier|标识符)", plan),
        "D_operator_not_scale": "scale" not in d_op.lower(),
    }


def main() -> None:
    rows = []
    for cfg in ("old_skill", "with_skill"):
        for rep in ("r1.md", "r2.md"):
            path = ROOT / cfg / rep
            if not path.is_file():
                rows.append((cfg, rep, None, f"missing {path}"))
                continue
            g = grade(path.read_text(encoding="utf-8"))
            rows.append((cfg, rep, g, None))
    for cfg, rep, g, err in rows:
        print(f"== {cfg}/{rep} ==")
        if err:
            print(" ", err)
            continue
        passed = sum(1 for v in g.values() if v)
        print(f"  {passed}/{len(g)}")
        for k, v in g.items():
            print(f"  {'PASS' if v else 'FAIL'} {k}")


if __name__ == "__main__":
    main()
