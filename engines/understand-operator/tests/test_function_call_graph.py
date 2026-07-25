"""Function call graph + overload-preserving candidate dedupe tests."""

from __future__ import annotations

from pathlib import Path

from uo._operator.artifacts import init_operator_contract_layout, operator_root
from uo.scripts._ir_io import write_yaml
from uo.scripts.extract_kernel_subgraph import extract_kernel_subgraph
from uo.scripts.function_body import (
    FunctionDefinition,
    iter_function_definitions,
    resolve_function_definition,
)
from uo.scripts.function_call_graph import build_call_edges_for_functions
from uo.scripts.resolve_entrypoints import _dedupe_candidates
from uo.scripts.semantic_identity import mint_symbol_identity


def test_candidate_dedupe_preserves_same_class_overloads() -> None:
    items = [
        {
            "name": "Process",
            "qualified_name": "DemoKernelA::Process",
            "class_or_namespace": "DemoKernelA",
            "file_path": "k.h",
            "start_line": 10,
            "signature_snippet": "void Process(int x) {",
            "confidence": 0.9,
        },
        {
            "name": "Process",
            "qualified_name": "DemoKernelA::Process",
            "class_or_namespace": "DemoKernelA",
            "file_path": "k.h",
            "start_line": 20,
            "signature_snippet": "void Process(float x) {",
            "confidence": 0.9,
        },
    ]
    out = _dedupe_candidates(items)
    assert len(out) == 2
    assert len({c.get("normalized_signature") for c in out}) == 2


def test_candidate_dedupe_preserves_template_specializations() -> None:
    items = [
        {
            "name": "Process",
            "qualified_name": "Kernel<T>::Process",
            "class_or_namespace": "Kernel",
            "file_path": "k.h",
            "start_line": 5,
            "signature_snippet": "template<typename T> void Process() {",
            "confidence": 0.8,
        },
        {
            "name": "Process",
            "qualified_name": "Kernel<float>::Process",
            "class_or_namespace": "Kernel",
            "file_path": "k.h",
            "start_line": 15,
            "signature_snippet": "template<> void Process() {",
            "confidence": 0.8,
        },
    ]
    assert len(_dedupe_candidates(items)) == 2


def test_real_extractor_passes_signature_to_identity(tmp_path: Path) -> None:
    src = tmp_path / "op_kernel" / "arch35"
    src.mkdir(parents=True)
    (src / "demo.h").write_text(
        "\n".join(
            [
                "class DemoKernelA {",
                "  void Process(int x) { Compute(); }",
                "  void Process(float x) { Compute(); }",
                "  void Compute() {}",
                "};",
                "",
            ]
        ),
        encoding="utf-8",
    )
    defs = iter_function_definitions(tmp_path, "op_kernel/arch35/demo.h", architecture="arch35")
    processes = [d for d in defs if d.name == "Process"]
    assert len(processes) == 2
    assert processes[0].identity_key != processes[1].identity_key


