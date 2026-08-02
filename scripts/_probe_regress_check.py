# -*- coding: utf-8 -*-
"""Run the new tests against the pre-fix behaviour, to prove they bite.

Each patch below restores exactly one of the three old behaviours; a test that
passes under them is testing nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engines" / "understand-operator"
sys.path.insert(0, str(ENGINE / "src"))
sys.path.insert(0, str(ROOT / "engines" / "common"))

import pytest  # noqa: E402

from uo_init import derive_key_fields, variable_model  # noqa: E402
from uo_init.expr_ir import Call, Expr, Ref  # noqa: E402
from uo_init.kb_model import Domain  # noqa: E402
from uo_init.source_resolver import CALL_ROOTS, Atom, SourceResolver, _match  # noqa: E402
from uo_init.variable_model import VarSpec, names_an_accessor  # noqa: E402


def _old_resolver_for(self, expr: Expr):
    scope = getattr(expr, "scope", "")
    if scope and self._scope_for is not None:
        return self._scope_for(scope)
    return self.resolver


def _old_guard_leaf_roots(self, cond: Expr):
    from uo_init.derive_key_fields import REACHED_PREFIX, _walk_dag

    roots: set[str] = set()
    reached = False
    unresolved = False
    for node in _walk_dag(cond):
        if isinstance(node, Ref):
            if node.symbol.startswith(REACHED_PREFIX):
                reached = True
                continue
            symbol = node.symbol
            resolver = self._resolver_for(node)
        elif isinstance(node, Call):
            symbol = (
                node.func[len("field:") :]
                if node.func.startswith("field:")
                else node.func
            )
            resolver = self.resolver
        else:
            continue
        got = False
        for atom in resolver.resolve(symbol).atoms:
            if atom.root:
                roots.add(atom.root)
                got = True
        if not got:
            unresolved = True
    return roots, reached, unresolved


def _old_operand_of(self, a: Expr, depth: int):
    inner: Atom | None = None
    if isinstance(a, Call):
        inner = self.resolve_call(a, depth + 1)
    elif isinstance(a, Ref) and (a.symbol in self.bindings or a.symbol in self.def_lists):
        sub = self.resolve(a.symbol, depth + 1)
        inner = sub.atoms[0] if sub.atoms else None
    if inner is None or not inner.symbol or inner.reason:
        return None
    if _match(CALL_ROOTS, inner.symbol) is not None:
        return None
    return inner.symbol, inner.index, inner.root


def _old_declare_on_demand(self, var_id: str, root: str, index: int | None = None):
    existing = self.variables.get(var_id)
    if existing is not None:
        return existing
    if root in ("INPUT_DTYPE", "INPUT_FORMAT", "TILING_DATA"):
        value_type = "enum"
    elif root in ("OPTIONAL_INPUT_PRESENCE", "SESSION_OPTION"):
        value_type = "bool"
    else:
        value_type = "int"
    lo = 1 if root == "INPUT_SHAPE" else None
    return self.add(
        VarSpec(
            var_id=var_id,
            name=var_id,
            value_type=value_type,
            domain=Domain(
                var_id=var_id,
                value_type=value_type,
                lo=lo,
                completeness="open",
                source="guard_reference",
            ),
            origin="guard_reference",
            description="referenced by a guard; domain not proven by the definition",
            identity_merged=names_an_accessor(var_id),
        )
    )


derive_key_fields._ValueNormalizer._resolver_for = _old_resolver_for
derive_key_fields._ValueNormalizer._guard_leaf_roots = _old_guard_leaf_roots
SourceResolver._operand_of = _old_operand_of
variable_model.VariableModel.declare_on_demand = _old_declare_on_demand

TESTS = [
    "tests/unit/test_key_exactness.py::test_a_call_is_resolved_in_the_scope_of_the_names_underneath_it",
    "tests/unit/test_key_exactness.py::test_two_tensors_read_through_locals_do_not_share_one_variable",
    "tests/unit/test_key_exactness.py::test_a_helper_call_is_classified_in_the_function_that_called_it",
    "tests/unit/test_source_resolver.py::test_a_shape_passed_into_a_helper_is_the_tensor_the_caller_passed",
    "tests/unit/test_shape_domains.py::test_a_shape_read_without_an_axis_may_be_zero",
    "tests/unit/test_shape_domains.py::test_the_bound_follows_the_axis_the_accessor_named",
    "tests/unit/test_shape_domains.py::test_the_absent_tensor_value_survives_into_what_gets_sampled",
]

raise SystemExit(pytest.main(["-q", "--no-header", *TESTS]))
