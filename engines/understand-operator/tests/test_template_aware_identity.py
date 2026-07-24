"""Template-aware semantic identity and fail-closed resolution (synthetic DemoKernel*)."""

from __future__ import annotations

from pathlib import Path

from uo.scripts.cbm_client import CbmClient, CbmSymbol
from uo.scripts.function_body import find_function_body, find_function_bodies
from uo.scripts.semantic_identity import (
    IDENTITY_VERSION,
    infer_specialization_kind,
    mint_method_identity,
    mint_scoped_node_id,
    mint_symbol_identity,
    normalize_cxx_signature,
    parse_template_arity,
)


def test_identity_version_is_three() -> None:
    assert IDENTITY_VERSION == 3


def test_different_classes_same_process_name_differ() -> None:
    a = mint_method_identity(
        name="Process",
        file_path="op_kernel/arch35/demo_a.h",
        class_or_namespace="DemoKernelA",
    )
    b = mint_method_identity(
        name="Process",
        file_path="op_kernel/arch35/demo_b.h",
        class_or_namespace="DemoKernelB",
    )
    assert a.stable_id != b.stable_id
    assert a.identity_key != b.identity_key


def test_overloads_different_signature_not_merged() -> None:
    a = mint_method_identity(
        name="Process",
        file_path="k.h",
        class_or_namespace="DemoKernelA",
        signature="void Process(int x)",
    )
    b = mint_method_identity(
        name="Process",
        file_path="k.h",
        class_or_namespace="DemoKernelA",
        signature="void Process(float x)",
    )
    assert a.identity_key != b.identity_key


def test_primary_vs_explicit_specialization_not_merged() -> None:
    primary = mint_symbol_identity(
        kind="tiling_template",
        name="DemoTiling",
        file_path="host.h",
        qualified_name="DemoTiling",
        template_arity_or_signature="typename T",
        specialization_kind="primary",
    )
    explicit = mint_symbol_identity(
        kind="tiling_template",
        name="DemoTiling",
        file_path="host.h",
        qualified_name="DemoTiling",
        template_arity_or_signature="",
        specialization_kind="explicit",
    )
    assert primary.identity_key != explicit.identity_key


def test_template_arity_strings_differ() -> None:
    a = mint_symbol_identity(
        kind="method",
        name="Process",
        file_path="k.h",
        class_or_namespace="DemoKernelA",
        template_arity_or_signature="typename T",
    )
    b = mint_symbol_identity(
        kind="method",
        name="Process",
        file_path="k.h",
        class_or_namespace="DemoKernelA",
        template_arity_or_signature="typename T,int N",
    )
    assert a.identity_key != b.identity_key


def test_branch_ids_differ_across_files_same_line() -> None:
    owner_a = mint_method_identity(
        name="Process",
        file_path="a.h",
        class_or_namespace="DemoKernelA",
    ).identity_key
    owner_b = mint_method_identity(
        name="Process",
        file_path="b.h",
        class_or_namespace="DemoKernelB",
    ).identity_key
    id_a = mint_scoped_node_id("KBR", owner_a, "a.h", 10, "runtime_0")
    id_b = mint_scoped_node_id("KBR", owner_b, "b.h", 10, "runtime_0")
    assert id_a != id_b


def test_parse_template_arity_and_infer_kind() -> None:
    hdr = "template<typename T, int N> class DemoKernelA { void Process(); };"
    assert parse_template_arity(hdr) == "typename T,int N"
    assert infer_specialization_kind(hdr) == "primary"
    assert infer_specialization_kind("template<> class DemoKernelA<int> {};") == "explicit"
    assert normalize_cxx_signature("void  f( int x )") == "void f(int x)"


def test_resolve_qn_ambiguous_returns_none() -> None:
    client = CbmClient.__new__(CbmClient)
    client.resolve_symbols = lambda *a, **k: [
        CbmSymbol(1, "Process", "DemoKernelA::Process", "a.h", 1, 2),
        CbmSymbol(2, "Process", "DemoKernelB::Process", "b.h", 3, 4),
    ]
    assert client.resolve_qn("Process") is None
    hit, cands = client.resolve_qn_or_ambiguous("Process")
    assert hit is None
    assert len(cands) == 2


def test_find_function_body_ambiguous_without_class(tmp_path: Path) -> None:
    cpp = tmp_path / "dup.cpp"
    cpp.write_text(
        """
class DemoKernelA { void Process() { a(); } };
class DemoKernelB { void Process() { b(); } };
""",
        encoding="utf-8",
    )
    assert find_function_body(tmp_path, "dup.cpp", "Process") is None
    bodies = find_function_bodies(tmp_path, "dup.cpp", "Process")
    assert len(bodies) == 2
    assert find_function_body(tmp_path, "dup.cpp", "Process", owning_class="DemoKernelA") is not None
