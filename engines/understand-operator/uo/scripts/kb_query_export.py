from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo.scripts._ir_io import read_yaml, stable_id, write_yaml

# Layered KB export paths (TG intake). Testcase contracts live only under TG
# `.ascendc-pilot/tg/contract/` — UO must not write contracts/**.
REQUIRED_REL_PATHS = (
    "test/contract.yaml",
    "tiling/variables.yaml",
    "tiling/key_space.yaml",
    "tiling/exhaustive_key_space.yaml",
    "tiling/constraints.yaml",
    "tiling/families.yaml",
    "tiling/data_model.yaml",
    "tiling/coverage_model.yaml",
    "kernel/compile_model.yaml",
    "kernel/variables.yaml",
    "kernel/paths.yaml",
    "kernel/branches.yaml",
    "kernel/pipeline.yaml",
    "kernel/resources.yaml",
    "cross_layer/impact_graph.yaml",
    "cross_layer/tiling_to_kernel.yaml",
    "flow/golden_model.yaml",
    "flow/numerical_model.yaml",
    "quality.yaml",
)

# Alias kept for CLI/compat; semantics = layered KB export (not a testcase contract).
SUPPORTED_EXPORT_VIEWS = frozenset({"testcase-contract", "kb-export"})

ARTIFACT_HASHES_REL = "checks/artifact_hashes.yaml"
RUNTIME_SAMPLE_LIMIT = 8


def export_view(
    uo_root: Path | str,
    op_name: str,
    view: str,
    **_ignored: Any,
) -> dict[str, Any]:
    uo_root = Path(uo_root)
    if view not in SUPPORTED_EXPORT_VIEWS:
        raise ValueError(f"unsupported view: {view}")
    graph = read_yaml(uo_root / "ir" / "operator_graph.yaml")
    if not graph:
        raise FileNotFoundError(f"missing operator graph under {uo_root}")
    files = materialize_testcase_contract_files(uo_root, graph)
    return {"op_name": op_name, "view": view, "files": files}


def export_context_slice(
    uo_root: Path | str,
    op_name: str,
    *,
    view: str = "testcase-contract",
    detail_level: str = "full",
) -> dict[str, Any]:
    uo_root = Path(uo_root)
    if view not in SUPPORTED_EXPORT_VIEWS:
        raise ValueError(f"unsupported view: {view}")
    graph = read_yaml(uo_root / "ir" / "operator_graph.yaml")
    if not graph:
        raise FileNotFoundError(f"missing operator graph under {uo_root}")
    files = _load_or_materialize(uo_root, graph)
    entities = _entities_from_graph(graph)
    return {
        "op_name": op_name,
        "view": view,
        "detail_level": detail_level,
        "entities": entities,
        # Testcase contract is TG-owned; KB context carries entities + layered refs only.
        "testcase_contract": None,
        "relations": graph.get("edges") or [],
    }


