# -*- coding: utf-8 -*-
"""Lemma verification and the E_sound exclusion set.

A lemma read out of the source can still be wrong -- the read can miss a path
that reassigns the value later. So every rule is first run against the whole
witness set. One witness satisfying a rule's `when` is a refutation, and the
rule does not get written.

Applying the rule book to D has the same gate at the end: a rule that excludes
a key some real run produced is wrong, and the run is what gets believed.
Writing the set without that check is how a closure argument comes to rest on
a lemma the host already disproved.
"""

from __future__ import annotations

import collections
import csv
from typing import Iterable, Mapping

from testcase_agent.closure import ledger
from testcase_agent.closure import workspace as W


def verify(when: Mapping[str, str], witnesses: Iterable[Mapping[str, str]]
           ) -> dict:
    """Return whether `when` holds of any real witness."""
    hits = [w for w in witnesses
            if all(str(w.get(d)) == str(v) for d, v in when.items())]
    return {
        "ok": len(hits) == 0,
        "refuted": len(hits) > 0,
        "hit_count": len(hits),
        "when": dict(when),
    }


def verify_lemmas(lemmas: Iterable[Mapping],
                  ws: W.Workspace | None = None) -> dict:
    """Check each proposed lemma against every real witness.

    Survivors are written to `lemmas_ok.txt`; keys they would close among the
    open set go to `closed_by_lemma.txt`. Refuted lemmas are reported and not
    written.
    """
    ws = (ws or W.default_workspace()).ensure()
    Rset, E, D = ledger.load_R(ws), ledger.load_E(ws), ledger.declared()
    wit = W.decode_many(sorted(Rset))
    open_keys = sorted(D - Rset - E)
    opn = list(zip(open_keys, W.decode_many(open_keys)))

    survivors, closed, refuted = [], set(), []
    for lem in lemmas:
        when = {str(k): str(v) for k, v in (lem.get("when") or {}).items()}
        if not when:
            continue
        check = verify(when, wit)
        label = " + ".join("%s=%s" % kv for kv in when.items())
        n_open = sum(1 for _, o in opn
                     if all(o.get(d) == v for d, v in when.items()))
        if check["refuted"]:
            refuted.append({"label": label, "hits": check["hit_count"],
                            "tag": lem.get("tag", "")})
            continue
        survivors.append({**lem, "when": when, "label": label, "closes": n_open})
        for k, o in opn:
            if all(o.get(d) == v for d, v in when.items()):
                closed.add(k)

    (ws.state / "lemmas_ok.txt").write_text(
        "".join("%s\t%s\n" % (s["label"], s.get("tag", "")) for s in survivors),
        encoding="utf-8", newline="\n")
    (ws.state / "closed_by_lemma.txt").write_text(
        "".join("%d\n" % k for k in sorted(closed)),
        encoding="utf-8", newline="\n")
    return {
        "ok": True,
        "survivors": len(survivors),
        "refuted": refuted,
        "closed": len(closed),
        "open_before": len(opn),
        "open_after": len(opn) - len(closed),
        "lemmas": survivors,
    }


def apply_rules(ws: W.Workspace | None = None, *, refresh: bool = True) -> dict:
    """Apply the rule book to every declared key and write E_sound.

    Refuses to write when any excluded key is also witnessed.
    """
    ws = (ws or W.default_workspace()).ensure()
    book = W.rule_book(refresh=refresh)
    D = ledger.declared()
    Rset = ledger.load_R(ws)

    excluded: dict[int, list[str]] = {}
    for k in sorted(D):
        try:
            inst = W.decode(int(k))
        except Exception:
            continue
        labels = book.excluded_by(inst)
        if labels:
            excluded[k] = labels

    bad = {k: v for k, v in excluded.items() if k in Rset}
    if bad:
        return {
            "ok": False,
            "error": "REFUTED RULES -- a real run produced these",
            "violating": [
                {"key": k, "rules": labels}
                for k, labels in list(bad.items())[:15]
            ],
            "violating_count": len(bad),
        }

    reasons = collections.Counter(labels[0] for labels in excluded.values())
    ws.e_path.write_text(
        "".join("%d\n" % k for k in sorted(excluded)),
        encoding="utf-8", newline="\n")
    with open(ws.e_why_path, "w", encoding="utf-8", newline="") as fh:
        fh.write("key,rules\n")
        for k in sorted(excluded):
            fh.write("%d,%s\n" % (k, " | ".join(excluded[k])))

    gap = D - (Rset & D) - set(excluded)
    ws.open_path.write_text(
        "".join("%d\n" % k for k in sorted(gap)),
        encoding="utf-8", newline="\n")
    return {
        "ok": True,
        "declared": len(D),
        "excluded": len(excluded),
        "R": len(Rset),
        "gap": len(gap),
        "by_rule": reasons.most_common(20),
        "e_path": str(ws.e_path),
    }


def soundness_ok(ws: W.Workspace | None = None) -> bool:
    """I1: R ∩ E = ∅."""
    ws = ws or W.default_workspace()
    return not (ledger.load_R(ws) & ledger.load_E(ws))
