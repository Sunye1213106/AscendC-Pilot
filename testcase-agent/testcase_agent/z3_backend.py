from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .constraint_ir import ConstraintIRError, compile_obligation_target, normalize_expr, parse_bool_literal


class Z3BackendError(RuntimeError):
    pass


@dataclass
class SolveConfig:
    timeout_ms: int = 5000


class Z3Backend:
    def __init__(self, ir: dict[str, Any], config: SolveConfig | None = None) -> None:
        try:
            import z3  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on user environment
            raise Z3BackendError("z3-solver is required for phase 2. Install testcase-agent[solver].") from exc
        self.z3 = z3
        self.ir = ir
        self.config = config or SolveConfig()
        self.symbols: dict[str, Any] = {}
        self.enum_value_to_int: dict[str, dict[str, int]] = {}
        self.enum_int_to_value: dict[str, dict[int, str]] = {}
        self.variables = {item["id"]: item for item in ir.get("variables", []) if isinstance(item, dict)}
        self._declare_symbols()
        self.base_solver, self.base_labels = self._build_base_solver()

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

    def solve_expr(self, expr: dict[str, Any], *, label: str = "expr", obligation_id: Any = "") -> dict[str, Any]:
        solver = self.base_solver
        solver.push()
        labels: dict[str, str] = dict(self.base_labels)
        try:
            self._assert_tracked(solver, self._compile_bool(expr), label, labels)
            check = solver.check()
            if check == self.z3.sat:
                model = solver.model()
                return {
                    "obligation_id": obligation_id,
                    "status": "sat",
                    "model": self.abstract_model(model),
                    "unsat_core": [],
                    "reason": "",
                }
            if check == self.z3.unsat:
                return {
                    "obligation_id": obligation_id,
                    "status": "unsat",
                    "model": {},
                    "unsat_core": [labels.get(str(label), str(label)) for label in solver.unsat_core()],
                    "reason": "unsat",
                }
            return {
                "obligation_id": obligation_id,
                "status": "unknown",
                "model": {},
                "unsat_core": [],
                "reason": solver.reason_unknown() or "unknown",
            }
        except (ConstraintIRError, Z3BackendError, TypeError, ValueError) as exc:
            return {
                "obligation_id": obligation_id,
                "status": "error",
                "model": {},
                "unsat_core": [],
                "reason": str(exc),
            }
        finally:
            solver.pop()

    def _build_base_solver(self) -> tuple[Any, dict[str, str]]:
        solver = self.z3.Solver()
        solver.set(timeout=self.config.timeout_ms)
        labels: dict[str, str] = {}
        self._add_base_domains(solver, labels)
        self._add_derived_constraints(solver, labels)
        self._add_contract_constraints(solver, labels)
        return solver, labels

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

    def model_satisfies(self, model: dict[str, Any], expr: dict[str, Any]) -> bool:
        fast = self.fast_model_satisfies(model, expr)
        if fast is not None:
            return fast
        z3 = self.z3
        solver = z3.Solver()
        solver.set(timeout=self.config.timeout_ms)
        labels: dict[str, str] = {}
        try:
            self._add_base_domains(solver, labels)
            self._add_derived_constraints(solver, labels)
            self._add_contract_constraints(solver, labels)
            for var_id, value in sorted(model.items()):
                if var_id in self.variables and not self.variables[var_id].get("derived"):
                    solver.add(self.symbols[var_id] == self._value(var_id, value))
            solver.add(self._compile_bool(expr))
            return solver.check() == z3.sat
        except (ConstraintIRError, Z3BackendError, TypeError, ValueError):
            return False

    def fast_model_satisfies(self, model: dict[str, Any], expr: dict[str, Any]) -> bool | None:
        try:
            return bool(self._eval_bool_from_model(model, expr))
        except (KeyError, TypeError, ValueError, ConstraintIRError, Z3BackendError, ZeroDivisionError):
            return None

    def _eval_bool_from_model(self, model: dict[str, Any], expr: Any) -> bool:
        expr = normalize_expr(expr)
        op = expr["op"]
        if op in {"eq", "ne", "lt", "le", "gt", "ge"}:
            if "lhs" in expr:
                lhs = self._eval_value_from_model(model, expr["lhs"])
                rhs = self._eval_value_from_model(model, expr["rhs"])
            else:
                lhs = self._eval_value_from_model(model, {"var": expr["var"]})
                rhs = self._eval_literal_for_var(str(expr["var"]), expr.get("value"))
            if op == "eq":
                return lhs == rhs
            if op == "ne":
                return lhs != rhs
            if op == "lt":
                return lhs < rhs
            if op == "le":
                return lhs <= rhs
            if op == "gt":
                return lhs > rhs
            return lhs >= rhs
        if op == "in":
            lhs = self._eval_value_from_model(model, {"var": expr["var"]})
            return lhs in [self._eval_literal_for_var(str(expr["var"]), value) for value in expr["values"]]
        if op == "not_in":
            lhs = self._eval_value_from_model(model, {"var": expr["var"]})
            return lhs not in [self._eval_literal_for_var(str(expr["var"]), value) for value in expr["values"]]
        if op == "and":
            return all(self._eval_bool_from_model(model, arg) for arg in expr["args"])
        if op == "or":
            return any(self._eval_bool_from_model(model, arg) for arg in expr["args"])
        if op == "not":
            return not self._eval_bool_from_model(model, expr["arg"])
        if op in {"implies", "requires"}:
            return (not self._eval_bool_from_model(model, expr["antecedent"])) or self._eval_bool_from_model(model, expr["consequent"])
        if op == "mutex":
            return sum(1 for arg in expr["args"] if self._eval_bool_from_model(model, arg)) <= 1
        if op == "aligned":
            return int(self._eval_value_from_model(model, {"var": expr["var"]})) % int(expr["alignment"]) == 0
        raise Z3BackendError(f"Expression op does not produce bool: {op}")

    def _eval_value_from_model(self, model: dict[str, Any], expr: Any) -> Any:
        if isinstance(expr, (bool, int, str)):
            return expr
        if isinstance(expr, dict) and "var" in expr and "op" not in expr:
            var_id = str(expr["var"])
            if var_id not in model:
                raise KeyError(var_id)
            return model[var_id]
        expr = normalize_expr(expr)
        op = expr["op"]
        if op in {"eq", "ne", "lt", "le", "gt", "ge", "in", "not_in", "and", "or", "not", "implies", "requires", "mutex", "aligned"}:
            return self._eval_bool_from_model(model, expr)
        if op in {"add", "sub", "mul", "div", "mod"}:
            args = [self._eval_value_from_model(model, arg) for arg in expr["args"]]
            if op == "add":
                return sum(args)
            if op == "sub":
                head, *tail = args
                for item in tail:
                    head -= item
                return head
            if op == "mul":
                result = args[0]
                for item in args[1:]:
                    result *= item
                return result
            if op == "div":
                return args[0] // args[1]
            return args[0] % args[1]
        if op == "if_then_else":
            return self._eval_value_from_model(model, expr["then"] if self._eval_bool_from_model(model, expr["condition"]) else expr["else"])
        if op == "derived":
            return self._eval_value_from_model(model, expr["expr"])
        raise Z3BackendError(f"Unsupported value expression op: {op}")

    def _eval_literal_for_var(self, var_id: str, value: Any) -> Any:
        spec = self.variables.get(var_id) or {}
        if spec.get("type") == "bool":
            return parse_bool_literal(value)
        if spec.get("type") == "int":
            return int(value)
        return str(value) if spec.get("type") == "enum" else value

    def abstract_model(self, model: Any) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for var_id, spec in sorted(self.variables.items()):
            if spec.get("derived") and not var_id.startswith(("VAR_CSV_", "VAR_KEY_", "VAR_KBR_", "VAR_KDEC_")):
                continue
            sym = self.symbols[var_id]
            value = model.eval(sym, model_completion=True)
            if spec["type"] == "bool":
                out[var_id] = bool(self.z3.is_true(value))
            elif spec["type"] == "int":
                out[var_id] = value.as_long()
            elif spec["type"] == "enum":
                out[var_id] = self.enum_int_to_value[var_id].get(value.as_long(), str(value.as_long()))
        return out

    def _declare_symbols(self) -> None:
        z3 = self.z3
        for var_id, spec in sorted(self.variables.items()):
            var_type = spec.get("type")
            if var_type == "bool":
                self.symbols[var_id] = z3.Bool(var_id)
            elif var_type == "int":
                self.symbols[var_id] = z3.Int(var_id)
            elif var_type == "enum":
                domain = [str(item) for item in spec.get("domain") or []]
                if not domain:
                    raise Z3BackendError(f"Enum variable {var_id} has no explicit domain")
                mapping = {value: idx for idx, value in enumerate(domain)}
                self.enum_value_to_int[var_id] = mapping
                self.enum_int_to_value[var_id] = {idx: value for value, idx in mapping.items()}
                self.symbols[var_id] = z3.Int(var_id)
            else:
                raise Z3BackendError(f"Unsupported variable type for {var_id}: {var_type}")

    def _add_base_domains(self, solver: Any, labels: dict[str, str]) -> None:
        z3 = self.z3
        for var_id, spec in sorted(self.variables.items()):
            sym = self.symbols[var_id]
            if spec.get("derived"):
                continue
            if spec["type"] == "bool":
                continue
            if spec["type"] == "int":
                domain = spec.get("domain") or {}
                if isinstance(domain, dict):
                    kind = str(domain.get("kind") or ("discrete" if "values" in domain else "range"))
                    if kind == "discrete":
                        values = [int(value) for value in domain.get("values") or []]
                        if values:
                            self._assert_tracked(solver, z3.Or([sym == value for value in values]), f"domain:{var_id}:values", labels)
                    elif domain.get("min") is not None:
                        self._assert_tracked(solver, sym >= int(domain["min"]), f"domain:{var_id}:min", labels)
                    if kind == "range" and domain.get("max") is not None:
                        self._assert_tracked(solver, sym <= int(domain["max"]), f"domain:{var_id}:max", labels)
                elif isinstance(domain, list) and domain:
                    self._assert_tracked(solver, z3.Or([sym == int(value) for value in domain]), f"domain:{var_id}:values", labels)
            elif spec["type"] == "enum":
                values = list(self.enum_value_to_int[var_id].values())
                self._assert_tracked(solver, z3.Or([sym == value for value in values]), f"domain:{var_id}:enum", labels)

    def _add_derived_constraints(self, solver: Any, labels: dict[str, str]) -> None:
        for var_id, spec in sorted(self.variables.items()):
            if not spec.get("derived"):
                continue
            definition = spec.get("definition")
            if not definition:
                raise Z3BackendError(f"Derived variable {var_id} has no definition")
            expr = normalize_expr(definition)
            self._assert_tracked(solver, self.symbols[var_id] == self._compile_value(expr), f"derived:{var_id}", labels)

    def _add_contract_constraints(self, solver: Any, labels: dict[str, str]) -> None:
        for item in self.ir.get("constraints") or []:
            if not isinstance(item, dict):
                continue
            expr = item.get("expr")
            cid = str(item.get("id") or "CONSTRAINT")
            if isinstance(expr, dict) and expr.get("op") == "derived":
                continue
            self._assert_tracked(solver, self._compile_bool(expr), f"contract:{cid}", labels)

    def _compile_bool(self, expr: Any) -> Any:
        z3 = self.z3
        expr = normalize_expr(expr)
        op = expr["op"]
        if op == "eq":
            if "lhs" in expr:
                lhs, rhs = self._binary_values(expr["lhs"], expr["rhs"])
                return lhs == rhs
            return self._symbol(expr["var"]) == self._value(expr["var"], expr.get("value"))
        if op == "ne":
            if "lhs" in expr:
                lhs, rhs = self._binary_values(expr["lhs"], expr["rhs"])
                return lhs != rhs
            return self._symbol(expr["var"]) != self._value(expr["var"], expr.get("value"))
        if op == "lt":
            if "lhs" in expr:
                lhs, rhs = self._binary_values(expr["lhs"], expr["rhs"])
                return lhs < rhs
            return self._symbol(expr["var"]) < self._value(expr["var"], expr.get("value"))
        if op == "le":
            if "lhs" in expr:
                lhs, rhs = self._binary_values(expr["lhs"], expr["rhs"])
                return lhs <= rhs
            return self._symbol(expr["var"]) <= self._value(expr["var"], expr.get("value"))
        if op == "gt":
            if "lhs" in expr:
                lhs, rhs = self._binary_values(expr["lhs"], expr["rhs"])
                return lhs > rhs
            return self._symbol(expr["var"]) > self._value(expr["var"], expr.get("value"))
        if op == "ge":
            if "lhs" in expr:
                lhs, rhs = self._binary_values(expr["lhs"], expr["rhs"])
                return lhs >= rhs
            return self._symbol(expr["var"]) >= self._value(expr["var"], expr.get("value"))
        if op == "in":
            return z3.Or([self._symbol(expr["var"]) == self._value(expr["var"], value) for value in expr["values"]])
        if op == "not_in":
            return z3.And([self._symbol(expr["var"]) != self._value(expr["var"], value) for value in expr["values"]])
        if op == "and":
            return z3.And([self._compile_bool(arg) for arg in expr["args"]])
        if op == "or":
            return z3.Or([self._compile_bool(arg) for arg in expr["args"]])
        if op == "not":
            return z3.Not(self._compile_bool(expr["arg"]))
        if op in {"implies", "requires"}:
            return z3.Implies(self._compile_bool(expr["antecedent"]), self._compile_bool(expr["consequent"]))
        if op == "mutex":
            args = [self._compile_bool(arg) for arg in expr["args"]]
            return z3.AtMost(*args, 1)
        if op == "aligned":
            return self._symbol(expr["var"]) % int(expr["alignment"]) == 0
        raise Z3BackendError(f"Expression op does not produce bool: {op}")

    def _compile_value(self, expr: Any) -> Any:
        z3 = self.z3
        if isinstance(expr, bool):
            return z3.BoolVal(expr)
        if isinstance(expr, int):
            return z3.IntVal(expr)
        if isinstance(expr, dict) and "var" in expr and "op" not in expr:
            return self._symbol(str(expr["var"]))
        expr = normalize_expr(expr)
        op = expr["op"]
        if op in {"eq", "ne", "lt", "le", "gt", "ge", "in", "not_in", "and", "or", "not", "implies", "requires", "mutex", "aligned"}:
            return self._compile_bool(expr)
        if op in {"add", "sub", "mul", "div", "mod"}:
            args = [self._arith_arg(arg) for arg in expr["args"]]
            if op == "add":
                return sum(args)
            if op == "sub":
                head, *tail = args
                for item in tail:
                    head = head - item
                return head
            if op == "mul":
                result = args[0]
                for item in args[1:]:
                    result = result * item
                return result
            if op == "div":
                return args[0] / args[1]
            if op == "mod":
                return args[0] % args[1]
        if op == "lit":
            return self._literal_or_expr(expr.get("value"))
        if op == "if_then_else":
            return z3.If(self._compile_bool(expr["condition"]), self._literal_or_expr(expr["then"]), self._literal_or_expr(expr["else"]))
        if op == "derived":
            return self._compile_value(expr["expr"])
        raise Z3BackendError(f"Unsupported value expression op: {op}")

    def _arith_arg(self, arg: Any) -> Any:
        if isinstance(arg, int):
            return self.z3.IntVal(arg)
        if isinstance(arg, dict) and "var" in arg and "op" not in arg:
            return self._symbol(str(arg["var"]))
        if isinstance(arg, dict):
            return self._compile_value(arg)
        raise Z3BackendError(f"Unsupported arithmetic argument: {arg}")

    def _literal_or_expr(self, value: Any) -> Any:
        if isinstance(value, dict):
            return self._compile_value(value)
        if isinstance(value, bool):
            return self.z3.BoolVal(value)
        if isinstance(value, int):
            return self.z3.IntVal(value)
        return value

    def _binary_values(self, lhs: Any, rhs: Any) -> tuple[Any, Any]:
        lhs_var = lhs.get("var") if isinstance(lhs, dict) and "var" in lhs and "op" not in lhs else None
        rhs_var = rhs.get("var") if isinstance(rhs, dict) and "var" in rhs and "op" not in rhs else None
        if lhs_var and not rhs_var and not isinstance(rhs, dict):
            return self._symbol(str(lhs_var)), self._value(str(lhs_var), rhs)
        if rhs_var and not lhs_var and not isinstance(lhs, dict):
            return self._value(str(rhs_var), lhs), self._symbol(str(rhs_var))
        return self._literal_or_expr(lhs), self._literal_or_expr(rhs)

    def _symbol(self, var_id: str) -> Any:
        if var_id not in self.symbols:
            raise Z3BackendError(f"Unknown variable: {var_id}")
        return self.symbols[var_id]

    def _value(self, var_id: str, value: Any) -> Any:
        spec = self.variables.get(var_id)
        if not spec:
            raise Z3BackendError(f"Unknown variable: {var_id}")
        if spec["type"] == "enum":
            if str(value) not in self.enum_value_to_int[var_id]:
                raise Z3BackendError(f"Value {value} is outside enum domain for {var_id}")
            return self.enum_value_to_int[var_id][str(value)]
        if spec["type"] == "bool":
            return parse_bool_literal(value)
        return int(value)

    def _assert_tracked(self, solver: Any, expr: Any, label: str, labels: dict[str, str]) -> None:
        safe = "LBL_" + "".join(ch if ch.isalnum() else "_" for ch in label)
        marker = self.z3.Bool(safe)
        labels[safe] = label
        solver.assert_and_track(expr, marker)
