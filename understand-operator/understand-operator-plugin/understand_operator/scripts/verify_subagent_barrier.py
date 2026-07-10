from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from understand_operator._operator.artifacts import (
    REQUIRED_TILING_ARCHIVE_FILES,
    operator_root,
    read_text,
    safe_op_name,
    write_json,
)


PHASE_HOST_FLOW = "host_flow"
PHASE_KERNEL_PATH = "kernel_path"

HOST_FLOW_ARTIFACTS = [
    "archive/proposals/host_tiling_proposal.yaml",
    "tiling/route.md",
    "tiling/index.yaml",
    "tiling/variables.yaml",
    "tiling/key_space.yaml",
    "tiling/constraints.yaml",
    "tiling/families.yaml",
    "tiling/data_model.yaml",
    "tiling/coverage_model.yaml",
    "tiling/evidence_index.yaml",
] + list(REQUIRED_TILING_ARCHIVE_FILES)

FLOW_ARTIFACTS = [
    "archive/proposals/flow_dataflow_proposal.yaml",
    "flow/index.yaml",
    "flow/compute_graph.yaml",
    "flow/dataflow.yaml",
    "flow/golden_model.yaml",
    "flow/numerical_model.yaml",
]

HOST_FLOW_COMPLETION = "tiling/.uo_host_extraction_complete.json"
FLOW_COMPLETION = "flow/.uo_flow_extraction_complete.json"

KERNEL_CANONICAL = [
    "kernel/paths.yaml",
    "kernel/pipeline.yaml",
    "kernel/resources.yaml",
]


@dataclass
class BarrierResult:
    ok: bool
    phase: str
    missing: list[str]
    stale: list[str]
    message: str


