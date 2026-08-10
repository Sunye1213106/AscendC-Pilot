# -*- coding: utf-8 -*-
"""Cold-start the tilingkey closure ledger.

Clears R / E / open / lemmas and writes ``cold_start.yaml`` with a timestamp
and fingerprint so later certify can prove E rules were promoted after this
run — not inherited from package ``proof_rules.yaml``.
"""
from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from testcase_agent.closure import workspace as W


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
    path = ws.state / "cold_start.yaml"
    path.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return {"ok": True, "path": str(path), **doc}


def load_cold_start(ws: W.Workspace | None = None) -> dict[str, Any]:
    ws = (ws or W.default_workspace()).ensure()
    path = ws.state / "cold_start.yaml"
    if not path.is_file():
        return {}
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return doc if isinstance(doc, dict) else {}


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

    return {
        "ok": len(issues) == 0,
        "E": len(E),
        "cold_start": bool(cold),
        "active_rules": active.is_file(),
        "issues": issues,
        "detail": f"provenance_issues={len(issues)}",
    }
