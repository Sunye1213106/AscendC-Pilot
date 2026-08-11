# -*- coding: utf-8 -*-
"""Pilot: for a spread of TilingKeys, how many branch outcomes does one case
reach, and how many are left open?

One case per key is deliberately the starting point. The number that matters is
not how many cases a key needs in the end, but how many outcomes remain
uncovered after the obvious case, because that is the size of the search the
real workflow would have to do.
"""

from __future__ import annotations

import base64
import json
import os
import re
import struct
import subprocess
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(HERE))

os.environ.setdefault("UO_OPERATOR", "flash_attention_score_grad")
os.environ.setdefault("UO_ARCH", "arch35")
os.environ.setdefault("UO_OPS_ROOT", str(ROOT.parent / "TEST" / "ops-transformer"))

from branch_eval import Env, evaluate, flat_name  # noqa: E402
from replay import inputs as I  # noqa: E402

UO = Path(sys.argv[1]) if len(sys.argv) > 1 else (
    ROOT / "artifacts" / "fa-pr13" / "flash_attention_score_grad.arch35.uo")

BIN = "/work/wsl/bin/replay_main"
SO = ("/work/ops-transformer/build/tests/ut/framework_normal/op_host"
      "/libophost_transformer_ut.so")

#: Kernel parameter spelling -> TilingKey dimension. The kernel renames the key
#: on the way in, so this is the join between the two vocabularies.
PARAM_TO_DIM = {
    "IS_EMPTY_TENSOR": "IsEmptyTensor", "SPLIT_AXIS": "SplitAxis",
    "INPUT_DTYPE": "InputDType", "IS_TND": "IsTnd", "IS_DROP": "IsDrop",
    "IS_PSE": "IsPse", "IS_ATTEN_MASK": "IsAttenMask",
    "S1_TEMPLATE_TYPE": "S1TemplateNum", "s1TemplateType": "S1TemplateNum",
    "S2_TEMPLATE_TYPE": "S2TemplateNum", "s2TemplateType": "S2TemplateNum",
    "D_TEMPLATE_TYPE": "DTemplateNum", "dTemplateType": "DTemplateNum",
    "DETER_SPARSE_TYPE": "DeterType", "IS_N_EQUAL": "IsNEqual",
    "IS_BN2_MULTIBLK": "IsBn2MultiBlk", "IS_D_NO_EQUAL": "IsDNoEqual",
    "IS_ROPE": "IsRope", "OUTDTYPE": "OutDType", "OUT_DTYPE": "OutDType",
    "IS_NZ_OUT": "IsNzOut", "IS_TND_SWIZZLE": "IsTndSwizzle",
    "IS_REGBASE": "IsRegbase", "splitAxis": "SplitAxis",
}

#: Named constants the conditions compare against.
ENUMS = {
    "SplitAxisType__BN2GS1S2": 0, "SplitAxisType__BN2": 1, "SplitAxisType__BN2S2": 5,
    "BN2GS1S2": 0, "BN2": 1, "BN2S2": 5,
    "SparseType__ALL": 0, "SparseType__CAUSAL": 1, "SparseType__BAND": 2,
    "NO_DETER": 0, "DETER_OLD": 1, "DETER_DENSE": 2, "DETER_CAUSAL": 3,
    "DETER_BAND": 4,
    "VEC_CORE_NUM_64": 64, "MAX_CORE_NUM": 36, "MAX_CUBE_CORE_NUM": 32,
    "AIV": 2, "AIC": 1, "g_coreType": 2,
}


def dtype_variant(input_dtype: str) -> str:
    return {"1": "DT_FLOAT", "2": "DT_BF16", "3": "DT_FLOAT16"}.get(
        str(input_dtype), "DT_FLOAT16")


