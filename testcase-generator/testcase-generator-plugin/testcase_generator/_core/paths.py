from __future__ import annotations

import re
from pathlib import Path

ARTIFACT_DIR = ".testcase-generator"
UNDERSTAND_ARTIFACT_DIR = ".understand-operator"

CANONICAL_TILING_FILES = [
    "tiling/key_space.yaml",
    "tiling/families.yaml",
    "tiling/data_model.yaml",
    "tiling/coverage_model.yaml",
]

UNDERSTAND_QUALITY_FILE = "quality.yaml"
UNDERSTAND_OPERATOR_FILE = "operator.yaml"
UNDERSTAND_KERNEL_PATHS = "kernel/paths.yaml"
UNDERSTAND_TILING_INDEX = "tiling/index.yaml"

TG_LAYOUT_DIRS = [
    "plan",
    "generate",
    "probe",
    "audit",
    "repair",
    "review",
    "report",
    "pr",
]


def safe_op_name(name: str | None, repo_root: Path) -> str:
    raw = (name or "").strip() or repo_root.name
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._")
    return cleaned or "unknown_operator"


def understand_root(repo_root: Path, op_name: str) -> Path:
    return repo_root / UNDERSTAND_ARTIFACT_DIR / op_name


def testcase_root(repo_root: Path, op_name: str, output_root: Path | None = None) -> Path:
    if output_root is not None:
        return output_root / op_name
    return repo_root / ARTIFACT_DIR / op_name


def ensure_tg_layout(base: Path) -> None:
    base.mkdir(parents=True, exist_ok=True)
    for rel in TG_LAYOUT_DIRS:
        (base / rel).mkdir(parents=True, exist_ok=True)


def resolve_paths(
    project_root: str | Path,
    op_name: str | None = None,
    output_root: str | Path | None = None,
) -> tuple[Path, str, Path, Path]:
    repo = Path(project_root).resolve()
    op = safe_op_name(op_name, repo)
    uo = understand_root(repo, op)
    out_base = Path(output_root).resolve() if output_root else repo / ARTIFACT_DIR
    tg = testcase_root(repo, op, out_base if output_root else None)
    return repo, op, uo, tg
