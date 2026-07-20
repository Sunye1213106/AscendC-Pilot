"""Tests for condition AST, atom bind, and branch alignment."""

from __future__ import annotations

from pathlib import Path

import yaml

from testcase_agent.atom_bind import BindContext, bind_atom
from testcase_agent.binding_lexicon import normalize_lexicon
from testcase_agent.branch_align import align_branches
from testcase_agent.condition_ast import parse_condition
from testcase_agent.condition_simplify import simplify_and_atomize
from testcase_agent.reachability import annotate_reachable_values
from testcase_agent.realization_map import build_realization_map, csv_var

_FIXTURE_LEXICON = normalize_lexicon(
    yaml.safe_load((Path(__file__).parent / "fixtures" / "sample_binding_lexicon.yaml").read_text(encoding="utf-8"))
)


def test_parse_and_and_or() -> None:
    ast = parse_condition("IS_TND && IS_ROPE")
    assert ast["op"] == "and"
    assert len(ast["args"]) == 2
    out = simplify_and_atomize("IS_TND && !IS_ROPE")
    assert out["status"] == "ok"
    ids = {a["id"] for a in out["atoms"]}
    assert "IS_TND" in ids
    assert "IS_ROPE" in ids


def test_parse_arith_cmp_no_spaces() -> None:
    out = simplify_and_atomize("p+q<=n")
    assert out["status"] == "ok"
    assert out["ast"]["op"] == "le"
    assert out["ast"]["lhs"]["op"] == "add"


def test_arith_cmp_binds_with_set_by_csv() -> None:
    snapshot = {
        "files": {
            "kernel/variables.yaml": {
                "runtime_variables": [
                    {"id": "KVAR_A", "name": "a", "domain": [0, 1, 2, 4], "set_by": {"csv": "a"}},
                    {"id": "KVAR_R1", "name": "R1", "domain": [0, 1, 2, 4], "set_by": {"csv": "R1"}},
                    {"id": "KVAR_R2", "name": "R2", "domain": [0, 1, 2, 4], "set_by": {"csv": "R2"}},
                ]
            }
        }
    }
    result = align_branches(
        {"branches": [{"id": "KBR_ARITH", "condition": "a <= R1 + R2", "determinant_source": "KernelVariable"}]},
        snapshot,
    )
    assert result["alignment_report"]["totals"]["mapped"] == 1
    mapped = result["branch_mappings"][0]
    expr = mapped["derived_variable"]["expr"]["expr"]
    assert expr["op"] == "le"
    assert "VAR_CSV_a" in str(expr)
    free_cols = {v["column"] for v in result["free_csv_variables"]}
    assert {"a", "R1", "R2"} <= free_cols


def test_baseclass_not_substitute_fail() -> None:
    result = align_branches(
        {
            "branches": [
                {"id": "KBR_NOT", "condition": "!BaseClass::IS_TND", "determinant_source": "TemplateArg"},
                {"id": "KBR_UF", "condition": "!ENABLE_UNITFLAG", "determinant_source": "CompileMacro"},
            ]
        },
        lexicon=_FIXTURE_LEXICON,
    )
    mapped = {item["branch_ref"] for item in result["branch_mappings"]}
    assert "KBR_NOT" in mapped
    assert "KBR_UF" in mapped
    assert result["alignment_report"]["reason_counts"].get("SUBSTITUTE_FAIL", 0) == 0


def test_parse_orig_dtype_and_unlikely() -> None:
    out = simplify_and_atomize("unlikely(ORIG_DTYPE_QUERY == DT_FLOAT16)")
    assert out["status"] == "ok"
    assert len(out["atoms"]) == 1
    assert "ORIG_DTYPE" in out["atoms"][0]["id"] or "DT_FLOAT16" in out["atoms"][0]["raw"]


def test_bind_key_and_loop_local() -> None:
    ctx = BindContext(lexicon=_FIXTURE_LEXICON)
    key = bind_atom({"id": "IS_TND", "kind": "ident", "raw": "IS_TND", "name": "IS_TND", "negated": False}, ctx)
    assert key["status"] == "bound"
    assert key["target"]["var"] == "VAR_KEY_ISTND"
    loop = bind_atom(
        {
            "id": "taskId > 0",
            "kind": "cmp",
            "raw": "taskId > 0",
            "name": "taskId",
            "lhs": "taskId",
            "cmp": "gt",
            "rhs": 0,
            "negated": False,
        },
        ctx,
    )
    assert loop["status"] == "unbound"
    assert loop["reason"] == "LOOP_LOCAL"


