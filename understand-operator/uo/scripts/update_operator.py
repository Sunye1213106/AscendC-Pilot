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
from uo._operator.kb_compiler import validate_kb
from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.build_layered_kb import build_layered_kb
from uo.scripts.detect_kb_changes import detect_kb_changes
from uo.scripts.export_diff_product import export_diff_product
from uo.scripts.plan_kb_update import plan_kb_update


def update_operator(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
    base: str | None = None,
    head: str | None = None,
    confirm_phase0: bool = False,
    skip_validate: bool = False,
) -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    if not (uo_root / "manifest.yaml").exists():
        raise FileNotFoundError(f"KB missing at {uo_root}; run /uo-init first")
    if not (uo_root / "ir" / "operator_graph.yaml").exists():
        raise FileNotFoundError("ir/operator_graph.yaml missing; run /uo-init extract first")

    change_set = detect_kb_changes(repo_root, op_name, base=base, head=head, write=True)
    plan = plan_kb_update(repo_root, op_name, change_set=change_set, write=True)

    run_id = _new_run_id()
    update_dir = uo_root / "runs" / run_id / "update"
    update_dir.mkdir(parents=True, exist_ok=True)
    write_yaml(update_dir / "change_set.yaml", change_set)
    write_yaml(update_dir / "update_plan.yaml", plan)

    if plan.get("mode") == "blocked_phase0" or (plan.get("needs_phase0_review") and not confirm_phase0 and not plan.get("scoped_changed_files")):
        export_diff_product(repo_root, op_name, change_set=change_set, update_plan=plan, status="blocked", write=True)
        receipt = _receipt(run_id, change_set, plan, status="blocked", message="needs Phase0 scope review before update")
        write_yaml(update_dir / "receipt.yaml", receipt)
        return {"status": "blocked", "run_id": run_id, "plan": plan, "change_set": change_set, "receipt": receipt}

    if plan.get("needs_phase0_review") and not confirm_phase0:
        # Scoped changes exist but also suspicious out-of-scope files: block unless confirmed.
        suspicious = [f for f in (change_set.get("files") or []) if f.get("suspicious_out_of_scope")]
        if suspicious:
            export_diff_product(repo_root, op_name, change_set=change_set, update_plan=plan, status="blocked", write=True)
            receipt = _receipt(
                run_id,
                change_set,
                plan,
                status="blocked",
                message="out-of-scope operator sources detected; re-run Phase0 or pass --confirm-phase0",
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

    graph = build_layered_kb(repo_root, op_name, architecture=architecture, layers=layers or None)
    write_yaml(update_dir / "rebuild_layers.yaml", {"layers": graph.get("rebuild_layers") or sorted(layers)})

    _bump_manifest(uo_root, repo_root, run_id, change_set.get("head_revision"))

    validate_result = None
    confidence_result: dict[str, Any] | None = None
    integrity_result: dict[str, Any] | None = None
    if not skip_validate:
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
        # Init-parity gates: classify → confidence → integrity (kb-review remains agent-owned).
        try:
            from uo.scripts.classify_input_derivable import classify_and_write

            classify_and_write(uo_root)
        except Exception as exc:  # noqa: BLE001
            export_diff_product(repo_root, op_name, change_set=change_set, update_plan=plan, status="blocked", write=True)
            receipt = _receipt(
                run_id,
                change_set,
                plan,
                status="fail",
                message=f"classify_input_derivable failed: {exc}",
                validate_status=validate_result.status if validate_result else "skipped",
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
        from uo.scripts.check_final_confidence import check_final_confidence
        from uo.scripts.check_kb_integrity import check_kb_integrity

        confidence_result = check_final_confidence(uo_root, write_skeleton=True)
        if str(confidence_result.get("status") or "").lower() == "fail":
            export_diff_product(repo_root, op_name, change_set=change_set, update_plan=plan, status="blocked", write=True)
            receipt = _receipt(
                run_id,
                change_set,
                plan,
                status="fail",
                message="confidence_gate failed",
                validate_status=validate_result.status if validate_result else "skipped",
            )
            receipt["confidence_gate"] = confidence_result.get("status")
            write_yaml(update_dir / "receipt.yaml", receipt)
            return {
                "status": "fail",
                "run_id": run_id,
                "plan": plan,
                "change_set": change_set,
                "receipt": receipt,
                "validate": validate_result,
                "confidence": confidence_result,
            }
        integrity_result = check_kb_integrity(repo_root, op_name, write_outputs=True)
        if str(integrity_result.get("status") or "").lower() == "fail":
            export_diff_product(repo_root, op_name, change_set=change_set, update_plan=plan, status="blocked", write=True)
            receipt = _receipt(
                run_id,
                change_set,
                plan,
                status="fail",
                message="integrity failed",
                validate_status=validate_result.status if validate_result else "skipped",
            )
            receipt["confidence_gate"] = (confidence_result or {}).get("status")
            receipt["integrity"] = integrity_result.get("status")
            write_yaml(update_dir / "receipt.yaml", receipt)
            return {
                "status": "fail",
                "run_id": run_id,
                "plan": plan,
                "change_set": change_set,
                "receipt": receipt,
                "validate": validate_result,
                "confidence": confidence_result,
                "integrity": integrity_result,
            }

    diff_product = export_diff_product(repo_root, op_name, change_set=change_set, update_plan=plan, status="ready", write=True)
    kb_graph_export = _safe_export_kb_graph(repo_root, op_name)
    human_views = _safe_export_human_views(uo_root)
    receipt = _receipt(
        run_id,
        change_set,
        plan,
        status="pass",
        message="update complete",
        validate_status=(validate_result.status if validate_result else "skipped"),
        rebuild_layers=graph.get("rebuild_layers"),
    )
    receipt["kb_graph"] = kb_graph_export
    receipt["human_views"] = human_views
    if confidence_result is not None:
        receipt["confidence_gate"] = confidence_result.get("status")
    if integrity_result is not None:
        receipt["integrity"] = integrity_result.get("status")
    write_yaml(update_dir / "receipt.yaml", receipt)
    return {
        "status": "pass",
        "run_id": run_id,
        "plan": plan,
        "change_set": change_set,
        "diff": diff_product["index"],
        "receipt": receipt,
        "graph_stats": graph.get("stats"),
        "kb_graph": kb_graph_export,
        "human_views": human_views,
        "confidence": confidence_result,
        "integrity": integrity_result,
    }


def _safe_export_kb_graph(repo_root: Path, op_name: str) -> dict[str, Any]:
    try:
        from uo.scripts.export_kb_graph import export_kb_graph

        return export_kb_graph(repo_root, op_name, write=True)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}


def _safe_export_human_views(uo_root: Path) -> dict[str, Any]:
    try:
        from uo.scripts.export_human_views import export_human_views

        return export_human_views(uo_root, write=True)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}


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
        "--confirm-phase0",
        action="store_true",
        help="Continue despite out-of-scope suspicious sources (after human Phase0 decision)",
    )
    parser.add_argument("--skip-validate", action="store_true")
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
            confirm_phase0=args.confirm_phase0,
            skip_validate=args.skip_validate,
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
        print("Action required: Phase0 scope review (or --confirm-phase0). Diff product written with status=blocked.")
        return 1
    if status == "fail":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
