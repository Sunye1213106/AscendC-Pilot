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
from pathlib import Path
from typing import Any, Iterable, Mapping

from testcase_agent.closure import ledger
from testcase_agent.closure import workspace as W


def _match_when(inst: Mapping[str, Any], when: Mapping[str, Any]) -> bool:
    try:
        from replay.rule_engine import match_when

        return match_when(inst, when)
    except Exception:
        return all(str(inst.get(d)) == str(v) for d, v in when.items())


def verify(when: Mapping[str, Any], witnesses: Iterable[Mapping[str, Any]]
           ) -> dict:
    """Return whether `when` holds of any real witness."""
    hits = [w for w in witnesses if _match_when(w, when)]
    return {
        "ok": len(hits) == 0,
        "refuted": len(hits) > 0,
        "hit_count": len(hits),
        "counterexamples": [dict(w) for w in hits[:5]],
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

    try:
        from replay.rule_engine import norm_when, when_label
    except Exception:  # pragma: no cover - fallback when replay is unavailable
        def norm_when(raw):  # type: ignore[misc]
            return {str(k): str(v) for k, v in (raw or {}).items()}

        def when_label(w):  # type: ignore[misc]
            return " + ".join("%s=%s" % kv for kv in w.items())

    survivors, closed, refuted = [], set(), []
    for lem in lemmas:
        when = norm_when(lem.get("when"))
        if not when:
            continue
        check = verify(when, wit)
        label = str(lem.get("label") or when_label(when))
        n_open = sum(1 for _, o in opn if _match_when(o, when))
        if check["refuted"]:
            refuted.append({
                "label": label,
                "hits": check["hit_count"],
                "tag": lem.get("tag", ""),
                "counterexamples": check["counterexamples"],
            })
            continue
        survivors.append({**lem, "when": when, "label": label, "closes": n_open})
        for k, o in opn:
            if _match_when(o, when):
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
    """Apply the sound rule book to every declared key and write E.

    Only ``SOUND_GRADES`` (source_lemma / solver_derived) shrink E. When a
    newly witnessed key intersects a rule's exclusion set, the conflicting
    rules are recorded as revoked and E is rebuilt without them — not a
    deadlock that refuses to write anything.
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
        labels = book.excluded_by_sound(inst)
        if labels:
            excluded[k] = labels

    bad = {k: v for k, v in excluded.items() if k in Rset}
    revoked: list[dict] = []
    if bad:
        # Revoke: drop every label that hit a real witness, then recompute E.
        bad_labels = {lab for labs in bad.values() for lab in labs}
        for lab in sorted(bad_labels):
            revoked.append({
                "label": lab,
                "status": "refuted",
                "reason": "new_R intersects rule_excluded_keys",
                "witness_keys": sorted(k for k, labs in bad.items() if lab in labs)[:20],
            })
        excluded = {
            k: [lab for lab in labs if lab not in bad_labels]
            for k, labs in excluded.items()
            if any(lab not in bad_labels for lab in labs)
        }
        # Drop empty entries.
        excluded = {k: labs for k, labs in excluded.items() if labs}
        lemmas_dir = ws.state / "lemmas"
        lemmas_dir.mkdir(parents=True, exist_ok=True)
        revoked_path = lemmas_dir / "revoked_rules.yaml"
        try:
            import yaml

            prev = []
            if revoked_path.is_file():
                prev = list(yaml.safe_load(revoked_path.read_text(encoding="utf-8")) or [])
            yaml.safe_dump(
                prev + revoked,
                revoked_path.open("w", encoding="utf-8"),
                allow_unicode=True,
                sort_keys=False,
            )
        except Exception:
            revoked_path.write_text(
                "\n".join(str(r) for r in revoked) + "\n", encoding="utf-8"
            )

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
        "revoked": revoked,
        "revoked_count": len(revoked),
    }


def soundness_ok(ws: W.Workspace | None = None) -> bool:
    """I1: R ∩ E = ∅."""
    ws = ws or W.default_workspace()
    return not (ledger.load_R(ws) & ledger.load_E(ws))


def reverify_active(
    ws: W.Workspace | None = None,
    *,
    current_uo_graph_fingerprint: str = "",
) -> dict:
    """Re-run sound apply after corpus growth; revoke rules contradicted by new R.

    Called after every corpus.commit that may have enlarged R. Fail-closed on
    freshness: rules whose uo_graph_fingerprint disagrees with the *current*
    UO fingerprint (preferred) or the active book stamp are marked stale and
    dropped from E. Without an active book, E stays empty (seed rules never
    auto-apply).
    """
    ws = (ws or W.default_workspace()).ensure()
    import yaml

    lemmas_dir = ws.state / "lemmas"
    active_path = lemmas_dir / "active_rules.yaml"
    if not active_path.is_file():
        # No promoted rules yet — leave E empty and rebuild open from R only.
        D = ledger.declared()
        Rset = ledger.load_R(ws)
        ws.e_path.write_text("", encoding="utf-8", newline="\n")
        if ws.e_why_path:
            try:
                ws.e_why_path.write_text("key,rules\n", encoding="utf-8")
            except Exception:
                pass
        gap = D - (Rset & D)
        ws.open_path.write_text(
            "".join("%d\n" % k for k in sorted(gap)),
            encoding="utf-8",
            newline="\n",
        )
        return {
            "ok": True,
            "excluded": 0,
            "gap": len(gap),
            "revoked_count": 0,
            "stale": [],
            "note": "no_active_rules",
        }

    doc = yaml.safe_load(active_path.read_text(encoding="utf-8")) or {}
    book_fp = str(doc.get("uo_graph_fingerprint") or "")
    expected_fp = str(current_uo_graph_fingerprint or "")
    kept = []
    stale = []
    if expected_fp and book_fp and book_fp != expected_fp:
        stale.append({
            "label": "*",
            "status": "stale",
            "reason": "active_book_uo_graph_fingerprint_mismatch",
            "book_fp": book_fp,
            "current_fp": expected_fp,
        })
        kept = []
    else:
        compare_fp = expected_fp or book_fp
        for raw in doc.get("rules") or []:
            fp = str((raw.get("freshness") or {}).get("uo_graph_fingerprint") or "")
            if compare_fp and fp and fp != compare_fp:
                stale.append({
                    "label": raw.get("label") or raw.get("when"),
                    "status": "stale",
                    "reason": "uo_graph_fingerprint_mismatch",
                    "rule_fp": fp,
                    "current_fp": compare_fp,
                })
                continue
            kept.append(raw)
    if stale:
        doc["rules"] = kept
        active_path.write_text(
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        stale_path = lemmas_dir / "stale_rules.yaml"
        prev = []
        if stale_path.is_file():
            prev = list(yaml.safe_load(stale_path.read_text(encoding="utf-8")) or [])
        stale_path.write_text(
            yaml.safe_dump(prev + stale, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    out = apply_rules(ws, refresh=True)
    out["stale"] = stale
    out["stale_count"] = len(stale)
    return out


def promote_reviewed(
    review: Mapping,
    ws: W.Workspace | None = None,
    *,
    source_revision: str = "",
    uo_graph_fingerprint: str = "",
) -> dict:
    """Write accepted review entries into ``lemmas/active_rules.yaml``.

    Only candidates with grade in SOUND_GRADES and a non-empty proof block
    are promoted. Package ``proof_rules.yaml`` remains seed-only.
    """
    import yaml
    from testcase_agent.closure.certificate import validate as validate_certificate

    try:
        from replay.rule_engine import SOUND_GRADES as _SG
    except Exception:
        _SG = frozenset({"solver_derived", "source_lemma"})

    ws = (ws or W.default_workspace()).ensure()
    lemmas_dir = ws.state / "lemmas"
    lemmas_dir.mkdir(parents=True, exist_ok=True)
    active_path = lemmas_dir / "active_rules.yaml"

    prev: dict = {}
    if active_path.is_file():
        prev = yaml.safe_load(active_path.read_text(encoding="utf-8")) or {}
    rules = list(prev.get("rules") or [])
    accepted = list(review.get("accepted") or [])
    promoted = 0
    skipped = 0

    def _load_evidence_pack(raw: Mapping) -> dict | None:
        path_hint = str(
            raw.get("evidence_path")
            or (raw.get("certificate") or {}).get("evidence_path")
            or ""
        ).strip().replace("\\", "/")
        lead_id = str(raw.get("lead_id") or "").strip()
        candidates: list[Path] = []
        if path_hint:
            p = Path(path_hint)
            if p.is_absolute():
                candidates.append(p)
            else:
                candidates.append(ws.root / path_hint)
                if "lemmas/evidence/" in path_hint:
                    candidates.append(ws.state / "lemmas" / "evidence" / Path(path_hint).name)
                elif path_hint.startswith("tg/closure/"):
                    candidates.append(ws.state / path_hint[len("tg/closure/"):])
                else:
                    candidates.append(ws.state / path_hint)
        if lead_id:
            candidates.append(ws.state / "lemmas" / "evidence" / f"{lead_id}.yaml")
        for cand in candidates:
            try:
                if cand.is_file():
                    doc = yaml.safe_load(cand.read_text(encoding="utf-8")) or {}
                    if isinstance(doc, dict) and doc.get("entries") is not None:
                        return doc
            except Exception:
                continue
        return None

    for raw in accepted:
        evidence_pack = _load_evidence_pack(raw)
        certificate_check = validate_certificate(
            raw,
            evidence_pack=evidence_pack,
            operator_root=ws.root,
        )
        if not certificate_check["ok"]:
            skipped += 1
            continue
        grade = str(raw.get("grade") or "source_lemma")
        if grade not in _SG and grade not in ("source_lemma_verified", "solver_unsat_verified"):
            skipped += 1
            continue
        # Map verified aliases onto SOUND_GRADES storage grades.
        if grade == "source_lemma_verified":
            grade = "source_lemma"
        if grade == "solver_unsat_verified":
            grade = "solver_derived"
        proof = raw.get("proof") or {}
        required = (
            "entry_branches_checked",
            "early_returns_checked",
            "all_writers_checked",
            "execution_order_checked",
            "exception_branches_checked",
        )
        if not all(proof.get(k) for k in required):
            skipped += 1
            continue
        entry = {
            "kind": str(raw.get("kind") or "combo"),
            "grade": grade,
            "when": dict(raw.get("when") or {}),
            "dim": str(raw.get("dim") or ""),
            "value": str(raw.get("value") or ""),
            "label": str(raw.get("label") or ""),
            "reason": str(raw.get("reason") or ""),
            "proof": dict(proof),
            "verification": dict(raw.get("verification") or {}),
            "certificate": dict(raw.get("certificate") or {}),
            "freshness": {
                "source_revision": source_revision or str(
                    (raw.get("freshness") or {}).get("source_revision") or ""
                ),
                "uo_graph_fingerprint": uo_graph_fingerprint or str(
                    (raw.get("freshness") or {}).get("uo_graph_fingerprint") or ""
                ),
            },
        }
        rules.append(entry)
        promoted += 1

    cold_fp = ""
    try:
        from testcase_agent.closure.cold_start import load_cold_start

        cold_fp = str(load_cold_start(ws).get("fingerprint") or "")
    except Exception:
        cold_fp = ""
    doc = {
        "schema": "tg-active-rules/v1",
        "uo_graph_fingerprint": uo_graph_fingerprint,
        "source_revision": source_revision,
        "cold_start_fingerprint": cold_fp,
        "rules": rules,
    }
    active_path.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    try:
        from testcase_agent.closure.cold_start import append_chain

        append_chain(
            ws,
            "promote",
            {
                "promoted": promoted,
                "skipped": skipped,
                "active_count": len(rules),
                "labels": [str(r.get("label") or "") for r in rules[-promoted:]] if promoted else [],
            },
        )
    except Exception:
        pass
    # Force rule_book reload on next apply.
    try:
        from replay import rule_engine as RE

        RE.default_book(refresh=True)
    except Exception:
        pass
    return {
        "ok": True,
        "promoted": promoted,
        "skipped": skipped,
        "active_path": str(active_path),
        "active_count": len(rules),
    }
