from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML optional at runtime
    yaml = None  # type: ignore[assignment]

from understand_operator._operator.artifacts import operator_root, read_text, safe_op_name

EXPORT_VIEWS: dict[str, list[str]] = {
    "tiling-test": [
        "tiling/variables.yaml",
        "tiling/key_space.yaml",
        "tiling/constraints.yaml",
        "tiling/families.yaml",
        "tiling/data_model.yaml",
        "tiling/coverage_model.yaml",
        "quality.yaml",
    ],
    "golden-gen": [
        "operator.yaml",
        "tiling/data_model.yaml",
        "flow/compute_graph.yaml",
        "flow/dataflow.yaml",
        "flow/golden_model.yaml",
        "flow/numerical_model.yaml",
        "evidence/fact_index.yaml",
        "quality.yaml",
    ],
    "testgenerate": [
        "operator.yaml",
        "tiling/variables.yaml",
        "tiling/key_space.yaml",
        "tiling/constraints.yaml",
        "tiling/families.yaml",
        "tiling/data_model.yaml",
        "tiling/coverage_model.yaml",
        "flow/compute_graph.yaml",
        "flow/dataflow.yaml",
        "flow/golden_model.yaml",
        "flow/numerical_model.yaml",
        "kernel/paths.yaml",
        "kernel/pipeline.yaml",
        "kernel/resources.yaml",
        "test/contract.yaml",
        "quality.yaml",
        "evidence/issues.yaml",
    ],
    "kernel-debug": [
        "kernel/paths.yaml",
        "kernel/pipeline.yaml",
        "kernel/resources.yaml",
        "flow/compute_graph.yaml",
        "flow/dataflow.yaml",
        "evidence/fact_index.yaml",
        "evidence/source_index.yaml",
    ],
    "human": [
        "route.md",
        "human/review.md",
        "quality.yaml",
        "evidence/issues.yaml",
    ],
    "query": [
        "query/routes.yaml",
        "contracts/query.yaml",
        "registry/variables.yaml",
        "cross_layer/variable_lineage.yaml",
        "quality.yaml",
    ],
    "code-change": [
        "contracts/code_change.yaml",
        "cross_layer/impact_graph.yaml",
        "registry/symbols.yaml",
        "registry/variables.yaml",
        "evidence/artifact_dependencies.yaml",
        "quality.yaml",
    ],
    "pr-review": [
        "contracts/pr_review.yaml",
        "cross_layer/impact_graph.yaml",
        "evidence/issues.yaml",
        "quality.yaml",
    ],
    "testcase-contract": [
        "contracts/testcase.yaml",
        "test/contract.yaml",
        "tiling/coverage_model.yaml",
        "kernel/branches.yaml",
        "cross_layer/impact_graph.yaml",
        "quality.yaml",
    ],
}

LEGACY_MARKERS = [
    "summary/operator_io.yaml",
    "summary/operator_manifest.yaml",
    "flows/compute_flow.yaml",
    "testing_hints/golden_hint.yaml",
    "route.json",
    "quality_gate.yaml",
    "tiling/tiling_branch_families.yaml",
    "kernel/kernel_task_plan.yaml",
]


def _parse_yaml(text: str, path: Path) -> Any:
    if not text.strip():
        raise ValueError(f"{path.as_posix()} is empty")
    if yaml is None:
        raise RuntimeError("PyYAML is required for yaml parsing; install with: pip install pyyaml")
    data = yaml.safe_load(text)
    if data is None:
        raise ValueError(f"{path.as_posix()} parsed to null")
    return data


def _load_file(uo_root: Path, rel: str) -> Any:
    path = uo_root / rel
    if not path.exists():
        raise FileNotFoundError(rel)
    text = read_text(path)
    if rel.endswith((".yaml", ".yml")):
        return _parse_yaml(text, path)
    return text


def _legacy_hint(uo_root: Path, missing: list[str]) -> str:
    has_legacy = any((uo_root / marker).exists() for marker in LEGACY_MARKERS)
    if has_legacy:
        return (
            " This KB uses legacy artifacts. Run /uo-update or /uo-init to regenerate canonical KB files."
        )
    if missing:
        return " Run /uo-init or /uo-update for this operator first."
    return ""


def export_view(uo_root: Path, op_name: str, view: str) -> dict[str, Any]:
    if view not in EXPORT_VIEWS:
        raise ValueError(f"Unsupported view: {view}")

    # Never read archive/ by default
    required = EXPORT_VIEWS[view]
    missing = [rel for rel in required if not (uo_root / rel).exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing canonical files for view '{view}': {', '.join(missing)}."
            + _legacy_hint(uo_root, missing)
        )

    files: dict[str, Any] = {}
    for rel in required:
        files[rel] = _load_file(uo_root, rel)

    return {
        "op_name": op_name,
        "uo_root": uo_root.as_posix(),
        "view": view,
        "files": files,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export canonical operator KB views (no source reads, no CBM, no archive)."
    )
    parser.add_argument("repo_root", type=Path, help="AscendC operator repository root")
    parser.add_argument("--op-name", required=True, help="Operator name")
    parser.add_argument(
        "--view",
        choices=sorted(EXPORT_VIEWS.keys()),
        default="tiling-test",
        help="Export view",
    )
    parser.add_argument(
        "--format",
        choices=["yaml", "json"],
        default="json",
        help="Output format (default: json)",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    uo_root = operator_root(repo_root, op_name)

    try:
        payload = export_view(uo_root, op_name, args.view)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if yaml is None:
            print(
                "PyYAML is required for yaml output; use --format json or pip install pyyaml",
                file=sys.stderr,
            )
            return 1
        print(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
