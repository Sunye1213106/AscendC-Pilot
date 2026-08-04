# -*- coding: utf-8 -*-
"""What is in the runtime corpus that the template never declared.

The gate reports `undeclared 96` beside `declared 8705`. Every one of those
keys decodes to values the declaration allows, so what the template refuses is
the *combination*: `expand_legal_instances` is building a smaller set than the
host can reach. A gap measured against that denominator is measured against
the wrong thing, and no amount of searching closes it.

Reports which dimension pairs occur at runtime and never in a declared
instance, which is what a too-narrow SEL group looks like from outside.
"""

from __future__ import annotations

import itertools
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from replay import runner as R  # noqa: E402
from replay_runtime_counterexample_gate import load_declared, load_runtime  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / ".probe_cache" / "undeclared.txt"


def main() -> int:
    seen = load_runtime()
    dec = load_declared()
    undeclared = {k: v for k, v in seen.items() if k not in dec}
    schema = R.SCHEMA
    names = [d.name for d in schema.dims]

    lines: list[str] = []
    w = lines.append
    w(f"runtime {len(seen)}   declared {len(dec)}   undeclared {len(undeclared)}")
    if not undeclared:
        OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n".join(lines))
        return 0

    # Which (dim, value) pairs and which 2-wise combinations the declaration
    # carries. A runtime combination absent from the second but present in the
    # first is a constraint the template states and the host does not honour.
    dec_pairs: set[tuple[str, str]] = set()
    dec_two: set[tuple[str, str, str, str]] = set()
    for inst in dec.values():
        vals = {n: str(v) for n, v in inst.items()}
        for n, v in vals.items():
            dec_pairs.add((n, v))
        for a, b in itertools.combinations(names, 2):
            dec_two.add((a, vals.get(a, ""), b, vals.get(b, "")))

    missing_two: Counter = Counter()
    example: dict[tuple, int] = {}
    decoded: list[dict] = []
    for key in undeclared:
        dims = {n: str(v) for n, v in schema.decode_tiling_key(key).items()}
        decoded.append(dims)
        for a, b in itertools.combinations(names, 2):
            t = (a, dims.get(a, ""), b, dims.get(b, ""))
            if t not in dec_two:
                missing_two[t] += 1
                example.setdefault(t, key)

    w("")
    w("dimension pairs that occur at runtime and in no declared instance:")
    if not missing_two:
        w("  none - every 2-wise projection is declared, so the template")
        w("  refuses these only at a higher arity")
    for t, n in missing_two.most_common(20):
        a, av, b, bv = t
        w(f"  {a}={av:3s} with {b}={bv:3s}   {n:4d} keys   e.g. {example[t]}")

    # What the runtime keys look like, to eyeball against the declaration.
    w("")
    w("value histogram over the undeclared keys:")
    for n in names:
        c = Counter(d.get(n, "") for d in decoded)
        allowed = sorted({v for (nm, v) in dec_pairs if nm == n},
                         key=lambda x: int(x) if x.isdigit() else 0)
        w(f"  {n:16s} runtime={dict(c.most_common())}  declared={allowed}")

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\n-> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