def test_out_of_class_method_definition_resolves_owner(tmp_path: Path) -> None:
    (tmp_path / "k.cpp").write_text(
        "\n".join(
            [
                "class KernelA {};",
                "void KernelA::Process() { Compute(); }",
                "void KernelA::Compute() {}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    resolved = resolve_function_definition(tmp_path, "k.cpp", "Process")
    assert resolved["ok"]
    fn: FunctionDefinition = resolved["function"]
    assert fn.class_or_namespace == "KernelA"


def _seed_same_file_two_classes(repo: Path, ir: Path) -> None:
    kdir = repo / "op_kernel" / "arch35"
    kdir.mkdir(parents=True)
    (kdir / "demo.h").write_text(
        "\n".join(
            [
                "template<class T>",
                "class DemoKernelA {",
                "  void Process() { if (a) Compute(); }",
                "  void Compute() {}",
                "};",
                "template<class T>",
                "class DemoKernelB {",
                "  void Process() { if (b) Compute(); }",
                "  void Compute() {}",
                "};",
                "",
            ]
        ),
        encoding="utf-8",
    )
    a = mint_symbol_identity(
        kind="entrypoint",
        name="DemoKernelA",
        file_path="op_kernel/arch35/demo.h",
        qualified_name="DemoKernelA",
        class_or_namespace="DemoKernelA",
        path_family="normal",
        architecture="arch35",
        prefix="EP",
    )
    b = mint_symbol_identity(
        kind="entrypoint",
        name="DemoKernelB",
        file_path="op_kernel/arch35/demo.h",
        qualified_name="DemoKernelB",
        class_or_namespace="DemoKernelB",
        path_family="varlen",
        architecture="arch35",
        prefix="EP",
    )
    write_yaml(
        ir / "entrypoint_graph.yaml",
        {
            "version": 2,
            "architecture": "arch35",
            "nodes": [
                {
                    "id": a.stable_id,
                    "role": "public_kernel_entry",
                    "architecture": "arch35",
                    "path_family": "normal",
                    "name": "DemoKernelA",
                    "locator": {
                        "file_path": "op_kernel/arch35/demo.h",
                        "start_line": 2,
                        "end_line": 5,
                    },
                    "symbol_ref": {**a.as_dict(), "class_or_namespace": "DemoKernelA"},
                },
                {
                    "id": b.stable_id,
                    "role": "public_kernel_entry",
                    "architecture": "arch35",
                    "path_family": "varlen",
                    "name": "DemoKernelB",
                    "locator": {
                        "file_path": "op_kernel/arch35/demo.h",
                        "start_line": 7,
                        "end_line": 10,
                    },
                    "symbol_ref": {**b.as_dict(), "class_or_namespace": "DemoKernelB"},
                },
            ],
            "edges": [],
            "extraction_units": [
                {
                    "id": "UNIT_A",
                    "architecture": "arch35",
                    "path_family": "normal",
                    "entry_root": a.stable_id,
                    "member_nodes": [a.stable_id],
                },
                {
                    "id": "UNIT_B",
                    "architecture": "arch35",
                    "path_family": "varlen",
                    "entry_root": b.stable_id,
                    "member_nodes": [b.stable_id],
                },
            ],
            "closure": {
                "host_main_chain": "closed",
                "kernel_main_chain": "closed",
                "blocking_unresolved": [],
            },
        },
    )
    write_yaml(
        ir / "extract_plan.yaml",
        {
            "version": 1,
            "confirmed_by": "test",
            "writers": [],
            "receivers": [],
            "aliases": [],
            "non_sink_roots": [],
            "extra_host_entries": [],
        },
    )


def test_same_file_multiple_kernel_classes_isolated(tmp_path: Path) -> None:
    op = "demo_same_file"
    repo = tmp_path / op
    root = operator_root(repo, op)
    init_operator_contract_layout(root, op, repo)
    _seed_same_file_two_classes(repo, root / "ir")
    payload = extract_kernel_subgraph(repo, op, architecture="arch35")
    processes = [n for n in payload["nodes"] if n.get("name") == "Process"]
    assert len(processes) >= 2
    assert len({n.get("identity_key") for n in processes}) >= 2
    classes = {n.get("class_or_namespace") for n in processes}
    assert "DemoKernelA" in classes and "DemoKernelB" in classes


def test_branches_attach_to_correct_function(tmp_path: Path) -> None:
    op = "demo_branch_owner"
    repo = tmp_path / op
    root = operator_root(repo, op)
    init_operator_contract_layout(root, op, repo)
    _seed_same_file_two_classes(repo, root / "ir")
    payload = extract_kernel_subgraph(repo, op, architecture="arch35")
    by_id = {n["id"]: n for n in payload["nodes"]}
    owned = [b for b in payload.get("branches") or [] if b.get("owning_function_id")]
    assert owned
    for br in owned:
        owner = by_id[br["owning_function_id"]]
        assert owner.get("name") == "Process"


def test_process_nodes_have_distinct_identity(tmp_path: Path) -> None:
    op = "demo_proc_id"
    repo = tmp_path / op
    root = operator_root(repo, op)
    init_operator_contract_layout(root, op, repo)
    _seed_same_file_two_classes(repo, root / "ir")
    payload = extract_kernel_subgraph(repo, op, architecture="arch35")
    processes = [n for n in payload["nodes"] if n.get("name") == "Process"]
    assert len({n["id"] for n in processes}) == len(processes)


def test_process_calls_correct_class_compute(tmp_path: Path) -> None:
    op = "demo_calls"
    repo = tmp_path / op
    root = operator_root(repo, op)
    init_operator_contract_layout(root, op, repo)
    _seed_same_file_two_classes(repo, root / "ir")
    payload = extract_kernel_subgraph(repo, op, architecture="arch35")
    by_id = {n["id"]: n for n in payload["nodes"]}
    resolved_calls = [
        e
        for e in payload["edges"]
        if e.get("type") == "calls" and e.get("target_status") == "resolved"
    ]
    assert resolved_calls
    for e in resolved_calls:
        caller = by_id[e["source"]]
        callee = by_id[e["target"]]
        if caller.get("name") == "Process" and callee.get("name") == "Compute":
            assert caller.get("class_or_namespace") == callee.get("class_or_namespace")


def test_overloaded_callee_ambiguous_is_candidate_set(tmp_path: Path) -> None:
    (tmp_path / "k.h").write_text(
        "\n".join(
            [
                "class K {",
                "  void Process() { Helper(1); }",
                "  void Helper(int x) {}",
                "  void Helper(float x) {}",
                "};",
                "",
            ]
        ),
        encoding="utf-8",
    )
    unresolved: list[dict] = []
    functions = iter_function_definitions(tmp_path, "k.h")
    by_id = {fn.stable_id: fn for fn in functions}
    _nodes, edges = build_call_edges_for_functions(functions, unresolved=unresolved)
    helper_calls = [e for e in edges if e.get("callee_name") == "Helper"]
    # Integer literal deterministically selects Helper(int) over Helper(float).
    assert helper_calls and helper_calls[0].get("target_status") == "resolved"
    target = by_id[str(helper_calls[0].get("target"))]
    assert target.normalized_signature.replace(" ", "").startswith("(int")


def test_unknown_callee_emits_unresolved(tmp_path: Path) -> None:
    (tmp_path / "k.h").write_text(
        "class K { void Process() { MissingHelper(); } };\n",
        encoding="utf-8",
    )
    unresolved: list[dict] = []
    _nodes, edges = build_call_edges_for_functions(
        iter_function_definitions(tmp_path, "k.h"), unresolved=unresolved
    )
    assert any(e.get("target_status") == "missing" for e in edges)
    assert any(u.get("kind") == "internal_definition_not_indexed" for u in unresolved)


def test_call_edge_has_source_locator(tmp_path: Path) -> None:
    (tmp_path / "k.h").write_text(
        "class K { void Process() { Compute(); } void Compute() {} };\n",
        encoding="utf-8",
    )
    unresolved: list[dict] = []
    _nodes, edges = build_call_edges_for_functions(
        iter_function_definitions(tmp_path, "k.h"), unresolved=unresolved
    )
    assert edges
    assert edges[0].get("locator", {}).get("file_path")
    assert edges[0].get("locator", {}).get("start_line")
