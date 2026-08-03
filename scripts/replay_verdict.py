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

from replay import corpus as C  # noqa: E402
from replay import runner as R  # noqa: E402
from replay import rule_engine as RE  # noqa: E402

# Compatibility re-exports for anything that still imports these names.
_BOOK = None


def _book() -> RE.RuleBook:
    global _BOOK
    if _BOOK is None:
        _BOOK = RE.default_book()
    return _BOOK


def _unreachable_map() -> dict[tuple[str, str], str]:
    out = {}
    for rule in _book().rules:
        if rule.kind == "value_unreachable":
            out[(rule.dim, rule.value)] = rule.reason
    return out


def _combo_list() -> list[tuple[dict, str]]:
    out = []
    for rule in _book().rules:
        if rule.kind == "combo":
            tag = rule.label
            out.append((dict(rule.when), tag))
    return out


# Lazy-looking aliases so `from replay_verdict import UNREACHABLE` still works
# for the few remaining sites that import the constants at module load.
class _LazyMap(dict):
    def _fill(self):
        if not self:
            self.update(_unreachable_map())

    def __contains__(self, key):
        self._fill()
        return dict.__contains__(self, key)

    def __getitem__(self, key):
        self._fill()
        return dict.__getitem__(self, key)

    def items(self):
        self._fill()
        return dict.items(self)


UNREACHABLE = _LazyMap()


class _LazyCombos(list):
    def _fill(self):
        if not self:
            self.extend(_combo_list())

    def __iter__(self):
        self._fill()
        return list.__iter__(self)

    def __len__(self):
        self._fill()
        return list.__len__(self)


UNREACHABLE_COMBOS = _LazyCombos()

PAIR_EVIDENCE = {}  # reasons now live on each Rule in the book



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
    # A single search saturates without being complete: two runs that differed
    # only in seed each stopped finding keys, yet each held ~85 the other never
    # saw. Every run's witnesses count, so the default is the union of all of
    # them rather than whichever file was written last.
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        srcs = [R.CACHE / a for a in args]
    else:
        srcs = C.wide_tables()
    srcs = [p for p in srcs if p.exists()]
    if not srcs:
        print(f"no wide tables matching the manifest glob under {R.CACHE}")
        return 1

    seen: dict[int, dict] = {}
    for p in srcs:
        found = _witnesses(p)
        fresh = len(set(found) - set(seen))
        for k, v in found.items():
            seen.setdefault(k, v)
        print(f"  {p.name}: {len(found)} keys, {fresh} not seen in earlier files")
    print(f"{len(seen)} distinct keys produced, from {len(srcs)} run(s)")

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
        for combo, tag in UNREACHABLE_COMBOS:
            if all(str(inst.get(d)) == v for d, v in combo.items()):
                reasons.append(PAIR_EVIDENCE[tag])
                blocked_by[" + ".join(f"{d}={v}" for d, v in combo.items())] += 1
        if reasons:
            verdicts[key] = ("unreachable_static", reasons[0])
            for d, v in inst.items():
                if (d, str(v)) in UNREACHABLE:
                    blocked_by[f"{d}={v}"] += 1
            continue
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
