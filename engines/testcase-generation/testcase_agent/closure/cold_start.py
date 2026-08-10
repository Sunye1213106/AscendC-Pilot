# -*- coding: utf-8 -*-
"""Cold-start the tilingkey closure ledger.

Clears R / E / open / lemmas and writes ``cold_start.yaml`` with a timestamp
and fingerprint so later certify can prove E rules were promoted after this
run — not inherited from package ``proof_rules.yaml``.

Provenance is an append-only hash chain (``provenance_chain.yaml``) whose
genesis entry is sealed by ``cold_start``.  Every promote links to the previous
entry and records the cold-start seal it observed, so a cold_start stamped
after the fact cannot retroactively legitimise an already-grown E.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from testcase_agent.closure import workspace as W

CHAIN_NAME = "provenance_chain.yaml"


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _digest(payload: Any) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()[:32]


def _chain_path(ws: W.Workspace) -> Path:
    return ws.state / CHAIN_NAME


def load_chain(ws: W.Workspace | None = None) -> list[dict[str, Any]]:
    ws = (ws or W.default_workspace()).ensure()
    path = _chain_path(ws)
    if not path.is_file():
        return []
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = doc.get("entries") if isinstance(doc, dict) else None
    return [dict(x) for x in (entries or []) if isinstance(x, dict)]


def _link(entry: dict[str, Any]) -> dict[str, Any]:
    """Return ``entry`` with its content hash attached."""
    body = {k: v for k, v in entry.items() if k != "hash"}
    entry["hash"] = _digest(body)
    return entry


def append_chain(
    ws: W.Workspace,
    kind: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append a linked provenance entry and return it.

    The cold-start seal observed *at this moment* is recorded in the entry; an
    empty seal is a permanent record that the step ran without a cold start.
    """
    entries = load_chain(ws)
    prev = entries[-1]["hash"] if entries else ""
    entry = _link(
        {
            "seq": len(entries),
            "kind": str(kind),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cold_seal": str(load_cold_start(ws).get("seal") or ""),
            "prev": prev,
            **(payload or {}),
        }
    )
    entries.append(entry)
    _chain_path(ws).write_text(
        yaml.safe_dump(
            {"schema": "tg-provenance-chain/v1", "entries": entries},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return entry


def verify_chain(ws: W.Workspace | None = None) -> dict[str, Any]:
    """Recompute every link; report the first structural break."""
    ws = (ws or W.default_workspace()).ensure()
    entries = load_chain(ws)
    issues: list[str] = []
    if not entries:
        return {"ok": False, "entries": 0, "issues": ["provenance_chain_missing"]}

    prev_hash = ""
    for i, entry in enumerate(entries):
        body = {k: v for k, v in entry.items() if k != "hash"}
        if _digest(body) != str(entry.get("hash") or ""):
            issues.append(f"provenance_chain_tampered:seq={i}")
            break
        if str(entry.get("prev") or "") != prev_hash:
            issues.append(f"provenance_chain_broken:seq={i}")
            break
        if int(entry.get("seq", -1)) != i:
            issues.append(f"provenance_chain_seq_gap:seq={i}")
            break
        prev_hash = str(entry.get("hash") or "")

    genesis = entries[0]
    if str(genesis.get("kind") or "") != "cold_start":
        issues.append("provenance_chain_genesis_not_cold_start")
    cold_seal = str(load_cold_start(ws).get("seal") or "")
    if cold_seal and str(genesis.get("seal") or "") != cold_seal:
        issues.append("cold_start_seal_mismatch")

    return {
        "ok": not issues,
        "entries": len(entries),
        "promotes": sum(1 for x in entries if str(x.get("kind")) == "promote"),
        "issues": issues,
    }


def _fingerprint(ws: W.Workspace) -> str:
    """Fingerprint from declared domain + UO/adapter identity (not a weak prefix hash)."""
    parts: list[str] = []
    try:
        from testcase_agent.closure import ledger

        D = ledger.declared()
        parts.append(f"D={len(D)}")
        # Content hash of declared keys (order-independent).
        blob = ",".join(str(k) for k in sorted(D))
        parts.append("Dhash=" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16])
    except Exception:
        parts.append("D=?")
    try:
        uo = ws.root / ".ascendc-pilot"
        for man in sorted(uo.glob("*/uo/manifest.yaml")):
            try:
                import yaml

                doc = yaml.safe_load(man.read_text(encoding="utf-8")) or {}
            except Exception:
                doc = {}
            parts.append(f"src_rev={doc.get('source_revision') or ''}")
            parts.append(
                f"graph_fp={doc.get('fingerprint') or doc.get('graph_fingerprint') or ''}"
            )
            break
        for cand in sorted(uo.glob("*/uo/ir/operator_graph.yaml")):
            # Prefer explicit fingerprint field when present; else full-file hash.
            try:
                import yaml

                gdoc = yaml.safe_load(cand.read_text(encoding="utf-8")) or {}
                gfp = str(gdoc.get("fingerprint") or gdoc.get("graph_fingerprint") or "")
            except Exception:
                gfp = ""
            if gfp:
                parts.append(f"op_graph={gfp}")
            else:
                text = cand.read_text(encoding="utf-8", errors="replace")
                parts.append(
                    "op_graph=" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
                )
            break
        for ap in sorted(uo.glob("*/uo/adapter/feature_bindings.yaml")):
            text = ap.read_text(encoding="utf-8", errors="replace")
            parts.append(
                "adapter=" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            )
            break
    except Exception:
        pass
    parts.append("oracle_protocol=host_v1")
    raw = "|".join(parts) or "empty"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def cold_start(
    ws: W.Workspace | None = None,
    *,
    clear_rounds: bool = True,
) -> dict[str, Any]:
    """Reset ledger artefacts and stamp cold_start provenance."""
    ws = (ws or W.default_workspace()).ensure()
    lemmas = ws.state / "lemmas"
    cleared: list[str] = []

    for path in (ws.r_path, ws.e_path, ws.open_path):
        path.write_text("", encoding="utf-8", newline="\n")
        cleared.append(path.name)
    if ws.e_why_path:
        try:
            ws.e_why_path.write_text("key,rules\n", encoding="utf-8")
            cleared.append(ws.e_why_path.name)
        except Exception:
            pass

    if lemmas.is_dir():
        for child in lemmas.iterdir():
            if child.is_file():
                child.unlink()
                cleared.append(f"lemmas/{child.name}")
            elif child.is_dir():
                shutil.rmtree(child)
                cleared.append(f"lemmas/{child.name}/")
    else:
        lemmas.mkdir(parents=True, exist_ok=True)

    if clear_rounds:
        for name in ("rounds", "round_budget.yaml", "oracle_suspect"):
            p = ws.state / name
            if p.is_file():
                p.unlink()
                cleared.append(name)
            elif p.is_dir():
                shutil.rmtree(p)
                cleared.append(f"{name}/")

    fp = _fingerprint(ws)
    ts = datetime.now(timezone.utc).isoformat()
    doc = {
        "schema": "tg-cold-start/v1",
        "timestamp": ts,
        "fingerprint": fp,
        "state": str(ws.state),
        "cleared": cleared,
    }
    # Seal binds the stamp to the state it actually cleared, so a stamp written
    # later (when R/E are already populated) cannot reproduce it.
    doc["seal"] = _digest(
        {
            "fingerprint": fp,
            "timestamp": ts,
            "cleared": sorted(cleared),
            "state": str(ws.state),
        }
    )
    path = ws.state / "cold_start.yaml"
    path.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    # Genesis of the append-only chain; every later promote links back to it.
    _chain_path(ws).unlink(missing_ok=True)
    append_chain(ws, "cold_start", {"seal": doc["seal"], "fingerprint": fp})
    return {"ok": True, "path": str(path), **doc}


def load_cold_start(ws: W.Workspace | None = None) -> dict[str, Any]:
    ws = (ws or W.default_workspace()).ensure()
    path = ws.state / "cold_start.yaml"
    if not path.is_file():
        return {}
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return doc if isinstance(doc, dict) else {}


def require_cold_start(ws: W.Workspace | None = None) -> dict[str, Any]:
    """Pre-promote gate: a sealed cold start with an intact chain must exist.

    ``check_e_provenance`` short-circuits while E is still empty, so the very
    first promote would otherwise slip through and only fail at certify.
    """
    ws = (ws or W.default_workspace()).ensure()
    cold = load_cold_start(ws)
    issues: list[str] = []
    if not cold:
        issues.append("cold_start_missing")
    elif not str(cold.get("seal") or ""):
        # Alias kept for the fa-pr13 acceptance check name.
        issues.extend(["cold_start_unsealed", "cold_start_unsigned"])
    else:
        chain = verify_chain(ws)
        if not chain["ok"]:
            issues.extend(chain["issues"])
    return {
        "ok": not issues,
        "issues": issues,
        "detail": f"cold_start_issues={len(issues)}",
    }


def check_e_provenance(ws: W.Workspace | None = None) -> dict[str, Any]:
    """Fail if E is non-empty but active_rules were not written after cold_start.

    Package ``proof_rules.yaml`` alone must never certify as the E source.
    """
    ws = (ws or W.default_workspace()).ensure()
    from testcase_agent.closure import ledger

    E = ledger.load_E(ws)
    cold = load_cold_start(ws)
    active = ws.state / "lemmas" / "active_rules.yaml"
    issues: list[str] = []

    if not E:
        return {
            "ok": True,
            "E": 0,
            "cold_start": bool(cold),
            "active_rules": active.is_file(),
            "issues": [],
        }

    if not cold:
        issues.append("cold_start_missing_with_nonempty_E")
    elif not str(cold.get("seal") or ""):
        issues.extend(["cold_start_unsealed", "cold_start_unsigned"])

    chain = verify_chain(ws)
    if not chain["ok"]:
        issues.extend(chain["issues"])
    elif not chain["promotes"]:
        issues.append("no_promote_in_provenance_chain")
    else:
        # A promote that ran before any cold start records an empty seal for
        # ever; back-dating cold_start.yaml afterwards cannot repair it.
        for entry in load_chain(ws):
            if str(entry.get("kind")) != "promote":
                continue
            if not str(entry.get("cold_seal") or ""):
                issues.append(f"promote_without_cold_start:seq={entry.get('seq')}")
                break
            if str(entry.get("cold_seal")) != str(cold.get("seal") or ""):
                issues.append(f"promote_cold_seal_mismatch:seq={entry.get('seq')}")
                break

    if not active.is_file():
        issues.append("active_rules_missing_with_nonempty_E")
        # Detect package-only proof_rules as sole source.
        try:
            from replay.package_data import resolve_adapter_file, package_file

            pkg_proof = resolve_adapter_file("proof_rules.yaml") or package_file(
                "proof_rules.yaml"
            )
            if pkg_proof.is_file():
                issues.append("proof_rules_package_only_without_post_cold_start_promotion")
        except Exception:
            issues.append("proof_rules_package_only_without_post_cold_start_promotion")
    else:
        # active_rules mtime / fingerprint must be after cold_start.
        if cold.get("timestamp"):
            try:
                cold_ts = datetime.fromisoformat(str(cold["timestamp"]))
                active_mtime = datetime.fromtimestamp(
                    active.stat().st_mtime, tz=timezone.utc
                )
                if active_mtime < cold_ts:
                    issues.append("active_rules_mtime_before_cold_start")
            except Exception:
                pass
        cold_fp = str(cold.get("fingerprint") or "")
        try:
            doc = yaml.safe_load(active.read_text(encoding="utf-8")) or {}
            book_fp = str(doc.get("cold_start_fingerprint") or "")
            if cold_fp and book_fp and book_fp != cold_fp:
                issues.append("active_rules_cold_start_fingerprint_mismatch")
            # Soft: if active has no cold_start stamp, require mtime check above.
            if cold_fp and not book_fp:
                # Still OK if mtime is after cold_start (checked above).
                pass
        except Exception as exc:  # noqa: BLE001
            issues.append(f"active_rules_unreadable:{exc}")

    # Every active rule must be accounted for by a promote entry.
    if active.is_file() and chain["ok"]:
        try:
            rule_count = len((yaml.safe_load(active.read_text(encoding="utf-8")) or {}).get("rules") or [])
            chained = sum(
                int(x.get("promoted") or 0)
                for x in load_chain(ws)
                if str(x.get("kind")) == "promote"
            )
            if rule_count != chained:
                issues.append(
                    f"active_rules_not_chain_backed:rules={rule_count},chain={chained}"
                )
        except Exception as exc:  # noqa: BLE001
            issues.append(f"active_rules_chain_check_failed:{exc}")

    return {
        "ok": len(issues) == 0,
        "E": len(E),
        "cold_start": bool(cold),
        "active_rules": active.is_file(),
        "chain": {k: chain[k] for k in ("ok", "entries", "promotes") if k in chain},
        "issues": issues,
        "detail": f"provenance_issues={len(issues)}",
    }
