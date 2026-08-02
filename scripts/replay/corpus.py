# -*- coding: utf-8 -*-
"""The recorded replay corpus, read once and deduplicated.

Six hundred thousand rows describe four hundred thousand distinct inputs, and
an analysis that walks the rows pays for the difference twice: once building
the case and its environment, once evaluating trees against it. Both are
functions of the input alone, so a repeated input has nothing new to say and
is folded into a weight.

Every consumer here is a scan with an answer that only sharpens as it runs, so
each takes a time budget and reports how far it got rather than running for as
long as the corpus happens to be.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from . import bridge as B
from . import inputs as I
from . import runner as R


@dataclass(slots=True)
class Sample:
    """One distinct input, and what the host made of it.

    `case` and `env` are built on first use rather than up front: holding four
    hundred thousand of these while every one is fully expanded pushes the
    process into swapping, which is where the slow actually comes from. The
    fields most consumers never touch stay unbuilt.
    """

    case_id: str
    row: dict
    count: int = 1          # rows that collapsed onto this input
    ok: bool = False
    key: int = 0
    _case: I.Case | None = None
    _env: dict | None = None

    @property
    def case(self) -> I.Case:
        if self._case is None:
            self._case = case_of(self.row)
        return self._case

    @property
    def env(self) -> dict:
        if self._env is None:
            self._env = B.env_of(self.case)
        return self._env


@dataclass
class Scan:
    """What a pass over the corpus managed to look at."""

    rows: int = 0
    distinct: int = 0
    accepted: int = 0
    refused: int = 0
    seconds: float = 0.0
    stopped_early: bool = False

    def report(self) -> str:
        how = "budget reached" if self.stopped_early else "corpus exhausted"
        return (f"{self.rows} rows -> {self.distinct} distinct inputs "
                f"({self.accepted} accepted, {self.refused} refused) "
                f"in {self.seconds:.0f}s, {how}")


def case_of(row: dict) -> I.Case:
    """Rebuild the case a recorded row was produced from.

    Older runs wrote fewer columns, so anything missing takes the default the
    generator would have used.
    """
    def s(name, dflt=""):
        v = row.get(name, dflt)
        return dflt if v in ("", "None") else v

    return I.Case(
        layout=s("layout", "BSND"), dtype=s("dtype", "FLOAT16"),
        b=int(s("b", 1)), s1=int(s("s1", 128)), s2=int(s("s2", 128)),
        n2=int(s("n2", 1)), g=int(s("g", 1)), d=int(s("d", 128)),
        d1=int(s("d1")) if s("d1") else None,
        atten_mask=s("atten_mask", "none"), pse=s("pse", "0") == "1",
        pse_shape=s("pse_shape", "bnss"), pse_type=int(s("pse_type", 1)),
        rope=s("rope", "0") == "1", keep_prob=float(s("keep_prob", 1.0)),
        sparse_mode=int(s("sparse_mode", 0)),
        pre_tokens=int(s("pre_tokens", 65536)),
        next_tokens=int(s("next_tokens", 65536)),
        out_dtype=int(s("out_dtype", 0)),
        deterministic=int(s("deterministic", 0)),
        seq_q=[int(x) for x in s("seq_q").split("/") if x] or None,
        seq_kv=[int(x) for x in s("seq_kv").split("/") if x] or None,
    )


def scan(limit: int = 0, timeout: float = 300.0) -> tuple[list[Sample], Scan]:
    """Distinct inputs from every recorded run, newest file last.

    `timeout` is a budget for the whole pass, in seconds. Hitting it stops the
    scan and says so; it does not fail, because a verdict over part of the
    corpus is still a verdict and every one of these checks is monotone.
    """
    started = time.time()
    stat = Scan()
    seen: dict[tuple, Sample] = {}
    cols = [c for c in I.describe(I.Case()).keys()]

    for path in sorted(R.CACHE.glob("fag_key_cases*.csv")):
        lines = path.read_text(encoding="utf-8").splitlines()
        if not lines:
            continue
        head = lines[0].split(",")
        idx = [head.index(c) for c in cols if c in head]
        for line in lines[1:]:
            f = line.split(",")
            if len(f) != len(head):
                continue
            stat.rows += 1
            sig = tuple(f[i] for i in idx)
            got = seen.get(sig)
            if got is not None:
                got.count += 1
                continue
            row = dict(zip(head, f))
            ok = row.get("ok") == "1"
            seen[sig] = Sample(
                case_id=row.get("case_id", ""),
                row=row,
                ok=ok,
                key=int(row["tiling_key"]) if ok and row.get("tiling_key") else 0,
            )
            stat.accepted += ok
            stat.refused += not ok
            if limit and len(seen) >= limit:
                stat.stopped_early = True
                break
            if not stat.rows % 4096 and time.time() - started > timeout:
                stat.stopped_early = True
                break
        if stat.stopped_early:
            break

    stat.distinct = len(seen)
    stat.seconds = time.time() - started
    return list(seen.values()), stat


def with_env(samples: list[Sample], timeout: float = 300.0) -> Iterator[Sample]:
    """Accepted samples, yielding within a time budget.

    The environment builds itself on first read. The budget is here so a pass
    that stalls on the tail reports what it saw rather than running for as
    long as the corpus happens to be.
    """
    started = time.time()
    for i, s in enumerate(samples):
        if not i % 2048 and time.time() - started > timeout:
            return
        yield s
