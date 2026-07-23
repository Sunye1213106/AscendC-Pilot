"""TG-owned testcase contract at `.ascendc-pilot/tg/contract/testcase.yaml`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import read_yaml, write_yaml
from .kb_semantics import (
    assemble_golden_contract,
    assemble_key_determinants,
    assemble_optional_inputs,
)


def tg_contract_path(out_root: Path) -> Path:
    return Path(out_root) / "contract" / "testcase.yaml"


def load_tg_contract(out_root: Path | None) -> dict[str, Any]:
    if out_root is None:
        return {}
    path = tg_contract_path(out_root)
    if not path.is_file():
        return {}
    data = read_yaml(path)
    return data if isinstance(data, dict) else {}


def resolve_plan_contract(
    snapshot: dict[str, Any],
    *,
    out_root: Path | None = None,
) -> tuple[dict[str, Any], str]:
    """Load TG-owned contract."""
    tg = load_tg_contract(out_root)
    if tg and int(tg.get("version") or 0) == 2:
        return tg, "tg_contract"
    return tg or {}, "missing"


def _variables_from_consumer_schema(schema: dict[str, Any]) -> list[dict[str, Any]]:
    variables: list[dict[str, Any]] = []
    for field in schema.get("fields") or []:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name") or field.get("id") or "")
        if not name:
            continue
        var_id = str(field.get("id") or f"VAR_CSV_{name}")
        domain = field.get("domain")
        variables.append(
            {
                "id": var_id,
                "name": name,
                "type": field.get("type") or field.get("data_type") or "enum",
                "domain": domain if domain is not None else [],
                "domain_authority": "consumer_csv",
                "role": field.get("role") or "",
            }
        )
    if not variables:
        for col in schema.get("columns") or []:
            name = str(col)
            if not name:
                continue
            variables.append(
                {
                    "id": f"VAR_CSV_{name}",
                    "name": name,
                    "type": "enum",
                    "domain": [],
                    "domain_authority": "consumer_csv",
                }
            )
    return variables


def _coverage_skeleton_from_kb(files: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    coverage = files.get("tiling/coverage_model.yaml") if isinstance(files.get("tiling/coverage_model.yaml"), dict) else {}
    branches = files.get("kernel/branches.yaml") if isinstance(files.get("kernel/branches.yaml"), dict) else {}
    key_space = files.get("tiling/key_space.yaml") if isinstance(files.get("tiling/key_space.yaml"), dict) else {}
    skeleton: dict[str, list[dict[str, Any]]] = {
        "families": [],
        "compile_template": [],
        "kernel_branch": [],
        "kernel_paths": [],
        "runtime_variable_state": [],
        "tiling_key_field": [],
        "tiling_keys": [],
        "tilingdata": [],
        "optional_input_mode": [],
        "numerical": [],
        "negative": [],
    }
    for item in coverage.get("family_obligations") or []:
        if isinstance(item, dict):
            skeleton["families"].append(
                {"id": item.get("id") or item.get("family_id"), "target_refs": [item.get("family_id") or item.get("id")]}
            )
    for item in branches.get("branches") or []:
        if isinstance(item, dict) and item.get("id"):
            skeleton["kernel_branch"].append({"id": item["id"], "target_refs": [item["id"]]})
    for field in key_space.get("fields") or []:
        if isinstance(field, dict) and field.get("id"):
            skeleton["tiling_key_field"].append(
                {"id": f"COV_{field['id']}", "target_refs": [str(field["id"])]}
            )
    return skeleton


def build_tg_contract(
    out_root: Path,
    *,
    op_name: str,
    consumer_schema: dict[str, Any],
    snapshot: dict[str, Any],
    level: str | None = None,
    realization_map: dict[str, Any] | None = None,
    lexicon: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write TG-owned version=2 contract (CSV domain × KB refs × optional level tag)."""
    files = snapshot.get("files") if isinstance(snapshot.get("files"), dict) else {}
    key_determinants = assemble_key_determinants(files)
    optional_inputs = assemble_optional_inputs(files)
    golden = assemble_golden_contract(files)
    variables = _variables_from_consumer_schema(consumer_schema)
    coverage = _coverage_skeleton_from_kb(files)
    for opt in optional_inputs:
        coverage["optional_input_mode"].append(
            {"id": f"COV_OPT_{opt.get('name') or opt.get('id')}", "target_refs": [opt.get("id")]}
        )

    lex = lexicon if isinstance(lexicon, dict) else {}
    # Prefer lexicon key_derivations as binding evidence when present.
    lex_derivs = [d for d in (lex.get("key_derivations") or []) if isinstance(d, dict)]
    if lex_derivs and not key_determinants:
        key_determinants = [
            {
                "id": d.get("key_id") or d.get("id"),
                "expr": d.get("expr") or d.get("expression"),
                "source": "binding_lexicon",
            }
            for d in lex_derivs
            if d.get("key_id") or d.get("id")
        ]

    arch = ""
    graph = files.get("ir/operator_graph.yaml") if isinstance(files.get("ir/operator_graph.yaml"), dict) else {}
    if graph:
        arch = str(graph.get("architecture") or graph.get("arch") or "")
    rmap = realization_map if isinstance(realization_map, dict) else {}
    contract: dict[str, Any] = {
        "version": 2,
        "op_name": op_name,
        "architecture": arch,
        "owner": "testcase-agent",
        "path": "contract/testcase.yaml",
        "source": {
            "understand_phase": "kb_snapshot",
            "quality_status": "pass",
            "domain_authority": "consumer_csv",
            "kb_refs": [
                "tiling/key_space.yaml",
                "ir/input_derivable.yaml",
                "kernel/branches.yaml",
                "tiling/coverage_model.yaml",
                "flow/golden_model.yaml",
            ],
            "snapshot_hash": snapshot.get("snapshot_hash") or "",
            "level": level or "",
            "binding_lexicon_source": lex.get("source") or rmap.get("binding_lexicon_source") or "",
            "lexicon_key_derivations": len(lex_derivs),
        },
        "interface": {
            "required_inputs": [],
            "optional_inputs": optional_inputs,
            "outputs": list(golden.get("outputs") or []),
            "attrs": [],
            "dtype_layout_domains": [],
            "primary_layout_field": "input_layout",
            "producible_fields": [],
        },
        "variables": variables,
        "typed_constraints": [],
        "constraint_ir": {"variables": variables, "constraints": []},
        "coverage_obligations": coverage,
        "key_determinants": key_determinants,
        "golden_contract": golden,
        "kernel_branch_obligations": [
            {"id": item["id"]} for item in coverage.get("kernel_branch") or [] if item.get("id")
        ][:80],
        "unresolved": [],
        "conflicts": [],
        "evidence_refs": [
            "realization/consumer_schema.yaml",
            "realization/realization_map.yaml",
            "realization/binding_lexicon.yaml",
        ],
        "binding_lexicon_ref": "realization/binding_lexicon.yaml",
    }

    path = tg_contract_path(out_root)
    write_yaml(path, contract)
    return contract


def stamp_tg_contract_level(out_root: Path, level: str, plan_hash: str = "") -> dict[str, Any]:
    """After plan, stamp level / plan_hash onto TG contract (coverage still owned by plan/)."""
    contract = load_tg_contract(out_root)
    if not contract:
        return {}
    source = dict(contract.get("source") or {})
    source["level"] = level
    if plan_hash:
        source["plan_hash"] = plan_hash
    contract["source"] = source
    write_yaml(tg_contract_path(out_root), contract)
    return contract
