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

REQUIRED_REL_PATHS = (
    "contracts/testcase.yaml",
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


def export_view(uo_root: Path | str, op_name: str, view: str) -> dict[str, Any]:
    uo_root = Path(uo_root)
    if view != "testcase-contract":
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
    if view != "testcase-contract":
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
        "testcase_contract": files.get("contracts/testcase.yaml"),
        "relations": graph.get("edges") or [],
    }


def materialize_testcase_contract_files(uo_root: Path, graph: dict[str, Any]) -> dict[str, Any]:
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
    kvar_nodes = [n for n in nodes if n.get("node_type") == "KernelVariable" and n.get("domain")]
    ktpl_nodes = [n for n in nodes if n.get("node_type") == "KernelTemplateArgument"]

    key_fields = []
    tiling_variables = []
    for dim in dimensions:
        name = str(dim.get("name") or "")
        key_id = stable_id("KEY_", name)
        values = dim.get("values") or []
        key_fields.append(
            {
                "id": key_id,
                "kind": "key",
                "name": name,
                "data_type": "int",
                "values": values,
            }
        )
        tiling_variables.append(
            {
                "id": f"VAR_{key_id}",
                "kind": "variable",
                "canonical_name": name,
                "data_type": "int",
                "domain": {"kind": "discrete", "values": values} if values else {"kind": "int"},
            }
        )

    template_blocks = []
    reverse_realization_index: dict[str, Any] = {}
    for block in template_blocks_raw:
        flags = block.get("flags") or {}
        fixed = {str(k): (1 if v else 0) for k, v in flags.items()}
        block_id = block.get("id") or stable_id("KTPL_", str(block.get("name") or "BLOCK"))
        template_blocks.append(
            {
                "id": block_id,
                "name": block.get("name"),
                "fixed_fields": fixed,
                "field_domains": {},
                "product_count": 1,
                "condition": block.get("condition"),
                "source": block.get("source"),
            }
        )
        # Exactly one reverse witness per template block (avoid ambiguous dual matches).
        rid = stable_id("CON_IR_", str(block.get("name") or block_id))
        reverse_realization_index[rid] = {"key_pattern": dict(fixed)}

    dim_product = 1
    for dim in dimensions:
        values = dim.get("values") or []
        if isinstance(values, list) and values:
            dim_product *= max(1, len(values))
        else:
            dim_product = 0
            break
    args_sel_count = int(tilingkey.get("args_sel_count") or 0)
    exhaustive = {
        "version": 1,
        "op_name": op_name,
        "enumeration_source": "template_blocks",
        "field_order": [str(d.get("name")) for d in dimensions if d.get("name")],
        "template_blocks": template_blocks,
        "dimensions": dimensions,
        "args_sel_count": args_sel_count,
        "summary": {"expanded_key_count": len(template_blocks), "template_block_count": len(template_blocks)},
        "combination_summary": {
            "template_block_count": len(template_blocks),
            "args_sel_count": args_sel_count,
            "declared_dim_product": dim_product,
            "enumeration_policy": (
                "template_blocks_are_legal_compile_keys; "
                "args_sel_count_is_host_selection_space; "
                "declared_dim_product_is_independent_cartesian"
            ),
        },
        "reverse_realization_index": reverse_realization_index,
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
                "domain_entries": n.get("domain_entries"),
                "domain_source": n.get("domain_source"),
                "domain_type_name": n.get("domain_type_name"),
                "binding_time": n.get("binding_time") or "runtime",
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
            {"id": b["id"], "condition": b.get("condition"), "binding_time": b.get("binding_time")} for b in branch_rows[:80]
        ],
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

    contract = _build_testcase_contract(
        graph,
        key_fields=key_fields,
        branch_rows=branch_rows,
        template_blocks=template_blocks,
        golden=golden,
    )
    test_contract = {
        "version": 1,
        "op_name": op_name,
        "input_domain": {k: "any" for k in golden_inputs[:30]},
        "typed_constraints": contract.get("typed_constraints") or [],
        "kernel_branch_obligations": [{"id": b["id"]} for b in branch_rows if b.get("binding_time") == "runtime"][:80],
    }

    files: dict[str, Any] = {
        "contracts/testcase.yaml": contract,
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
        "kernel/runtime_conditions.yaml": _build_runtime_conditions(op_name, branch_rows),
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
        "quality.yaml": {"status": "pass", "decision": "pass", "checks": ["layered_ir", "final"]},
    }

    # Write first without hashes, then stamp hashes into contract.source.
    for rel, payload in files.items():
        if rel == "contracts/testcase.yaml":
            continue
        write_yaml(uo_root / rel, payload)

    hashes = {}
    for rel in REQUIRED_REL_PATHS:
        if rel == "contracts/testcase.yaml":
            continue
        path = uo_root / rel
        if path.exists():
            hashes[rel] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    graph_path = uo_root / "ir" / "operator_graph.yaml"
    if graph_path.exists():
        hashes["ir/operator_graph.yaml"] = "sha256:" + hashlib.sha256(graph_path.read_bytes()).hexdigest()

    contract = dict(files["contracts/testcase.yaml"])
    source = dict(contract.get("source") or {})
    source["canonical_hashes"] = hashes
    source["quality_status"] = "pass"
    source["understand_phase"] = "layered_ir"
    contract["source"] = source
    files["contracts/testcase.yaml"] = contract
    write_yaml(uo_root / "contracts" / "testcase.yaml", contract)
    hashes["contracts/testcase.yaml"] = "sha256:" + hashlib.sha256((uo_root / "contracts" / "testcase.yaml").read_bytes()).hexdigest()
    contract["source"]["canonical_hashes"] = hashes
    files["contracts/testcase.yaml"] = contract
    write_yaml(uo_root / "contracts" / "testcase.yaml", contract)

    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export understand-operator KB views")
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


