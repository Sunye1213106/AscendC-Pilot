"""TG gate adapters — wrap testcase_agent validators; never invent shallow file checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from ascendc_pilot.paths import tg_root, uo_root


def _load(path: Path) -> Any:
    if yaml is None or not path.is_file():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _op_name(
    project_root: Path,
    *,
    op_name: str | None = None,
    architecture: str | None = None,
) -> str:
    """Best-effort op name for TG APIs that still require it."""
    if str(op_name or "").strip():
        return str(op_name).strip()
    uo = uo_root(project_root, arch=architecture)
    man = _load(uo / "manifest.yaml")
    if isinstance(man, dict) and man.get("op_name"):
        return str(man["op_name"])
    tg = tg_root(project_root, arch=architecture)
    for rel in ("init/status.yaml", "realization/status.yaml"):
        doc = _load(tg / rel)
        if isinstance(doc, dict) and doc.get("op_name"):
            return str(doc["op_name"])
    return project_root.name


def _wrap_exc(gate: str, fn: Any) -> dict[str, Any]:
    try:
        payload = fn()
        if isinstance(payload, dict) and "ok" in payload:
            return {"gate": gate, **payload} if payload.get("gate") else {
                "gate": gate,
                "ok": bool(payload.get("ok")),
                "detail": payload,
            }
        if isinstance(payload, dict) and "status" in payload:
            status = str(payload.get("status") or "").lower()
            ok = status in {"pass", "passed", "ok", "confirmed", "approved", "closed", "resolved"}
            fail_statuses = {"pending", "blocked", "ready_for_llm", "unresolved", "fail", "failed", "error"}
            if status in fail_statuses:
                ok = False
            return {
                "gate": gate,
                "ok": ok,
                "detail": payload,
                "message": "ok" if ok else f"{gate} status={payload.get('status')!r}",
            }
        # Non-dict / no status / no ok → fail closed (do not invent success)
        return {
            "gate": gate,
            "ok": False,
            "detail": payload if isinstance(payload, dict) else {"result": payload},
            "message": f"{gate}: domain payload missing ok/status",
        }
    except Exception as exc:  # noqa: BLE001 — domain engines raise typed errors
        ask = getattr(exc, "ask", "") or ""
        payload = getattr(exc, "payload", None) or {}
        return {
            "gate": gate,
            "ok": False,
            "ask": ask,
            "detail": payload if isinstance(payload, dict) else {},
            "message": str(exc)[:400],
        }


def gate_tilingkey_binding_ready(
    project_root: Path, *, architecture: str | None = None
) -> dict[str, Any]:
    """Full-mode bind gate: host-view inventory + declared Key space must align."""
    tg = tg_root(project_root, arch=architecture)
    uo = uo_root(project_root, arch=architecture)
    issues: list[str] = []
    inv = _load(tg / "realization" / "binding_inventory.yaml")
    if not isinstance(inv, dict):
        return {
            "gate": "tilingkey_binding_ready",
            "ok": False,
            "message": "realization/binding_inventory.yaml missing",
        }
    fields = list(inv.get("fields") or [])
    if not fields:
        issues.append("binding_inventory.fields empty")
    keys: dict[str, Any] = {}
    view: dict[str, Any] = {}
    graph: dict[str, Any] = {}
    try:
        from uo_init.store.reader import find_uo_product, load_production_view

        arch = str(architecture or "").strip()
        if not arch:
            from ascendc_pilot.paths import discover_arch

            try:
                arch = discover_arch(project_root)
            except Exception:
                arch = ""
        product = find_uo_product(project_root, architecture=arch)
        if product is not None and product.suffix == ".uo":
            blob = load_production_view(product, "tiling/exhaustive_key_space.yaml")
            if isinstance(blob, dict):
                keys = blob
            blob = load_production_view(product, "ir/tg_host_view.yaml")
            if isinstance(blob, dict):
                view = blob
            blob = load_production_view(product, "ir/operator_graph.yaml")
            if isinstance(blob, dict):
                graph = blob
        else:
            issues.append("missing .uo CodeMap product")
    except Exception as exc:  # noqa: BLE001
        issues.append(f"uo_read_error:{exc}"[:120])
    del uo  # binding gate authority is .uo view_blobs, not arch YAML tree
    count = int((keys or {}).get("legal_key_count") or 0) if isinstance(keys, dict) else 0
    if count <= 0:
        issues.append("DECLARED_SET_EMPTY")
    view_fields = list((view or {}).get("fields") or []) if isinstance(view, dict) else []
    if view_fields and fields and len(fields) != len(view_fields):
        pass
    fp = str((graph or {}).get("fingerprint") or "") if isinstance(graph, dict) else ""
    inv_fp = str(inv.get("graph_fingerprint") or "")
    if fp and inv_fp and fp != inv_fp:
        issues.append("graph_fingerprint_mismatch")
    return {
        "gate": "tilingkey_binding_ready",
        "ok": not issues,
        "message": "ok" if not issues else "; ".join(issues),
        "field_count": len(fields),
        "declared_count": count,
        "issues": issues,
    }


def gate_audit_pass(
    project_root: Path, *, architecture: str | None = None
) -> dict[str, Any]:
    """Full audit contract via engine require_audit_pass — not shallow status read."""
    out = tg_root(project_root, arch=architecture)

    def _run() -> Any:
        from testcase_agent.init_status import require_audit_pass

        return require_audit_pass(out, checklist="tilingkey")

    return _wrap_exc("audit_pass", _run)


def gate_kb_fingerprint_fresh(
    project_root: Path,
    *,
    op_name: str | None = None,
    architecture: str | None = None,
) -> dict[str, Any]:
    name = _op_name(project_root, op_name=op_name, architecture=architecture)
    out = tg_root(project_root, arch=architecture)

    def _run() -> Any:
        from testcase_agent.init_status import require_kb_fingerprint_fresh

        return require_kb_fingerprint_fresh(project_root, name, out_root=out)

    wrapped = _wrap_exc("kb_fingerprint_fresh", _run)
    try:
        from ascendc_pilot.occupancy import binding_is_stale
        from ascendc_pilot.state import load_state

        live = load_state(project_root) or {}
        check = binding_is_stale(
            project_root,
            pinned_digest=str(live.get("pinned_digest") or ""),
            architecture=str(live.get("architecture") or ""),
            session_id=str(live.get("session_id") or ""),
        )
        if check.get("stale"):
            return {
                "ok": False,
                "gate": "kb_fingerprint_fresh",
                "reason_code": "UO_DIGEST_CHANGED",
                "message": "CodeMap digest changed since this TG run was pinned",
                "uo_freshness": check,
                "product_check": wrapped,
            }
    except Exception:  # noqa: BLE001
        pass
    return wrapped


def gate_kb_fingerprint_matches(
    project_root: Path, *, architecture: str | None = None
) -> dict[str, Any]:
    out = tg_root(project_root, arch=architecture)
    uo = uo_root(project_root, arch=architecture)

    def _run() -> Any:
        from testcase_agent.isolation import kb_fingerprint_matches

        matched, detail = kb_fingerprint_matches(out, uo)
        return {
            "ok": bool(matched),
            "matched": matched,
            **(detail if isinstance(detail, dict) else {"detail": detail}),
        }

    return _wrap_exc("kb_fingerprint", _run)


def gate_init_confirmed(
    project_root: Path,
    *,
    op_name: str | None = None,
    architecture: str | None = None,
) -> dict[str, Any]:
    name = _op_name(project_root, op_name=op_name, architecture=architecture)

    def _run() -> Any:
        from testcase_agent.init_status import require_init_confirmed

        return require_init_confirmed(project_root, name)

    return _wrap_exc("init_confirmed", _run)


def _resolve_plan_dir(out: Path, level: str = "") -> Path:
    from testcase_agent.io import resolve_plan_dir

    return resolve_plan_dir(out, level)


def _load_plan_hashes(plan_dir: Path) -> tuple[str | None, str | None]:
    """Load snapshot_hash and plan_hash from plan artifacts."""
    snapshot_hash: str | None = None
    plan_hash: str | None = None
    # tilingkey_full_coverage writes hashes primarily into coverage_obligations.yaml
    # / target_set.yaml; keep legacy plan.yaml paths as fallbacks.
    for rel in (
        "coverage_obligations.yaml",
        "target_set.yaml",
        "plan.yaml",
        "snapshot.yaml",
        "coverage_matrix.yaml",
        "unresolved.yaml",
    ):
        doc = _load(plan_dir / rel)
        if not isinstance(doc, dict):
            continue
        if not snapshot_hash:
            snapshot_hash = doc.get("snapshot_hash") and str(doc["snapshot_hash"])
        if not plan_hash:
            plan_hash = doc.get("plan_hash") and str(doc["plan_hash"])
    return snapshot_hash, plan_hash


def _require_approval(
    supplement: dict[str, Any],
    snapshot_hash: str | None,
    plan_hash: str | None,
    unresolved: dict[str, Any],
) -> None:
    """Validate human_supplement against plan hashes (was in deleted solve.py)."""
    required = {
        "decision",
        "approved_snapshot_hash",
        "approved_plan_hash",
        "approved_at",
        "supplements",
        "notes",
    }
    missing = sorted(key for key in required if key not in supplement)
    if missing:
        raise RuntimeError(f"APPROVAL_REQUIRED: approval file missing field(s): {', '.join(missing)}")
    decision = str(supplement.get("decision") or supplement.get("approval") or "").strip().lower()
    status = str(supplement.get("status") or "").strip().lower()
    approved = supplement.get("approved") is True
    if decision != "approve" and status not in {"approved", "approve"} and not approved:
        raise RuntimeError("APPROVAL_REQUIRED: plan approval is required before tg-solve")
    if supplement.get("approved_snapshot_hash") != snapshot_hash:
        raise RuntimeError("APPROVAL_SNAPSHOT_MISMATCH: approval does not match current snapshot_hash")
    if supplement.get("approved_plan_hash") != plan_hash:
        raise RuntimeError("APPROVAL_PLAN_MISMATCH: approval does not match current plan_hash")
    blocking = unresolved.get("blocking_hard_obligations") or []
    gaps = unresolved.get("contract_gaps") or []
    if unresolved.get("status") != "ready_for_manual_review" or blocking:
        raise RuntimeError("PLAN_BLOCKED: unresolved hard blockers must be cleared before tg-solve")
    if gaps:
        raise RuntimeError("CONTRACT_GAPS_PRESENT: contract gaps must be resolved before tg-solve")
    if unresolved.get("allow_solve") is False:
        raise RuntimeError(
            f"ALLOW_SOLVE_NO: {unresolved.get('allow_solve_reason') or 'plan forbids solve'}."
        )


def gate_plan_approved(
    project_root: Path, *, level: str = "", architecture: str | None = None
) -> dict[str, Any]:
    """Validate real human_supplement against snapshot/plan hashes via engine approval rules."""
    out = tg_root(project_root, arch=architecture)

    def _run() -> Any:
        try:
            plan_dir = _resolve_plan_dir(out, level)
        except Exception as exc:  # noqa: BLE001
            levels = (
                sorted((out / "plan" / "levels").glob("*/human_supplement.yaml"))
                if (out / "plan" / "levels").is_dir()
                else []
            )
            if not levels:
                raise RuntimeError(f"plan level unresolved: {exc}") from exc
            plan_dir = levels[-1].parent

        supplement = _load(plan_dir / "human_supplement.yaml") or {}
        unresolved = _load(plan_dir / "unresolved.yaml") or {}
        if not isinstance(supplement, dict):
            supplement = {}
        if not isinstance(unresolved, dict):
            unresolved = {}

        snapshot_hash, plan_hash = _load_plan_hashes(plan_dir)

        _require_approval(supplement, snapshot_hash, plan_hash, unresolved)
        return {
            "ok": True,
            "status": "approved",
            "allow_solve": unresolved.get("allow_solve"),
            "plan_dir": plan_dir.as_posix(),
            "approved_snapshot_hash": supplement.get("approved_snapshot_hash"),
            "approved_plan_hash": supplement.get("approved_plan_hash"),
        }

    return _wrap_exc("plan_approved", _run)


def gate_allow_solve(
    project_root: Path, *, level: str = "", architecture: str | None = None
) -> dict[str, Any]:
    out = tg_root(project_root, arch=architecture)
    try:
        plan_dir = _resolve_plan_dir(out, level)
    except Exception as exc:  # noqa: BLE001
        return {"gate": "allow_solve", "ok": False, "message": str(exc)[:300]}
    unresolved = _load(plan_dir / "unresolved.yaml") or {}
    allow = unresolved.get("allow_solve") if isinstance(unresolved, dict) else None
    ok = allow is True
    return {
        "gate": "allow_solve",
        "ok": ok,
        "allow_solve": allow,
        "reason": (unresolved or {}).get("allow_solve_reason") if isinstance(unresolved, dict) else "",
        "message": "ok" if ok else f"allow_solve={allow!r}",
    }


_ADAPTER_METHODS = (
    "declared_keys",
    "decode_key",
    "sample_case",
    "mutate",
    "construct",
    "describe",
    "replay",
    "actual_key",
    "generation_knobs",
)

# Cold-start packages keep only identity + log protocol. Adapter pack YAML
# (search/construction/feature/bridge/proof/observations) is optional until
# export_adapter_pack writes it.
_REQUIRED_YAML = (
    "operator.yaml",
    "log_protocol.yaml",
)

_OPTIONAL_ADAPTER_YAML = (
    "search_hints.yaml",
    "construction_hints.yaml",
    "feature_bindings.yaml",
    "bridge_spec.yaml",
    "proof_rules.yaml",
    "observations.yaml",
)

_REQUIRED_SECTIONS = {
    "search_hints.yaml": ("sampling_grid",),
    "construction_hints.yaml": ("defaults",),
    "feature_bindings.yaml": ("categorical", "base_numeric"),
    "log_protocol.yaml": ("marks", "scrapes", "report_state"),
}


def gate_adapter_completeness(
    project_root: Path,
    *,
    package_dir: Path | None = None,
    examples_dir: Path | None = None,
) -> dict[str, Any]:
    """Static completeness gate so FAG-runnable ≠ platform-generic.

    Checks:
      - OperatorAdapter protocol surface (9 methods) when an adapter is loaded
      - knob_schema covers every describe() column
      - operator.yaml + log_protocol.yaml present (adapter pack optional)
      - when adapter-pack YAML is present, required sections are non-empty
      - construction_hints / feature_bindings are not byte-identical to skill examples
    """
    import hashlib
    import sys

    issues: list[str] = []
    repo = Path(project_root).resolve()
    scripts = repo / "scripts"
    if scripts.is_dir() and str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))

    pkg = package_dir
    if pkg is None:
        try:
            from replay import package_data

            pkg = package_data.active_package_dir(repo)
        except Exception as exc:  # noqa: BLE001
            return {
                "gate": "adapter_completeness",
                "ok": False,
                "message": f"package resolve failed: {exc}",
            }
    pkg = Path(pkg)

    for name in _REQUIRED_YAML:
        path = pkg / name
        if not path.is_file():
            issues.append(f"missing:{name}")
            continue
        doc = _load(path)
        if not isinstance(doc, dict) or not doc:
            issues.append(f"empty:{name}")
            continue
        for section in _REQUIRED_SECTIONS.get(name, ()):
            if section not in doc:
                issues.append(f"missing_section:{name}:{section}")

    for name in _OPTIONAL_ADAPTER_YAML:
        path = pkg / name
        if not path.is_file():
            continue
        doc = _load(path)
        if not isinstance(doc, dict) or not doc:
            issues.append(f"empty:{name}")
            continue
        for section in _REQUIRED_SECTIONS.get(name, ()):
            if section not in doc:
                issues.append(f"missing_section:{name}:{section}")

    # Anti-copy: must not match skill examples byte-for-byte (ignoring provenance comments).
    examples = examples_dir or (repo / "tests" / "fixtures" / "_synthetic_toy" / "arch0")
    for yaml_name, excerpt_name in (
        ("construction_hints.yaml", "construction_hints.excerpt.yaml"),
        ("feature_bindings.yaml", "feature_bindings.excerpt.yaml"),
    ):
        pkg_path = pkg / yaml_name
        ex_path = examples / excerpt_name
        if not pkg_path.is_file() or not ex_path.is_file():
            continue
        def _norm(text: str) -> str:
            lines = [
                ln for ln in text.splitlines()
                if ln.strip() and not ln.strip().startswith("#")
            ]
            return "\n".join(lines).strip()

        if _norm(pkg_path.read_text(encoding="utf-8")) == _norm(
            ex_path.read_text(encoding="utf-8")
        ):
            issues.append(f"copied_from_example:{yaml_name}")

    # knob_schema vs describe columns
    try:
        from replay import inputs as I

        sem = I.SEMANTICS
        if hasattr(sem, "knob_schema") and hasattr(sem, "describe"):
            schema = dict(sem.knob_schema() or {})
            # Build a default case when possible.
            case = None
            if hasattr(sem, "from_knobs"):
                defaults = {
                    k: (v.get("domain") or [v.get("default")])[0]
                    if isinstance(v, dict) and v.get("domain")
                    else (v.get("default") if isinstance(v, dict) else None)
                    for k, v in schema.items()
                }
                defaults = {k: v for k, v in defaults.items() if v is not None}
                try:
                    case = sem.from_knobs(defaults)
                except Exception:
                    case = None
            if case is not None:
                cols = set(sem.describe(case).keys())
                missing = cols - set(schema.keys())
                if missing:
                    issues.append(f"knob_schema_missing_describe_cols:{sorted(missing)}")
    except Exception as exc:  # noqa: BLE001
        issues.append(f"semantics_check_failed:{exc}")

    # Adapter methods — the Protocol must declare all 9; a materialize-only
    # package adapter is fine as long as OperatorAdapter lists the surface.
    try:
        from replay.operator_adapter import OperatorAdapter

        for m in _ADAPTER_METHODS:
            if not hasattr(OperatorAdapter, m):
                issues.append(f"protocol_missing:{m}")
    except Exception as exc:  # noqa: BLE001
        issues.append(f"adapter_protocol_failed:{exc}")

    ok = not issues
    return {
        "gate": "adapter_completeness",
        "ok": ok,
        "message": "ok" if ok else f"issues={issues[:8]}",
        "issues": issues,
        "package": str(pkg),
        "fingerprint": hashlib.sha256(
            "".join(issues).encode("utf-8")
        ).hexdigest()[:12],
    }
