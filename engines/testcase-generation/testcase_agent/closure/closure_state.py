"""Authoritative, solver-free snapshot of the D/R/E/U closure sets."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from testcase_agent.closure import ledger
from testcase_agent.closure.finite_predicate import Truth, evaluate
from testcase_agent.closure.ledger import baseline_fingerprint
from testcase_agent.closure import workspace as W


def legal_domain(
    d_tpl: Iterable[int],
    *,
    relations: Iterable[dict[str, Any]] = (),
) -> tuple[set[int], list[dict[str, Any]]]:
    """Apply only exactly false finite relations; unknown values stay in D."""
    keys: set[int] = set()
    audit: list[dict[str, Any]] = []
    rules = list(relations)
    for key in d_tpl:
        dims = W.decode(int(key))
        verdicts = [evaluate(rule, dims) for rule in rules]
        false_rules = [i for i, verdict in enumerate(verdicts) if verdict.result is Truth.FALSE]
        unknown_rules = [i for i, verdict in enumerate(verdicts) if verdict.result in {Truth.UNKNOWN, Truth.UNSUPPORTED}]
        if not false_rules:
            keys.add(int(key))
        audit.append(
            {
                "key": int(key),
                "kept": not bool(false_rules),
                "false_rules": false_rules,
                "unknown_or_unsupported_rules": unknown_rules,
            }
        )
    return keys, audit


def build(
    ws: W.Workspace | None = None,
    *,
    relations: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    ws = (ws or W.default_workspace()).ensure()
    d_tpl = set(ledger.declared())
    d, relation_audit = legal_domain(d_tpl, relations=relations)
    r = ledger.load_R(ws)
    e = ledger.load_E(ws)
    u = d - (r & d) - e
    return {
        "schema": "tg-closure-state/v1",
        "baseline": baseline_fingerprint(ws.root),
        "D_tpl": sorted(d_tpl),
        "D": sorted(d),
        "R": sorted(r),
        "E": sorted(e),
        "U": sorted(u),
        "counts": {"D_tpl": len(d_tpl), "D": len(d), "R": len(r), "E": len(e), "U": len(u)},
        "invariants": {
            "r_intersects_e": sorted(r & e),
            "e_subset_d": sorted(e - d),
            "unknown_never_removed": all(
                row["kept"] or bool(row["false_rules"]) for row in relation_audit
            ),
        },
        "relation_audit": relation_audit,
    }


def write(ws: W.Workspace | None = None, *, relations: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
    import yaml

    ws = (ws or W.default_workspace()).ensure()
    document = build(ws, relations=relations)
    path = ws.report("closure_state.yaml")
    path.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"path": path.as_posix(), **document}
