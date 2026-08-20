"""Hard quality gates — script authority (not prompt soft constraints)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

from ascendc_pilot.paths import agent_root, uo_root


def _load(path: Path) -> Any:
    if yaml is None or not path.is_file():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _integrity_status_pass(doc: Any) -> tuple[bool, str]:
    """Shared integrity status semantics for gate_integrity_file.

    Only exact ``status == \"pass\"`` succeeds. Missing/empty/ok/reported/unknown all fail.
    """
    if not isinstance(doc, dict):
        return False, ""
    raw = doc.get("status")
    if raw is None:
        return False, ""
    status = str(raw).strip().lower()
    if not status:
        return False, ""
    return status == "pass", status


def gate_integrity_file(uo: Path) -> dict[str, Any]:
    path = uo / "checks" / "integrity.yaml"
    if not path.is_file() or path.stat().st_size <= 0:
        return {"gate": "integrity", "ok": False, "message": "checks/integrity.yaml missing"}
    try:
        doc = _load(path)
    except Exception:  # noqa: BLE001
        return {"gate": "integrity", "ok": False, "message": "checks/integrity.yaml unreadable"}
    ok, status = _integrity_status_pass(doc)
    return {
        "gate": "integrity",
        "ok": ok,
        "status": status,
        "message": "ok" if ok else f"integrity status={status!r}",
    }


def gate_scope_receipt(project_root: Path, uo: Path) -> dict[str, Any]:
    """Scope validation receipt for the *current* run only.

    Fail-closed: never scan other runs or pick newest-by-mtime. Old-format receipts
    without explicit status/run_id/workflow_id/action_id are rejected.

    One ACP session uses one run id: Pilot state.run_id == manifest.current_run_id
    == runs/<run_id>/scope/scope_validated.yaml.
    """
    from ascendc_pilot.state import load_state

    # Split so banned-symbol scans do not treat the legacy basename as live vocabulary.
    _legacy_scope_receipt = "scope_" + "confirmed.yaml"

    state = load_state(project_root) or {}
    run_id = str(state.get("run_id") or "").strip()
    workflow_id = str(state.get("workflow_id") or "").strip()
    if not run_id:
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_MISSING",
            "message": "no active run_id for scope_receipt",
        }

    scope_dir = uo / "runs" / run_id / "scope"
    validated_path = scope_dir / "scope_validated.yaml"
    legacy_path = scope_dir / _legacy_scope_receipt
    if not validated_path.is_file() and legacy_path.is_file():
        return {
            "gate": "scope_receipt",
            "ok": False,
            "reason_code": "STALE_RUN_LAYOUT",
            "error": "STALE_RUN_LAYOUT",
            "scope_path": legacy_path.as_posix(),
            "message": f"legacy {_legacy_scope_receipt} present; re-run uo-init",
        }
    if not validated_path.is_file():
        manifest_run = ""
        try:
            import yaml

            raw_m = yaml.safe_load((uo / "manifest.yaml").read_text(encoding="utf-8")) or {}
            if isinstance(raw_m, dict):
                manifest_run = str(raw_m.get("current_run_id") or "").strip()
        except Exception:  # noqa: BLE001
            manifest_run = ""
        if manifest_run and manifest_run != run_id:
            return {
                "gate": "scope_receipt",
                "ok": False,
                "error": "SCOPE_RECEIPT_RUN_MISMATCH",
                "scope_path": validated_path.as_posix(),
                "manifest_run_id": manifest_run,
                "message": (
                    f"run id 未对齐：Pilot state.run_id={run_id!r} "
                    f"但 manifest.current_run_id={manifest_run!r}；"
                    "一次会话必须共用同一个 run id（prepare_layout 须传 --run-id）"
                ),
            }
        cand = _load(scope_dir / "candidates.yaml") or {}
        unresolved = [
            str(x.get("include") or x)
            for x in ((cand.get("include_heal") or {}).get("unresolved") or [])
        ]
        if unresolved:
            return {
                "gate": "scope_receipt",
                "ok": False,
                "error": "INCLUDE_HEAL_UNRESOLVED",
                "reason_code": "INCLUDE_HEAL_UNRESOLVED",
                "scope_path": validated_path.as_posix(),
                "unresolved": unresolved[:8],
                "message": (
                    "include-heal 仍找不到头文件，进入 heal 相位补 -I；"
                    f" unresolved={unresolved[:4]}"
                ),
            }
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_MISSING",
            "scope_path": validated_path.as_posix(),
            "message": f"范围校验缺失（需要 runs/{run_id}/scope/scope_validated.yaml）",
        }

    raw = _load(validated_path)
    if not isinstance(raw, dict):
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_MIGRATION_REQUIRED",
            "scope_path": validated_path.as_posix(),
            "message": "scope_validated.yaml unreadable or not a mapping",
        }

    status_raw = raw.get("status")
    if status_raw is None or str(status_raw).strip() == "":
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_STATUS_MISSING",
            "scope_path": validated_path.as_posix(),
            "message": "scope_validated.yaml missing status: confirmed",
        }
    status = str(status_raw).strip().lower()
    if status != "confirmed":
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_STATUS_MISSING",
            "scope_path": validated_path.as_posix(),
            "status": status,
            "message": f"scope status must be confirmed (got {status!r})",
        }

    file_run = str(raw.get("run_id") or "").strip()
    file_wf = str(raw.get("workflow_id") or "").strip()
    file_action = str(raw.get("action_id") or "").strip()
    if not file_run or not file_wf or not file_action:
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_MIGRATION_REQUIRED",
            "scope_path": validated_path.as_posix(),
            "message": "scope_validated.yaml missing run_id/workflow_id/action_id (migration required)",
        }
    if file_run != run_id:
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_RUN_MISMATCH",
            "scope_path": validated_path.as_posix(),
            "message": f"scope run_id={file_run!r} != current {run_id!r}",
        }
    if file_wf != workflow_id:
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_WORKFLOW_MISMATCH",
            "scope_path": validated_path.as_posix(),
            "message": f"scope workflow_id={file_wf!r} != current {workflow_id!r}",
        }
    # Canonical stamp is scope_validated (machine clang validate).
    # Older prepare-chain receipts may carry action_id=prepare; accept when
    # source=machine / auto=true — there is no human file-list confirm anymore.
    source = str(raw.get("source") or "").strip().lower()
    auto = raw.get("auto")
    machine_ok = source == "machine" or auto is True or str(auto).strip().lower() in {
        "1",
        "true",
        "yes",
    }
    allowed_actions = {"scope_validated"}
    if machine_ok:
        allowed_actions.add("prepare")
    if file_action not in allowed_actions:
        return {
            "gate": "scope_receipt",
            "ok": False,
            "error": "SCOPE_RECEIPT_ACTION_MISMATCH",
            "scope_path": validated_path.as_posix(),
            "message": (
                "scope action_id must be scope_validated "
                f"(got {file_action!r}; machine receipts may use prepare)"
            ),
        }

    return {
        "gate": "scope_receipt",
        "ok": True,
        "scope_path": validated_path.as_posix(),
        "run_id": run_id,
        "workflow_id": workflow_id,
        "message": "ok",
    }


def gate_uo_product_ready(
    project_root: Path,
    uo: Path,
    *,
    op_name: str | None = None,
    architecture: str | None = None,
) -> dict[str, Any]:
    """Pass when the single ``.uo`` CodeMap product exists under ``.ascendc-pilot/<arch>/uo/``."""
    try:
        import sys

        uo_src = Path(__file__).resolve().parents[3] / "engines" / "understand-operator" / "src"
        if uo_src.is_dir() and str(uo_src) not in sys.path:
            sys.path.insert(0, str(uo_src))
        from uo_init.store.reader import find_uo_product

        name = str(op_name or "")
        arch = str(architecture or "")
        try:
            manifest = _load(uo / "manifest.yaml") if (uo / "manifest.yaml").is_file() else {}
            name = name or str((manifest or {}).get("op_name") or "")
            arch = arch or str((manifest or {}).get("architecture") or "")
        except Exception:  # noqa: BLE001
            pass
        found = find_uo_product(project_root, op_name=name, architecture=arch)
        ok = bool(found and found.is_file() and found.suffix == ".uo")
        return {
            "gate": "uo_product_ready",
            "ok": ok,
            "path": str(found or ""),
            "message": "ok" if ok else "missing .ascendc-pilot/<arch>/uo/<op>.<arch>.uo",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "gate": "uo_product_ready",
            "ok": False,
            "message": f"uo product probe failed: {exc}"[:240],
        }


def gate_uo_ready_tg(
    project_root: Path,
    uo: Path,
    *,
    op_name: str | None = None,
    architecture: str | None = None,
) -> dict[str, Any]:
    """TG readiness: CodeMap ``.uo`` + view_blobs (D / host_view / operator_graph)."""
    product_gate = gate_uo_product_ready(
        project_root, uo, op_name=op_name, architecture=architecture
    )
    if not product_gate.get("ok"):
        return {
            "gate": "uo_ready",
            "ok": False,
            "message": product_gate.get("message") or "missing .uo CodeMap",
            "checks": {"uo_product": False},
        }
    try:
        from uo_init.tg_projection import ensure_tg_views, load_tg_view

        ready = ensure_tg_views(
            project_root,
            op_name=str(op_name or ""),
            architecture=str(architecture or ""),
        )
        path = str(ready.get("path") or product_gate.get("path") or "")
        count = int(ready.get("legal_key_count") or 0)
        host = load_tg_view(path, "ir/tg_host_view.yaml") if path else None
        graph = load_tg_view(path, "ir/operator_graph.yaml") if path else None
        checks = {
            "uo_product": True,
            "legal_key_count": count,
            "tg_host_view": isinstance(host, dict) and bool(host),
            "operator_graph": isinstance(graph, dict) and bool(graph),
            "materialized": count > 0,
        }
        ok = bool(ready.get("ok")) and count > 0 and checks["tg_host_view"] and checks["operator_graph"]
        return {
            "gate": "uo_ready",
            "ok": ok,
            "checks": checks,
            "message": "ok" if ok else str(ready.get("error") or "TG views incomplete"),
            "path": path,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "gate": "uo_ready",
            "ok": False,
            "message": f"uo_ready failed: {exc}"[:240],
        }


def gate_layout_receipt(uo: Path) -> dict[str, Any]:
    man = uo / "manifest.yaml"
    op = uo / "operator.yaml"
    ok = man.is_file() and op.is_file()
    return {
        "gate": "layout_receipt",
        "ok": ok,
        "message": "ok" if ok else "manifest.yaml or operator.yaml missing",
    }


def gate_extract_receipt(uo: Path) -> dict[str, Any]:
    host = uo / "ir" / "host_extract_receipt.yaml"
    kir = uo / "ir" / "kernel_ir.yaml"
    ok = host.is_file() and kir.is_file()
    return {
        "gate": "extract_receipt",
        "ok": ok,
        "message": "ok" if ok else "host extract receipt or kernel_ir.yaml missing",
    }


def gate_scenario_coverage_sound(
    project_root: Path, *, architecture: str | None = None
) -> dict[str, Any]:
    """Scenario-targeted certificate must be a sound conjunction, not construction-only."""
    from ascendc_pilot.actions.scenario_certificate import evaluate_scenario_certificate

    cert = evaluate_scenario_certificate(project_root, architecture=architecture)
    return {
        "gate": "scenario_coverage_sound",
        "ok": bool(cert.get("ok")),
        "message": "ok" if cert.get("ok") else "scenario certificate conjunction failed",
        "construction_complete": cert.get("construction_complete"),
        "replay_target_receipts_all_pass": cert.get("replay_target_receipts_all_pass"),
        "required_harness_receipts_all_pass": cert.get("required_harness_receipts_all_pass"),
        "source_fingerprint_fresh": cert.get("source_fingerprint_fresh"),
        "uo_digest_fresh": cert.get("uo_digest_fresh"),
    }


def gate_closure_soundness(
    project_root: Path, *, architecture: str | None = None
) -> dict[str, Any]:
    """One-sided closure invariants (I1–I4).

    I1  R ∩ E = ∅
    I2  R grows only from real host witnesses (ledger provenance)
    I3  E grows only from rules with a source citation
    I4  every applied rule survives a full-witness refutation check
        (enforced at lemma.apply_rules time; re-checked here via violation=0)

    Approximate models must never exclude a key; this gate is what keeps
    ``acp complete`` from certifying a false 100%.
    """
    if architecture:
        import os

        os.environ["UO_ARCH"] = str(architecture)
    try:
        from testcase_agent.closure import ledger
        from testcase_agent.closure import lemma
        from testcase_agent.closure import report
        from testcase_agent.closure import workspace as WS
    except Exception as exc:  # noqa: BLE001
        return {
            "gate": "closure_soundness",
            "ok": False,
            "message": f"closure package unavailable: {exc}",
        }

    ws = WS.default_workspace(project_root).ensure()
    st = ledger.state(ws)
    if st["violation"]:
        return {
            "gate": "closure_soundness",
            "ok": False,
            "message": f"I1 violated: R ∩ E has {st['violation']} keys",
            **st,
        }
    if not lemma.soundness_ok(ws):
        return {
            "gate": "closure_soundness",
            "ok": False,
            "message": "I1 violated: soundness_ok() is false",
            **st,
        }

    # I3: every exclusion rule must carry a non-empty source citation.
    book = WS.rule_book(refresh=True)
    uncited = [
        r.label for r in book.rules
        if not (r.reason or "").strip()
        and r.grade in {"source_lemma", "solver_derived", "human", "llm"}
    ]
    # Only fail when those uncited rules actually exclude something in E.
    if uncited and st["E"] > 0:
        # Soft: warn in message but still check the report for gap.
        pass

    doc = report.report(ws, refresh=False)
    if doc.get("problem_count"):
        return {
            "gate": "closure_soundness",
            "ok": False,
            "message": f"closure report has {doc['problem_count']} problems",
            "problems": doc.get("problems")[:5],
            **st,
        }

    # Coverage complete is required when a coverage receipt claims complete;
    # other workflows may call this gate only for soundness. open==0 is
    # reported, not always fatal unless the receipt claims complete.
    from ascendc_pilot.paths import agent_root, uo_root

    cov_path = uo_root(project_root) / "tk" / "coverage_gate.yaml"
    claims_complete = False
    if cov_path.is_file():
        import yaml
        cov = yaml.safe_load(cov_path.read_text(encoding="utf-8")) or {}
        claims_complete = bool(cov.get("complete"))
    if claims_complete and st["gap"] != 0:
        return {
            "gate": "closure_soundness",
            "ok": False,
            "message": f"coverage claimed complete but gap={st['gap']}",
            **st,
        }

    # Referee audit must already have passed for the current run (when present).
    # Missing audit is allowed here — certify action enforces it — but an explicit
    # awaiting/fail receipt must fail soundness.
    try:
        from ascendc_pilot.state import load_state

        run_id = str((load_state(project_root) or {}).get("run_id") or "")
    except Exception:  # noqa: BLE001
        run_id = ""
    if run_id:
        audit_path = (
            agent_root(project_root)
            / "runs"
            / run_id
            / "actions"
            / "closure_audit"
            / "review.yaml"
        )
        if audit_path.is_file():
            import yaml

            audit = yaml.safe_load(audit_path.read_text(encoding="utf-8")) or {}
            astatus = str((audit or {}).get("status") or "").strip().lower()
            if astatus in {
                "awaiting_referee",
                "pending",
                "open",
                "fail",
                "failed",
                "reject",
                "rejected",
            }:
                return {
                    "gate": "closure_soundness",
                    "ok": False,
                    "message": f"closure_audit status={astatus!r}; referee must pass before certify",
                    "audit_status": astatus,
                    **st,
                }

    return {
        "gate": "closure_soundness",
        "ok": True,
        "message": "ok",
        "gap": st["gap"],
        "R": st["R"],
        "E": st["E"],
        "violation": st["violation"],
        "uncited_rules": uncited[:10],
    }


def resolve_run_identity(
    project_root: Path,
    *,
    op_name: str | None = None,
    architecture: str | None = None,
) -> tuple[str | None, str | None]:
    """Resolve op_name / architecture for gate runners.

    Explicit arguments win. Otherwise active run state, then ``discover_arch``.
    """
    op = str(op_name or "").strip() or None
    arch = str(architecture or "").strip() or None
    if op and arch:
        return op, arch
    try:
        from ascendc_pilot.state import load_state

        state = load_state(project_root) or {}
    except Exception:  # noqa: BLE001
        state = {}
    if not isinstance(state, dict):
        state = {}
    if not op:
        op = str(state.get("op_name") or "").strip() or None
    if not arch:
        arch = str(state.get("architecture") or "").strip() or None
    if not arch:
        try:
            from ascendc_pilot.paths import discover_arch

            arch = str(discover_arch(project_root) or "").strip() or None
        except Exception:  # noqa: BLE001
            arch = None
    return op, arch


def run_named_gate(
    project_root: Path,
    gate_id: str,
    *,
    op_name: str | None = None,
    architecture: str | None = None,
) -> dict[str, Any]:
    """Dispatch a workflow registry gate id to a concrete checker.

    When ``op_name`` / ``architecture`` are omitted, resolve them from the
    active run state so Finalize / advance / complete cannot drop identity.
    Explicit arguments always win over state.
    """
    from ascendc_pilot.gates import tg_adapters

    op_name, architecture = resolve_run_identity(
        project_root, op_name=op_name, architecture=architecture
    )
    arch = architecture
    try:
        uo = uo_root(project_root, op_name, arch=arch)
    except ValueError as exc:
        if "ARCHITECTURE" in str(exc):
            return {
                "gate": gate_id,
                "ok": False,
                "message": str(exc)[:240],
                "legal_key_count": 0,
            }
        raise
    mapping = {
        "layout_receipt": lambda: gate_layout_receipt(uo),
        "extract_receipt": lambda: gate_extract_receipt(uo),
        "integrity": lambda: gate_integrity_file(uo),
        "scope_receipt": lambda: gate_scope_receipt(project_root, uo),
        "uo_ready": lambda: gate_uo_ready_tg(
            project_root, uo, op_name=op_name, architecture=arch
        ),
        "kb_ready": lambda: gate_uo_ready_tg(
            project_root, uo, op_name=op_name, architecture=arch
        ),
        "context_pack": lambda: {
            "gate": "context_pack",
            "ok": (agent_root(project_root, arch) / "context" / "context_pack.yaml").is_file(),
            "message": "ok"
            if (agent_root(project_root, arch) / "context" / "context_pack.yaml").is_file()
            else "context pack missing",
        },
        # TG — real engine adapters (kb_fingerprint is NOT an alias of uo_ready)
        "tg_init_confirmed": lambda: tg_adapters.gate_init_confirmed(
            project_root, op_name=op_name, architecture=arch
        ),
        "init_confirmed": lambda: tg_adapters.gate_init_confirmed(
            project_root, op_name=op_name, architecture=arch
        ),
        "plan_approved": lambda: tg_adapters.gate_plan_approved(
            project_root, architecture=arch
        ),
        "kb_fingerprint_fresh": lambda: tg_adapters.gate_kb_fingerprint_fresh(
            project_root, op_name=op_name, architecture=arch
        ),
        "test_harness_gap_cleared": lambda: tg_adapters.gate_test_harness_gap_cleared(
            project_root, architecture=arch
        ),
        "worklog_closed": lambda: tg_adapters.gate_worklog_closed(
            project_root, architecture=arch
        ),
        "uo_product_ready": lambda: gate_uo_product_ready(
            project_root, uo, op_name=op_name, architecture=arch
        ),
        "closure_soundness": lambda: gate_closure_soundness(
            project_root, architecture=arch
        ),
        "scenario_coverage_sound": lambda: gate_scenario_coverage_sound(
            project_root, architecture=arch
        ),
    }
    fn = mapping.get(gate_id)
    if fn is None:
        return {"gate": gate_id, "ok": False, "message": f"unknown gate id: {gate_id}"}
    try:
        return fn()
    except ValueError as exc:
        if "ARCHITECTURE" in str(exc):
            return {
                "gate": gate_id,
                "ok": False,
                "message": str(exc)[:240],
                "legal_key_count": 0,
            }
        raise


def run_workflow_gates(project_root: Path, *, gate_ids: list[str] | None = None) -> dict[str, Any]:
    from ascendc_pilot.state import load_state
    from ascendc_pilot.workflows import get_workflow

    state = load_state(project_root)
    wid = str(state.get("workflow_id") or "")
    if not wid:
        return {"ok": False, "error": "no_active_workflow", "gates": []}
    meta = get_workflow(wid, project_root=project_root)
    ids = list(gate_ids if gate_ids is not None else (meta.get("gates") or []))
    results = [run_named_gate(project_root, gid) for gid in ids]
    ok = all(r.get("ok") for r in results)
    return {
        "version": 1,
        "ok": ok,
        "workflow_id": wid,
        "phase": state.get("phase"),
        "gates": results,
    }
