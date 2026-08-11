# -*- coding: utf-8 -*-
"""What TilingKey closure already knows that TilingData closure needs.

The two surfaces are not independent. A key dimension and a TilingData field are
usually computed from the *same* host state, so work spent closing keys is
partly work already done for fields and branches:

  1. shared roots      a key dimension packed from `keepProb` and a field whose
                       only non-default write sits under `keepProb < 1` cannot
                       vary independently. That is a pin candidate, derivable
                       from UO structure instead of hand-written per operator.
  2. free witnesses    every replay that produced a key also produced that
                       key's TilingData. Harvesting the dumps a key search
                       already wrote costs no extra runs.
  3. inherited E       a key proved unreachable takes its whole per-key branch
                       and field obligation subtree with it.

Nothing here *proves* anything: a lead is a candidate for lemma mine/review,
which still owes a source window per the evidence policy. Emitting exclusions
from a shared identifier would be exactly the unsound shortcut the ledger exists
to prevent.
"""
from __future__ import annotations

import base64
import re
from typing import Any, Iterable

#: Types, casts and keywords that two expressions share without sharing state.
_NOISE = frozenset({
    "static_cast", "reinterpret_cast", "uint8_t", "uint16_t", "uint32_t",
    "uint64_t", "int8_t", "int16_t", "int32_t", "int64_t", "size_t", "bool",
    "float", "double", "auto", "true", "false", "return", "if", "else", "std",
    "ge", "sizeof", "const", "void", "nullptr", "value", "OptionEnum",
    "ENABLE", "DISABLE", "EMPTY_TENSOR", "NORMAL_TENSOR", "strcmp",
})

_DONE = re.compile(r"^###DONE (?P<cid>\S+) ok=(?P<ok>\d+) key=(?P<key>-?\d+)")
_TD = re.compile(r"^###TD (?P<n>\d+) (?P<b64>\S+)")
_BLOCK = re.compile(r"^###BLOCK (?P<n>\d+)")
_CASE = re.compile(r"^###CASE (?P<cid>\S+)")


_MEMBER = re.compile(r"\b[A-Za-z_]\w*(?:\s*(?:\.|->)\s*[A-Za-z_]\w*)+")


def roots(text: str) -> set[str]:
    """State-bearing names in an expression.

    Member paths contribute their leaf and their normalised path; the receiver
    alone does not. Every field on the host lives on the same params aggregate,
    so counting that aggregate as shared state would make every dimension look
    coupled to every field.
    """
    text = text or ""
    out: set[str] = set()
    consumed: list[tuple[int, int]] = []
    for m in _MEMBER.finditer(text):
        consumed.append((m.start(), m.end()))
        path = re.sub(r"\s*(?:\.|->)\s*", ".", m.group(0))
        parts = [p for p in path.split(".") if p]
        leaf = parts[-1]
        if leaf not in _NOISE and not leaf.isupper():
            out.add(leaf)
            out.add(path)
    for m in re.finditer(r"\b[A-Za-z_]\w*\b", text):
        if any(start <= m.start() < end for start, end in consumed):
            continue
        tok = m.group(0)
        if tok in _NOISE or tok.isupper():
            continue
        out.add(tok)
    return out


