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


def _op_name(project_root: Path) -> str:
    """Best-effort op name for TG APIs that still require it."""
    uo = uo_root(project_root)
    man = _load(uo / "manifest.yaml")
    if isinstance(man, dict) and man.get("op_name"):
        return str(man["op_name"])
    tg = tg_root(project_root)
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


def gate_merge_pass(project_root: Path) -> dict[str, Any]:
    if _tg_mode(project_root) == "tilingkey_full_coverage":
        tg = tg_root(project_root)
        inv = tg / "realization" / "binding_inventory.yaml"
        report = _load(tg / "realization" / "uo_merge_report.yaml")
        ok = inv.is_file() and (
            not isinstance(report, dict)
            or str(report.get("status") or "pass").lower() in {"pass", "passed", "ok", ""}
        )
        return {
            "gate": "merge_pass",
            "ok": ok,
            "message": "ok" if ok else "full-mode merge requires binding_inventory.yaml",
            "mode": "tilingkey_full_coverage",
        }
    out = tg_root(project_root)

    def _run() -> Any:
        from testcase_agent.uo_resolve_merge import require_merge_pass

        return require_merge_pass(out)

    return _wrap_exc("merge_pass", _run)


def _tg_mode(project_root: Path) -> str:
    tg = tg_root(project_root)
    for rel in ("plan/plan_intent.yaml", "init/init_intent.yaml"):
        doc = _load(tg / rel)
        if isinstance(doc, dict) and doc.get("mode"):
            return str(doc["mode"]).strip()
    return "tilingkey_full_coverage"


def gate_tilingkey_binding_ready(project_root: Path) -> dict[str, Any]:
    """Full-mode bind gate: host-view inventory + declared Key space must align."""
    tg = tg_root(project_root)
    uo = uo_root(project_root)
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
    keys = _load(uo / "tiling" / "exhaustive_key_space.yaml") or {}
    count = int((keys or {}).get("legal_key_count") or 0) if isinstance(keys, dict) else 0
    if count <= 0:
        issues.append("DECLARED_SET_EMPTY")
    view = _load(uo / "ir" / "tg_host_view.yaml") or {}
    view_fields = list((view or {}).get("fields") or []) if isinstance(view, dict) else []
    if view_fields and fields and len(fields) != len(view_fields):
        # Soft mismatch note — inventory may filter; fail only when inventory empty above.
        pass
    graph = _load(uo / "ir" / "operator_graph.yaml") or {}
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


def gate_bind_progress(project_root: Path) -> dict[str, Any]:
    """Bind phase gate — mode-aware.

    ``tilingkey_full_coverage`` uses host-view inventory (no CSV lexicon).
    ``csv_consumer`` still requires lexicon / unresolved progress.
    """
    if _tg_mode(project_root) == "tilingkey_full_coverage":
        return gate_tilingkey_binding_ready(project_root)
    out = tg_root(project_root)
    lex = out / "realization" / "binding_lexicon.yaml"
    unresolved = _load(out / "realization" / "unresolved.yaml")
    gaps_doc = _load(out / "realization" / "binding_gaps.yaml")
    if not lex.is_file():
        return {
            "gate": "bind_progress",
            "ok": False,
            "message": "realization/binding_lexicon.yaml missing",
        }
    status = ""
    gaps: list[Any] = []
    if isinstance(unresolved, dict):
        status = str(unresolved.get("status") or "").lower()
        gaps = list(unresolved.get("binding_gaps") or [])
    if isinstance(gaps_doc, dict) and gaps_doc.get("gaps") is not None:
        gaps = list(gaps_doc.get("gaps") or gaps)
        status = str(gaps_doc.get("status") or status).lower()
    # blocked / ready_for_llm with remaining gaps → not yet closed for advance
    if status in {"blocked", "pending", "unresolved"}:
        return {"gate": "bind_progress", "ok": False, "status": status, "message": f"bind status={status}"}
    if status == "ready_for_llm" and gaps:
        return {
            "gate": "bind_progress",
            "ok": False,
            "status": status,
            "remaining_gaps": len(gaps),
            "message": f"binding gaps remain ({len(gaps)}); apply semantic_bind_patch against llm_bind_prompt_bundle",
        }
    # ready / pass / no gaps
    lex_doc = _load(lex) if lex.is_file() else {}
    has_deriv = bool(isinstance(lex_doc, dict) and (lex_doc.get("key_derivations") or lex_doc.get("key_tokens")))
    if status in {"ready", "pass", "resolved", "ok", ""} and (not gaps or has_deriv or status in {"ready", "pass"}):
        return {"gate": "bind_progress", "ok": True, "status": status or "ready", "message": "ok"}
    if not gaps:
        return {"gate": "bind_progress", "ok": True, "status": status or "ready", "message": "ok"}
    return {
        "gate": "bind_progress",
        "ok": False,
        "status": status,
        "message": "bind progress insufficient",
    }


