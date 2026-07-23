"""Resolve conversational path forms into operator project_root / op_name / consumer / contract."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .io import output_root
from .realization_contract import realization_paths
from .understand import understand_root


REQUIRED_CONTRACT_FILES = (
    "realization_map.yaml",
    "consumer_schema.yaml",
    "consumer_evidence.yaml",
)


@dataclass(frozen=True)
class PlanPathBundle:
    project_root: Path
    op_name: str
    test_tool_root: Path | None
    contract_root: Path | None
    mode: str  # "build_contract" | "reuse_contract" | "reuse_init"


def resolve_operator_project_root(path: Path) -> Path:
    """Accept op package, `.ascendc-agent`, `.ascendc-agent/uo`, or `.ascendc-agent/tg`."""
    root = path.expanduser().resolve(strict=False)
    # Structural markers can be resolved even if the marker dir was not created yet
    if root.name == "uo" and root.parent.name == ".ascendc-agent":
        return root.parent.parent
    if root.name == "tg" and root.parent.name == ".ascendc-agent":
        return root.parent.parent
    if root.name == ".ascendc-agent":
        return root.parent
    if root.exists() and (root / ".ascendc-agent").is_dir():
        return root
    if not root.exists():
        raise ValueError(f"Path does not exist: {root}")
    return root


def infer_op_name(project_root: Path, explicit: str | None = None, kb_hint: Path | None = None) -> str:
    if explicit and str(explicit).strip():
        return str(explicit).strip()

    if kb_hint is not None:
        hint = kb_hint.expanduser().resolve()
        manifest = hint / "manifest.yaml" if hint.name == "uo" else hint / "uo" / "manifest.yaml"
        if manifest.is_file():
            try:
                import yaml

                data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
                if isinstance(data, dict) and isinstance(data.get("op_name"), str):
                    return data["op_name"]
            except Exception:  # noqa: BLE001
                pass

    uo = understand_root(project_root, "")
    if (uo / "manifest.yaml").is_file():
        try:
            import yaml

            data = yaml.safe_load((uo / "manifest.yaml").read_text(encoding="utf-8")) or {}
            if isinstance(data, dict) and isinstance(data.get("op_name"), str):
                return data["op_name"]
        except Exception:  # noqa: BLE001
            pass

    raise ValueError(f"Cannot infer --op-name from {project_root}. Pass --op-name.")


def normalize_contract_root(path: Path) -> Path:
    """Accept realization/, .ascendc-agent/tg/, or a dir that contains realization/."""
    root = path.expanduser().resolve()
    if not root.exists():
        raise ValueError(f"Contract path does not exist: {root}")
    if root.is_file():
        raise ValueError(f"Contract path must be a directory: {root}")

    candidates = [
        root,
        root / "realization",
    ]
    if (root / "realization_map.yaml").is_file():
        return root
    if (root / "realization" / "realization_map.yaml").is_file():
        return (root / "realization").resolve()
    for candidate in candidates:
        if all((candidate / name).is_file() for name in REQUIRED_CONTRACT_FILES):
            return candidate.resolve()
    raise ValueError(
        "CONTRACT_ARTIFACTS_INVALID: expected realization_map.yaml + consumer_schema.yaml + "
        f"consumer_evidence.yaml under {root} or {root / 'realization'}"
    )


def validate_contract_dir(contract_dir: Path) -> None:
    missing = [name for name in REQUIRED_CONTRACT_FILES if not (contract_dir / name).is_file()]
    if missing:
        raise ValueError(f"CONTRACT_ARTIFACTS_INCOMPLETE: missing {missing} under {contract_dir}")


def install_contract_into_project(project_root: Path, op_name: str, contract_root: Path) -> Path:
    """Copy/reuse contract artifacts into <project>/.ascendc-agent/tg/realization/."""
    src = normalize_contract_root(contract_root)
    validate_contract_dir(src)
    dest_dir = realization_paths(output_root(project_root, op_name))["dir"]
    dest_dir.mkdir(parents=True, exist_ok=True)
    if src.resolve() == dest_dir.resolve():
        return dest_dir
    for name in REQUIRED_CONTRACT_FILES:
        shutil.copy2(src / name, dest_dir / name)
    for name in (
        "realization_report.yaml",
        "alignment_report.yaml",
        "binding_lexicon.yaml",
        "unresolved.yaml",
        "agent_report.yaml",
    ):
        src_file = src / name
        if src_file.is_file():
            shutil.copy2(src_file, dest_dir / name)
    return dest_dir


def resolve_plan_paths(
    *,
    project_root: Path | None,
    op_name: str | None,
    csv_consumer_root: Path | None,
    test_script_root: Path | None = None,
    kb_root: Path | None = None,
    contract_root: Path | None = None,
) -> PlanPathBundle:
    """Normalize plan CLI paths into a strict input bundle."""
    test_tool = csv_consumer_root or test_script_root
    if test_tool is not None:
        test_tool = test_tool.expanduser().resolve()
        if not test_tool.exists():
            raise ValueError(f"Test tool path does not exist: {test_tool}")

    contract = contract_root.expanduser().resolve() if contract_root is not None else None

    kb_hint = kb_root.expanduser().resolve() if kb_root is not None else None
    raw_project = project_root
    if raw_project is None and kb_hint is not None:
        raw_project = kb_hint
    if raw_project is None:
        raise ValueError(
            "OPERATOR_ROOT_REQUIRED: pass project_root (算子仓) or --kb-root (.ascendc-agent/uo)."
        )

    resolved_project = resolve_operator_project_root(raw_project)
    raw_resolved = raw_project.expanduser().resolve()
    if kb_hint is None and (
        raw_resolved.name == ".ascendc-agent"
        or raw_resolved.parent.name == ".ascendc-agent"
        or (raw_resolved.name == "uo" and raw_resolved.parent.name == ".ascendc-agent")
    ):
        kb_hint = raw_resolved

    name = infer_op_name(resolved_project, explicit=op_name, kb_hint=kb_hint)

    if test_tool is not None and contract is not None:
        return PlanPathBundle(
            project_root=resolved_project,
            op_name=name,
            test_tool_root=test_tool,
            contract_root=None,
            mode="build_contract",
        )
    if test_tool is not None:
        return PlanPathBundle(
            project_root=resolved_project,
            op_name=name,
            test_tool_root=test_tool,
            contract_root=None,
            mode="build_contract",
        )
    if contract is not None:
        normalized = normalize_contract_root(contract)
        return PlanPathBundle(
            project_root=resolved_project,
            op_name=name,
            test_tool_root=None,
            contract_root=normalized,
            mode="reuse_contract",
        )

    local_realization = output_root(resolved_project, name) / "realization"
    if (local_realization / "realization_map.yaml").is_file():
        return PlanPathBundle(
            project_root=resolved_project,
            op_name=name,
            test_tool_root=None,
            contract_root=local_realization.resolve(),
            mode="reuse_init",
        )

    raise ValueError(
        "PLAN_INPUTS_REQUIRED: tg-plan needs init-confirmed realization (run tg-init), "
        "or pass --test-script-root / --contract-root. "
        "Preferred: tg-init <算子仓> --op-name <op> --test-script-root <测试工具> → confirm → tg-plan."
    )


def realization_map_exists(project_root: Path, op_name: str) -> bool:
    return (output_root(project_root, op_name) / "realization" / "realization_map.yaml").is_file()
