# Grade iteration-2 bind-init Composer outputs. Expected keys stay here, never in the skill.

from __future__ import annotations

import re
from pathlib import Path

import yaml

WS = Path(__file__).resolve().parent
IT2 = WS / "iteration-2"
SKILL = WS.parent / "bind-init"
LEAK_PATS = (
    "keep_prob",
    "Drop_Out",
    "IsTnd",
    "actualSeqQlen",
    "scaleValue",
    "npu_fusion_attention",
    "flash_attention",
    "seqlens_list",
    "inner_drop",
    "dropMaskOuter",
    "drop_mask",
    "`query`",
    "`key`",
    "`value`",
    "`dy`",
)


def _doc(text: str) -> dict:
    body = text
    m = re.search(r"```(?:yaml)?\s*([\s\S]*?)```", text)
    if m:
        body = m.group(1)
    try:
        data = yaml.safe_load(body) or {}
        return data if isinstance(data, dict) else {}
    except yaml.YAMLError:
        return {}


def _field(text: str, col: str, key: str) -> str:
    data = _doc(text)
    for section in ("mapping", "domains"):
        row = (data.get(section) or {}).get(col) or {}
        if isinstance(row, dict) and key in row:
            val = row.get(key)
            if val is None:
                return ""
            return str(val).strip().strip("'\"")
    return _field_lines(text, col, key)


def _field_lines(text: str, col: str, key: str) -> str:
    lines = text.replace("\r\n", "\n").split("\n")
    in_col = False
    for line in lines:
        if re.match(rf"^[ \t]*{re.escape(col)}:\s*$", line):
            in_col = True
            continue
        if in_col:
            if re.match(r"^[ \t]{0,2}\S", line) and not line.strip().startswith("#"):
                in_col = False
                continue
            m = re.match(rf"^[ \t]+{re.escape(key)}:\s*(.*)$", line)
            if m:
                return m.group(1).strip().strip("'\"")
    return ""


def _empty(val: str) -> bool:
    return val.lower() in {"", "''", '""', "~", "null", "none"}


def leak_check() -> dict[str, bool]:
    blob = ""
    for rel in (
        "references/columns.md",
        "references/column-binding-edge-cases.md",
        "references/review.md",
        "references/harness.md",
        "SKILL.md",
    ):
        path = SKILL / rel
        if path.is_file():
            blob += "\n" + path.read_text(encoding="utf-8")
    return {f"no_leak:{pat}": pat not in blob for pat in LEAK_PATS}


def grade_d4(text: str) -> dict[str, bool]:
    d_uo = _field(text, "D", "uo_id").lower()
    d_op = _field(text, "D", "operator")
    inner_role = _field(text, "inner_drop", "role").lower()
    inner_uo = _field(text, "inner_drop", "uo_id")
    inner_op = _field(text, "inner_drop", "operator")
    eod_role = _field(text, "eod", "role").lower()
    eod_uo = _field(text, "eod", "uo_id")
    seq_op = _field(text, "seqlens_list_q", "operator")
    seq_uo = _field(text, "seqlens_list_q", "uo_id")
    prefix_uo = _field(text, "prefix", "uo_id")
    verify = ""
    vm = re.search(r"verify:\s*(.+)", text)
    if vm:
        verify = vm.group(1).lower()
    plan = ""
    tools = _doc(text).get("plan_tools") or []
    if isinstance(tools, list):
        plan = "\n".join(str(x) for x in tools).lower()
    else:
        pm = re.search(r"plan_tools:([\s\S]*?)\nmapping:", text)
        if pm:
            plan = pm.group(1).lower()
    return {
        "D_binds_head_dim": d_uo in {"d", "d1"} and "scale" not in d_uo,
        "D_operator_not_scale": "scale" not in d_op.lower(),
        "prefix_uo_filled": bool(prefix_uo) and not _empty(prefix_uo),
        "inner_drop_feature_header": inner_role == "feature" and "drop" in inner_uo.lower(),
        "inner_drop_domain_empty": inner_role != "feature" or _empty(inner_op),
        "eod_feature": eod_role == "feature",
        "eod_not_borrow_neighbor": _empty(eod_uo)
        or eod_uo.lower() not in {"b", "actualseqqlen", "s1", "d"},
        "seqlens_not_istnd": "istnd" not in seq_op.lower() and "istnd" not in seq_uo.lower(),
        "seqlens_binds_proto": "seq" in seq_uo.lower() and "istnd" not in seq_uo.lower(),
        "verify_inspect_yaml": "inspect yaml" in verify or "inspect yaml" in plan,
        "plan_header_first": "tiling" in plan or "头文件" in plan or "header" in plan,
        "plan_not_eight_queries": not re.search(r"8\s*(identifier|标识符)", plan),
    }


def grade_alt(text: str) -> dict[str, bool]:
    w_uo = _field(text, "Width", "uo_id").lower()
    w_op = _field(text, "Width", "operator")
    b_uo = _field(text, "Batch", "uo_id").lower()
    segs_uo = _field(text, "segs", "uo_id")
    segs_op = _field(text, "segs", "operator")
    pad_role = _field(text, "pad_tail", "role").lower()
    pad_uo = _field(text, "pad_tail", "uo_id")
    gate_role = _field(text, "gate_on", "role").lower()
    gate_uo = _field(text, "gate_on", "uo_id")
    gate_op = _field(text, "gate_on", "operator")
    verify = ""
    vm = re.search(r"verify:\s*(.+)", text)
    if vm:
        verify = vm.group(1).lower()
    return {
        "Width_binds_width": w_uo in {"width", "width1"} and "scale" not in w_uo,
        "Width_not_scale": "scale" not in w_op.lower() and "scale" not in w_uo,
        "Batch_binds_b": b_uo in {"b", "batch"},
        "segs_binds_packedSeg": "packed" in segs_uo.lower() and "dim=" not in segs_uo.lower(),
        "segs_not_dim_packed": "dim=" not in segs_op.lower() and "packed" != segs_op.strip("`"),
        "pad_tail_feature": pad_role == "feature",
        "pad_tail_not_borrow": _empty(pad_uo)
        or pad_uo.lower() not in {"b", "packedseg", "width", "padtoken"},
        "gate_on_feature_mask": gate_role == "feature" and "mask" in gate_uo.lower(),
        "gate_on_domain_empty": gate_role != "feature" or _empty(gate_op),
        "verify_inspect_yaml": "inspect yaml" in verify.lower() if False else "inspect yaml" in verify,
    }


def _print(label: str, g: dict[str, bool] | None, err: str | None) -> None:
    print(f"== {label} ==")
    if err:
        print(" ", err)
        return
    assert g is not None
    passed = sum(1 for v in g.values() if v)
    print(f"  {passed}/{len(g)}")
    for k, v in g.items():
        print(f"  {'PASS' if v else 'FAIL'} {k}")


def main() -> None:
    leak = leak_check()
    _print("skill-leak-check", leak, None)
    for it_name in ("iteration-2", "iteration-3"):
        it_root = WS / it_name
        if not it_root.is_dir():
            continue
        for eval_name, grader in (("d4-bind-accuracy", grade_d4), ("alt-scene-bind", grade_alt)):
            root = it_root / eval_name
            if not root.is_dir():
                continue
            for cfg in ("old_skill", "with_skill"):
                for rep in ("r1.md", "r2.md", "r3.md", "r4.md"):
                    path = root / cfg / rep
                    if not path.is_file():
                        continue
                    _print(f"{it_name}/{eval_name}/{cfg}/{rep}", grader(path.read_text(encoding="utf-8")), None)


if __name__ == "__main__":
    main()