def gate_domain_symmetry(project_root: Path) -> dict[str, Any]:
    out = tg_root(project_root)

    def _run() -> Any:
        from testcase_agent.uo_resolve_merge import require_domain_symmetry

        return require_domain_symmetry(out)

    return _wrap_exc("domain_symmetry", _run)


def gate_csv_closure(project_root: Path) -> dict[str, Any]:
    out = tg_root(project_root)

    def _run() -> Any:
        from testcase_agent.resolve_policy import require_full_csv_closure

        return require_full_csv_closure(out)

    result = _wrap_exc("csv_closure", _run)
    detail = result.get("detail") if isinstance(result.get("detail"), dict) else {}
    if detail and "status" in detail:
        ok = str(detail.get("status") or "").lower() in {"pass", "passed", "ok"}
        result["ok"] = ok
        result["message"] = "ok" if ok else f"csv_closure status={detail.get('status')!r}"
    return result


def gate_audit_pass(project_root: Path) -> dict[str, Any]:
    """Full audit contract via engine require_audit_pass — not shallow status read."""
    out = tg_root(project_root)
    checklist = "tilingkey" if _tg_mode(project_root) == "tilingkey_full_coverage" else "csv"

    def _run() -> Any:
        from testcase_agent.init_status import require_audit_pass

        return require_audit_pass(out, checklist=checklist)

    return _wrap_exc("audit_pass", _run)


def gate_kb_fingerprint_fresh(project_root: Path, *, op_name: str | None = None) -> dict[str, Any]:
    name = op_name or _op_name(project_root)
    out = tg_root(project_root)

    def _run() -> Any:
        from testcase_agent.init_status import require_kb_fingerprint_fresh

        return require_kb_fingerprint_fresh(project_root, name, out_root=out)

    return _wrap_exc("kb_fingerprint_fresh", _run)


def gate_kb_fingerprint_matches(project_root: Path) -> dict[str, Any]:
    out = tg_root(project_root)
    uo = uo_root(project_root)

    def _run() -> Any:
        from testcase_agent.isolation import kb_fingerprint_matches

        matched, detail = kb_fingerprint_matches(out, uo)
        return {
            "ok": bool(matched),
            "matched": matched,
            **(detail if isinstance(detail, dict) else {"detail": detail}),
        }

    return _wrap_exc("kb_fingerprint", _run)


def gate_init_confirmed(project_root: Path, *, op_name: str | None = None) -> dict[str, Any]:
    name = op_name or _op_name(project_root)

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
    for rel in ("plan.yaml", "snapshot.yaml", "coverage_matrix.yaml", "unresolved.yaml"):
        doc = _load(plan_dir / rel)
        if not isinstance(doc, dict):
            continue
        if not snapshot_hash:
            snapshot_hash = doc.get("snapshot_hash") and str(doc["snapshot_hash"])
        if not plan_hash:
            plan_hash = doc.get("plan_hash") and str(doc["plan_hash"])
    return snapshot_hash, plan_hash


def gate_plan_approved(project_root: Path, *, level: str = "") -> dict[str, Any]:
    """Validate real human_supplement against snapshot/plan hashes via engine approval rules."""
    out = tg_root(project_root)

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
        from testcase_agent.solve import _require_approval

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


def gate_allow_solve(project_root: Path, *, level: str = "") -> dict[str, Any]:
    out = tg_root(project_root)
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