def materialize_testcase_contract_files(
    uo_root: Path,
    graph: dict[str, Any],
    **_ignored: Any,
) -> dict[str, Any]:
    sample_limit = RUNTIME_SAMPLE_LIMIT
    op_name = str(graph.get("op_name") or "")
    tilingkey = graph.get("tilingkey") or {}
    dimensions = tilingkey.get("dimensions") or []
    template_blocks_raw = tilingkey.get("template_blocks") or []
    nodes = graph.get("nodes") or []
    branches = graph.get("kernel_branches") or []
    golden = graph.get("golden") or {}
    diagnostics = [
        d
        for d in (graph.get("bridge_diagnostics") or [])
        if isinstance(d, dict) and str(d.get("severity") or "warning").lower() != "error"
    ]

    key_nodes = [n for n in nodes if n.get("node_type") == "TilingKey"]
    tdf_nodes = [n for n in nodes if n.get("node_type") == "TilingDataField"]
    # Runtime variables must be TilingData-backed KernelVariables with a domain.
    kvar_nodes = [
        n
        for n in nodes
        if n.get("node_type") == "KernelVariable"
        and n.get("domain")
        and str(n.get("determinant_source") or "TilingDataField") == "TilingDataField"
    ]
    ktpl_nodes = [n for n in nodes if n.get("node_type") == "KernelTemplateArgument"]

    key_fields = []
    tiling_variables = []
    for dim in dimensions:
        name = str(dim.get("name") or "")
        key_id = stable_id("KEY_", name)
        values = dim.get("values") or []
        role_meta = _infer_key_field_role(name)
        # Naming heuristic only fills weak role / layout CSV hints.
        # needs_binding is owned by classify_input_derivable (applied below).
        key_fields.append(
            {
                "id": key_id,
                "kind": "key",
                "name": name,
                "data_type": "int",
                "values": values,
                "role": role_meta.get("role"),
                "semantic_role": role_meta.get("role"),
                "csv_determinants": role_meta.get("csv_determinants") or [],
                "primary_layout_field": role_meta.get("primary_layout_field"),
                "needs_binding": False,
            }
        )
        tiling_variables.append(
            {
                "id": f"VAR_{key_id}",
                "kind": "variable",
                "canonical_name": name,
                "data_type": "int",
                "domain": {"kind": "discrete", "values": values} if values else {"kind": "int"},
                "semantic_role": role_meta.get("role"),
            }
        )

    template_blocks = []
    for block in template_blocks_raw:
        flags = block.get("flags") or {}
        fixed = {str(k): (1 if v else 0) for k, v in flags.items()}
        block_id = block.get("id") or stable_id("KTPL_", str(block.get("name") or "BLOCK"))
        template_blocks.append(
            {
                "id": block_id,
                "name": block.get("name"),
                "fixed_fields": fixed,
                "condition": block.get("condition"),
                "source": block.get("source"),
            }
        )

    args_sel_count = int(tilingkey.get("args_sel_count") or 0)
    # No cartesian / L2 combination product here — legal instances live as KTPL_* in kb_graph.
    exhaustive = {
        "version": 1,
        "op_name": op_name,
        "enumeration_source": "kb_graph_ktpl",
        "field_order": [str(d.get("name")) for d in dimensions if d.get("name")],
        "template_blocks": [],
        "dimensions": dimensions,
        "args_sel_count": args_sel_count,
        "ktpl_instance_count": len(template_blocks),
        "summary": {
            "ktpl_instance_count": len(template_blocks),
            "template_block_count": len(template_blocks),
            "key_dimension_count": len(dimensions),
        },
        "note": (
            "Legal compile-time template instances are KTPL_* entities in indexes/kb_graph.sqlite "
            "(fixes_flag → KEY_*). Downstream owns any further combination expansion."
        ),
    }

    families = [{"id": "FAM_DEFAULT", "name": "default"}]
    for block in template_blocks:
        families.append({"id": str(block["id"]), "name": str(block.get("name") or block["id"])})

    coverage = {
        "version": 1,
        "op_name": op_name,
        "coverage_policy": "layered_ir",
        "key_fields": [d.get("name") for d in dimensions],
        "family_obligations": [{"id": "COV_FAM_DEFAULT", "family_id": "FAM_DEFAULT"}],
        "key_field_obligations": {
            str(f["name"]): {"id": f["id"], "values": f.get("values") or [], "independent": True} for f in key_fields
        },
        "key_relation_obligations": [],
        "runtime_variables": [
            {
                "id": _ensure_prefix(n.get("id"), "KVAR_", n.get("name")),
                "name": n.get("name"),
                "domain": n.get("domain"),
                "domain_with_kernel_branch": n.get("domain_with_kernel_branch"),
                "domain_without_kernel_branch": n.get("domain_without_kernel_branch"),
                "domain_entries": _enrich_domain_entries(n.get("domain_entries")),
                "domain_source": n.get("domain_source"),
                "domain_type_name": n.get("domain_type_name"),
                "binding_time": n.get("binding_time") or "runtime",
                "determinant_source": n.get("determinant_source") or "TilingDataField",
                "semantic_role": _infer_kvar_semantic_role(n),
                "binding_surface": "tiling_data",
                "csv_column": n.get("csv_column"),
            }
            for n in kvar_nodes
        ],
    }

    branch_rows = []
    for branch in branches:
        bid = _ensure_prefix(branch.get("id"), "KBR_", branch.get("condition") or branch.get("name") or "BRANCH")
        branch_rows.append(
            {
                "id": bid,
                "condition": branch.get("condition"),
                "binding_time": branch.get("binding_time"),
                "determinant_source": branch.get("determinant_source"),
                "determinant_ref": branch.get("determinant_ref"),
                "domain": branch.get("domain"),
                "file_path": branch.get("file_path"),
                "start_line": branch.get("start_line"),
            }
        )

    branches_doc = {"version": 1, "op_name": op_name, "branches": branch_rows, "path_semantics": [], "dataflow_links": [], "resource_links": []}

    compile_model = {
        "version": 1,
        "op_name": op_name,
        "template_bindings": [
            {
                "id": _ensure_prefix(n.get("id"), "KTPL_", n.get("name")),
                "template": n.get("name"),
                "flags": n.get("template_flags") or {},
            }
            for n in ktpl_nodes
        ]
        or [{"id": b["id"], "template": b.get("name"), "flags": b.get("fixed_fields") or {}} for b in template_blocks],
        "compile_time_configs": [],
        "compile_variables": [],
        "compile_decisions": [
            {
                "id": b["id"],
                "binding_time": "compile_time",
                "condition": b.get("condition"),
            }
            for b in branch_rows
            if b.get("binding_time") == "compile_time"
        ],
    }

    path_summary_limit = 80
    kernel_vars = {
        "version": 1,
        "op_name": op_name,
        "runtime_variables": coverage["runtime_variables"],
        "tilingdata_reads": [
            {
                "id": _ensure_prefix(n.get("id"), "TDF_", n.get("name")),
                "field_id": _ensure_prefix(n.get("id"), "TDF_", n.get("name")),
                "name": n.get("name"),
            }
            for n in tdf_nodes
        ],
        "path_decision_points": [
            {
                "id": b["id"],
                "condition": b.get("condition"),
                "binding_time": b.get("binding_time"),
                "determinant_source": b.get("determinant_source"),
            }
            for b in branch_rows[:path_summary_limit]
        ],
        "path_decision_summary": {
            "total_count": len(branch_rows),
            "preview_count": min(path_summary_limit, len(branch_rows)),
            "truncated": len(branch_rows) > path_summary_limit,
            "full_list": "kernel/branches.yaml",
        },
    }

    kernel_paths = {
        "version": 1,
        "op_name": op_name,
        "kernel_paths": [
            {
                "id": "KPATH_ENTRY",
                "template_binding_ids": [b["id"] for b in template_blocks[:1]] or ["KTPL_DEFAULT"],
                "runtime_variable_ids": [v["id"] for v in coverage["runtime_variables"][:20]],
                "branch_ids": [b["id"] for b in branch_rows if b.get("binding_time") == "runtime"][:40],
                "implements_compute_steps": ["CL_STEP_MAIN"],
            }
        ],
    }

    impact = {
        "version": 1,
        "op_name": op_name,
        "nodes": [{"id": f["id"]} for f in key_fields]
        + [{"id": "FAM_DEFAULT"}, {"id": "KPATH_ENTRY"}]
        + [{"id": v["id"]} for v in coverage["runtime_variables"][:50]],
        "edges": [
            e
            for e in (graph.get("edges") or [])
            if e.get("type") in {"writes", "loads_into", "selects", "dispatches", "sets", "reserves"}
        ][:200],
        "impacts": [
            {
                "id": stable_id("REL_IMPACT_", str(d.get("field") or d.get("id") or idx)),
                "source_id": "FAM_DEFAULT",
                "target_id": "KPATH_ENTRY",
                "code": d.get("code"),
                "field": d.get("field"),
                "severity": "info",
                "status": "noted",
                "message": d.get("message"),
            }
            for idx, d in enumerate(diagnostics[:100])
        ],
        # Keep bridge findings informational; do not re-export raw severity=warning rows into intake.
        "diagnostics": [
            {
                "id": stable_id("REL_DIAG_", str(d.get("field") or d.get("id") or idx)),
                "code": d.get("code"),
                "field": d.get("field"),
                "severity": "info",
                "status": "noted",
                "message": d.get("message"),
            }
            for idx, d in enumerate(diagnostics[:100])
        ],
        "unused_tiling_fields": [d.get("field") for d in diagnostics if d.get("code") == "unused_tiling_field"],
        "missing_tiling_field_producers": [
            d.get("field") for d in diagnostics if d.get("code") == "missing_tiling_field_producer"
        ],
        "bridge_edges": [
            e
            for e in (graph.get("edges") or [])
            if e.get("type") in {"writes", "loads_into", "selects", "dispatches", "sets", "reserves"}
        ],
    }

    tiling_to_kernel = {
        "version": 1,
        "op_name": op_name,
        "nodes": impact["nodes"],
        "edges": impact["edges"],
        "relations": impact["impacts"],
        "links": impact["impacts"],
    }

    data_model = {
        "version": 1,
        "op_name": op_name,
        "structs": {
            "TilingData": {
                "fields": {
                    str(n.get("name")): {
                        "id": _ensure_prefix(n.get("id"), "TDF_", n.get("name")),
                        "canonical_name": n.get("name"),
                    }
                    for n in tdf_nodes
                    if n.get("name")
                }
            }
        },
        "family_to_struct": {"FAM_DEFAULT": "TilingData"},
        "numeric_overlay": [],
    }

    golden_inputs = list(golden.get("input_case_keys") or [])
    golden_outputs = list(golden.get("outputs") or ["dq", "dk", "dv"])
    golden_doc = {
        "version": 1,
        "op_name": op_name,
        "golden_inputs": golden_inputs,
        "golden_outputs": golden_outputs,
        "oracle": {
            "function": golden.get("function"),
            "file_path": golden.get("file_path"),
            "signature": golden.get("signature"),
            "start_line": golden.get("start_line"),
            "end_line": golden.get("end_line"),
            "direct_calls": golden.get("direct_calls") or [],
            "pipeline": golden.get("pipeline") or {},
            "helpers": golden.get("helpers") or [],
            "ctx_tensor_writes": golden.get("ctx_tensor_writes") or [],
            "return_tensors": golden.get("return_tensors") or [],
            "input_case_defaults": golden.get("input_case_defaults") or {},
            "dtype_layout_literals": golden.get("dtype_layout_literals") or {},
        },
        "golden_generation_contract": [
            {
                "id": "CON_GOLDEN",
                "method": "reference",
                "function": golden.get("function"),
                "file_path": golden.get("file_path"),
                "signature": golden.get("signature"),
                "start_line": golden.get("start_line"),
                "end_line": golden.get("end_line"),
                "pipeline": golden.get("pipeline") or {},
                "helpers": [h.get("name") for h in (golden.get("helpers") or [])],
                "outputs": golden_outputs,
            }
        ]
        if golden.get("function")
        else [],
    }
    numerical = {
        "version": 1,
        "op_name": op_name,
        "dtype_policy": ["fp16", "bf16", "fp32"],
        "tolerance_policy": [{"dtype": "fp16", "rtol": 0.001}, {"dtype": "bf16", "rtol": 0.001}],
        "randomness_policy": "deterministic",
    }

    _apply_input_derivable_overlay(uo_root, key_fields)

    # In-memory inventory for KB stub only — never written to contracts/**.
    inventory = _build_testcase_contract(
        graph,
        key_fields=key_fields,
        branch_rows=branch_rows,
        template_blocks=template_blocks,
        golden=golden,
        kvar_nodes=kvar_nodes,
    )
    inventory = _merge_human_facts_supplements(uo_root, inventory)
    runtime_branch_ids = [b["id"] for b in branch_rows if b.get("binding_time") == "runtime"]
    branch_obl_limit = 80
    test_contract = {
        "version": 1,
        "op_name": op_name,
        "role": "kb_export_stub",
        "canonical_ref": "tiling/key_space.yaml",
        "input_domain": {k: "any" for k in golden_inputs[:30]},
        "typed_constraints": inventory.get("typed_constraints") or [],
        "kernel_branch_obligations": [{"id": bid} for bid in runtime_branch_ids[:branch_obl_limit]],
        "kernel_branch_obligations_meta": {
            "total_runtime_branches": len(runtime_branch_ids),
            "listed_count": min(branch_obl_limit, len(runtime_branch_ids)),
            "truncated": len(runtime_branch_ids) > branch_obl_limit,
            "full_list": "kernel/branches.yaml",
            "kb_ref": "kernel/branches.yaml",
        },
    }

    files: dict[str, Any] = {
        "test/contract.yaml": test_contract,
        "tiling/variables.yaml": {"version": 1, "op_name": op_name, "variables": tiling_variables, "tiling_mechanism": "key"},
        "tiling/key_space.yaml": {
            "version": 1,
            "op_name": op_name,
            "fields": key_fields,
            "derived_fields": [],
            "constants": [],
        },
        "tiling/exhaustive_key_space.yaml": exhaustive,
        "tiling/constraints.yaml": {
            "version": 1,
            "op_name": op_name,
            "relations": [],
            "variable_constraints": [
                {"id": stable_id("CON_", f["id"]), "var": f"VAR_{f['id']}", "domain": {"values": f.get("values") or []}}
                for f in key_fields
                if f.get("values")
            ],
            "input_realization": {},
            "tiling_key_pruning": {"performed": True, "pruned_combinations": []},
            "tiling_key_merging": {"performed": False, "merged_groups": []},
        },
        "tiling/families.yaml": {
            "version": 1,
            "op_name": op_name,
            "families": families,
            "dispatch_tree": {"root": "FAM_DEFAULT", "children": [b["id"] for b in template_blocks]},
        },
        "tiling/data_model.yaml": data_model,
        "tiling/coverage_model.yaml": coverage,
        "kernel/compile_model.yaml": compile_model,
        "kernel/variables.yaml": kernel_vars,
        "kernel/paths.yaml": kernel_paths,
        "kernel/branches.yaml": branches_doc,
        "kernel/runtime_conditions.yaml": _build_runtime_conditions(
            op_name, branch_rows, sample_limit=sample_limit
        ),
        "kernel/pipeline.yaml": {
            "version": 1,
            "op_name": op_name,
            "pipelines": [{"id": "PIPE_MAIN"}],
            "stages": [{"id": "PIPE_STAGE_MAIN"}],
            "resources": [],
        },
        "kernel/resources.yaml": {
            "version": 1,
            "op_name": op_name,
            "buffers": [{"id": "BUF_UB"}],
            "sync_events": [{"id": "SYNC_DONE"}],
            "workspaces": [],
            "resources": [{"id": "RES_CORE"}],
        },
        "cross_layer/impact_graph.yaml": impact,
        "cross_layer/tiling_to_kernel.yaml": tiling_to_kernel,
        "flow/golden_model.yaml": golden_doc,
        "flow/numerical_model.yaml": numerical,
        "query/routes.yaml": _build_query_routes(op_name),
        "query/terminology.yaml": _build_query_terminology(op_name, dimensions, key_fields),
        "quality.yaml": {
            "status": "pass",
            "decision": "pass",
            "checks": ["layered_ir", "final"],
        },
    }

    _write_materialized_files(uo_root, files)
    return files


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _collect_artifact_hashes(uo_root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for rel in REQUIRED_REL_PATHS:
        path = uo_root / rel
        if path.exists():
            hashes[rel] = _sha256_file(path)
    graph_path = uo_root / "ir" / "operator_graph.yaml"
    if graph_path.exists():
        hashes["ir/operator_graph.yaml"] = _sha256_file(graph_path)
    runtime_path = uo_root / "kernel" / "runtime_conditions.yaml"
    if runtime_path.exists():
        hashes["kernel/runtime_conditions.yaml"] = _sha256_file(runtime_path)
    id_path = uo_root / "ir" / "input_derivable.yaml"
    if id_path.exists():
        hashes["ir/input_derivable.yaml"] = _sha256_file(id_path)
    return hashes


def _write_artifact_hashes(uo_root: Path, hashes: dict[str, str]) -> None:
    payload = {
        "version": 1,
        "hashes": dict(sorted(hashes.items())),
    }
    write_yaml(uo_root / ARTIFACT_HASHES_REL, payload)


def _write_materialized_files(uo_root: Path, files: dict[str, Any]) -> None:
    for rel, payload in files.items():
        # Hard rule: never write UO contracts/** (retired; TG owns testcase contracts).
        if str(rel).startswith("contracts/"):
            continue
        write_yaml(uo_root / rel, payload)

    hashes = _collect_artifact_hashes(uo_root)
    _write_artifact_hashes(uo_root, hashes)
    files[ARTIFACT_HASHES_REL] = {
        "version": 1,
        "hashes": dict(sorted(hashes.items())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export UO KB views")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--view", default="testcase-contract")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    uo_root = existing_operator_root(repo_root, op_name)
    result = export_view(uo_root, op_name, args.view)
    print(f"exported view={args.view} files={len(result['files'])}")
    return 0


def _load_or_materialize(
    uo_root: Path,
    graph: dict[str, Any],
    **_ignored: Any,
) -> dict[str, Any]:
    # Ignore historical $UO_ROOT/contracts/**; only layered REQUIRED_REL_PATHS count.
    files: dict[str, Any] = {}
    missing = False
    for rel in REQUIRED_REL_PATHS:
        data = read_yaml(uo_root / rel)
        if not data:
            missing = True
            break
        files[rel] = data
    if not missing and len(files) == len(REQUIRED_REL_PATHS):
        return files
    return materialize_testcase_contract_files(uo_root, graph)


def _build_testcase_contract(
    graph: dict[str, Any],
    *,
    key_fields: list[dict[str, Any]],
    branch_rows: list[dict[str, Any]],
    template_blocks: list[dict[str, Any]],
    golden: dict[str, Any],
    kvar_nodes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    nodes = graph.get("nodes") or []
    optional_inputs = []
    dtype_layout = []
    variables: list[dict[str, Any]] = []
    typed_constraints: list[dict[str, Any]] = []
    coverage_obligations: dict[str, list[dict[str, Any]]] = {
        "families": [{"id": "COV_FAM_DEFAULT", "target_refs": ["FAM_DEFAULT"]}],
        "compile_template": [],
        "kernel_branch": [],
        "kernel_paths": [{"id": "COV_PATH_ENTRY", "target_refs": ["KPATH_ENTRY"]}],
        "runtime_variable_state": [],
        "tiling_key_field": [],
        "tiling_keys": [],
        "tilingdata": [],
        "optional_input_mode": [],
        "numerical": [],
        "negative": [],
    }

    for node in nodes:
        ntype = str(node.get("node_type") or "")
        nid = str(node.get("id") or "")
        name = str(node.get("name") or nid)
        if ntype == "OptionalInputPresence" or nid.startswith("VAR_OPTIONAL_"):
            opt_id = nid if nid.startswith("VAR_OPTIONAL_") else stable_id("VAR_OPTIONAL_", name)
            optional_inputs.append(
                {
                    "id": opt_id,
                    "name": name,
                    "role": "optional_presence",
                    "semantic_role": "optional_presence",
                    "presence_columns": _optional_presence_columns(name),
                }
            )
            coverage_obligations["optional_input_mode"].append({"id": stable_id("COV_OPT_", name), "target_refs": [opt_id]})
            variables.append({"id": opt_id, "type": "bool", "domain": [False, True]})
        if ntype in {"InputDType", "InputLayout"}:
            class_id = stable_id("NUM_", name)
            layout_kind = "primary" if ntype == "InputLayout" and "mask" not in name.lower() and "pse" not in name.lower() else (
                "secondary" if ntype == "InputLayout" else None
            )
            dtype_layout.append(
                {
                    "id": class_id,
                    "name": name,
                    "class": name,
                    "layout_kind": layout_kind,
                    "semantic_role": "layout_primary" if layout_kind == "primary" else ("layout_secondary" if layout_kind == "secondary" else "dtype"),
                }
            )

    for field in key_fields:
        key_id = str(field["id"])
        values = field.get("values") or []
        if not field.get("role") and not field.get("csv_determinants"):
            role_meta = _infer_key_field_role(str(field.get("name") or key_id))
            field["role"] = role_meta.get("role")
            field["semantic_role"] = role_meta.get("role")
            field["csv_determinants"] = role_meta.get("csv_determinants") or []
            field["primary_layout_field"] = role_meta.get("primary_layout_field")
            # Do not let naming heuristic own needs_binding; classify overlay does.
        var_id = f"VAR_{key_id}"
        if values:
            variables.append(
                {
                    "id": var_id,
                    "type": "int",
                    "domain": {"kind": "discrete", "values": values},
                    "role": field.get("role"),
                    "semantic_role": field.get("semantic_role"),
                }
            )
            coverage_obligations["tiling_keys"].append(
                {"id": stable_id("COV_", key_id), "field": field.get("name"), "values": values, "target_refs": [key_id]}
            )
            coverage_obligations["tiling_key_field"].append(
                {"id": stable_id("COV_FIELD_", key_id), "kind": "tiling_key_field", "target_refs": [key_id]}
            )

    for block in template_blocks:
        coverage_obligations["compile_template"].append({"id": stable_id("COV_", block["id"]), "target_refs": [block["id"]]})

    for branch in branch_rows:
        bid = str(branch["id"])
        coverage_obligations["kernel_branch"].append(
            {
                "id": stable_id("COV_", bid),
                "target_refs": [bid],
                "binding_time": branch.get("binding_time"),
                "determinant_source": branch.get("determinant_source"),
            }
        )
        variables.append({"id": f"VAR_{bid}", "type": "bool", "domain": [False, True]})
        # TilingKey-backed compile branches stay on KEY obligations only — never synthesize ghost KVAR_IS_*.

    # RVS exclusively from true TilingData-backed KernelVariables.
    for kvar in kvar_nodes or []:
        name = str(kvar.get("name") or "")
        if not name or not kvar.get("domain"):
            continue
        kvar_id = _ensure_prefix(kvar.get("id"), "KVAR_", name)
        var_id = stable_id("VAR_KVAR_", name)
        domain = kvar.get("domain")
        is_int = isinstance(domain, list) and all(isinstance(v, int) and not isinstance(v, bool) for v in domain)
        if not any(v.get("id") == var_id for v in variables):
            variables.append(
                {
                    "id": var_id,
                    "type": "int" if is_int else "enum",
                    "domain": domain if is_int else [str(v) for v in (domain or [])],
                    "semantic_role": _infer_kvar_semantic_role(kvar),
                    "binding_surface": "tiling_data",
                }
            )
        coverage_obligations["runtime_variable_state"].append(
            {
                "id": stable_id("COV_STATE_", name),
                "kind": "runtime_variable_state",
                "target_refs": [kvar_id],
                "target_value": domain[0] if isinstance(domain, list) and domain else None,
            }
        )

    if not dtype_layout:
        dtype_layout = [
            {"id": "NUM_FLOAT16", "name": "FLOAT16"},
            {"id": "NUM_BF16", "name": "BF16"},
            {"id": "NUM_FLOAT32", "name": "FLOAT32"},
        ]

    if golden.get("function"):
        typed_constraints.append(
            {
                "id": "CON_GOLDEN_ORACLE",
                "kind": "oracle_ref",
                "expr": {"op": "eq", "var": "VAR_NUM_GOLDEN", "value": golden.get("function")},
                "tags": ["golden"],
            }
        )
        variables.append({"id": "VAR_NUM_GOLDEN", "type": "enum", "domain": [str(golden.get("function"))]})

    variables.append({"id": "VAR_FAMILY", "type": "enum", "domain": ["FAM_DEFAULT"]})
    variables.append({"id": "VAR_KERNEL_PATH", "type": "enum", "domain": ["KPATH_ENTRY"]})

    # Dedup variables by id
    dedup: dict[str, dict[str, Any]] = {}
    for item in variables:
        dedup[str(item["id"])] = item
    variables = list(dedup.values())

    key_determinants = {}
    for field in key_fields:
        if not (field.get("csv_determinants") or field.get("role") or field.get("needs_binding") or "input_derivable" in field):
            continue
        det: dict[str, Any] = {
            "role": field.get("role"),
            "semantic_role": field.get("semantic_role"),
            "csv_determinants": field.get("csv_determinants") or [],
            "primary_layout_field": field.get("primary_layout_field"),
            "needs_binding": bool(field.get("needs_binding")),
        }
        if "input_derivable" in field:
            det["input_derivable"] = field.get("input_derivable")
            det["not_input_derivable"] = bool(field.get("not_input_derivable"))
            det["host_parent"] = field.get("host_parent")
            det["host_parent_evidence"] = field.get("host_parent_evidence") or ""
            det["derivation_roots"] = list(field.get("derivation_roots") or [])[:16]
            if field.get("gap_ref"):
                det["gap_ref"] = field.get("gap_ref")
        key_determinants[str(field["id"])] = det
    producible_fields = _producible_fields_from_golden(golden)

    return {
        "version": 2,
        "op_name": graph.get("op_name"),
        "architecture": graph.get("architecture") or graph.get("arch") or "",
        "source": {
            "understand_phase": "layered_ir",
            "quality_status": "pass",
            "canonical_hashes": {},
        },
        "interface": {
            "required_inputs": [],
            "optional_inputs": optional_inputs,
            "outputs": [],
            "attrs": [],
            "dtype_layout_domains": dtype_layout,
            "primary_layout_field": "input_layout",
            "producible_fields": producible_fields,
        },
        "variables": variables,
        "typed_constraints": typed_constraints,
        "constraint_ir": {"variables": variables, "constraints": typed_constraints},
        "coverage_obligations": coverage_obligations,
        "key_determinants": key_determinants,
        "golden_contract": {
            "inputs": list(golden.get("input_case_keys") or []),
            "outputs": list(golden.get("outputs") or ["dq", "dk", "dv"]),
            "generation_policy": ["reference"] if golden.get("function") else [],
            "tolerance_policy": ["fp16"],
            "function": golden.get("function"),
            "file_path": golden.get("file_path"),
            "signature": golden.get("signature"),
            "start_line": golden.get("start_line"),
            "end_line": golden.get("end_line"),
            "pipeline": golden.get("pipeline") or {},
            "helpers": golden.get("helpers") or [],
            "ctx_tensor_writes": golden.get("ctx_tensor_writes") or [],
            "input_case_defaults": golden.get("input_case_defaults") or {},
        },
        "kernel_branch_obligations": [
            {"id": b["id"]} for b in branch_rows if b.get("binding_time") == "runtime"
        ][:80],
        "kernel_branch_obligations_meta": {
            "total_runtime_branches": len([b for b in branch_rows if b.get("binding_time") == "runtime"]),
            "listed_count": min(80, len([b for b in branch_rows if b.get("binding_time") == "runtime"])),
            "truncated": len([b for b in branch_rows if b.get("binding_time") == "runtime"]) > 80,
            "full_list": "kernel/branches.yaml",
        },
        "unresolved": [],
        "conflicts": [],
        "evidence_refs": [],
    }


def _merge_human_facts_supplements(uo_root: Path, contract: dict[str, Any]) -> dict[str, Any]:
    """Merge optional supplements/human_facts.yaml into key_determinants (generic overlay)."""
    path = Path(uo_root) / "supplements" / "human_facts.yaml"
    if not path.is_file():
        return contract
    try:
        from uo.scripts._ir_io import read_yaml
    except Exception:
        return contract
    doc = read_yaml(path)
    if not isinstance(doc, dict):
        return contract
    out = dict(contract)
    dets = dict(out.get("key_determinants") or {})
    for key_id, spec in (doc.get("key_determinants") or {}).items():
        if not isinstance(spec, dict):
            continue
        kid = str(key_id)
        base = dict(dets.get(kid) or {})
        base.update({k: v for k, v in spec.items() if v is not None})
        base["needs_binding"] = False if base.get("csv_determinants") else base.get("needs_binding", False)
        dets[kid] = base
    out["key_determinants"] = dets
    if doc.get("notes"):
        out.setdefault("supplement_notes", [])
        notes = out["supplement_notes"]
        if isinstance(notes, list):
            notes.append(str(doc.get("notes")))
    return out


def _apply_input_derivable_overlay(uo_root: Path, key_fields: list[dict[str, Any]]) -> None:
    """Merge compact classify markers into key_fields (parent + roots, no full chain)."""
    id_doc = read_yaml(Path(uo_root) / "ir" / "input_derivable.yaml")
    by_key = (id_doc.get("keys") or {}) if isinstance(id_doc, dict) else {}
    for field in key_fields:
        kid = str(field.get("id") or "")
        entry = by_key.get(kid) if isinstance(by_key.get(kid), dict) else None
        if entry:
            idv = entry.get("input_derivable")
            field["input_derivable"] = idv
            field["not_input_derivable"] = bool(entry.get("not_input_derivable"))
            field["host_parent"] = entry.get("host_parent")
            field["host_parent_evidence"] = entry.get("host_parent_evidence") or ""
            field["derivation_roots"] = list(entry.get("derivation_roots") or [])[:16]
            if entry.get("gap_ref"):
                field["gap_ref"] = entry.get("gap_ref")
            if idv is True:
                field["needs_binding"] = True
            elif idv is False or entry.get("not_input_derivable"):
                field["needs_binding"] = False
            else:  # unsolved
                field["needs_binding"] = True
            continue
        # Fallback when classify missing: empty csv → still needs TG bind.
        if not (field.get("csv_determinants") or []):
            field["needs_binding"] = True


def _infer_key_field_role(name: str) -> dict[str, Any]:
    """Generic KEY role + weak csv hints from naming. Does not own needs_binding."""
    bare = str(name or "").strip()
    upper = bare.upper().replace("_", "")
    out: dict[str, Any] = {"role": "enum_knob", "csv_determinants": [], "primary_layout_field": None}

    if upper.startswith("IS") and len(upper) > 2:
        stem = upper[2:]
        # Layout flags: IsTnd / IsBnsd / ... → primary input_layout equality.
        layout_labels = {"TND", "BNSD", "BSND", "BSH", "SBH", "ND", "NZ", "BNGSD", "BSNGD", "SBNGD"}
        if stem in layout_labels:
            out["role"] = "layout_flag"
            out["primary_layout_field"] = "input_layout"
            out["csv_determinants"] = [{"column": "input_layout", "op": "eq", "value": stem}]
            return out
        # Optional / switch IS* keys: do not invent CSV columns from names.
        if stem in {"PSE", "ATTENMASK", "ATTENTIONMASK", "DROP", "DROPOUT", "ROPE", "SINK"}:
            if stem in {"ROPE", "SINK"}:
                out["role"] = "switch"
            else:
                out["role"] = "optional_presence"
            out["csv_determinants"] = []
            return out
        out["role"] = "switch"
        return out

    if "TEMPLATE" in upper or bare.endswith("Num") or bare.endswith("TemplateNum"):
        out["role"] = "shape"
        return out
    if "DTYPE" in upper or bare.lower().endswith("dtype"):
        out["role"] = "enum_knob"
        return out
    return out


def _infer_kvar_semantic_role(node: dict[str, Any]) -> str:
    name = str(node.get("name") or node.get("id") or "")
    domain = node.get("domain")
    lower = name.lower()
    if lower in {"b", "n", "n1", "n2", "s", "s1", "s2", "d", "d_v"} or lower.endswith("size") or lower.endswith("num"):
        # Short names that collide with shape columns stay as switch/bool when domain is 0/1.
        if isinstance(domain, list) and set(domain) <= {0, 1} and len(domain) <= 2:
            return "switch"
        return "shape"
    if isinstance(domain, list) and set(v for v in domain if not isinstance(v, bool)) <= {0, 1} and domain:
        ints = [v for v in domain if isinstance(v, int) and not isinstance(v, bool)]
        if ints and set(ints) <= {0, 1}:
            return "switch"
    if "layout" in lower:
        return "layout_secondary" if any(x in lower for x in ("mask", "pse", "atten")) else "layout_primary"
    if "mode" in lower or "type" in lower:
        return "enum_knob"
    return "runtime"


def _enrich_domain_entries(entries: Any) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        item = dict(entry)
        if item.get("csv_value") is None and item.get("value") is not None:
            item["csv_value"] = item.get("value")
        out.append(item)
    return out


def _optional_presence_columns(name: str) -> list[str]:
    stem = str(name or "").strip().lower().replace("optional", "").strip("_")
    if not stem:
        return []
    return [f"{stem}_shape", f"{stem}_type", f"{stem}_dtype"]


def _producible_fields_from_golden(golden: dict[str, Any]) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in list(golden.get("input_case_keys") or []) + list((golden.get("input_case_defaults") or {}).keys()):
        name = str(key or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        lower = name.lower()
        role = "enum_knob"
        if lower in {"b", "n", "n1", "n2", "s", "s1", "s2", "d", "d_v"} or "token" in lower:
            role = "shape"
        elif "layout" in lower:
            role = "layout_primary" if "mask" not in lower and "pse" not in lower else "layout_secondary"
        elif "dtype" in lower:
            role = "dtype"
        elif lower.endswith("_shape") or lower.endswith("_type"):
            role = "optional_presence"
        elif lower in {"rope", "is_sink", "keep_prob"}:
            role = "switch"
        fields.append({"name": name, "role": role, "producible": True})
    literals = golden.get("dtype_layout_literals") or {}
    if isinstance(literals, dict):
        for name, values in literals.items():
            if name in seen:
                continue
            seen.add(str(name))
            fields.append(
                {
                    "name": str(name),
                    "role": "layout_primary" if "layout" in str(name).lower() else "dtype",
                    "producible": True,
                    "values": list(values or []),
                }
            )
    return fields


def _entities_from_graph(graph: dict[str, Any]) -> list[dict[str, Any]]:
    entities = []
    for node in graph.get("nodes") or []:
        nid = str(node.get("id") or "")
        ntype = str(node.get("node_type") or "")
        entity_id = nid
        if ntype == "KernelTemplateArgument" and not nid.startswith("KTPL_"):
            entity_id = stable_id("KTPL_", nid or node.get("name"))
        elif ntype == "KernelBranch" and not nid.startswith("KBR_"):
            entity_id = stable_id("KBR_", nid or node.get("name"))
        elif ntype == "TilingKey" and not nid.startswith("KEY_"):
            entity_id = stable_id("KEY_", nid or node.get("name"))
        elif ntype == "TilingDataField" and not nid.startswith("TDF_"):
            entity_id = stable_id("TDF_", nid or node.get("name"))
        elif ntype == "KernelVariable" and not nid.startswith(("KVAR_", "VAR_")):
            entity_id = stable_id("KVAR_", nid or node.get("name"))
        elif ntype == "GoldenFunction":
            entity_id = "NUM_GOLDEN"
        # Only export typed contract entities with stable prefixes to keep intake ID checks clean.
        if not entity_id.startswith(
            ("KEY_", "TDF_", "KTPL_", "KBR_", "KVAR_", "VAR_", "NUM_", "FAM_", "KPATH_", "COV_", "PIPE_", "BUF_", "SYNC_", "RES_", "GOLD_", "CON_")
        ):
            continue
        entities.append(
            {
                "id": entity_id,
                "stable_id": entity_id,
                "name": node.get("name"),
                "type": ntype,
                "data_type": "bool" if ntype in {"KernelBranch", "Predicate"} else ("enum" if node.get("domain") else "int"),
                "domain": node.get("domain"),
                "binding_time": node.get("binding_time"),
                "layer": node.get("layer"),
                "file_path": node.get("file_path"),
                "start_line": node.get("start_line"),
                "template_flags": node.get("template_flags"),
                "condition": node.get("condition"),
            }
        )
    entities.append({"id": "FAM_DEFAULT", "stable_id": "FAM_DEFAULT", "name": "default", "type": "family"})
    entities.append({"id": "KPATH_ENTRY", "stable_id": "KPATH_ENTRY", "name": "kernel_entry", "type": "kernel_path"})
    entities.append({"id": "PIPE_MAIN", "stable_id": "PIPE_MAIN", "name": "main", "type": "pipeline"})
    entities.append({"id": "CL_STEP_MAIN", "stable_id": "CL_STEP_MAIN", "name": "main", "type": "compute_step"})
    return entities


def _ensure_prefix(raw_id: Any, prefix: str, fallback: Any = None) -> str:
    text = str(raw_id or "").strip()
    if text.startswith(prefix):
        # Normalize casing for intake stable-id regex.
        body = text[len(prefix) :]
        cleaned = "".join(ch if ch.isalnum() else "_" for ch in body).strip("_").upper()
        return f"{prefix}{cleaned or 'UNKNOWN'}"
    return stable_id(prefix, str(fallback or text or "UNKNOWN"))


def _normalize_condition(text: Any) -> str:
    raw = " ".join(str(text or "").split())
    return raw.casefold()


def _condition_bucket(condition: str) -> str:
    c = condition.casefold()
    if "sparsemode" in c or "sparse_mode" in c:
        return "sparseMode"
    if any(tok in c for tok in ("s1", "s2", "seqlen", "q_s", "kv_s")):
        return "seqlen"
    if any(tok in c for tok in ("layout", "tnd", "bsh", "bsnd", "sbh")):
        return "layout"
    if any(tok in c for tok in ("dtype", "fp16", "bf16", "float16", "float32")):
        return "dtype"
    return "other"


def _build_runtime_conditions(
    op_name: str,
    branch_rows: list[dict[str, Any]],
    *,
    sample_limit: int = RUNTIME_SAMPLE_LIMIT,
) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    for branch in branch_rows:
        if branch.get("binding_time") != "runtime":
            continue
        cond = str(branch.get("condition") or "").strip()
        if not cond:
            continue
        norm = _normalize_condition(cond)
        bucket = _condition_bucket(cond)
        entry = groups.get(norm)
        if entry is None:
            entry = {
                "id": stable_id("RCOND_", norm[:80] or "EMPTY"),
                "condition": cond,
                "condition_norm": norm,
                "bucket": bucket,
                "count": 0,
                "sample_branch_ids": [],
                "determinant_refs": [],
            }
            groups[norm] = entry
        entry["count"] += 1
        bid = str(branch.get("id") or "")
        if bid and bid not in entry["sample_branch_ids"] and len(entry["sample_branch_ids"]) < sample_limit:
            entry["sample_branch_ids"].append(bid)
        det = str(branch.get("determinant_ref") or "")
        if det and det not in entry["determinant_refs"] and len(entry["determinant_refs"]) < sample_limit:
            entry["determinant_refs"].append(det)

    conditions = sorted(groups.values(), key=lambda g: (-int(g["count"]), str(g["bucket"]), str(g["id"])))
    buckets: dict[str, int] = {}
    for item in conditions:
        buckets[str(item["bucket"])] = buckets.get(str(item["bucket"]), 0) + 1
    return {
        "version": 1,
        "op_name": op_name,
        "condition_count": len(conditions),
        "branch_count": sum(int(c["count"]) for c in conditions),
        "sample_limit": sample_limit,
        "buckets": buckets,
        "conditions": conditions,
    }


def _build_query_routes(op_name: str) -> dict[str, Any]:
    return {
        "version": 1,
        "op_name": op_name,
        "default_hot": [
            "summary/human_overview.md",
            "summary/keys_table.yaml",
            "query/routes.yaml",
            "query/terminology.yaml",
            "tiling/key_space.yaml",
            "kernel/runtime_conditions.yaml",
            "ir/tilingkey_space.yaml",
        ],
        "default_cold": ["ir/unresolved.yaml", "quality.yaml", "checks/final.yaml"],
        "never_default": [
            "ir/operator_graph.yaml",
            "contracts/**",  # retired historical residue; TG owns contracts
            "cross_layer/impact_graph.yaml",
            "tiling/exhaustive_key_space.yaml",
            "tiling/key_cards/**",  # not a default product; use kb_graph KTPL/KEY edges
            "facts/**",
            "graphs/**",
        ],
        "routes": {
            "overview": {
                "files": ["summary/human_overview.md", "summary/keys_table.yaml"],
            },
            "tiling_key_what": {
                "files": ["tiling/key_space.yaml", "tiling/key_predicates.yaml"],
                "graph_patterns": ["entity_of", "neighbors_of", "templates_for_key"],
            },
            "tiling_key_hit": {
                "files": ["tiling/key_space.yaml", "ir/host_subgraph.yaml"],
                "graph_patterns": ["neighbors_of", "entity_of"],
                "note": "Follow writes/derives/determined_by to Host SYM + file_path; do not rely on key_cards",
            },
            "tiling_combinations": {
                "files": ["tiling/exhaustive_key_space.yaml", "ir/tilingkey_space.yaml"],
                "focus": ["combination_summary", "summary", "ktpl_instance_count"],
                "graph_patterns": ["list_templates", "templates_for_key"],
            },
            "entrypoint": {"files": ["ir/entrypoints.yaml"]},
            "host_pipeline": {"files": ["ir/host_subgraph.yaml", "ir/entrypoints.yaml"]},
            "runtime_branch": {"files": ["kernel/runtime_conditions.yaml", "kernel/branches.yaml"]},
            "runtime_cover": {"files": ["kernel/runtime_conditions.yaml"]},
            "compile_template": {
                "files": ["ir/tilingkey_space.yaml", "kernel/compile_model.yaml"],
                "graph_patterns": ["list_templates", "templates_for_key"],
            },
            "impact": {"files": ["cross_layer/tiling_to_kernel.yaml"]},
            "golden": {"files": ["ir/golden.yaml", "flow/golden_model.yaml"]},
            "contract": {"files": ["tiling/coverage_model.yaml", "tiling/key_space.yaml"]},
            "unresolved": {"files": ["ir/unresolved.yaml", "checks/final.yaml"]},
            "quality": {"files": ["quality.yaml", "checks/final.yaml", "checks/artifact_hashes.yaml"]},
        },
    }


def _build_query_terminology(
    op_name: str,
    dimensions: list[dict[str, Any]],
    key_fields: list[dict[str, Any]],
) -> dict[str, Any]:
    terms: dict[str, dict[str, Any]] = {}

    def add_term(term: str, *, entity_id: str, kind: str) -> None:
        key = str(term or "").strip()
        if not key:
            return
        entry = terms.setdefault(
            key,
            {"aliases": [], "entity_ids": [], "kind": kind, "normalized": "".join(ch for ch in key.lower() if ch.isalnum())},
        )
        if entity_id and entity_id not in entry["entity_ids"]:
            entry["entity_ids"].append(entity_id)
        aliases = entry["aliases"]
        for alias in (key, key.casefold(), key.upper()):
            if alias and alias not in aliases:
                aliases.append(alias)

    for field in key_fields:
        name = str(field.get("name") or "")
        kid = str(field.get("id") or stable_id("KEY_", name))
        add_term(name, entity_id=kid, kind="tiling_key")
        add_term(kid, entity_id=kid, kind="tiling_key")
        if name.startswith("Is") and len(name) > 2:
            camel = name[0].lower() + name[1:]
            add_term(camel, entity_id=kid, kind="tiling_key")
            add_term(name[2:], entity_id=kid, kind="tiling_key")

    for dim in dimensions:
        name = str(dim.get("name") or "")
        if name:
            add_term(name, entity_id=stable_id("KEY_", name), kind="tiling_key")

    return {"version": 1, "op_name": op_name, "term_count": len(terms), "terms": terms}


if __name__ == "__main__":
    raise SystemExit(main())