def test_align_maps_and_abstracts() -> None:
    result = align_branches(
        {
            "branches": [
                {"id": "KBR_AND", "condition": "IS_TND && IS_ROPE", "determinant_source": "TemplateArg"},
                {"id": "KBR_LOOP", "condition": "taskId > 0", "determinant_source": "KernelVariable"},
                {"id": "KBR_FOO", "condition": "foo && bar", "determinant_source": "TemplateArg"},
            ]
        },
        lexicon=_FIXTURE_LEXICON,
    )
    mapped = {item["branch_ref"] for item in result["branch_mappings"]}
    abstract = {item["branch_ref"]: item for item in result["abstract_branches"]}
    assert "KBR_AND" in mapped
    assert abstract["KBR_LOOP"]["reason"] == "LOOP_LOCAL"
    assert abstract["KBR_FOO"]["reason"] in {"UNBOUND_ATOM", "UNBOUND_CMP", "UNBOUND_TEMPLATE"}
    assert result["alignment_report"]["totals"]["mapped"] == 1


def test_topo_reachability_for_branch_on_key() -> None:
    realization_map = {
        "csv_variables": [
            {"id": csv_var("Input_Layout"), "column": "Input_Layout", "type": "enum", "domain": ["TND", "BSH"]},
            {"id": csv_var("B"), "column": "B", "type": "int", "domain": [1, 2]},
        ],
        "derived_variables": [
            {
                "id": "VAR_KEY_ISTND",
                "type": "int",
                "domain": [0, 1],
                "expr": {
                    "op": "derived",
                    "var": "VAR_KEY_ISTND",
                    "expr": {
                        "op": "if_then_else",
                        "condition": {"op": "eq", "var": csv_var("Input_Layout"), "value": "TND"},
                        "then": 1,
                        "else": 0,
                    },
                },
            },
            {
                "id": "VAR_KBR_TND",
                "type": "bool",
                "domain": [False, True],
                "expr": {
                    "op": "derived",
                    "var": "VAR_KBR_TND",
                    "expr": {"op": "eq", "var": "VAR_KEY_ISTND", "value": 1},
                },
            },
        ],
    }
    out = annotate_reachable_values(realization_map)
    by_id = {item["id"]: item for item in out["derived_variables"]}
    assert by_id["VAR_KEY_ISTND"]["reachable_status"] == "ok"
    assert by_id["VAR_KBR_TND"]["reachable_status"] == "ok"
    assert set(by_id["VAR_KBR_TND"]["reachable_values"]) == {False, True}


def test_build_map_uses_alignment() -> None:
    schema = {
        "columns": ["Testcase_Name", "Enable", "Input_Layout", "rope", "B"],
        "fields": [
            {"name": "Testcase_Name", "order": 0, "role": "case_id"},
            {"name": "Enable", "order": 1, "role": "constant"},
            {"name": "Input_Layout", "order": 2, "role": "solver_input", "value_type": "enum", "domain": ["TND"]},
            {"name": "rope", "order": 3, "role": "solver_input", "value_type": "int", "domain": {"values": [0, 1]}},
            {"name": "B", "order": 4, "role": "solver_input", "value_type": "int", "domain": {"values": [1, 2]}},
        ],
        "warnings": [],
    }
    snapshot = {
        "snapshot_hash": "snap",
        "files": {
            "tiling/key_space.yaml": {
                "fields": [{"id": "KEY_ISTND", "values": [0, 1]}, {"id": "KEY_ISROPE", "values": [0, 1]}]
            },
            "kernel/branches.yaml": {
                "branches": [
                    {"id": "KBR_TND", "condition": "IS_TND", "determinant_source": "TemplateArg"},
                    {"id": "KBR_AND", "condition": "IS_TND && IS_ROPE", "determinant_source": "TemplateArg"},
                    {"id": "KBR_COMPLEX", "condition": "foo && bar", "determinant_source": "TemplateArg"},
                ]
            },
        },
    }
    realization_map = build_realization_map(snapshot, schema, lexicon=_FIXTURE_LEXICON)
    mapped = {item["branch_ref"] for item in realization_map["branch_mappings"]}
    assert "KBR_TND" in mapped
    assert "KBR_AND" in mapped
    assert "KBR_COMPLEX" not in mapped
    assert realization_map.get("alignment_report", {}).get("totals", {}).get("mapped", 0) >= 2


def test_no_hardcoded_fag_tokens_in_module() -> None:
    from testcase_agent import atom_bind as ab

    assert ab.TOKEN_KEY_VALUE == {}
    assert ab.EXTRA_KEY_TOKENS == {}
    assert ab.CSV_FIELD_ALIASES == {}
