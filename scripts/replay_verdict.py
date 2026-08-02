# -*- coding: utf-8 -*-
"""Judge every declared tiling key against what replay actually produced.

The kernel declares 8705 template instances. Replay says which of them the host
can really ask for. The four verdicts are:

  confirmed_runtime  declared, and a concrete input produces it
  unreachable_static declared, but a host code path rules it out
  candidate_static   declared, not produced, and nothing rules it out
  undeclared_runtime produced by the host with no kernel instance behind it

The last one is the interesting failure: the host would ask for a kernel that
was never compiled. The middle one is the honest unknown -- the search simply
has not found an input yet.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "engines" / "understand-operator" / "src")
)

from uo_init.tpl_dsl import expand_legal_instances  # noqa: E402

from replay import runner as R  # noqa: E402

#: Dimension values the host cannot emit, with the code that rules them out.
#: These come from reading the tiling source, and replay agrees with all of them.
UNREACHABLE = {
    ("InputDType", "4"): (
        "FLOAT8_E5M2 input is rejected by ProcessQuantInfo before tiling runs "
        "(flash_attention_score_grad_tiling_common_regbase.cpp:1148-1155)"),
    ("InputDType", "5"): (
        "FLOAT8_E4M3FN input is rejected by ProcessQuantInfo "
        "(flash_attention_score_grad_tiling_common_regbase.cpp:1148-1155)"),
    ("InputDType", "6"): (
        "HIFLOAT8 input is rejected by ProcessQuantInfo "
        "(flash_attention_score_grad_tiling_common_regbase.cpp:1148-1155)"),
    ("S1TemplateNum", "512"): (
        "only GetS1S2TemplateType's HIFLOAT8 branch sets 512, and HIFLOAT8 "
        "never reaches it (common_regbase.cpp:825-829)"),
    ("S2TemplateNum", "256"): (
        "only the FP8 branch sets 256, and FP8 is rejected earlier "
        "(common_regbase.cpp:819-824)"),
    ("S2TemplateNum", "512"): (
        "only the HIFLOAT8 branch sets 512 (common_regbase.cpp:825-829)"),
    ("IsRegbase", "0"): (
        "GetTilingKey passes isRegbasePlatformValue as ENABLE unconditionally "
        "(normal_regbase.cpp:1447)"),
}


def _witnesses(path: Path) -> dict[int, dict]:
    rows = path.read_text(encoding="utf-8").splitlines()
    head = rows[0].split(",")
    idx = {n: i for i, n in enumerate(head)}
    out: dict[int, dict] = {}
    for line in rows[1:]:
        f = line.split(",")
        if len(f) != len(head) or f[idx["ok"]] != "1":
            continue
        key = int(f[idx["tiling_key"]])
        if key in out:
            continue
        out[key] = {n: f[i] for n, i in idx.items()}
    return out


def main() -> int:
    src = R.CACHE / "fag_key_cases_full.csv"
    if not src.exists():
        src = R.CACHE / "fag_key_cases.csv"
    seen = _witnesses(src)
    print(f"{len(seen)} distinct keys produced, from {src.name}")

    declared = expand_legal_instances(R.SCHEMA)
    print(f"{len(declared)} template instances declared by the kernel")

    dec_key: dict[int, dict] = {}
    for inst in declared:
        dec_key[R.SCHEMA.encode_tiling_key({k: int(v) for k, v in inst.items()})] = inst

    verdicts: dict[int, tuple[str, str]] = {}
    blocked_by: Counter = Counter()
    for key, inst in dec_key.items():
        if key in seen:
            verdicts[key] = ("confirmed_runtime", seen[key]["case_id"])
            continue
        reasons = [UNREACHABLE[(d, v)] for d, v in inst.items()
                   if (d, str(v)) in UNREACHABLE]
        if reasons:
            verdicts[key] = ("unreachable_static", reasons[0])
            for d, v in inst.items():
                if (d, str(v)) in UNREACHABLE:
                    blocked_by[f"{d}={v}"] += 1
        else:
            verdicts[key] = ("candidate_static", "")

    undeclared = sorted(set(seen) - set(dec_key))
    counts = Counter(v[0] for v in verdicts.values())

    print("\n--- verdicts over declared instances ---")
    for name in ("confirmed_runtime", "unreachable_static", "candidate_static"):
        n = counts.get(name, 0)
        print(f"  {name:<20} {n:>6}  ({n / len(dec_key) * 100:.1f}%)")
    print(f"  undeclared_runtime   {len(undeclared):>6}  "
          f"(produced but no kernel instance)")

    print("\n--- what blocks the unreachable ones ---")
    for name, n in blocked_by.most_common():
        print(f"  {name:<22} {n:>6} instances")

    if undeclared:
        print("\n--- host produced these with no declared kernel instance ---")
        for key in undeclared[:10]:
            dims = R.SCHEMA.decode_tiling_key(key)
            odd = {k: v for k, v in dims.items()}
            print(f"  key={key}  case={seen[key]['case_id']}")
            print(f"    {odd}")

    # A declared instance is a cartesian product of ARGS_SEL groups, so it can
    # pair values that the host never puts together -- IsTnd=0 with a TND-only
    # swizzle, say. Those pairs never co-occur in anything replay produced, and
    # separating them keeps the honest unknowns from drowning in noise.
    cand_keys = [k for k, v in verdicts.items() if v[0] == "candidate_static"]
    seen_pairs: set = set()
    for key in seen:
        dims = R.SCHEMA.decode_tiling_key(key)
        names = [n for n in R.DIM_NAMES if n in dims]
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                seen_pairs.add((a, str(dims[a]), b, str(dims[b])))

    contradictory, open_cands = [], []
    blame: Counter = Counter()
    for key in cand_keys:
        inst = dec_key[key]
        names = [n for n in R.DIM_NAMES if n in inst]
        unseen = [(a, str(inst[a]), b, str(inst[b]))
                  for i, a in enumerate(names) for b in names[i + 1:]
                  if (a, str(inst[a]), b, str(inst[b])) not in seen_pairs]
        if unseen:
            contradictory.append(key)
            for a, av, b, bv in unseen[:1]:
                blame[f"{a}={av} with {b}={bv}"] += 1
        else:
            open_cands.append(key)

    print(f"\n--- splitting the {len(cand_keys)} candidates ---")
    print(f"  never-co-occurring pair   {len(contradictory):>6}  "
          f"(a value pair replay never produced together)")
    print(f"  all pairs seen            {len(open_cands):>6}  "
          f"(genuinely open: search has not found an input)")
    print("\n  most common blocking pair:")
    for name, n in blame.most_common(10):
        print(f"    {name:<48} {n:>5}")

    if open_cands:
        print(f"\n  open candidates by dimension:")
        per_dim: dict[str, Counter] = defaultdict(Counter)
        for key in open_cands:
            for d, v in dec_key[key].items():
                per_dim[d][v] += 1
        for d in R.DIM_NAMES:
            spread = per_dim[d]
            if len(spread) > 1:
                top = ", ".join(f"{v}:{n}" for v, n in spread.most_common(6))
                print(f"    {d:<18} {top}")

    for key in contradictory:
        verdicts[key] = ("candidate_contradictory", "")
    for key in open_cands:
        verdicts[key] = ("candidate_open", "")

    out = R.CACHE / "key_reachability.csv"
    lines = ["tiling_key,verdict,evidence," + ",".join(f"dim_{n}" for n in R.DIM_NAMES)]
    for key in sorted(dec_key):
        verdict, ev = verdicts[key]
        inst = dec_key[key]
        lines.append(",".join([str(key), verdict, '"' + ev.replace('"', "'") + '"']
                              + [str(inst.get(n, "")) for n in R.DIM_NAMES]))
    for key in undeclared:
        dims = R.SCHEMA.decode_tiling_key(key)
        lines.append(",".join(
            [str(key), "undeclared_runtime", '"' + seen[key]["case_id"] + '"']
            + [str(dims.get(n, "")) for n in R.DIM_NAMES]))
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"\nverdicts -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
