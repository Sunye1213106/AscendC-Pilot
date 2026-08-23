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
    for rel in ("init.yaml",):
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


def gate_plan_approved(
    project_root: Path, *, level: str = "", architecture: str | None = None
) -> dict[str, Any]:
    del level
    out = tg_root(project_root, arch=architecture)

    def _run() -> Any:
        from testcase_agent.products import is_plan_approved, load_plan, pending_test_harness_gap

        text, fence = load_plan(out)
        if pending_test_harness_gap(text, fence):
            raise RuntimeError("TEST_HARNESS_GAP_PENDING: CE-apply the test-script repo then /tg-init before solve")
        if not is_plan_approved(fence):
            raise RuntimeError("APPROVAL_REQUIRED: plan.md is not approved")
        return {
            "ok": True,
            "status": "approved",
            "plan": (out / "plan.md").as_posix(),
        }

    return _wrap_exc("plan_approved", _run)


def gate_test_harness_gap_cleared(
    project_root: Path, *, architecture: str | None = None
) -> dict[str, Any]:
    out = tg_root(project_root, arch=architecture)

    def _run() -> Any:
        from testcase_agent.products import load_plan, pending_test_harness_gap

        text, fence = load_plan(out)
        if pending_test_harness_gap(text, fence):
            raise RuntimeError("TEST_HARNESS_GAP_PENDING")
        return {"ok": True, "test_harness_gap_pending": False}

    return _wrap_exc("test_harness_gap_cleared", _run)


def gate_harness_intent_cleared(
    project_root: Path, *, architecture: str | None = None
) -> dict[str, Any]:
    return gate_test_harness_gap_cleared(project_root, architecture=architecture)


def gate_worklog_closed(
    project_root: Path, *, architecture: str | None = None
) -> dict[str, Any]:
    out = tg_root(project_root, arch=architecture)

    def _run() -> Any:
        from testcase_agent.coverage.ledger import ledger_closed, parse_worklog_fence
        from testcase_agent.products import worklog_path

        path = worklog_path(out)
        if not path.is_file():
            raise RuntimeError("missing tg/worklog.md")
        ledger = parse_worklog_fence(path.read_text(encoding="utf-8"))
        closed, problems = ledger_closed(ledger)
        if not closed:
            raise RuntimeError(f"worklog ledger not closed: {problems}")
        return {"ok": True, "problems": []}

    return _wrap_exc("worklog_closed", _run)


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
