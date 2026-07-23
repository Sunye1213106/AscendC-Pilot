from __future__ import annotations

from pathlib import Path
from typing import Any

from .consumer_evidence import prepare_consumer_evidence
from .hashing import stable_hash
from .io import read_yaml

CONSUMER_SCHEMA_VERSION = 1
REALIZATION_MAP_VERSION = 2


class ContractError(RuntimeError):
    pass


def realization_paths(out_root: Path) -> dict[str, Path]:
    realization_dir = out_root / "realization"
    contract_dir = out_root / "contract"
    return {
        "dir": realization_dir,
        "evidence": realization_dir / "consumer_evidence.yaml",
        "schema": realization_dir / "consumer_schema.yaml",
        "map": realization_dir / "realization_map.yaml",
        "report": realization_dir / "realization_report.yaml",
        "alignment_report": realization_dir / "alignment_report.yaml",
        "binding_lexicon": realization_dir / "binding_lexicon.yaml",
        "unresolved": realization_dir / "unresolved.yaml",
        "agent_report": realization_dir / "agent_report.yaml",
        "contract_dir": contract_dir,
        "testcase_contract": contract_dir / "testcase.yaml",
    }


def prepare_contract_inputs(
    out_root: Path,
    *,
    consumer_root: Path | None,
    snapshot_path: Path,
    obligations_path: Path,
) -> dict[str, Any]:
    return prepare_consumer_evidence(
        out_root,
        consumer_root=consumer_root,
        snapshot_path=snapshot_path,
        obligations_path=obligations_path,
    )


def contract_hash(consumer_schema: dict[str, Any], realization_map: dict[str, Any]) -> str:
    return stable_hash(
        {
            "consumer_schema": consumer_schema,
            "realization_map": realization_map,
        }
    )


def load_contract(paths: dict[str, Path]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not paths["evidence"].exists():
        raise ContractError("CSV_CONTRACT_REQUIRED: missing realization/consumer_evidence.yaml")
    if not paths["schema"].exists():
        raise ContractError("CSV_CONTRACT_REQUIRED: missing realization/consumer_schema.yaml")
    if not paths["map"].exists():
        raise ContractError("CSV_CONTRACT_REQUIRED: missing realization/realization_map.yaml")
    evidence = read_yaml(paths["evidence"])
    consumer_schema = read_yaml(paths["schema"])
    realization_map = read_yaml(paths["map"])
    return evidence, consumer_schema, realization_map
