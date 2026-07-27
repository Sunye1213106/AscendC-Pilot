from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.build_layered_kb import build_layered_kb
from uo.scripts.detect_kb_changes import detect_kb_changes
from uo.scripts.export_diff_product import export_diff_product
from uo.scripts.plan_kb_update import plan_kb_update
from uo.scripts.update_artifact_io import load_change_set_if_fresh, load_update_plan_if_fresh


def update_operator(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
    base: str | None = None,
    head: str | None = None,
    confirm_scope: bool = False,
    skip_validate: bool = True,
    run_gates: bool = False,
    run_id: str | None = None,
    reuse_artifacts: bool = True,
) -> dict[str, Any]:
    """Apply structural KB update only.

    Confidence / integrity / sqlite / human views belong to workflow phases
    ``confidence_report`` and ``export_integrity`` (via ``publish_kb_products``).
    ``run_gates`` is legacy opt-in and defaults to False.
    """
    del skip_validate  # legacy CLI flag; gates are never run unless run_gates=True
    uo_root = existing_operator_root(repo_root, op_name)
    if not (uo_root / "manifest.yaml").exists():
        raise FileNotFoundError(f"KB missing at {uo_root}; run /uo-init first")
    if not (uo_root / "ir" / "operator_graph.yaml").exists():
        raise FileNotFoundError("ir/operator_graph.yaml missing; run /uo-init extract first")

    change_set: dict[str, Any] | None = None
    plan: dict[str, Any] | None = None
    if reuse_artifacts and base is None and head is None:
        change_set = load_change_set_if_fresh(uo_root)
        if change_set is not None:
            plan = load_update_plan_if_fresh(uo_root, change_set=change_set)
    if change_set is None:
        change_set = detect_kb_changes(repo_root, op_name, base=base, head=head, write=True)
    if plan is None:
        plan = plan_kb_update(repo_root, op_name, change_set=change_set, write=True)

    bound = str(run_id or "").strip()
    if bound:
        from uo._operator.run_context import is_active_run_id

        if not is_active_run_id(bound):
            raise ValueError(f"invalid run_id: {bound!r}")
        run_id = bound
    else:
        run_id = _new_run_id()
    update_dir = uo_root / "runs" / run_id / "update"
    update_dir.mkdir(parents=True, exist_ok=True)
    write_yaml(update_dir / "change_set.yaml", change_set)
    write_yaml(update_dir / "update_plan.yaml", plan)

    if plan.get("mode") == "blocked_scope" or (plan.get("needs_scope_review") and not confirm_scope and not plan.get("scoped_changed_files")):
        export_diff_product(repo_root, op_name, change_set=change_set, update_plan=plan, status="blocked", write=True)
        receipt = _receipt(run_id, change_set, plan, status="blocked", message="needs scope confirmation review before update")
        write_yaml(update_dir / "receipt.yaml", receipt)
        return {"status": "blocked", "run_id": run_id, "plan": plan, "change_set": change_set, "receipt": receipt}

    if plan.get("needs_scope_review") and not confirm_scope:
        # Scoped changes exist but also suspicious out-of-scope files: block unless confirmed.
        suspicious = [f for f in (change_set.get("files") or []) if f.get("suspicious_out_of_scope")]
        if suspicious:
            export_diff_product(repo_root, op_name, change_set=change_set, update_plan=plan, status="blocked", write=True)
            receipt = _receipt(
                run_id,
                change_set,
                plan,
                status="blocked",
                message="out-of-scope operator sources detected; re-run scope confirmation or pass --confirm-scope",
            )
            write_yaml(update_dir / "receipt.yaml", receipt)
            return {"status": "blocked", "run_id": run_id, "plan": plan, "change_set": change_set, "receipt": receipt}

    if plan.get("mode") == "noop":
        export_diff_product(repo_root, op_name, change_set=change_set, update_plan=plan, status="ready", write=True)
        _bump_manifest(uo_root, repo_root, run_id, change_set.get("head_revision"))
        receipt = _receipt(run_id, change_set, plan, status="pass", message="no in-scope changes")
        write_yaml(update_dir / "receipt.yaml", receipt)
        return {"status": "pass", "run_id": run_id, "plan": plan, "change_set": change_set, "receipt": receipt}

    layers = set(plan.get("affected_layers") or [])
    if plan.get("mode") == "full_extract":
        layers = set()  # empty => all layers in build_layered_kb

    graph = build_layered_kb(
        repo_root,
        op_name,
        architecture=architecture,
        layers=layers or None,
        mode="structural",
        allow_empty_plan=True,
    )
    write_yaml(update_dir / "rebuild_layers.yaml", {"layers": graph.get("rebuild_layers") or sorted(layers)})

    _bump_manifest(uo_root, repo_root, run_id, change_set.get("head_revision"))

    # Structural apply only — gates/export live in confidence_report / export_integrity.
    if run_gates:
        from uo._operator.kb_compiler import validate_kb
        from uo.scripts.check_final_confidence import check_final_confidence
        from uo.scripts.check_kb_integrity import check_kb_integrity
        from uo.scripts.classify_input_derivable import classify_and_write
        from uo.scripts.publish_kb_products import publish_kb_products

        validate_result = validate_kb(uo_root, op_name, phase="final", write_outputs=True)
        if validate_result.status == "fail":
            export_diff_product(repo_root, op_name, change_set=change_set, update_plan=plan, status="blocked", write=True)
            receipt = _receipt(
                run_id,
                change_set,
                plan,
                status="fail",
                message="validate_kb failed",
                validate_status=validate_result.status,
            )
            write_yaml(update_dir / "receipt.yaml", receipt)
            return {
                "status": "fail",
                "run_id": run_id,
                "plan": plan,
                "change_set": change_set,
                "receipt": receipt,
                "validate": validate_result,
            }
        classify_and_write(uo_root)
        confidence_result = check_final_confidence(uo_root, write_skeleton=True)
        publish = publish_kb_products(repo_root, op_name, graph=graph, write=True, include_integrity=True)
        integrity_result = publish.get("integrity") if isinstance(publish.get("integrity"), dict) else {}
        if str(confidence_result.get("status") or "").lower() == "fail" or not publish.get("ok", True):
            export_diff_product(repo_root, op_name, change_set=change_set, update_plan=plan, status="blocked", write=True)
            receipt = _receipt(
                run_id,
                change_set,
                plan,
                status="fail",
                message="legacy run_gates failed",
                validate_status=validate_result.status,
                rebuild_layers=graph.get("rebuild_layers"),
            )
            write_yaml(update_dir / "receipt.yaml", receipt)
            return {
                "status": "fail",
                "run_id": run_id,
                "plan": plan,
                "change_set": change_set,
                "receipt": receipt,
                "confidence": confidence_result,
                "integrity": integrity_result,
            }

    diff_product = export_diff_product(
        repo_root, op_name, change_set=change_set, update_plan=plan, status="ready", write=True
    )
    receipt = _receipt(
        run_id,
        change_set,
        plan,
        status="pass",
        message="structural update complete; export_integrity owns sqlite/human views",
        validate_status="deferred",
        rebuild_layers=graph.get("rebuild_layers"),
    )
    receipt["publish_deferred_to"] = "export_integrity"
    write_yaml(update_dir / "receipt.yaml", receipt)
    return {
        "status": "pass",
        "run_id": run_id,
        "plan": plan,
        "change_set": change_set,
        "diff": diff_product["index"],
        "receipt": receipt,
        "graph_stats": graph.get("stats"),
        "build_layered_kb_mode": "structural",
        "publish_deferred": True,
    }


