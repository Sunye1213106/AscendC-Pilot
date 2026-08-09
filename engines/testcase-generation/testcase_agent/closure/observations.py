# -*- coding: utf-8 -*-
"""Classify Host replay rows into HIT / REWRITE / REFUSE observations.

Lemma leads must originate here — never from pair/triple absence alone.
``mine.mine_pairs/triples`` may only rank / filter observation-backed leads.
"""
from __future__ import annotations

import collections
import hashlib
import re
from typing import Any, Mapping

import pandas as pd

from testcase_agent.closure import corpus as C
from testcase_agent.closure.key_utils import int_exact
from testcase_agent.closure import ledger
from testcase_agent.closure import workspace as W

KIND_HIT = "hit"
KIND_REWRITE = "rewrite"
KIND_REFUSE = "refuse"

_NON_VERDICT_PREFIXES = ("HOST_CRASHED", "NOT_RUN", "PARSE_FAIL", "parse_fail")


def _reject_str(row: Mapping[str, Any]) -> str:
    return str(row.get("reject") or "").strip()


def is_judged_verdict(row: Mapping[str, Any]) -> bool:
    """True when the row carries a real Host verdict (not crash / not-run)."""
    reject = _reject_str(row)
    if any(reject.startswith(p) for p in _NON_VERDICT_PREFIXES):
        return False
    # Require a target attempt; zero/missing target is not a directed observation.
    target = int_exact(row.get("_target_key"), default=0)
    return bool(target)


def classify_row(row: Mapping[str, Any]) -> str | None:
    """Return hit / rewrite / refuse, or None if not usable for lemma leads."""
    if not is_judged_verdict(row):
        return None
    target = int_exact(row.get("_target_key"), default=0)
    # Key 0 is a valid tiling key — do not treat it as missing via truthiness.
    raw_actual = row.get("tiling_key")
    if raw_actual is None or str(raw_actual).strip() == "":
        actual: int | None = None
    else:
        actual = int_exact(raw_actual, default=-1)
        if actual < 0:
            actual = None
    ok = int(row.get("ok") or 0) == 1
    if ok and actual is not None and actual == target:
        return KIND_HIT
    if ok and actual is not None and actual != target:
        return KIND_REWRITE
    if not ok:
        return KIND_REFUSE
    return None


def _obs_id(row: Mapping[str, Any], kind: str, idx: int) -> str:
    raw = "|".join(
        [
            kind,
            str(int_exact(row.get("_target_key"), default=0)),
            str(int_exact(row.get("tiling_key"), default=0)),
            _reject_str(row)[:80],
            str(row.get("_mismatch_dims") or ""),
            str(row.get("_src") or ""),
            str(idx),
        ]
    )
    return "OBS_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def _reject_family(reject: str) -> str:
    text = (reject or "").strip()
    if not text:
        return ""
    # Keep a stable family token (first path-like / identifier chunk).
    m = re.match(r"^[A-Za-z_][\w./:-]*", text)
    return (m.group(0) if m else text)[:64]


def _target_when(row: Mapping[str, Any], dims: list[str]) -> dict[str, str]:
    """Decode target key into dim→value; fall back to dim_* columns if present."""
    target = int_exact(row.get("_target_key"), default=0)
    if target:
        try:
            inst = W.decode(target)
            return {d: str(inst.get(d)) for d in dims if d in inst}
        except Exception:
            pass
    out: dict[str, str] = {}
    for d in dims:
        col = "dim_" + d
        if col in row and str(row.get(col) or "").strip() != "":
            out[d] = str(int_exact(row.get(col), default=row.get(col)))
    return out


def _rewrite_to(row: Mapping[str, Any], dims: list[str]) -> dict[str, str]:
    mismatch = [x for x in str(row.get("_mismatch_dims") or "").split("|") if x]
    if not mismatch:
        return {}
    actual = int_exact(row.get("tiling_key"), default=0)
    if not actual:
        return {}
    try:
        got = W.decode(actual)
    except Exception:
        return {}
    return {d: str(got.get(d)) for d in mismatch if d in got}


