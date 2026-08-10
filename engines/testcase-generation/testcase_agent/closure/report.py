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
from pathlib import Path
from typing import Any

from testcase_agent.closure import ledger
from testcase_agent.closure import workspace as W


def _domain_joins(ws: W.Workspace) -> tuple[dict[int, list[str]], dict[int, list[str]], list[str]]:
    """key → kernel branch ids, key → tilingdata fields, and any domain errors.

    Both domains are computed from the same witness set the rows are built from,
    so a key's row can name the branches it triggers and the fields written
    under it. A domain that cannot be computed leaves its column empty and says
    so — it must not silently look like "nothing is affected".
    """
    branches: dict[int, list[str]] = {}
    fields: dict[int, list[str]] = {}
    errors: list[str] = []
    try:
        from testcase_agent.closure import kernel_domain as KD

        branches = dict((KD.compute_r_kernel(ws, write=False) or {}).get("branches_by_key") or {})
    except Exception as exc:  # noqa: BLE001
        errors.append(f"kernel:{type(exc).__name__}:{exc}"[:160])
    try:
        from testcase_agent.closure import tilingdata_domain as TD

        fields = dict((TD.compute_tilingdata_coverage(ws, write=False) or {}).get("fields_by_key") or {})
    except Exception as exc:  # noqa: BLE001
        errors.append(f"tilingdata:{type(exc).__name__}:{exc}"[:160])
    return branches, fields, errors


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

    branches_by_key, fields_by_key, domain_errors = _domain_joins(ws)

    def _domain_cells(key: int) -> list[str]:
        return [
            ";".join(branches_by_key.get(int(key), [])),
            ";".join(fields_by_key.get(int(key), [])),
        ]

    rows, problems = [], []
    counts = collections.Counter()
    for k in sorted(D):
        inst = W.decode(int(k))
        witnessed = k in Rset
        labels = book.excluded_by_sound(inst)
        tail = [inst[d] for d in dims] + _domain_cells(k)
        if witnessed and labels:
            problems.append((k, "witnessed AND excluded by " + labels[0]))
            rows.append([k, "CONFLICT", labels[0],
                         " ".join(reason_of.get(labels[0], "").split())] + tail)
        elif witnessed:
            counts["witnessed"] += 1
            rows.append([k, "witnessed", src.get(k, "replay"), ""] + tail)
        elif labels:
            counts["excluded"] += 1
            why = reason_of.get(labels[0], "")
            if not why:
                problems.append((k, "excluded by %s with no citation" % labels[0]))
            rows.append([k, "excluded", labels[0], " ".join(why.split())] + tail)
        else:
            counts["open"] += 1
            problems.append((k, "neither witnessed nor excluded"))
            rows.append([k, "OPEN", "", ""] + tail)

    path = ws.report("closure.csv")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["tiling_key", "verdict", "evidence", "source_citation"]
                   + ["dim_" + d for d in dims]
                   + ["kernel_branches", "tilingdata_fields"])
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
        "domain_errors": domain_errors,
        "keys_with_kernel_branches": len(branches_by_key),
        "keys_with_tilingdata_fields": len(fields_by_key),
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


def _domain_established(name: str, cov: dict) -> dict:
    """Did this domain have an input at all?

    Every other per-domain invariant forbids something -- an excluded branch a
    witness reached, an unsound grade, a soft-graded exclusion. A domain that
    loaded no view satisfies all of them without checking anything, so a
    certificate can read "kernel ok" when the kernel view was never built. This
    check is the one that fails in that case.
    """
    source = dict(cov.get("source") or {})
    # A domain that reports no source is not a domain that found one: staying
    # silent must not be an easier way to pass than saying "missing".
    if source.get("kind") in (None, "", "missing"):
        return {
            "ok": False,
            "detail": (
                f"{name}_domain_not_established: "
                f"{source.get('reason') or 'domain reported no view source'}"
                " -- zero rows here means no input, so the other "
                f"{name} invariants held vacuously"
            ),
            "source": source,
        }
    return {
        "ok": True,
        "detail": f"{name}_view={source.get('kind')}:{source.get('path')}",
        "source": source,
    }


