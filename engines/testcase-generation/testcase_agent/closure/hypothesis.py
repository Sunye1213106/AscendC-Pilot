# -*- coding: utf-8 -*-
"""Minimal dimension combinations the residue asks for and R never produced.

These are *hypotheses*, never lemmas. "No witness has this combination" is a
statement about what replay happened to find, and the closure argument refuses
to read that as "unreachable" — that circularity is what the ledger exists to
prevent. What they are good for is aiming: a producer handed a minimised,
already-R-consistent antecedent has to confirm or refute it against the source,
instead of inventing candidates a witness disproves on arrival.

The minimisation is the part reading code cannot do: drop every dimension whose
removal keeps the combination absent from R, so what survives is the weakest
antecedent still worth proving.

Operator-agnostic by construction — dimension names come from the workspace key
schema and values from key decoding. Operator-specific guard knowledge belongs
in skills, not here.
"""

from __future__ import annotations

import collections
from typing import Any, Mapping

from testcase_agent.closure import ledger
from testcase_agent.closure import residual as RES
from testcase_agent.closure import workspace as W

# Grade for engine-proposed antecedents. Deliberately outside SOUND_GRADES:
# nothing here may shrink E until a producer cites source for it.
HYPOTHESIS_GRADE = "hypothesis"


def _match(inst: Mapping[str, Any], when: Mapping[str, Any]) -> bool:
    try:
        from replay.rule_engine import match_when

        return match_when(inst, when)
    except Exception:
        return all(str(inst.get(d)) == str(v) for d, v in when.items())


def _r_hits(when: Mapping[str, Any], wit: list[Mapping[str, Any]]) -> int:
    return sum(1 for w in wit if _match(w, when))


def _open_hits(when: Mapping[str, Any], opn: list[Mapping[str, Any]]) -> int:
    return sum(1 for o in opn if _match(o, when))


def minimise_when(
    when: Mapping[str, Any],
    wit: list[Mapping[str, Any]],
    opn: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Weakest sub-combination of ``when`` still absent from R.

    Greedy: repeatedly drop whichever dimension leaves R empty and covers the
    most residue. Returns ``{}`` when the input already hits a witness.
    """
    current = {str(k): v for k, v in when.items()}
    if not current or _r_hits(current, wit):
        return {}
    while len(current) > 1:
        best: tuple[int, str] | None = None
        for dim in list(current):
            trial = {k: v for k, v in current.items() if k != dim}
            if not trial or _r_hits(trial, wit):
                continue
            gain = _open_hits(trial, opn)
            if best is None or gain > best[0]:
                best = (gain, dim)
        if best is None:
            break
        current.pop(best[1])
    return current


def fold_set_terms(
    candidates: list[dict[str, Any]],
    wit: list[Mapping[str, Any]],
    opn: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Fold siblings differing in one dimension into a single ``in`` term.

    Antecedents that agree everywhere except one dimension are one proposition
    with one proof obligation; keeping them apart inflates the rule book and
    hides that they stand or fall together.
    """
    by_shape: dict[tuple, list[dict[str, Any]]] = collections.OrderedDict()
    for cand in candidates:
        when = cand.get("when") or {}
        for dim, val in when.items():
            if isinstance(val, (list, dict)):
                continue
            rest = tuple(sorted((k, str(v)) for k, v in when.items() if k != dim))
            by_shape.setdefault((dim, rest), []).append(cand)

    folded: list[dict[str, Any]] = []
    consumed: set[int] = set()
    for (dim, _rest), group in by_shape.items():
        if len(group) < 2 or any(id(c) in consumed for c in group):
            continue
        values = sorted({str(c["when"][dim]) for c in group})
        merged = dict(group[0]["when"])
        merged[dim] = {"in": values}
        if _r_hits(merged, wit):
            continue
        folded.append(
            {
                "when": merged,
                "closes": _open_hits(merged, opn),
                "folded_dim": dim,
                "folded_values": values,
                "folded_from": len(group),
            }
        )
        consumed.update(id(c) for c in group)

    return folded + [c for c in candidates if id(c) not in consumed]


def propose(
    ws: W.Workspace | None = None,
    *,
    max_candidates: int = 32,
    analysis: dict | None = None,
) -> dict[str, Any]:
    """Minimised, R-consistent antecedents covering the current residue."""
    ws = (ws or W.default_workspace()).ensure()
    res = analysis or RES.analyse(ws)

    Rset, E, D = ledger.load_R(ws), ledger.load_E(ws), ledger.declared()
    wit = [dict(x) for x in W.decode_many(sorted(Rset))]
    open_keys = sorted(D - Rset - E)
    opn = [dict(x) for x in W.decode_many(open_keys)]

    raw: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for pattern in res.get("open_patterns") or []:
        if not pattern.get("exclusive_to_open"):
            continue
        when = minimise_when(pattern.get("when") or {}, wit, opn)
        if not when:
            continue
        sig = tuple(sorted((k, str(v)) for k, v in when.items()))
        if sig in seen:
            continue
        seen.add(sig)
        raw.append(
            {
                "when": when,
                "closes": _open_hits(when, opn),
                "from_pattern": dict(pattern.get("when") or {}),
            }
        )

    merged = fold_set_terms(raw, wit, opn)
    merged = [c for c in merged if int(c.get("closes") or 0) > 0]
    merged.sort(key=lambda c: int(c.get("closes") or 0), reverse=True)
    merged = merged[:max_candidates]

    try:
        from replay.rule_engine import when_label
    except Exception:
        def when_label(w):  # type: ignore[misc]
            return " + ".join(f"{k}={v}" for k, v in w.items())

    hypotheses: list[dict[str, Any]] = []
    for i, cand in enumerate(merged):
        entry = {
            "id": f"HYP_{i:03d}",
            "grade": HYPOTHESIS_GRADE,
            "kind": "combo",
            "when": cand["when"],
            "label": when_label(cand["when"]),
            "closes_open": cand["closes"],
            "r_hits": 0,
            "verdict": "INSUFFICIENT",
            "proposition": "",
            "source_citations": [],
            "codemap_anchors": [],
            "obligations": [
                {
                    "id": "source_forbids_combination",
                    "status": "OPEN",
                    "evidence": "",
                    "ask": (
                        "Cite the host code that makes this combination "
                        "impossible, or refute the hypothesis."
                    ),
                }
            ],
            "note": (
                "Engine-proposed antecedent: minimised and absent from R. "
                "Absence from R is not unreachability; source evidence required."
            ),
        }
        for key in ("folded_dim", "folded_values", "folded_from", "from_pattern"):
            if key in cand:
                entry[key] = cand[key]
        hypotheses.append(entry)

    covered = {
        i for i, o in enumerate(opn)
        if any(_match(o, h["when"]) for h in hypotheses)
    }
    return {
        "schema": "tg-lemma-hypotheses/v1",
        "open": len(open_keys),
        "R": len(Rset),
        "candidate_count": len(hypotheses),
        "covered_open": len(covered),
        "pattern_dims": res.get("pattern_dims"),
        "hypotheses": hypotheses,
    }