def replay(cases: dict[str, object]) -> dict[str, dict]:
    """Run every case in one driver invocation, with tiling data dumped."""
    in_csv = HERE / "pilot_in.csv"
    in_csv.write_text(
        "\n".join(I.to_csv_line(c, cid) for cid, c in cases.items()) + "\n",
        encoding="utf-8", newline="\n")
    wsl_in = "/mnt/d" + str(in_csv).replace("\\", "/")[2:]
    script = (
        "source /usr/local/Ascend/cann/set_env.sh >/dev/null 2>&1 || true; "
        "export REPLAY_DUMP_TD=1 REPLAY_TILING_DATA_SIZE=65536 "
        "ASCEND_SLOG_PRINT_TO_STDOUT=1 ASCEND_GLOBAL_LOG_LEVEL=3; "
        f"cd /tmp && {BIN} {wsl_in} /tmp/pilot_out.csv {SO}")
    proc = subprocess.run(["wsl", "-e", "/bin/bash", "-c", script],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    out: dict[str, dict] = {}
    cur = None
    for line in (proc.stdout or "").splitlines():
        m = re.match(r"^###CASE (\S+)", line)
        if m:
            cur = {"case_id": m.group(1)}
            out[m.group(1)] = cur
            continue
        if cur is None:
            continue
        m = re.match(r"^###TD (\d+) (\S+)$", line)
        if m:
            cur["td_size"] = int(m.group(1))
            cur["td"] = base64.b64decode(m.group(2))
            continue
        m = re.match(r"^###BLOCK (\d+)$", line)
        if m:
            cur["block_num"] = int(m.group(1))
            continue
        m = re.match(r"^###DONE (\S+) ok=(\d) key=(\d+)$", line)
        if m:
            cur["ok"] = m.group(2) == "1"
            cur["key"] = int(m.group(3))
            cur = None
    if not out:
        print((proc.stdout or "")[-800:])
        print((proc.stderr or "")[-500:])
    return out


def decode(raw: bytes, layout: dict) -> dict:
    """Bind every decodable field under the names a condition can name it by.

    Three spellings reach the evaluator for the same field, because the kernel
    writes `tilingData->preTilingData.hasInvalidCol` in one place and
    `m_tilingData->isRope` in another: the flattened struct+field, the flattened
    field alone, and the bare leaf.
    """
    vals: dict[str, object] = {}
    for f in layout["fields"]:
        if not f["code"]:
            continue
        try:
            if f["count"] > 1:
                v = list(struct.unpack_from(
                    "<" + f["code"] * f["count"], raw, f["offset"]))
            else:
                v = struct.unpack_from("<" + f["code"], raw, f["offset"])[0]
        except struct.error:
            continue
        path = f["path"]
        leaf = path.rsplit(".", 1)[-1]
        struct_name = path.rsplit(".", 1)[0] if "." in path else ""
        vals[path] = v
        vals.setdefault(leaf, v)
        vals.setdefault(flat_name(leaf), v)
        if struct_name:
            vals.setdefault(flat_name(struct_name, leaf), v)
    return vals


def load_derived() -> dict[str, str]:
    """Kernel member -> defining expression, for the members that have one.

    A member written differently in two places has no single definition, so it
    is left out and the branches on it stay undecided rather than being decided
    from whichever write was seen last.
    """
    p = HERE / "derived_members.json"
    if not p.is_file():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {k: v["expression"] for k, v in (data.get("unguarded") or {}).items()
            if not v.get("conflicts")}


def load_pinned(dims: dict) -> dict[str, object]:
    """Fields a proved lemma fixes for a key with these dimensions.

    Only rules that survived refutation are used, and only those whose `when`
    matches, so a rule about IsDrop=0 keys says nothing about a key with dropout.
    """
    import yaml

    lemmas = HERE / "lemmas.yaml"
    verdict = HERE / "lemma_check.json"
    if not lemmas.is_file():
        return {}
    rules = yaml.safe_load(lemmas.read_text(encoding="utf-8")).get("rules") or []
    usable = None
    if verdict.is_file():
        usable = set(json.loads(verdict.read_text(encoding="utf-8")).get("usable") or [])
    out: dict[str, object] = {}
    for r in rules:
        if usable is not None and r["id"] not in usable:
            continue
        if all(str(dims.get(k)) == str(v) for k, v in (r.get("when") or {}).items()):
            out[r["field"]] = r["value"]
            out[flat_name(r["field"])] = r["value"]
    return out


def owner_of_leaf(layouts: dict) -> dict[str, str]:
    """leaf field name -> the top-level member that carries it.

    Built from every variant together: a member absent from one variant has its
    fields in another, and without the union a branch reading it looks like an
    unknown symbol rather than an absent member.
    """
    out: dict[str, str] = {}
    for lay in layouts.values():
        for f in lay["fields"]:
            if not f["code"] or "." not in f["path"]:
                continue
            top = f["path"].split(".", 1)[0]
            out.setdefault(f["path"].rsplit(".", 1)[-1], top)
    return out


def main() -> None:
    picked = json.loads((HERE / "picked_keys.json").read_text(encoding="utf-8"))
    layouts = json.loads((HERE / "layout.json").read_text(encoding="utf-8"))
    branches = json.loads(
        (HERE / "steerable_branches.json").read_text(encoding="utf-8"))
    by_size = {lay["size"]: (name, lay) for name, lay in layouts.items()}
    owner = owner_of_leaf(layouts)
    print(f"keys={len(picked)} branches={len(branches)} "
          f"layout variants={len(layouts)}")

    cases = {}
    for trait, row in picked.items():
        made = I.construct_case(row["dims"])
        if made:
            cases[trait] = made[0]
    print(f"constructed {len(cases)} cases\n")

    results = replay(cases)

    summary = []
    for trait, row in picked.items():
        r = results.get(trait) or {}
        want = row["tiling_key"]
        got = r.get("key")
        raw = r.get("td")
        line = {"trait": trait, "want_key": want, "got_key": got,
                "hit": got == want, "ok": bool(r.get("ok")),
                "td_size": r.get("td_size")}
        if not raw:
            line["status"] = "no tiling data"
            summary.append(line)
            continue
        hit = by_size.get(len(raw))
        if hit is None:
            line["status"] = f"no layout for {len(raw)} bytes"
            summary.append(line)
            continue
        variant, layout = hit
        line["variant"] = variant
        fields = decode(raw, layout)

        dims = {k: int(v) for k, v in row["dims"].items() if str(v).lstrip("-").isdigit()}
        env = Env(fields=fields, dims=dims, param_to_dim=PARAM_TO_DIM,
                  enums=dict(ENUMS), block_num=int(r.get("block_num") or 0),
                  derived=load_derived())
        line["block_num"] = env.block_num
        # dtype predicates, resolved from the key rather than left unknown
        idt = str(row["dims"].get("InputDType"))
        env.enums.update({
            "__is_same_T1_float": idt == "1", "__is_same_T_float": idt == "1",
            "__is_same_T1_half": idt == "3", "__is_same_T1_bfloat16_t": idt == "2",
            "__is_same_INPUT_TYPE_float": idt == "1",
        })

        absent = set(layout.get("absent_members") or [])
        present_leaves = {f["path"].rsplit(".", 1)[-1]
                          for f in layout["fields"] if f["code"]}
        counts = Counter()
        detail = []
        for b in branches:
            # Two ways a branch is simply not there under this key. Either the
            # conditional member it reads resolved to nullptr_t, or the whole
            # struct is a different one -- the empty-tensor path has its own,
            # so the main-path branches read fields it does not define, and
            # vice versa. Both are exclusions, not coverage debt.
            gone = sorted({owner.get(f, "") for f in b["fields"]} & absent)
            unknown_fields = [f for f in b["fields"] if f not in present_leaves]
            if gone or (b["fields"] and len(unknown_fields) == len(b["fields"])):
                why = (f"absent member: {', '.join(gone)}" if gone
                       else f"not a field of this variant: "
                            f"{', '.join(unknown_fields)}")
                counts["unreachable"] += 1
                detail.append({"file": b["file"], "line": b["line"],
                               "state": "unreachable", "detail": why,
                               "unknown": []})
                continue
            oc = evaluate(b["condition"], env)
            if oc.both_ways:
                state = "both"
            elif oc.value is True:
                state = "true"
            elif oc.value is False:
                state = "false"
            else:
                state = "undecided"
            counts[state] += 1
            detail.append({"file": b["file"], "line": b["line"], "state": state,
                           "detail": oc.detail,
                           "unknown": list(oc.unknown_symbols)[:6]})
        line["counts"] = dict(counts)
        line["detail"] = detail
        summary.append(line)

    out = HERE / "pilot_result.json"
    out.write_text(json.dumps(summary, indent=1, ensure_ascii=False),
                   encoding="utf-8")

    print(f"{'trait':20s} {'hit':>5s} {'variant':8s} {'bytes':>6s}  "
          f"{'live':>5s} {'true':>5s} {'false':>5s} {'both':>5s} "
          f"{'unreach':>8s} {'undec':>6s}")
    for s in summary:
        c = s.get("counts") or {}
        live = len(branches) - c.get("unreachable", 0)
        print(f"{s['trait']:20s} {str(s['hit']):>5s} "
              f"{s.get('variant','-'):8s} {str(s.get('td_size','-')):>6s}  "
              f"{live:5d} {c.get('true',0):5d} {c.get('false',0):5d} "
              f"{c.get('both',0):5d} {c.get('unreachable',0):8d} "
              f"{c.get('undecided',0):6d}"
              + (f"   {s.get('status','')}" if s.get("status") else ""))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
