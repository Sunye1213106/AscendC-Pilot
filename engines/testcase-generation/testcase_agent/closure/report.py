# -*- coding: utf-8 -*-
"""The closure report: for every declared key, the evidence that settles it.

Two ways a key may be settled and no third:

  witnessed   a real host run produced it, named by the batch and case that did
  excluded    a rule forbids it, and the rule cites the source lines it read

The report fails loudly rather than rounding up. A key with neither, a key
with both, or a rule with no citation each stop it.
"""

from __future__ import annotations

import collections
import csv

from testcase_agent.closure import ledger
from testcase_agent.closure import workspace as W


def report(ws: W.Workspace | None = None, *, refresh: bool = True) -> dict:
    """Write the per-key closure CSV and return the summary counts."""
    ws = (ws or W.default_workspace()).ensure()
    D = ledger.declared()
    Rset = ledger.load_R(ws)
    src = ledger.build(ws) if not ws.r_path.is_file() else {
        int(line.split(",")[0]): (line.split(",", 1)[1]
                                  if "," in line else "replay")
        for line in ws.r_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and line.split(",")[0].isdigit()
    }
    book = W.rule_book(refresh=refresh)
    reason_of = {r.label: (r.reason or "").strip() for r in book.rules}
    dims = W.dim_names()

    rows, problems = [], []
    counts = collections.Counter()
    for k in sorted(D):
        inst = W.decode(int(k))
        witnessed = k in Rset
        labels = book.excluded_by(inst)
        if witnessed and labels:
            problems.append((k, "witnessed AND excluded by " + labels[0]))
            rows.append([k, "CONFLICT", labels[0],
                         " ".join(reason_of.get(labels[0], "").split())]
                        + [inst[d] for d in dims])
        elif witnessed:
            counts["witnessed"] += 1
            rows.append([k, "witnessed", src.get(k, "replay"), ""]
                        + [inst[d] for d in dims])
        elif labels:
            counts["excluded"] += 1
            why = reason_of.get(labels[0], "")
            if not why:
                problems.append((k, "excluded by %s with no citation" % labels[0]))
            rows.append([k, "excluded", labels[0], " ".join(why.split())]
                        + [inst[d] for d in dims])
        else:
            counts["open"] += 1
            problems.append((k, "neither witnessed nor excluded"))
            rows.append([k, "OPEN", "", ""] + [inst[d] for d in dims])

    path = ws.report("closure.csv")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tiling_key", "verdict", "evidence", "source_citation"]
                   + ["dim_" + d for d in dims])
        w.writerows(rows)

    by_rule = collections.Counter(r[2] for r in rows if r[1] == "excluded")
    return {
        "ok": not problems,
        "declared": len(D),
        "witnessed": counts["witnessed"],
        "excluded": counts["excluded"],
        "open": counts["open"],
        "violation": len(Rset & ledger.load_E(ws)),
        "undeclared": len(Rset - D),
        "by_rule": by_rule.most_common(),
        "problems": problems[:20],
        "problem_count": len(problems),
        "path": str(path),
        "gap_zero": counts["open"] == 0 and not problems,
    }