def _approved_task_ids(uo_root: Path) -> list[str]:
    # prefer human/kernel_dispatch_review.yaml; fall back to legacy path
    candidates = [
        uo_root / "human" / "kernel_dispatch_review.yaml",
        uo_root / "kernel" / "kernel_dispatch_review.yaml",
    ]
    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        return []
    ids: list[str] = []
    in_block = False
    for line in read_text(path).splitlines():
        stripped = line.strip()
        if stripped.startswith("approved_task_ids:"):
            in_block = True
            continue
        if in_block:
            if stripped.startswith("- "):
                ids.append(stripped[2:].strip().strip('"').strip("'"))
            elif stripped and not line.startswith((" ", "\t")):
                break
    return ids


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _is_placeholder(rel_path: str, text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if rel_path.endswith("route.md") and "Tiling Entry\nunknown" in stripped:
        return True
    if rel_path.endswith("decision_tree.md") and (
        "host extraction must replace this skeleton" in stripped or stripped.endswith("unknown")
    ):
        return True
    placeholders = {
        "tiling/index.yaml": {"op_name: unknown"},
        "tiling/key_space.yaml": {"fields: {}", "encoding:\n  macro: unknown"},
        "tiling/variables.yaml": {"variables: {}"},
        "tiling/families.yaml": {"families: {}"},
        "tiling/data_model.yaml": {"family_to_struct: {}"},
        "tiling/coverage_model.yaml": {"family_obligations: []"},
        "tiling/evidence_index.yaml": {"symbols: {}"},
        "tiling/archive/frontier.yaml": {"status: pending"},
        "tiling/archive/dispatch_variables.yaml": {"status: pending"},
        "tiling/archive/predicate_space.yaml": {"status: pending"},
        "tiling/archive/compile_time_bindings.yaml": {"status: pending"},
        "flow/compute_graph.yaml": {"compute_steps: {}"},
        "flow/dataflow.yaml": {"dataflow_edges: {}"},
        "flow/golden_model.yaml": {"golden_steps: {}"},
        "flow/numerical_model.yaml": {"dtype_policy: []"},
        "kernel/paths.yaml": {"kernel_paths: {}"},
        "kernel/pipeline.yaml": {"pipelines: {}"},
        "kernel/resources.yaml": {"buffers: {}"},
    }
    if rel_path == "tiling/key_space.yaml":
        # key_space is now encoding-only; a draft is macro unknown + no fields.
        if "encoding:\n  macro: unknown" in stripped and "fields: {}" in stripped:
            return True
        return False
    if rel_path == "tiling/variables.yaml":
        # Step 1 draft: no variables and mechanism entry still unknown.
        if "variables: {}" in stripped and "entry: {file: unknown" in stripped:
            return True
        if "variables: {}" in stripped:
            return True
        return False
    if rel_path == "tiling/constraints.yaml":
        # Step 2 draft: relations empty, input_realization empty, pruning/merging unanswered.
        if (
            "relations: []" in stripped
            and "input_realization: {}" in stripped
            and "performed: unknown" in stripped
        ):
            return True
        return False
    if rel_path == "tiling/coverage_model.yaml":
        if "family_obligations: []" in stripped and "key_relation_obligations: []" in stripped:
            return True
        if "family_obligations: []" in stripped:
            return True
        return False
    for marker in placeholders.get(rel_path, set()):
        if marker in stripped:
            return True
    if rel_path.endswith("frontier.yaml") and "frontier_nodes: []" in stripped:
        return True
    if rel_path.endswith("dispatch_variables.yaml") and "variables: []" in stripped:
        return True
    if rel_path.endswith("predicate_space.yaml") and "predicate_atoms: []" in stripped:
        return True
    # compile_time_bindings: empty macros+constexpr+templates with no unresolved is lazy
    if rel_path.endswith("compile_time_bindings.yaml"):
        if (
            "macros: []" in stripped
            and "constexpr_constants: []" in stripped
            and "instantiations: []" in stripped
            and "unresolved_symbols: []" in stripped
        ):
            return True
    return False

def _completion_ok(path: Path, expected_subagent: str) -> tuple[bool, str]:
    if not path.exists():
        return False, f"missing completion manifest: {path.as_posix()}"
    data = _load_json(path)
    if data.get("status") != "complete":
        return False, f"incomplete manifest: {path.as_posix()} status={data.get('status')!r}"
    if data.get("subagent") != expected_subagent:
        return False, f"unexpected subagent in {path.name}: {data.get('subagent')!r}"
    if expected_subagent == "uo-host-extraction":
        archive = data.get("archive_artifacts") or []
        required = set(REQUIRED_TILING_ARCHIVE_FILES)
        if not required.issubset(set(archive)):
            missing = sorted(required - set(archive))
            return False, f"host completion missing archive_artifacts: {', '.join(missing)}"
    return True, ""


def verify_host_flow_barrier(uo_root: Path) -> BarrierResult:
    missing: list[str] = []
    stale: list[str] = []

    for rel in HOST_FLOW_ARTIFACTS + FLOW_ARTIFACTS:
        path = uo_root / rel
        if not path.exists():
            missing.append(rel)
            continue
        text = read_text(path)
        if _is_placeholder(rel, text):
            stale.append(rel)

    for rel, expected in (
        (HOST_FLOW_COMPLETION, "uo-host-extraction"),
        (FLOW_COMPLETION, "uo-flow-extraction"),
    ):
        ok, reason = _completion_ok(uo_root / rel, expected)
        if not ok:
            missing.append(reason)

    ok = not missing and not stale
    if ok:
        message = "host_flow barrier passed"
    else:
        parts = []
        if missing:
            parts.append(f"missing: {', '.join(missing)}")
        if stale:
            parts.append(f"still placeholder: {', '.join(stale)}")
        message = "; ".join(parts)
    return BarrierResult(ok, PHASE_HOST_FLOW, missing, stale, message)


def verify_kernel_path_barrier(uo_root: Path, task_ids: list[str]) -> BarrierResult:
    """Accept either merged canonical kernel/*.yaml or per-task raw agent outputs."""
    missing: list[str] = []
    stale: list[str] = []

    paths_yaml = uo_root / "kernel" / "paths.yaml"
    pipeline_yaml = uo_root / "kernel" / "pipeline.yaml"
    resources_yaml = uo_root / "kernel" / "resources.yaml"
    canonical_ready = all(p.exists() and not _is_placeholder(p.relative_to(uo_root).as_posix(), read_text(p)) for p in (paths_yaml, pipeline_yaml, resources_yaml))

    if canonical_ready:
        # ensure each approved task appears in paths.yaml
        text = read_text(paths_yaml)
        for task_id in task_ids:
            task_id = task_id.strip()
            if not task_id:
                continue
            if task_id not in text and not re.search(rf"(?m)^\s*{re.escape(task_id)}\s*:", text):
                # also allow Kxxx ids mapped via stable_key / name
                missing.append(f"kernel/paths.yaml missing task {task_id}")
            completion_rel = f"archive/raw_agents/kernel_paths/.uo_kernel_path_{task_id}_complete.json"
            legacy_completion = f"kernel/paths/.uo_kernel_path_{task_id}_complete.json"
            ok_raw, _ = _completion_ok(uo_root / completion_rel, "uo-kernel-path")
            ok_legacy, reason = _completion_ok(uo_root / legacy_completion, "uo-kernel-path")
            if not ok_raw and not ok_legacy:
                # if host aggregator merged, allow missing per-task completion when aggregator manifest exists
                agg = uo_root / "kernel" / ".uo_kernel_alignment_complete.json"
                if not agg.exists():
                    missing.append(reason if reason else f"missing completion for {task_id}")
    else:
        # fall back to per-task raw outputs under archive or legacy kernel/paths
        for task_id in task_ids:
            task_id = task_id.strip()
            if not task_id:
                continue
            candidates = [
                f"archive/raw_agents/kernel_paths/{task_id}_kernel_path.yaml",
                f"kernel/paths/{task_id}_kernel_path.yaml",
            ]
            found = False
            for rel in candidates:
                path = uo_root / rel
                if path.exists() and read_text(path).strip():
                    found = True
                    break
            if not found:
                missing.append(f"raw/canonical kernel path missing for {task_id}")
            for completion_rel in (
                f"archive/raw_agents/kernel_paths/.uo_kernel_path_{task_id}_complete.json",
                f"kernel/paths/.uo_kernel_path_{task_id}_complete.json",
            ):
                ok, reason = _completion_ok(uo_root / completion_rel, "uo-kernel-path")
                if ok:
                    break
            else:
                missing.append(reason)

        for rel in KERNEL_CANONICAL:
            if not (uo_root / rel).exists():
                stale.append(f"{rel} not merged yet (raw agent outputs present)")

    ok = not missing and not stale
    message = "kernel_path barrier passed" if ok else f"missing: {', '.join(missing + stale)}"
    return BarrierResult(ok, PHASE_KERNEL_PATH, missing, stale, message)


def write_barrier_report(uo_root: Path, result: BarrierResult) -> Path:
    report = {
        "phase": result.phase,
        "ok": result.ok,
        "checked_at": datetime.now(tz=timezone.utc).isoformat(),
        "missing": result.missing,
        "stale": result.stale,
        "message": result.message,
    }
    out_dir = uo_root / "archive" / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"barrier_{result.phase}.json"
    write_json(out, report)
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Verify subagent completion before host continues.")
    parser.add_argument("repo_root", type=Path)
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--phase", choices=[PHASE_HOST_FLOW, PHASE_KERNEL_PATH], required=True)
    parser.add_argument("--task-ids", help="Comma-separated task ids for kernel_path phase")
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    uo_root = operator_root(repo_root, op_name)

    if args.phase == PHASE_HOST_FLOW:
        result = verify_host_flow_barrier(uo_root)
    else:
        task_ids = [item.strip() for item in (args.task_ids or "").split(",") if item.strip()]
        if not task_ids:
            task_ids = _approved_task_ids(uo_root)
        if not task_ids:
            result = BarrierResult(False, PHASE_KERNEL_PATH, ["approved_task_ids"], [], "no approved task ids")
        else:
            result = verify_kernel_path_barrier(uo_root, task_ids)

    report_path = write_barrier_report(uo_root, result)
    print(json.dumps({"ok": result.ok, "phase": result.phase, "message": result.message, "report": str(report_path)}, ensure_ascii=False))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
