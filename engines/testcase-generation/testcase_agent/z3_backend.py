# -*- coding: utf-8 -*-
"""TG's Z3 backend: the shared compiler plus TG's obligation model.

The IR compiler, domain handling and model abstraction live in
`acp_common.z3_backend`. What remains here is everything tied to obligations,
which are a TG concept, plus the two variable-prefix conventions the shared
backend now takes as configuration.
"""
from __future__ import annotations

from typing import Any

from acp_common.z3_backend import SolveConfig, Z3Backend as _CommonZ3Backend, Z3BackendError

from .constraint_ir import compile_obligation_target

__all__ = ["Z3BackendError", "SolveConfig", "Z3Backend"]


class Z3Backend(_CommonZ3Backend):
    exposed_derived_prefixes = ("VAR_CSV_", "VAR_KEY_", "VAR_KBR_", "VAR_KDEC_")
    generalize_prefixes = ("VAR_SHAPE_", "VAR_CSV_")
    generalize_suffixes = ("_DIM", "_LEN")

    def solve_obligations(self, obligations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        variable_ids = set(self.variables)
        for obligation in obligations:
            results.append(self.solve_one(obligation, variable_ids))
        return results

    def solve_one(self, obligation: dict[str, Any], variable_ids: set[str] | None = None) -> dict[str, Any]:
        target = compile_obligation_target(obligation, self.ir)
        if target.status != "ok":
            return {
                "obligation_id": obligation.get("id"),
                "status": target.status,
                "code": target.code,
                "model": {},
                "unsat_core": [],
                "reason": target.reason,
            }
        return self.solve_expr(target.expr, label=f"obligation:{obligation.get('id')}", obligation_id=obligation.get("id"))

    def evaluate_model_coverage(self, model: dict[str, Any], obligations: list[dict[str, Any]]) -> list[str]:
        covered: list[str] = []
        for obligation in obligations:
            if obligation.get("status") in {"proof_required", "conflicting", "unresolved"}:
                continue
            target = compile_obligation_target(obligation, self.ir)
            if target.status != "ok":
                continue
            if self.model_satisfies(model, target.expr):
                covered.append(str(obligation.get("id")))
        return sorted(dict.fromkeys(covered))