def _new_run_id() -> str:
    return "UO_RUN_" + datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S%f")


def _git_revision(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _bump_manifest(uo_root: Path, repo_root: Path, run_id: str, head_revision: Any) -> None:
    path = uo_root / "manifest.yaml"
    data = read_yaml(path)
    revision = str(head_revision or _git_revision(repo_root) or "unknown")
    source = data.setdefault("source", {})
    if isinstance(source, dict):
        source["revision"] = revision
        digest = hashlib.sha256((str(repo_root) + revision).encode("utf-8")).hexdigest()[:16].upper()
        source["snapshot_id"] = f"SOURCE_{digest}"
    data["current_run_id"] = run_id
    stages = data.setdefault("stages", {})
    if isinstance(stages, dict):
        stages.setdefault("update_layered_ir", {})["status"] = "complete"
    write_yaml(path, data)


def _receipt(
    run_id: str,
    change_set: dict[str, Any],
    plan: dict[str, Any],
    *,
    status: str,
    message: str,
    validate_status: str = "",
    rebuild_layers: Any = None,
) -> dict[str, Any]:
    return {
        "version": 1,
        "run_id": run_id,
        "status": status,
        "message": message,
        "base_revision": change_set.get("base_revision"),
        "head_revision": change_set.get("head_revision"),
        "mode": plan.get("mode"),
        "affected_layers": plan.get("affected_layers") or [],
        "rebuild_layers": rebuild_layers or plan.get("affected_layers") or [],
        "validate_status": validate_status,
        "finalized_at": datetime.now(tz=timezone.utc).isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Incremental /uo-update: refresh KB + emit diff/ product")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--architecture", default="arch35")
    parser.add_argument("--base", default=None, help="Override base revision (default: manifest.source.revision)")
    parser.add_argument("--head", default=None, help="Override head revision (default: git HEAD)")
    parser.add_argument(
        "--confirm-scope",
        action="store_true",
        help="Continue despite out-of-scope suspicious sources (after human scope confirmation decision)",
    )
    parser.add_argument(
        "--skip-validate",
        action="store_true",
        help="Deprecated no-op: apply_update never runs integrity/export (use export_integrity).",
    )
    parser.add_argument(
        "--run-gates",
        action="store_true",
        help="Legacy: run validate/confidence/publish after structural rebuild (not used by Pilot workflow).",
    )
    parser.add_argument(
        "--run-id",
        default="",
        help="Bind Pilot state.run_id (one session → one run id). Omit only for standalone/legacy.",
    )
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    try:
        result = update_operator(
            repo_root,
            op_name,
            architecture=args.architecture,
            base=args.base,
            head=args.head,
            confirm_scope=args.confirm_scope,
            skip_validate=True,
            run_gates=bool(args.run_gates),
            run_id=str(args.run_id or "").strip() or None,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"uo-update failed: {exc}", file=sys.stderr)
        return 2

    status = result.get("status")
    plan = result.get("plan") or {}
    print(
        f"uo-update status={status} mode={plan.get('mode')} layers={plan.get('affected_layers')} "
        f"run={result.get('run_id')}"
    )
    if status == "blocked":
        print("Action required: scope confirmation review (or --confirm-scope). Diff product written with status=blocked.")
        return 1
    if status == "fail":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