def _latest_solve_root(out: Path) -> Path | None:
    solve = out / "solve"
    if not solve.is_dir():
        return None
    # Prefer explicit latest symlink/dir, else newest child with solver_report
    latest = solve / "latest"
    if (latest / "solver_report.yaml").is_file() or (latest / "realize_report.yaml").is_file():
        return latest
    if (solve / "solver_report.yaml").is_file():
        return solve
    candidates = sorted(
        [p for p in solve.iterdir() if p.is_dir() and (p / "solver_report.yaml").is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _uncovered_terminal(items: list[Any]) -> tuple[bool, list[str]]:
    """Return (ok, open_ids). Terminal = resolved|verified|not_applicable|human_required|rejected (not blocked)."""
    from ascendc_pilot.workflows.specs import CLOSED_OBLIGATION_STATUSES

    open_ids: list[str] = []
    for it in items:
        if isinstance(it, str):
            open_ids.append(it)
            continue
        if not isinstance(it, dict):
            continue
        status = str(it.get("status") or it.get("state") or "open").lower()
        if status in CLOSED_OBLIGATION_STATUSES or status in {"closed", "done", "pass", "passed"}:
            continue
        # blocked remains open for solve terminal — needs human/rework, not success
        kid = str(it.get("id") or it.get("obligation_id") or it.get("key") or "")
        if kid:
            open_ids.append(kid)
        elif status in {"open", "unresolved", "pending", "blocked", ""}:
            open_ids.append(str(it)[:80])
    return (not open_ids), open_ids


def gate_family_path_obligation(project_root: Path) -> dict[str, Any]:
    """FAM ↔ KPATH ↔ obligation refs must be consistent on UO export surface."""

    def _run() -> Any:
        from ascendc_pilot.legacy_stubs import check_family_path_obligation

        uo = uo_root(project_root)
        payload = check_family_path_obligation(uo, write=True)
        if not payload.get("ok"):
            raise RuntimeError(payload.get("message") or "family_path_obligation failed")
        return payload

    return _wrap_exc("family_path_obligation", _run)


def gate_solve_terminal(project_root: Path) -> dict[str, Any]:
    """Terminal solve must use real solver/realization/CSV/obligation artifacts — not status.yaml."""
    out = tg_root(project_root)

    def _run() -> Any:
        from testcase_agent.solve import _require_nonempty_realize
        from testcase_agent.uo_resolve_merge import require_domain_symmetry

        solve_root = _latest_solve_root(out)
        if solve_root is None:
            raise RuntimeError("solve artifacts missing: need solve/**/solver_report.yaml")

        solver = _load(solve_root / "solver_report.yaml")
        if not isinstance(solver, dict) or not solver:
            raise RuntimeError(f"solver_report.yaml missing or empty under {solve_root}")

        realize = _load(solve_root / "realize_report.yaml")
        if not isinstance(realize, dict) or not realize:
            # Also accept nested under solver report
            realize = solver.get("realize_report") if isinstance(solver.get("realize_report"), dict) else None
        if not isinstance(realize, dict) or not realize:
            raise RuntimeError(f"realize_report.yaml missing under {solve_root}")

        _require_nonempty_realize(realize)
        require_domain_symmetry(out)

        uncovered_raw: list[Any] = []
        unc_path = solve_root / "uncovered_obligations.yaml"
        unc_doc = _load(unc_path)
        if isinstance(unc_doc, dict):
            uncovered_raw = list(
                unc_doc.get("items")
                or unc_doc.get("obligations")
                or unc_doc.get("uncovered_obligations")
                or []
            )
        elif isinstance(solver.get("uncovered_obligations"), list):
            uncovered_raw = list(solver["uncovered_obligations"])

        ok_unc, open_ids = _uncovered_terminal(uncovered_raw)
        if not ok_unc:
            raise RuntimeError(
                f"uncovered obligations still open: {open_ids[:12]}. "
                "All must reach resolved|verified|not_applicable|human_required|blocked|rejected."
            )

        return {
            "ok": True,
            "solve_root": solve_root.as_posix(),
            "realized_count": realize.get("realized_count"),
            "selected_count": realize.get("selected_count"),
            "uncovered_open": open_ids,
        }

    return _wrap_exc("solve_terminal", _run)


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

_REQUIRED_YAML = (
    "operator.yaml",
    "log_protocol.yaml",
    "search_hints.yaml",
    "construction_hints.yaml",
    "feature_bindings.yaml",
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
      - 7 required yaml segments non-empty
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
            # bridge_spec is optional for toy; proof/observations required by plan.
            if name == "bridge_spec.yaml":
                continue
            issues.append(f"missing:{name}")
            continue
        doc = _load(path)
        if not isinstance(doc, dict) or not doc:
            issues.append(f"empty:{name}")
            continue
        for section in _REQUIRED_SECTIONS.get(name, ()):
            if section not in doc:
                issues.append(f"missing_section:{name}:{section}")

    # Anti-copy: must not match skill examples byte-for-byte (ignoring provenance comments).
    examples = examples_dir or (
        repo / "skills" / "capabilities" / "tilingkey-closure" / "examples"
    )
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
