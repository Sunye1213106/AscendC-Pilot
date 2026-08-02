# -*- coding: utf-8 -*-
"""Check the derivation against the only real input->key pairs that exist.

The arch35 unit tests assert a tiling key that came out of the real host tiling
code. Decoding those keys gives per-dimension truth; feeding the same inputs to
the derived expressions gives the prediction. Every coverage number reported so
far rests on the derivation being right, and nothing has ever checked it.

A dimension is only reported as agreeing or disagreeing when the mapping from
what the test sets to what the expression reads is unambiguous. The rest are
listed as unchecked rather than quietly counted as passing.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".probe_cache"
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.concrete_eval import (  # noqa: E402
    Auxiliaries,
    Unknown,
    ValueTree,
    ZeroDenominator,
)
from uo_init.tpl_dsl import parse_file  # noqa: E402

OPS = Path(r"D:\TEST\ops-transformer")
UT = (
    OPS
    / "attention/flash_attention_score_grad/tests/ut/op_host/arch35"
    / "test_flash_attention_score_grad_tiling.cpp"
)
TPL = (
    OPS
    / "attention/flash_attention_score_grad/op_kernel/arch35"
    / "flash_attention_score_grad_template_tiling_key.h"
)

#: ge::DataType values, as the derived expressions compare against them.
DTYPE = {
    "DT_FLOAT": 0, "DT_FLOAT16": 1, "DT_INT8": 2, "DT_INT32": 3, "DT_UINT8": 4,
    "DT_INT16": 6, "DT_UINT16": 7, "DT_UINT32": 8, "DT_INT64": 9, "DT_UINT64": 10,
    "DT_DOUBLE": 11, "DT_BOOL": 12, "DT_BF16": 27, "DT_HIFLOAT8": 34,
    "DT_FLOAT8_E5M2": 35, "DT_FLOAT8_E4M3FN": 36,
}

#: Positional order of the operator's inputs in TilingContextPara.
IN_ORDER = [
    "query", "key", "value", "dy", "pse_shift", "drop_mask", "padding_mask",
    "atten_mask", "softmax_max", "softmax_sum", "softmax_in", "attention_in",
    "prefix", "actual_seq_qlen", "actual_seq_kvlen", "q_start_idx", "kv_start_idx",
    "dScaleQ", "dScaleK", "dScaleV", "dScaledy", "dScaleo", "queryRope", "keyRope",
]
OUT_ORDER = ["dq", "dk", "dv", "dpse", "dq_rope", "dk_rope"]

_CASE = re.compile(r"TEST_F\(\s*\w+\s*,\s*(\w+)\s*\)")
_KEY = re.compile(r"expectTilingKey\s*=\s*(\d+)")
# Tensors carrying real data add two more fields, e.g.
#   {{{4}, {4}}, ge::DT_INT64, ge::FORMAT_ND, true, actual_seq_qlist}
# Missing those shifts every later tensor by one and silently corrupts the
# input-to-output split, so the trailing fields have to be tolerated.
_TENSOR = re.compile(
    r"\{\s*\{\s*\{([^{}]*)\}\s*,\s*\{([^{}]*)\}\s*\}\s*,\s*ge::(DT_\w+)\s*,"
    r"\s*ge::(FORMAT_\w+)\s*(,[^{}]*)?\}"
)
_ATTR = re.compile(
    r'\{\s*"(\w+)"\s*,\s*Ops::Transformer::AnyValue::CreateFrom<([\w:]+)>\s*\(\s*([^)]*?)\s*\)\s*\}'
)


def _dims(text: str) -> list[int]:
    text = text.strip()
    if not text:
        return []
    return [int(x) for x in re.findall(r"-?\d+", text)]


def parse_cases(text: str) -> list[dict]:
    """One dict per TEST_F: its tensors, attrs and asserted key."""
    marks = [(m.start(), m.group(1)) for m in _CASE.finditer(text)]
    out = []
    for i, (pos, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        body = text[pos:end]
        km = _KEY.search(body)
        if not km:
            continue
        tensors = [
            {"shape": _dims(m.group(1)), "origin": _dims(m.group(2)), "dtype": m.group(3)}
            for m in _TENSOR.finditer(body)
        ]
        attrs = {}
        for m in _ATTR.finditer(body):
            k, ty, raw = m.group(1), m.group(2), m.group(3).strip()
            if "string" in ty:
                attrs[k] = raw.strip('"')
            elif ty == "float":
                attrs[k] = float(raw.rstrip("f"))
            else:
                attrs[k] = int(raw)
        out.append(
            {
                "name": name,
                "key": int(km.group(1)),
                "inputs": dict(zip(IN_ORDER, tensors[: len(IN_ORDER)])),
                "outputs": dict(zip(OUT_ORDER, tensors[len(IN_ORDER):])),
                "attrs": attrs,
            }
        )
    return out


#: A tensor the test does not supply. The expressions guard on `!= null`
#: before comparing to 0, so an absent tensor has to read as null and not as
#: a zero size, or every `size == 0` guard fires on inputs that never had one.
ABSENT = None


def _numel(t: dict | None):
    if not t or not t["shape"]:
        return ABSENT
    n = 1
    for d in t["shape"]:
        n *= d
    return n


def _layout_d(q: dict | None, layout: str, head_num):
    """D as the operator reads it, which depends on the layout.

    The derivation resolves D to `queryShape->GetDim(2)`, which is only D for
    the three-dimensional layouts. This computes it properly so the two can be
    compared and the difference attributed.
    """
    if not q or not q["shape"]:
        return None
    s = q["shape"]
    if layout in ("BNSD", "BSND") and len(s) >= 4:
        return s[3]
    if layout == "TND" and len(s) >= 3:
        return s[2]
    if layout in ("SBH", "BSH") and len(s) >= 3:
        return s[2] // head_num if head_num else s[2]
    return s[-1]


def _dim(t: dict | None, i: int):
    if not t or len(t["shape"]) <= i:
        return None
    return t["shape"][i]


def env_of(case: dict, *, layout_aware_d: bool = False) -> dict:
    """Map what the test sets onto the variables the expressions read.

    Only the variables whose meaning is pinned by the expressions themselves
    are set. An absent variable makes the dimensions reading it come back
    unevaluated, which is the honest outcome.

    With ``layout_aware_d`` the D-carrying variable is filled with D computed
    per layout instead of literally dim 2. That is not what the derivation
    says; it is a control to show whether the layout is the whole difference.
    """
    ins, outs, at = case["inputs"], case["outputs"], case["attrs"]
    q, k, v = ins.get("query"), ins.get("key"), ins.get("value")

    def present(name: str) -> bool:
        n = _numel(ins.get(name))
        return n is not None and n > 0

    env: dict = {
        "VAR_DTYPE_QUERY": DTYPE.get(q["dtype"], -1) if q else -1,
        # Optional inputs: presence flag plus a size the guards compare to 0.
        "VAR_OPT_PSE_SHIFT": present("pse_shift"),
        "VAR_SHAPE_PSE_SHIFT": _numel(ins.get("pse_shift")),
        "VAR_OPT_ATTEN_MASK": present("atten_mask"),
        "VAR_SHAPE_ATTEN_MASK": _numel(ins.get("atten_mask")),
        "VAR_OPT_DROP_MASK": present("drop_mask"),
        "VAR_SHAPE_DROP_MASK": _numel(ins.get("drop_mask")),
        "VAR_OPT_QUERY_ROPE_IDX": present("queryRope"),
        "VAR_SHAPE_QUERY_ROPE_IDX": _numel(ins.get("queryRope")),
        "VAR_OPT_KEY_ROPE_IDX": present("keyRope"),
        "VAR_SHAPE_KEY_ROPE_IDX": _numel(ins.get("keyRope")),
        "VAR_SHAPE_ACTUAL_SEQ_Q_LEN": _numel(ins.get("actual_seq_qlen")),
        # Outputs, read by IsEmptyTensor.
        "VAR_SHAPE_DQ": _numel(outs.get("dq")),
        "VAR_SHAPE_DK": _numel(outs.get("dk")),
        "VAR_SHAPE_DV": _numel(outs.get("dv")),
        "VAR_SHAPE_DQ_ROPE": _numel(outs.get("dq_rope")),
        "VAR_SHAPE_DK_ROPE": _numel(outs.get("dk_rope")),
        # Attributes.
        "VAR_ATTR_HEAD_NUM": at.get("head_num"),
        "VAR_ATTR_KEEP_PROB": at.get("keep_prob"),
        "VAR_ATTR_PRE_TOCKENS": at.get("pre_tockens"),
        "VAR_ATTR_NEXT_TOCKENS": at.get("next_tockens"),
        "VAR_ATTR_SPARSE_MODE": at.get("sparse_mode"),
        "VAR_ATTR_INPUT_LAYOUT": at.get("input_layout"),
        "VAR_PLATFORM_ARCH": 35,
        "VAR_SESSION_DETERMINISTIC": 0,
    }
    # A dim index past the end of a shape is not null, it is a question this
    # test cannot answer, so it is left out and the dimension reading it
    # reports as unevaluated.
    for tensor, tag, idx in (
        (q, "QUERY", 0), (q, "QUERY", 1), (q, "QUERY", 2), (q, "QUERY", 3),
        (k, "KEY", 0), (k, "KEY", 1), (k, "KEY", 2),
        (v, "VALUE", 2), (v, "VALUE", 3),
    ):
        got = _dim(tensor, idx)
        if got is not None:
            env[f"VAR_SHAPE_{tag}_D{idx}"] = got
    if layout_aware_d:
        env["VAR_SHAPE_QUERY_D2"] = _layout_d(
            q, at.get("input_layout", ""), at.get("head_num")
        )
    # Shape variables stay in even when null: that *is* their value when the
    # test omits the tensor. Only a dim index past the end of a shape is
    # genuinely unknown, and `_dim` already leaves those out.
    return {k2: v2 for k2, v2 in env.items() if not (v2 is None and "SHAPE" not in k2)}


def main() -> int:
    schema = parse_file(TPL)
    cases = parse_cases(UT.read_text(encoding="utf-8", errors="replace"))
    print(f"{len(cases)} ground-truth cases from the arch35 UT\n")

    doc = json.loads((CACHE / "fag_derive.json").read_text(encoding="utf-8"))
    saved = doc.get("host_derivation") or {}
    aux = Auxiliaries.from_rows(saved.get("auxiliaries") or {})
    trees = {
        f["name"]: ValueTree(f["value_expr"])
        for f in doc["fields"]
        if f.get("value_expr") is not None
    }

    # Which dimensions this comparison can speak about: the ones whose whole
    # variable set the mapping above covers. The rest read host tiling state
    # that no test input decides, so silence is the correct answer for them.
    sample_env = env_of(cases[0])
    coverable, uncoverable = [], {}
    for name, t in trees.items():
        _c, need = t.cuts()
        need = set(need) - aux.names
        miss = sorted(need - set(sample_env))
        if miss:
            uncoverable[name] = miss
        else:
            coverable.append(name)
    print(f"{len(coverable)} dimensions the test inputs fully determine: {coverable}")
    print(f"{len(uncoverable)} they do not:")
    for name, miss in uncoverable.items():
        print(f"  {name:<18} missing {len(miss)}: {miss[:4]}{' ...' if len(miss) > 4 else ''}")

    def run(layout_aware_d: bool):
        agree: Counter = Counter()
        disagree: Counter = Counter()
        failed: Counter = Counter()
        details: list[str] = []
        rows: list[str] = []
        for case in cases:
            truth = schema.decode_tiling_key(case["key"])
            env = env_of(case, layout_aware_d=layout_aware_d)
            env = {**env, **aux.resolve(env)}
            cells = []
            for name in coverable:
                want = str(truth[name])
                try:
                    got = trees[name].value(env)
                except (Unknown, ZeroDenominator) as exc:
                    failed[name] += 1
                    cells.append("ERR")
                    details.append(f"{case['name']} {name}: {type(exc).__name__} {exc}")
                    continue
                if isinstance(got, bool):
                    got = int(got)
                got = str(got)
                if got == want:
                    agree[name] += 1
                    cells.append(f"{got}=")
                else:
                    disagree[name] += 1
                    cells.append(f"{got}!={want}")
                    details.append(f"{case['name']} {name}: derived={got} truth={want}")
            tag = case["name"].rsplit("_", 1)[-1]
            rows.append(f"{tag:>4}  " + "  ".join(f"{c:>12}" for c in cells))
        return agree, disagree, failed, details, rows

    agree, disagree, failed, details, rows = run(False)

    print(f"\n{'=' * 104}")
    hdr = f"{'case':>4}  " + "  ".join(f"{n[:12]:>12}" for n in coverable)
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(r)

    print(f"\n{'=' * 62}")
    print("逐维结论（= 表示与真值一致）")
    perfect = 0
    for name in coverable:
        a, d, f = agree[name], disagree[name], failed[name]
        verdict = "全部一致" if d == 0 and f == 0 else f"{d} 处不一致, {f} 处求值失败"
        perfect += d == 0 and f == 0
        print(f"  {name:<18} {a}/{len(cases)} 一致   {verdict}")
    print(f"\n{perfect}/{len(coverable)} 个可验证维度完全正确")
    print(f"{len(uncoverable)} 个维度无法用这批用例验证（依赖 host 状态）")

    if details:
        print(f"\n=== 不一致明细 ===")
        for line in details[:25]:
            print(f"  {line}")

    # Control: same run with D computed per layout instead of as dim 2. If the
    # remaining disagreements vanish, the derivation lost the layout branch
    # rather than being wrong about anything else.
    _a2, d2, f2, _det2, _r2 = run(True)
    print(f"\n{'=' * 62}")
    print("对照实验：把 D 按 layout 正确算出来再喂进同一套表达式")
    for name in coverable:
        before = disagree[name] + failed[name]
        after = d2[name] + f2[name]
        if before or after:
            mark = "  <== 差异完全由 layout 解释" if before and not after else ""
            print(f"  {name:<18} 原本 {before} 处不符 -> 现在 {after} 处{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