def iter_observations(
    ws: W.Workspace | None = None,
    *,
    df: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    """Load corpus and emit classified observation records (non-HIT only for leads)."""
    ws = ws or W.default_workspace()
    if df is None:
        df = C.dedup(C.load(ws))
    if df is None or getattr(df, "empty", True):
        return []
    dims = list(W.dim_names())
    out: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        kind = classify_row(row)
        if kind is None or kind == KIND_HIT:
            continue
        rec = {
            "id": _obs_id(row, kind, int(idx) if isinstance(idx, int) else len(out)),
            "kind": kind,
            "target_key": int_exact(row.get("_target_key"), default=0),
            "actual_key": int_exact(row.get("tiling_key"), default=0),
            "ok": int(row.get("ok") or 0),
            "reject": _reject_str(row),
            "reject_family": _reject_family(_reject_str(row)),
            "mismatch_dims": [
                x for x in str(row.get("_mismatch_dims") or "").split("|") if x
            ],
            "when": _target_when(row, dims),
            "rewrite_to": _rewrite_to(row, dims) if kind == KIND_REWRITE else {},
            "src": str(row.get("_src") or ""),
        }
        if not rec["when"]:
            continue
        out.append(rec)
    return out


def _cluster_key(obs: Mapping[str, Any]) -> tuple:
    when = obs.get("when") or {}
    when_items = tuple(sorted((str(k), str(v)) for k, v in when.items()))
    mismatch = tuple(sorted(str(x) for x in (obs.get("mismatch_dims") or [])))
    return (str(obs.get("kind") or ""), when_items, mismatch, str(obs.get("reject_family") or ""))


def _lead_id(kind: str, when: Mapping[str, str], idx: int) -> str:
    combo = ",".join(f"{k}={v}" for k, v in sorted(when.items()))
    raw = f"{kind}|{combo}|{idx}"
    return "OBS_LEAD_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8].upper()


def _affected_open(when: Mapping[str, str], open_insts: list[dict[str, str]]) -> int:
    if not when:
        return 0
    n = 0
    for inst in open_insts:
        if all(str(inst.get(k)) == str(v) for k, v in when.items()):
            n += 1
    return n


def _rank_leads_with_mine(
    leads: list[dict[str, Any]],
    ws: W.Workspace,
) -> list[dict[str, Any]]:
    """Attach mine pair/triple residual scores; never invent new leads."""
    try:
        from testcase_agent.closure import mine

        pairs = mine.mine_pairs(ws, top=0)
        triples = mine.mine_triples(ws, top=0)
    except Exception:
        pairs, triples = [], []
    pair_index = {
        tuple(sorted((str(k), str(v)) for k, v in (p.get("when") or {}).items())): p
        for p in pairs
    }
    triple_index = {
        tuple(sorted((str(k), str(v)) for k, v in (t.get("when") or {}).items())): t
        for t in triples
    }
    for lead in leads:
        when_key = tuple(sorted((str(k), str(v)) for k, v in (lead.get("when") or {}).items()))
        mine_hit = pair_index.get(when_key) or triple_index.get(when_key)
        if mine_hit:
            lead["mine_open"] = int(mine_hit.get("open") or 0)
            lead["mine_min_support"] = int(mine_hit.get("min_support") or 0)
            lead["mine_kind"] = str(mine_hit.get("kind") or "")
        else:
            lead["mine_open"] = 0
            lead["mine_min_support"] = 0
            lead["mine_kind"] = ""
        # Priority: observation support, then residual leverage from mine.
        lead["priority"] = (
            int(lead.get("support", {}).get("attempts") or 0) * 1000
            + int(lead.get("affected_open_keys") or 0) * 10
            + int(lead.get("mine_open") or 0)
        )
    leads.sort(key=lambda x: int(x.get("priority") or 0), reverse=True)
    return leads


def build_leads(
    ws: W.Workspace | None = None,
    *,
    top: int = 40,
    df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Cluster REWRITE/REFUSE observations into lemma leads.

    Returns a ``tg-lemma-leads/v1`` document. Empty ``leads`` when no oracle
    observations exist — callers must not invent substitutes.
    """
    ws = (ws or W.default_workspace()).ensure()
    observations = iter_observations(ws, df=df)
    try:
        D = ledger.declared()
        Rset = ledger.load_R(ws)
        E = ledger.load_E(ws)
        open_keys = sorted(D - Rset - E)
        open_insts = [dict(x) for x in W.decode_many(open_keys)]
    except Exception:
        open_insts = []

    clusters: dict[tuple, list[dict[str, Any]]] = collections.OrderedDict()
    for obs in observations:
        clusters.setdefault(_cluster_key(obs), []).append(obs)

    leads: list[dict[str, Any]] = []
    for i, (_key, members) in enumerate(clusters.items()):
        kind = str(members[0]["kind"])
        when = dict(members[0]["when"])
        lead_id = _lead_id(kind, when, i)
        rewrite_counter: collections.Counter[tuple[str, str]] = collections.Counter()
        for m in members:
            for dim, val in (m.get("rewrite_to") or {}).items():
                rewrite_counter[(str(dim), str(val))] += 1
        rewrite_to = {d: v for (d, v), _n in rewrite_counter.most_common(8)}
        support = {
            "attempts": len(members),
            "rewrite": sum(1 for m in members if m["kind"] == KIND_REWRITE),
            "refuse": sum(1 for m in members if m["kind"] == KIND_REFUSE),
            "hit": 0,
        }
        combo = ",".join(f"{k}={v}" for k, v in sorted(when.items()))
        evidence_rel = f"tg/closure/lemmas/evidence/{lead_id}.yaml"
        leads.append({
            "id": lead_id,
            "kind": kind,
            "when": when,
            "combo": combo,
            "observations": [m["id"] for m in members],
            "observation_count": len(members),
            "support": support,
            "rewrite_to": rewrite_to,
            "reject_family": str(members[0].get("reject_family") or ""),
            "mismatch_dims": list(members[0].get("mismatch_dims") or []),
            "affected_open_keys": _affected_open(when, open_insts),
            "evidence_path": evidence_rel,
            "source": "oracle_observation",
        })

    leads = _rank_leads_with_mine(leads, ws)
    if top and len(leads) > top:
        leads = leads[:top]

    return {
        "schema": "tg-lemma-leads/v1",
        "source": "oracle_observation",
        "observation_count": len(observations),
        "lead_count": len(leads),
        "leads": leads,
        # Retained for diagnostics only — not primary lead producers.
        "pairs": [],
        "triples": [],
        "pair_count": 0,
        "triple_count": 0,
        "error": "",
        "note": (
            "leads require Host REWRITE/REFUSE observations; "
            "mine_pairs/triples used only for ranking"
        ),
    }


def combo_from_lead(lead: Mapping[str, Any]) -> str:
    """``Dim=Val,...`` string for lemma_evidence.collect."""
    if lead.get("combo"):
        return str(lead["combo"])
    when = lead.get("when") or {}
    return ",".join(f"{k}={v}" for k, v in sorted(when.items()))
