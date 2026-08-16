"""Scenario-targeted coverage certificate evaluation.

Certificate OK is a conjunction of construction, harness receipts, replay
target receipts, and freshness. ``disabled_no_npu`` is an explicit
not-executed state and must never be treated as PASS.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

SCHEMA = "tg-scenario-coverage/v1"
NOT_EXECUTED_REASONS = frozenset({"disabled_no_npu", "npu_unavailable"})
SKIPPED_BY_DESIGN_REASONS = frozenset({"skipped_by_design", "oracle_none"})


def _load(path: Path) -> dict[str, Any]:
    if yaml is None or not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def _tg(project_root: Path, *, arch: str | None = None) -> Path:
    from ascendc_pilot.paths import tg_root

    return tg_root(project_root, arch=arch)


def live_source_fingerprint(project_root: Path) -> str:
    try:
        from testcase_agent.closure.ledger import baseline_fingerprint

        doc = baseline_fingerprint(project_root) or {}
        return str(doc.get("source_fingerprint") or doc.get("digest") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def live_uo_digest(project_root: Path, *, architecture: str = "") -> str:
    try:
        from ascendc_pilot.occupancy import live_digest_for

        return str(
            live_digest_for(project_root, architecture=architecture) or ""
        ).strip()
    except Exception:  # noqa: BLE001
        return ""


def harness_row_pass(row: dict[str, Any]) -> bool:
    """True only for a completed passing run or an intentional design skip."""
    verdict = str(row.get("verdict") or "").strip().lower()
    reason = str(row.get("reason") or "").strip()
    if verdict in {"not_executed", "not-executed"} or reason in NOT_EXECUTED_REASONS:
        return False
    if verdict == "skipped_by_design" or reason in SKIPPED_BY_DESIGN_REASONS:
        return True
    if verdict in {"fail", "failed", "error"}:
        return False
    return bool(row.get("ok"))


def replay_receipts_dir(project_root: Path, *, arch: str | None = None) -> Path:
    return _tg(project_root, arch=arch) / "closure" / "replay_receipts"


def load_replay_receipts(
    project_root: Path, *, arch: str | None = None
) -> list[dict[str, Any]]:
    root = replay_receipts_dir(project_root, arch=arch)
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.yaml")):
        doc = _load(path)
        if doc:
            out.append(doc)
    return out


def write_replay_receipt(
    project_root: Path,
    *,
    architecture: str | None,
    scenario_id: str,
    obligation_id: str = "",
    target_reached: bool,
    reason: str = "",
    extra: dict[str, Any] | None = None,
) -> Path:
    dest = replay_receipts_dir(project_root, arch=architecture)
    dest.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": "tg-replay-target-receipt/v1",
        "id": scenario_id,
        "scenario_id": scenario_id,
        "obligation_id": obligation_id,
        "target_reached": bool(target_reached),
        "reason": reason,
        "source_fingerprint": live_source_fingerprint(project_root),
        "uo_digest": live_uo_digest(project_root, architecture=str(architecture or "")),
        **(extra or {}),
    }
    path = dest / f"{scenario_id}.yaml"
    if yaml is None:
        raise RuntimeError("PyYAML required")
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def evaluate_scenario_certificate(
    project_root: Path,
    *,
    architecture: str | None = None,
) -> dict[str, Any]:
    """Recompute certificate predicates from durable artifacts (fail-closed)."""
    arch = str(architecture or "").strip() or None
    dest_root = _tg(project_root, arch=arch) / "closure" / "scenarios"
    construct = _load(dest_root / "construct.yaml")
    results = _load(dest_root / "harness_results.yaml")
    intent = _load(_tg(project_root, arch=arch) / "plan" / "plan_intent.yaml")
    scenarios = list(
        intent.get("scenarios")
        or [row.get("id") for row in (construct.get("scenarios") or []) if isinstance(row, dict)]
    )
    constructed = [
        row for row in (construct.get("scenarios") or []) if isinstance(row, dict) and row.get("id")
    ]
    construction_complete = bool(constructed)

    harness_runs = [
        row for row in (results.get("runs") or []) if isinstance(row, dict)
    ]
    by_id = {str(row.get("id") or ""): row for row in harness_runs}
    missing_harness = [str(row.get("id")) for row in constructed if str(row.get("id")) not in by_id]
    harness_fail = [
        str(row.get("id") or "")
        for row in harness_runs
        if not harness_row_pass(row)
    ]
    required_harness_receipts_all_pass = (
        construction_complete
        and not missing_harness
        and not harness_fail
        and bool(harness_runs)
    )

    receipts = load_replay_receipts(project_root, arch=arch)
    constructed_ids = {str(row.get("id") or "") for row in constructed}
    receipt_ok = True
    if not receipts:
        receipt_ok = False
    else:
        covered: set[str] = set()
        for rec in receipts:
            oid = str(rec.get("scenario_id") or rec.get("case_id") or rec.get("id") or "")
            reached = rec.get("target_reached")
            if reached is None:
                reached = (rec.get("verdict") or {}).get("target_reached") if isinstance(rec.get("verdict"), dict) else rec.get("ok")
            if not bool(reached):
                receipt_ok = False
            if oid:
                covered.add(oid)
        if constructed_ids and not constructed_ids.issubset(covered):
            receipt_ok = False

    stored_fp = str(construct.get("source_fingerprint") or "").strip()
    stored_digest = str(construct.get("uo_digest") or "").strip()
    live_fp = live_source_fingerprint(project_root)
    live_digest = live_uo_digest(project_root, architecture=str(arch or ""))
    source_fingerprint_fresh = bool(stored_fp) and stored_fp == live_fp
    uo_digest_fresh = bool(stored_digest) and stored_digest == live_digest
    # Empty live digest with matching empty stored is not "fresh" — fail closed.
    if not live_fp:
        source_fingerprint_fresh = False
    if not live_digest:
        uo_digest_fresh = False

    ok = (
        construction_complete
        and receipt_ok
        and required_harness_receipts_all_pass
        and source_fingerprint_fresh
        and uo_digest_fresh
    )
    return {
        "schema": SCHEMA,
        "mode": "scenario_targeted",
        "target_mode": "scenario_set",
        "scenarios": scenarios,
        "construct": construct,
        "harness": results,
        "construction_complete": construction_complete,
        "replay_target_receipts_all_pass": receipt_ok,
        "required_harness_receipts_all_pass": required_harness_receipts_all_pass,
        "source_fingerprint_fresh": source_fingerprint_fresh,
        "uo_digest_fresh": uo_digest_fresh,
        "missing_harness": missing_harness,
        "harness_fail": harness_fail,
        "replay_receipt_count": len(receipts),
        "source_fingerprint": live_fp,
        "uo_digest": live_digest,
        "ok": ok,
    }