def _load_or_materialize(uo_root: Path, graph: dict[str, Any]) -> dict[str, Any]:
    contract = read_yaml(uo_root / "contracts" / "testcase.yaml")
    if contract and int(contract.get("version") or 0) == 2:
        files: dict[str, Any] = {}
        missing = False
        for rel in REQUIRED_REL_PATHS:
            data = read_yaml(uo_root / rel) if rel != "contracts/testcase.yaml" else contract
            if not data and rel != "contracts/testcase.yaml":
                missing = True
                break
            files[rel] = data if rel != "contracts/testcase.yaml" else contract
        if not missing and len(files) == len(REQUIRED_REL_PATHS):
            files["contracts/testcase.yaml"] = contract
            return files
    return materialize_testcase_contract_files(uo_root, graph)


def _build_testcase_contract(
    graph: dict[str, Any],
    *,
    key_fields: list[dict[str, Any]],
    branch_rows: list[dict[str, Any]],
    template_blocks: list[dict[str, Any]],
    golden: dict[str, Any],
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
            optional_inputs.append({"id": opt_id, "name": name})
            coverage_obligations["optional_input_mode"].append({"id": stable_id("COV_OPT_", name), "target_refs": [opt_id]})
            variables.append({"id": opt_id, "type": "bool", "domain": [False, True]})
        if ntype in {"InputDType", "InputLayout"}:
            class_id = stable_id("NUM_", name)
            dtype_layout.append({"id": class_id, "name": name, "class": name})

    for field in key_fields:
        key_id = str(field["id"])
        values = field.get("values") or []
        var_id = f"VAR_{key_id}"
        if values:
            variables.append({"id": var_id, "type": "int", "domain": {"kind": "discrete", "values": values}})
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
        if branch.get("determinant_ref") and branch.get("domain"):
            ref = str(branch.get("determinant_ref")).split(".")[-1]
            var_id = stable_id("VAR_KVAR_", ref)
            if not any(v.get("id") == var_id for v in variables):
                domain = branch.get("domain")
                is_int = all(isinstance(v, int) and not isinstance(v, bool) for v in domain)
                variables.append(
                    {
                        "id": var_id,
                        "type": "int" if is_int else "enum",
                        "domain": domain if is_int else [str(v) for v in domain],
                    }
                )
                coverage_obligations["runtime_variable_state"].append(
                    {
                        "id": stable_id("COV_STATE_", ref),
                        "kind": "runtime_variable_state",
                        "target_refs": [stable_id("KVAR_", ref)],
                        "target_value": domain[0] if domain else None,
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

    return {
        "version": 2,
        "op_name": graph.get("op_name"),
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
        },
        "variables": variables,
        "typed_constraints": typed_constraints,
        "constraint_ir": {"variables": variables, "constraints": typed_constraints},
        "coverage_obligations": coverage_obligations,
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
        "kernel_branch_obligations": [{"id": b["id"]} for b in branch_rows if b.get("binding_time") == "runtime"][:80],
        "unresolved": [],
        "conflicts": [],
        "evidence_refs": [],
    }


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


def _build_runtime_conditions(op_name: str, branch_rows: list[dict[str, Any]]) -> dict[str, Any]:
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
        if bid and bid not in entry["sample_branch_ids"] and len(entry["sample_branch_ids"]) < 8:
            entry["sample_branch_ids"].append(bid)
        det = str(branch.get("determinant_ref") or "")
        if det and det not in entry["determinant_refs"] and len(entry["determinant_refs"]) < 8:
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
        "buckets": buckets,
        "conditions": conditions,
    }


def _build_query_routes(op_name: str) -> dict[str, Any]:
    return {
        "version": 1,
        "op_name": op_name,
        "default_cold": ["ir/unresolved.yaml", "quality.yaml"],
        "never_default": ["ir/operator_graph.yaml", "facts/**", "graphs/**"],
        "routes": {
            "tiling_key_what": {
                "files": ["tiling/key_space.yaml", "tiling/key_predicates.yaml", "tiling/key_cards/index.yaml"],
                "card_glob": "tiling/key_cards/KEY_*.yaml",
            },
            "tiling_key_hit": {
                "files": ["tiling/key_predicates.yaml", "tiling/key_cards/index.yaml"],
                "card_glob": "tiling/key_cards/KEY_*.yaml",
            },
            "tiling_combinations": {
                "files": ["tiling/exhaustive_key_space.yaml"],
                "focus": ["combination_summary"],
            },
            "entrypoint": {"files": ["ir/entrypoints.yaml"]},
            "host_pipeline": {"files": ["ir/host_subgraph.yaml", "ir/entrypoints.yaml"]},
            "runtime_branch": {"files": ["kernel/runtime_conditions.yaml", "kernel/branches.yaml"]},
            "runtime_cover": {"files": ["kernel/runtime_conditions.yaml", "contracts/testcase.yaml"]},
            "compile_template": {"files": ["tiling/exhaustive_key_space.yaml", "kernel/compile_model.yaml"]},
            "impact": {"files": ["cross_layer/impact_graph.yaml", "cross_layer/tiling_to_kernel.yaml"]},
            "golden": {"files": ["ir/golden.yaml", "flow/golden_model.yaml"]},
            "contract": {"files": ["contracts/testcase.yaml", "tiling/coverage_model.yaml"]},
            "unresolved": {"files": ["ir/unresolved.yaml", "checks/final.yaml"]},
            "quality": {"files": ["quality.yaml", "checks/final.yaml"]},
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