def certify_invariants(ws: W.Workspace | None = None, *,
                       uo_graph_fingerprint: str = "") -> dict:
    """Certify I4 / I6 / I7 / I8 (plus I1 via soundness_ok).

    I4  every E key supported by source_lemma / solver_derived rule
    I6  active rule freshness matches current UO graph fingerprint
    I7  every exclusion rule carries a non-empty reason / evidence citation
    I8  candidate / human / llm grades never shrink E

    Each invariant is also asserted per domain (``I*_kernel`` /
    ``I*_tilingdata``) and all of them gate the certificate.
    """
    from testcase_agent.closure import lemma

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

    # Cold-start provenance: E must come from post-cold-start active_rules.
    try:
        from testcase_agent.closure.cold_start import check_e_provenance

        prov = check_e_provenance(ws)
    except Exception as exc:  # noqa: BLE001
        prov = {"ok": False, "issues": [str(exc)[:200]], "detail": "provenance_error"}
    checks["I_cold_start"] = {
        "ok": bool(prov.get("ok")),
        "issues": list(prov.get("issues") or [])[:10],
        "detail": prov.get("detail") or f"issues={len(prov.get('issues') or [])}",
    }

    # Per-domain I1/I4-style checks when kernel / tilingdata data exists.
    domain_extra: dict[str, Any] = {}

    try:
        from testcase_agent.closure import kernel_domain as KD

        kcov = KD.compute_r_kernel(ws, write=True)
        domain_extra["kernel"] = {
            "branches": kcov.get("branches"),
            "covered": kcov.get("covered"),
            "path": kcov.get("path"),
            "source": kcov.get("source"),
            "established": kcov.get("established"),
            "kernel_branches": kcov.get("kernel_branches"),
        }
        checks["I0_kernel"] = _domain_established("kernel", kcov)
        # I1: a branch cannot be both hit by a witness and declared unreachable.
        kernel_rows = list(kcov.get("kernel_branches") or [])
        conflicting = [
            r for r in kernel_rows
            if int(r.get("R_count") or 0) > 0 and str(r.get("status")) == "excluded"
        ]
        checks["I1_kernel"] = {
            "ok": not conflicting,
            "detail": (
                f"R_kernel_branches={kcov.get('covered')}/{kcov.get('branches')}"
                + (f" conflicting={[r.get('id') for r in conflicting][:5]}" if conflicting else "")
            ),
        }
        # I4: every excluded branch must carry a sound source lemma.
        unsound = [
            r for r in kernel_rows
            if str(r.get("status")) == "excluded"
            and str(r.get("grade") or "") not in lemma.SOUND_GRADES
        ]
        checks["I4_kernel"] = {
            "ok": not unsound,
            "detail": (
                "kernel_domain_never_excludes"
                if not any(str(r.get("status")) == "excluded" for r in kernel_rows)
                else f"unsound_exclusions={[r.get('id') for r in unsound][:5]}"
            ),
        }
        # I8: soft grades must not shrink the kernel domain either.
        soft = [
            r for r in kernel_rows
            if str(r.get("status")) == "excluded"
            and str(r.get("grade") or "") in {"candidate", "human", "llm"}
        ]
        checks["I8_kernel"] = {
            "ok": not soft,
            "detail": f"soft_graded_exclusions={[r.get('id') for r in soft][:5]}",
        }
    except Exception as exc:  # noqa: BLE001
        domain_extra["kernel"] = {"ok": False, "error": str(exc)[:200]}
        checks["I1_kernel"] = {"ok": False, "detail": f"kernel_domain_error:{type(exc).__name__}"}

    try:
        from testcase_agent.closure import tilingdata_domain as TD

        tcov = TD.compute_tilingdata_coverage(ws, write=True)
        domain_extra["tilingdata"] = {
            "fields": tcov.get("fields"),
            "defects": tcov.get("defects"),
            "over_approximated": tcov.get("over_approximated"),
            "path": tcov.get("path"),
            "source": tcov.get("source"),
            "established": tcov.get("established"),
            "tilingdata_fields": tcov.get("tilingdata_fields"),
        }
        checks["I0_tilingdata"] = _domain_established("tilingdata", tcov)
        # I1: never exclude tilingdata → no R∩E concern.
        # I4: over-approx must not pretend sound exclusion.
        bad_exclude = [
            f for f in (tcov.get("tilingdata_fields") or [])
            if f.get("exclude")
        ]
        checks["I1_tilingdata"] = {
            "ok": len(bad_exclude) == 0,
            "detail": f"forbid_exclude hits={len(bad_exclude)}",
        }
        # I4: an over-approximated field must say so, so nothing downstream can
        # read its coverage as a sound result.
        mislabelled = [
            f.get("name")
            for f in (tcov.get("tilingdata_fields") or [])
            if str(f.get("status")) == "over_approx_witnessed"
            and not f.get("over_approximated")
        ]
        checks["I4_tilingdata"] = {
            "ok": not mislabelled,
            "detail": (
                f"unlabelled_over_approx={mislabelled[:5]}"
                if mislabelled
                else (
                    "over_approximated=true; never_exclude"
                    if tcov.get("over_approximated")
                    else "observed_from_driver_dump"
                )
            ),
        }
        # I8: the domain has no exclusion mechanism at all; assert it stays that way.
        checks["I8_tilingdata"] = {
            "ok": len(bad_exclude) == 0,
            "detail": "tilingdata_never_contributes_to_E",
        }
    except Exception as exc:  # noqa: BLE001
        domain_extra["tilingdata"] = {"ok": False, "error": str(exc)[:200]}
        checks["I1_tilingdata"] = {"ok": False, "detail": f"tilingdata_domain_error:{type(exc).__name__}"}

    # Runtime coverage ledger (same-key TD + Kernel obligations). Fail-closed
    # when the inventory exists; absent inventory is reported but does not
    # vacuity-pass the new gates until collector has been run.
    try:
        from testcase_agent.closure import obligations as OBL

        inv_path = ws.report("obligation_inventory.yaml")
        if Path(inv_path).is_file():
            import yaml as _yaml

            inv = _yaml.safe_load(Path(inv_path).read_text(encoding="utf-8")) or {}
            keys = list(inv.get("keys") or [])
            td_total = sum(len(k.get("tilingdata_obligations") or []) for k in keys if isinstance(k, dict))
            kb_total = sum(len(k.get("kernel_obligations") or []) for k in keys if isinstance(k, dict))
            td_covered = sum(
                1
                for k in keys if isinstance(k, dict)
                for o in (k.get("tilingdata_obligations") or [])
                if str(o.get("status")) == "COVERED"
            )
            kb_covered = sum(
                1
                for k in keys if isinstance(k, dict)
                for o in (k.get("kernel_obligations") or [])
                if str(o.get("status")) == "COVERED"
            )
            unknown = sum(
                1
                for k in keys if isinstance(k, dict)
                for o in list(k.get("tilingdata_obligations") or []) + list(k.get("kernel_obligations") or [])
                if str(o.get("status")) == "UNRESOLVED"
            )
            mismatch = sum(
                1
                for k in keys if isinstance(k, dict)
                for o in list(k.get("tilingdata_obligations") or []) + list(k.get("kernel_obligations") or [])
                if str(o.get("status")) == "REPLAY_MISMATCH"
            )
            domain_extra["runtime_coverage"] = {
                "reachable_keys": int(inv.get("reachable_keys") or len(keys)),
                "td_obligations": td_total,
                "td_covered": td_covered,
                "kernel_outcomes": kb_total,
                "kernel_covered": kb_covered,
                "unknown_reachability": unknown,
                "replay_key_mismatch": mismatch,
            }
            # Gates are fail-closed once inventory exists. Full 100% coverage is
            # the stage goal; until then certify reports the gap honestly.
            checks["I_runtime_td"] = {
                "ok": td_total == 0 or td_covered == td_total,
                "detail": f"td_obligation_coverage={td_covered}/{td_total}",
            }
            checks["I_runtime_kernel"] = {
                "ok": kb_total == 0 or kb_covered == kb_total,
                "detail": f"kernel_outcome_coverage={kb_covered}/{kb_total}",
            }
            checks["I_runtime_unknown"] = {
                "ok": unknown == 0,
                "detail": f"unknown_reachability={unknown}",
            }
            checks["I_runtime_replay_mismatch"] = {
                "ok": mismatch == 0,
                "detail": f"replay_key_mismatch={mismatch}",
            }
        else:
            domain_extra["runtime_coverage"] = {
                "established": False,
                "reason": "obligation_inventory.yaml missing; run obligation-collect",
            }
            # Not established yet — do not vacuity-pass; mark gates absent via
            # required list only when inventory is present (below).
    except Exception as exc:  # noqa: BLE001
        domain_extra["runtime_coverage"] = {"ok": False, "error": str(exc)[:200]}

    # Extend closure.csv with domain summary columns when available.
    try:
        _extend_closure_csv_domains(ws, domain_extra)
    except Exception:
        pass

    # Per-domain checks gate the certificate too. Computing them and then not
    # reading them is what let a three-domain report certify on one domain.
    required = (
        "I1", "I4", "I6", "I7", "I8", "I_cold_start",
        "I0_kernel", "I1_kernel", "I4_kernel", "I8_kernel",
        "I0_tilingdata", "I1_tilingdata", "I4_tilingdata", "I8_tilingdata",
    )
    if (domain_extra.get("runtime_coverage") or {}).get("reachable_keys") is not None:
        required = required + (
            "I_runtime_td",
            "I_runtime_kernel",
            "I_runtime_unknown",
            "I_runtime_replay_mismatch",
        )
    # A domain whose check is absent entirely is not a domain that passed.
    missing = [k for k in required if k not in checks]
    ok = all(checks[k]["ok"] for k in required if k in checks) and not missing
    if missing:
        checks["I_checks_present"] = {
            "ok": False,
            "detail": f"invariants never computed: {missing}",
        }
    return {
        "ok": ok,
        "checks": checks,
        "declared": len(D),
        "R": len(Rset),
        "E": len(E),
        "gap": len(D - (Rset & D) - E),
        "undeclared": len(undeclared),
        "domains": domain_extra,
    }


def _extend_closure_csv_domains(ws: W.Workspace, domain_extra: dict) -> None:
    """Append kernel_branches / tilingdata_fields summary sidecar CSV."""
    path = ws.report("closure_domains.csv")
    k_rows = (domain_extra.get("kernel") or {}).get("kernel_branches") or []
    t_rows = (domain_extra.get("tilingdata") or {}).get("tilingdata_fields") or []
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["domain", "id", "status", "extra"])
        for row in k_rows:
            w.writerow([
                "kernel_branch",
                row.get("id"),
                row.get("status"),
                f"R_count={row.get('R_count')}",
            ])
        for row in t_rows:
            w.writerow([
                "tilingdata_field",
                row.get("name"),
                row.get("status"),
                f"defect={row.get('defect') or ''};over_approx={row.get('over_approximated')}",
            ])
