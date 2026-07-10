from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from testcase_generator._core.paths import (
    CANONICAL_TILING_FILES,
    UNDERSTAND_KERNEL_PATHS,
    UNDERSTAND_OPERATOR_FILE,
    UNDERSTAND_QUALITY_FILE,
    UNDERSTAND_TILING_INDEX,
    ensure_tg_layout,
)
from testcase_generator._core.yaml_io import dump_yaml, load_yaml


class SnapshotError(RuntimeError):
    pass


@dataclass
class SnapshotResult:
    kb_snapshot: dict[str, Any]
    route_md: str
    missing: list[str]


def _check_understand_kb(uo_root: Path) -> list[str]:
    missing: list[str] = []
    for rel in CANONICAL_TILING_FILES:
        if not (uo_root / rel).exists():
            missing.append(rel)
    if not (uo_root / UNDERSTAND_QUALITY_FILE).exists():
        missing.append(UNDERSTAND_QUALITY_FILE)
    return missing


def build_kb_snapshot(uo_root: Path, op_name: str) -> dict[str, Any]:
    missing = _check_understand_kb(uo_root)
    if missing:
        raise SnapshotError(
            "Missing canonical understand-operator KB files: "
            + ", ".join(missing)
            + ". Run /uo-init or /uo-update first."
        )

    quality = load_yaml(uo_root / UNDERSTAND_QUALITY_FILE)
    operator = load_yaml(uo_root / UNDERSTAND_OPERATOR_FILE)
    tiling_index = load_yaml(uo_root / UNDERSTAND_TILING_INDEX)
    key_space = load_yaml(uo_root / "tiling/key_space.yaml")
    families = load_yaml(uo_root / "tiling/families.yaml")
    data_model = load_yaml(uo_root / "tiling/data_model.yaml")
    coverage_model = load_yaml(uo_root / "tiling/coverage_model.yaml")
    kernel_paths = load_yaml(uo_root / UNDERSTAND_KERNEL_PATHS)

    return {
        "version": 1,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "op_name": op_name,
        "understand_root": str(uo_root),
        "quality_gate": quality,
        "operator_io": operator.get("io", {}),
        "operator_attrs": operator.get("attrs", operator.get("shape_ontology", {})),
        "tiling": {
            "index": tiling_index,
            "key_space": key_space,
            "families": families,
            "data_model": data_model,
            "coverage_model": coverage_model,
        },
        "kernel": {
            "kernel_path_matrix": kernel_paths,
        },
    }


def build_route_md(op_name: str, tg_root: Path, snapshot: dict[str, Any]) -> str:
    uo = snapshot.get("understand_root", "")
    return f"""# Testcase Generator Route — {op_name}

Human-readable map for `.testcase-generator/{op_name}/`.

## Source KB

- understand root: `{uo}`
- quality: `quality.yaml` snapshot in `kb_snapshot.yaml`
- tiling: key_space / families / data_model / coverage_model

## Workflow

```text
tg-init   -> kb_snapshot.yaml, route.md
tg-plan   -> plan/coverage_obligations.yaml
tg-generate -> generate/* + probe_cases.jsonl
tg-probe  -> probe/observed_keys.jsonl
tg-audit  -> audit/coverage_audit.yaml, coverage_matrix.md
tg-report -> report/final_report.md
```

## Rules

- Family coverage != tiling_key coverage.
- expected_key is a target only; observed_key is coverage evidence.
- mock probe => verified=false, coverage_verified=false.

## Machine entry

Start at `kb_snapshot.yaml`, then `plan/coverage_obligations.yaml`.
"""


def write_snapshot_artifacts(tg_root: Path, op_name: str, uo_root: Path) -> SnapshotResult:
    ensure_tg_layout(tg_root)
    missing = _check_understand_kb(uo_root)
    if missing:
        raise SnapshotError(
            "Missing canonical understand-operator KB files: "
            + ", ".join(missing)
            + ". Run /uo-init or /uo-update first."
        )

    snapshot = build_kb_snapshot(uo_root, op_name)
    route = build_route_md(op_name, tg_root, snapshot)
    dump_yaml(tg_root / "kb_snapshot.yaml", snapshot)
    (tg_root / "route.md").write_text(route, encoding="utf-8")
    return SnapshotResult(kb_snapshot=snapshot, route_md=route, missing=missing)
