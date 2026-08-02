# -*- coding: utf-8 -*-
"""Hold the static derivation to account against every real witness.

The upper bound U is computed from the derivation, so if the derivation is
wrong about a dimension, U is wrong and every unreachable verdict resting on it
is worthless. Hundreds of thousands of cases have had their true 19 values
reported by a real host, which makes this checkable without running anything:
predict each exact dimension from the case's inputs and compare.

A disagreement is a bug in the static model, never a curiosity. It is reported
as DERIVATION_RUNTIME_MISMATCH and outranks any coverage number.

Usage: replay_derivation_check.py [max_inputs] [--timeout SECONDS]
"""

from __future__ import annotations

import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "engines" / "understand-operator" / "src")
)

from uo_init.concrete_eval import Unknown, ValueTree, _hashable  # noqa: E402

from replay import bridge as B  # noqa: E402
from replay import corpus as C  # noqa: E402
from replay import runner as R  # noqa: E402

case_of = C.case_of  # re-exported: other scripts import it from here


class Predictor:
    """One dimension's tree, answering per distinct set of what it reads.

    A dimension is a function of its own variables, and the corpus varies
    mostly in variables any one dimension ignores. Without this the same
    fourteen trees get walked hundreds of thousands of times to produce a few
    dozen distinct answers.
    """

    def __init__(self, name: str, field: dict) -> None:
        self.name = name
        self.exactness = field["exactness"]
        self.tree = ValueTree(field["value_expr"])
        _, names = self.tree.cuts()
        self.vars = tuple(sorted(names))
        self.memo: dict[tuple, str | None] = {}

    def predict(self, env: dict) -> str | None:
        """The value this dimension should take, or None if unevaluable."""
        key = tuple(_hashable(env.get(v)) for v in self.vars)
        if key in self.memo:
            return self.memo[key]
        try:
            got = self.tree.value(env)
        except Unknown:
            out = None
        else:
            out = str(int(got)) if isinstance(got, bool) else str(got)
        self.memo[key] = out
        return out


class Tally:
    """Agreement for one dimension under one env layer."""

    def __init__(self) -> None:
        self.agree = self.differ = self.unknown = 0
        self.examples: list[tuple] = []

    def add(self, got: str | None, want: str, sample) -> bool:
        if got is None:
            self.unknown += 1
        elif got == want:
            self.agree += 1
        else:
            self.differ += 1
            if len(self.examples) < 3:
                self.examples.append(
                    (sample.case_id, sample.row.get("layout"), got, want))
        return got is not None and got != want

    @property
    def answered(self) -> int:
        return self.agree + self.differ

    def line(self) -> str:
        tot, u = self.answered, self.unknown
        cover = f"{tot / (tot + u) * 100:5.1f}%" if tot + u else "    --"
        rate = f"{self.agree / tot * 100:5.1f}%" if tot else "    --"
        return f"{self.agree:>8}{self.differ:>7}{u:>8}{cover:>9}{rate:>9}"


def main() -> int:
    argv = [a for a in sys.argv[1:]]
    timeout = 300.0
    if "--timeout" in argv:
        i = argv.index("--timeout")
        timeout = float(argv[i + 1])
        del argv[i:i + 2]
    limit = int(argv[0]) if argv else 0

    # Every dimension is checked, including the five the derivation calls
    # overapproximated. Exactness is a property of a path, not of a dimension:
    # those five carry forty-odd input variables and six to nine blockers, and
    # evaluation is short-circuiting, so an input whose path misses the
    # blockers gets an exact answer from a tree labelled approximate. Refusing
    # to look would discard most of what the derivation actually knows about
    # them. Whether the answer is *right* is what the corpus is for.
    preds = [Predictor(n, f) for n, f in sorted(B.fields().items())
             if f.get("value_expr")]
    print(f"checking all {len(preds)} dimensions against the corpus")

    samples, stat = C.scan(limit=limit, timeout=timeout / 3)
    print(f"\n{stat.report()}")

    tallies = {(p.name, layer): Tally() for p in preds for layer in (0, 1)}
    checked = empty = 0
    started = time.time()

    out = R.CACHE / "derivation_check.csv"
    with out.open("w", encoding="utf-8") as fh:
        fh.write("case_id,weight,dimension,env_layer,predicted,actual,verdict\n")
        for s in C.with_env([s for s in samples if s.ok], timeout=timeout):
            checked += 1
            actual = R.SCHEMA.decode_tiling_key(s.key)
            obs = B.observed(s.row, s.case)
            # An empty output short-circuits the whole tiling: the host returns
            # before any other dimension is computed, so all 18 of them read 0
            # whatever their own expression says. The derivation carries no
            # cross-dimension edge for this, so checking them here would report
            # 18 mismatches per case for a value the source never asked for.
            short = actual["IsEmptyTensor"] == "1"
            empty += short
            for p in preds:
                if short and p.name not in ("IsEmptyTensor", "IsRegbase"):
                    continue
                want = str(actual[p.name])
                grounded = B.grounded_env(s.env, obs)
                for layer, env in ((0, s.env), (1, grounded)):
                    got = p.predict(env)
                    if tallies[p.name, layer].add(got, want, s):
                        fh.write(f"{s.case_id},{s.count},{p.name},{layer},"
                                 f"{got},{want},MISMATCH\n")

    print(f"{checked} distinct witnesses evaluated in {time.time() - started:.0f}s "
          f"({empty} short-circuited by IsEmptyTensor=1)\n")

    head = f"{'dimension':<17}{'exactness':<16}{'  input-only':>44}{'  +observed':>44}"
    print(head)
    print(f"{'':>33}{'agree':>8}{'differ':>7}{'unknown':>8}{'answered':>9}"
          f"{'accur':>9}{'agree':>8}{'differ':>7}{'unknown':>8}{'answered':>9}{'accur':>9}")
    bad: set = set()
    for p in sorted(preds, key=lambda p: (p.exactness, p.name)):
        t0, t1 = tallies[p.name, 0], tallies[p.name, 1]
        flag = ""
        if t0.differ or t1.differ:
            bad.add(p.name)
            flag = "  <-- MISMATCH"
        print(f"  {p.name:<16}{p.exactness:<16}{t0.line()}{t1.line()}{flag}")

    if bad:
        print("\nDERIVATION_RUNTIME_MISMATCH in: " + ", ".join(sorted(bad)))
        for dim in sorted(bad):
            for layer in (0, 1):
                t = tallies[dim, layer]
                for cid, layout, got, want in t.examples:
                    print(f"  [{dim} layer{layer}] {cid} layout={layout}: "
                          f"predicted {got}, actual {want}")
    print(f"\n-> {out}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