def _dim_roots(dim: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for expr in dim.get("host_packing_expressions") or []:
        out |= roots(str(expr))
    for site in dim.get("packing_value_sites") or []:
        out |= roots(str(site.get("rhs") or ""))
    return out


def _site_guard_roots(site: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for guard in site.get("guards") or []:
        out |= roots(str(guard.get("condition") or ""))
    for caller in site.get("caller_guards") or []:
        for guard in caller.get("guards") or []:
            out |= roots(str(guard.get("condition") or ""))
    return out


def _default_write(sites: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The single unguarded write, or None when the field has no clear default."""
    unconditional = [s for s in sites if s.get("unconditional")]
    if len(unconditional) != 1:
        return None
    return unconditional[0]


def derive_pin_leads(
    key_dims: list[dict[str, Any]],
    td_fields: list[dict[str, Any]],
    *,
    max_leads: int = 500,
) -> list[dict[str, Any]]:
    """Candidate `key dim value pins field` leads, ranked by shared-root count.

    A lead is emitted when the field has exactly one unguarded write (its
    default) and every other write is guarded by a condition sharing host state
    with a key dimension's packing expression. Which dimension *value* falsifies
    the guard is left to the prover: the lead names the obligation instead of
    assuming it.
    """
    leads: list[dict[str, Any]] = []
    dim_index = [(str(d.get("name") or ""), _dim_roots(d), d) for d in key_dims]
    for field in td_fields:
        name = str(field.get("name") or "")
        sites = list(field.get("value_defining_sites") or [])
        if not name or not sites:
            continue
        default = _default_write(sites)
        if default is None:
            continue
        guarded = [s for s in sites if not s.get("unconditional")]
        if not guarded:
            continue
        guard_roots: set[str] = set()
        for site in guarded:
            guard_roots |= _site_guard_roots(site)
        if not guard_roots:
            continue
        for dim_name, droots, dim in dim_index:
            shared = sorted(guard_roots & droots)
            if not shared:
                continue
            leads.append({
                "id": f"PIN::{dim_name}::{name}",
                "kind": "key_dim_pins_tilingdata_field",
                "field": name,
                "field_class": field.get("field_class"),
                "dim": dim_name,
                "dim_allowed_values": list(dim.get("allowed_values") or []),
                "candidate_value_expr": str(default.get("rhs") or ""),
                "shared_roots": shared,
                "default_site": {
                    "file": default.get("file"),
                    "line": default.get("line"),
                    "function": default.get("function"),
                },
                "guarded_sites": [
                    {
                        "file": s.get("file"),
                        "line": s.get("line"),
                        "function": s.get("function"),
                        "guards": [g.get("condition") for g in (s.get("guards") or [])],
                        "caller_guards": [
                            g.get("condition")
                            for c in (s.get("caller_guards") or [])
                            for g in (c.get("guards") or [])
                        ],
                    }
                    for s in guarded[:6]
                ],
                # A lead is never evidence. These are the obligations a lemma
                # must discharge before the pin may shrink any goal.
                "status": "LEAD",
                "requires": [
                    "dim_value_implies_all_guards_false",
                    "source_window_proof",
                    "referee_review",
                    "refutation_against_R",
                ],
                "score": len(shared),
            })
    leads.sort(key=lambda x: (-int(x["score"]), x["id"]))
    return leads[:max_leads]


def harvest_td_observations(log_text: str) -> list[dict[str, Any]]:
    """TilingData dumps already present in TilingKey-closure replay logs.

    A key search writes `###CASE / ###TD / ###BLOCK / ###DONE` per case. Reading
    the TD lines turns every key witness into a field/branch observation without
    a single extra host run.
    """
    out: list[dict[str, Any]] = []
    cur: dict[str, Any] = {}
    for line in (log_text or "").splitlines():
        line = line.strip()
        m = _CASE.match(line)
        if m:
            cur = {"case_id": m.group("cid")}
            continue
        m = _TD.match(line)
        if m:
            try:
                cur["td"] = base64.b64decode(m.group("b64"))
            except Exception:  # noqa: BLE001 - a truncated log line
                cur.pop("td", None)
            else:
                cur["td_size"] = int(m.group("n"))
            continue
        m = _BLOCK.match(line)
        if m:
            cur["block_num"] = int(m.group("n"))
            continue
        m = _DONE.match(line)
        if m:
            if m.group("ok") == "1" and cur.get("td"):
                out.append({
                    "case_id": cur.get("case_id") or m.group("cid"),
                    "tiling_key": int(m.group("key")),
                    "td": cur["td"],
                    "td_size": cur.get("td_size") or len(cur["td"]),
                    "block_num": int(cur.get("block_num") or 0),
                    "source": "tilingkey_closure_log",
                })
            cur = {}
    return out


def prune_outcomes_by_e_keys(
    per_key_rows: Iterable[dict[str, Any]],
    e_keys: Iterable[int],
) -> dict[str, Any]:
    """Drop per-key outcome obligations for keys already proved unreachable.

    An unreachable key has no runs, so asking for branch outcomes under it is
    debt nobody can ever pay. The proof that closed the key closes its subtree.
    """
    excluded = {int(k) for k in e_keys}
    kept: list[dict[str, Any]] = []
    dropped = 0
    dropped_obligations = 0
    for row in per_key_rows:
        try:
            key = int(row.get("tiling_key"))
        except (TypeError, ValueError):
            kept.append(row)
            continue
        if key in excluded:
            dropped += 1
            counts = row.get("counts") or {}
            dropped_obligations += int(counts.get("td_obligations") or 0)
            dropped_obligations += int(counts.get("runtime_branch_outcomes") or 0)
            continue
        kept.append(row)
    return {
        "kept": kept,
        "dropped_keys": dropped,
        "dropped_obligations": dropped_obligations,
        "reason": "key_proved_unreachable_inherits_subtree",
    }


def leads_to_lemma_candidates(leads: list[dict[str, Any]], dim_value: str = "0") -> list[dict[str, Any]]:
    """Shape leads like the rules `field_pins.load_pinned` consumes.

    The value is a *proposal*: `when {dim: dim_value}` still has to survive
    refutation and referee before it may pin anything.
    """
    out: list[dict[str, Any]] = []
    for lead in leads:
        out.append({
            "id": lead["id"].replace("PIN::", "pin_").lower(),
            "field": lead["field"],
            "when": {lead["dim"]: dim_value},
            "value_expr": lead["candidate_value_expr"],
            "status": "candidate",
            "evidence": {
                "shared_roots": lead["shared_roots"],
                "default_site": lead["default_site"],
                "guarded_sites": lead["guarded_sites"],
            },
        })
    return out
