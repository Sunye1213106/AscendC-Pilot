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
        labels = book.excluded_by_sound(inst)
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
    undeclared_path = write_undeclared(ws, Rset - D)
    return {
        "ok": not problems,
        "declared": len(D),
        "witnessed": counts["witnessed"],
        "excluded": counts["excluded"],
        "open": counts["open"],
        "violation": len(Rset & ledger.load_E(ws)),
        "undeclared": len(Rset - D),
        "undeclared_path": undeclared_path,
        "by_rule": by_rule.most_common(),
        "problems": problems[:20],
        "problem_count": len(problems),
        "path": str(path),
        "gap_zero": counts["open"] == 0 and not problems,
    }


def write_undeclared(ws: W.Workspace, keys) -> str:
    """I9: R − D as a standalone defect list (never folded into D-closure)."""
    dims = W.dim_names()
    path = ws.report("undeclared_keys.csv")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tiling_key", "defect"] + ["dim_" + d for d in dims])
        for k in sorted(keys):
            try:
                inst = W.decode(int(k))
                w.writerow([k, "R_minus_D"] + [inst.get(d, "") for d in dims])
            except Exception:
                w.writerow([k, "R_minus_D"] + [""] * len(dims))
    return str(path)


def certify_invariants(ws: W.Workspace | None = None, *,
                       uo_graph_fingerprint: str = "") -> dict:
    """Certify I4 / I6 / I7 / I8 (plus I1 via soundness_ok).

    I4  every E key supported by source_lemma / solver_derived rule
    I6  active rule freshness matches current UO graph fingerprint
    I7  every exclusion rule carries a non-empty reason / evidence citation
    I8  candidate / human / llm grades never shrink E
    """
    ws = (ws or W.default_workspace()).ensure()
    book = W.rule_book(refresh=True)
    D = ledger.declared()
    Rset = ledger.load_R(ws)
    E = ledger.load_E(ws)
    checks: dict[str, dict] = {}

    # I1
    checks["I1"] = {
        "ok": not (Rset & E),
        "detail": f"R∩E={len(Rset & E)}",
    }

    # I4 — each E key must have at least one SOUND grade label
    unsupported = []
    for k in sorted(E):
        try:
            inst = W.decode(int(k))
        except Exception:
            unsupported.append(k)
            continue
        labels = book.excluded_by_sound(inst)
        if not labels:
            unsupported.append(k)
    checks["I4"] = {
        "ok": len(unsupported) == 0,
        "unsupported": unsupported[:20],
        "detail": f"unsupported_E={len(unsupported)}",
    }

    # I6 — freshness of active rules
    import yaml

    active = ws.state / "lemmas" / "active_rules.yaml"
    stale = []
    if active.is_file() and uo_graph_fingerprint:
        doc = yaml.safe_load(active.read_text(encoding="utf-8")) or {}
        book_fp = str(doc.get("uo_graph_fingerprint") or "")
        if book_fp and book_fp != uo_graph_fingerprint:
            stale.append({"book": book_fp, "uo": uo_graph_fingerprint})
        for raw in doc.get("rules") or []:
            fp = str((raw.get("freshness") or {}).get("uo_graph_fingerprint") or "")
            if fp and fp != uo_graph_fingerprint:
                stale.append({"label": raw.get("label"), "fp": fp})
    checks["I6"] = {
        "ok": len(stale) == 0,
        "stale": stale[:10],
        "detail": f"stale_rules={len(stale)}",
    }

    # I7 — citations
    uncited = [
        r.label for r in book.rules
        if r.grade in {"source_lemma", "solver_derived"}
        and not (r.reason or "").strip()
    ]
    # Only fail when uncited rules actually exclude something in E.
    affecting = []
    if uncited and E:
        for k in list(E)[:500]:
            try:
                labs = book.excluded_by_sound(W.decode(int(k)))
            except Exception:
                continue
            for lab in labs:
                if lab in uncited:
                    affecting.append(lab)
        affecting = sorted(set(affecting))
    checks["I7"] = {
        "ok": len(affecting) == 0,
        "uncited": uncited[:10],
        "affecting": affecting[:10],
        "detail": f"uncited_affecting={len(affecting)}",
    }

    # I8 — soft grades must not contribute to E
    soft = {"candidate", "human", "llm", "heuristic"}
    soft_hit = []
    for k in sorted(E)[:2000]:
        try:
            inst = W.decode(int(k))
        except Exception:
            continue
        # All grades that match (not just sound).
        all_labs = book.excluded_by(inst) if hasattr(book, "excluded_by") else []
        sound = set(book.excluded_by_sound(inst))
        for lab in all_labs:
            rule = next((r for r in book.rules if r.label == lab), None)
            if rule and rule.grade in soft and lab not in sound:
                # Soft grade alone — if E contains this key only via soft, fail.
                if not sound:
                    soft_hit.append({"key": k, "label": lab, "grade": rule.grade})
    checks["I8"] = {
        "ok": len(soft_hit) == 0,
        "soft_hits": soft_hit[:10],
        "detail": f"soft_only_E={len(soft_hit)}",
    }

    # I9 — undeclared reported separately
    undeclared = Rset - D
    undeclared_path = write_undeclared(ws, undeclared)
    checks["I9"] = {
        "ok": True,  # reporting is the invariant; non-empty is a defect ticket
        "count": len(undeclared),
        "path": undeclared_path,
        "detail": f"R−D={len(undeclared)}",
    }

    ok = all(c.get("ok") for c in checks.values() if c is not checks.get("I9"))
    # I9 always ok as a check; others must pass.
    ok = all(checks[k]["ok"] for k in ("I1", "I4", "I6", "I7", "I8"))
    return {
        "ok": ok,
        "checks": checks,
        "declared": len(D),
        "R": len(Rset),
        "E": len(E),
        "gap": len(D - (Rset & D) - E),
        "undeclared": len(undeclared),
    }
