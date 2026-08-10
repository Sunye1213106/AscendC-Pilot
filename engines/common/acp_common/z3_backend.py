# -*- coding: utf-8 -*-
"""Z3 compiler and solver for the shared constraint IR.

Extracted from the testcase-generation engine. The parts that were specific to
TG's obligation model stayed behind in `testcase_agent.z3_backend`, which now
subclasses this; the two variable-name prefix heuristics TG relies on became
class attributes rather than literals, so understand-operator can reuse the
compiler without inheriting TG's naming conventions.

Beyond satisfiability this exposes `prove_implies` / `prove_equivalent`, which
understand-operator needs to show a derived key expression means the same thing
as the condition read off the source.
"""
from __future__ import annotations

import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from acp_common.constraint_ir import ConstraintIRError, normalize_expr, parse_bool_literal

__all__ = ["Z3BackendError", "SolveConfig", "Z3Backend"]

#: Compilation recurses once per level of the expression, several Python frames
#: deep per level. Real expressions reach a few hundred levels -- shallow in
#: themselves, but past the default 1000-frame ceiling, which surfaces as a
#: `RecursionError` from inside a z3 call rather than as anything readable.
#: Depth is bounded by the source's nesting, so this is a ceiling, not a budget
#: to be consumed.
_COMPILE_RECURSION_LIMIT = 20000


@contextmanager
def _deep_recursion(limit: int = _COMPILE_RECURSION_LIMIT):
    previous = sys.getrecursionlimit()
    sys.setrecursionlimit(max(previous, limit))
    try:
        yield
    finally:
        sys.setrecursionlimit(previous)


class Z3BackendError(RuntimeError):
    pass


@dataclass
class SolveConfig:
    timeout_ms: int = 5000

    #: Z3's deterministic resource bound. `timeout_ms` is polled by the search
    #: loop and so does not fire while the solver is inside preprocessing --
    #: which is exactly where a large nonlinear-integer system goes to die.
    #: `rlimit` is checked in more places and, being a step count rather than a
    #: clock, gives the same verdict on every machine. 0 leaves it unset.
    rlimit: int = 0

    #: Last resort: interrupt the context from a timer thread. Neither of the
    #: bounds above is guaranteed to be polled everywhere, and a solver that
    #: never returns takes the whole run with it. 0 disables the watchdog.
    hard_timeout_ms: int = 0


class Z3Backend:
    #: Derived variables whose values are still worth reporting in a model.
    #: Derived variables are normally hidden because they are functions of the
    #: free ones; these prefixes mark the ones a caller asked to see.
    exposed_derived_prefixes: tuple[str, ...] = ()

    #: After a SAT result, if at least two free int variables matching these
    #: name patterns all came back as 1, retry once demanding one of them
    #: exceed 1. Z3 loves the all-ones cube and it makes for useless witnesses.
    generalize_prefixes: tuple[str, ...] = ()
    generalize_suffixes: tuple[str, ...] = ()

    def __init__(self, ir: dict[str, Any], config: SolveConfig | None = None) -> None:
        try:
            import z3  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on user environment
            raise Z3BackendError("z3-solver is required. Install acp-common's z3-solver dependency.") from exc
        self.z3 = z3
        self.ir = ir
        self.config = config or SolveConfig()
        self.symbols: dict[str, Any] = {}
        self.enum_value_to_int: dict[str, dict[str, int]] = {}
        self.enum_int_to_value: dict[str, dict[int, str]] = {}
        self.variables = {item["id"]: item for item in ir.get("variables", []) if isinstance(item, dict)}
        self._bool_memo: dict[int, Any] = {}
        self._value_memo: dict[int, Any] = {}
        self._norm_memo: dict[int, Any] = {}
        #: Keeps memoised nodes alive so their ids cannot be reused.
        self._memo_keep: list[Any] = []
        #: Set while the base solver is being populated, so its assertions can
        #: be replayed onto a replacement; see `_replace_base_solver`.
        self._recording: list[tuple[Any, str]] | None = None
        self._base_assertions: list[tuple[Any, str]] = []
        self._declare_symbols()
        self.base_solver, self.base_labels = self._build_base_solver()

    def _apply_limits(self, solver: Any) -> None:
        """Give the solver its budget for one query.

        Re-applied per query on purpose. Z3 counts resources on the context, not
        on the call, so a budget set once is a budget for the whole session: the
        first query to exhaust it leaves every later one raising `canceled`
        before it does any work. Those come back as `unknown`, which is safe but
        worthless -- the run looks like it solved thousands of queries when it
        stopped solving at the first hard one.
        """
        solver.set(timeout=self.config.timeout_ms)
        if self.config.rlimit > 0:
            solver.set(rlimit=self.config.rlimit)

    @contextmanager
    def _watchdog(self, solver: Any):
        """Interrupt the solver's context if it outstays the hard timeout."""
        ms = self.config.hard_timeout_ms
        if ms <= 0:
            yield
            return
        timer = threading.Timer(ms / 1000.0, solver.ctx.interrupt)
        timer.daemon = True
        timer.start()
        try:
            yield
        finally:
            timer.cancel()

    def solve_expr(self, expr: dict[str, Any], *, label: str = "expr", obligation_id: Any = "") -> dict[str, Any]:
        return self.solve_terms([(expr, label)], obligation_id=obligation_id)

    def solve_terms(
        self,
        terms: list[tuple[dict[str, Any], str]],
        *,
        obligation_id: Any = "",
    ) -> dict[str, Any]:
        """Ask whether several labelled conditions can hold together.

        One `And` of the same conditions answers the same question, but its
        unsat core cannot: the whole conjunction is one assertion, so a core
        can only report that it took part. Named separately, the core says
        which of them the contradiction needed — and that is what makes the
        answer reusable for every other query containing those few.
        """
        try:
            return self._solve_once(self.base_solver, terms, obligation_id)
        except Exception:  # noqa: BLE001 - the solver, not the query, is at fault
            # Anything z3 raises here is about the solver's state rather than
            # this expression: a budget it already spent, an interrupt it is
            # still holding. A replacement gets an honest answer for this query
            # and for every one after it.
            pass
        solver = self._replace_base_solver()
        try:
            return self._solve_once(solver, terms, obligation_id)
        except Exception as exc:  # noqa: BLE001 - report, do not take the run down
            return {
                "obligation_id": obligation_id,
                "status": "error",
                "model": {},
                "unsat_core": [],
                "reason": f"{type(exc).__name__}: {exc}",
            }

    def _solve_once(
        self,
        solver: Any,
        terms: list[tuple[dict[str, Any], str]],
        obligation_id: Any,
    ) -> dict[str, Any]:
        solver.push()
        self._apply_limits(solver)
        labels: dict[str, str] = dict(self.base_labels)
        expr = terms[0][0] if len(terms) == 1 else {
            "op": "and",
            "args": [t for t, _ in terms],
        }
        try:
            with _deep_recursion():
                for term, label in terms:
                    self._assert_tracked(
                        solver, self._compile_bool(term), label, labels
                    )
            with self._watchdog(solver):
                check = solver.check()
            if check == self.z3.sat:
                model = solver.model()
                abstract = self.abstract_model(model)
                abstract = self._generalize_away_all_ones(solver, labels, expr, abstract)
                return {
                    "obligation_id": obligation_id,
                    "status": "sat",
                    "model": abstract,
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
            try:
                solver.pop()
            except Exception:  # noqa: BLE001 - a wedged solver is being replaced anyway
                pass

    def prove_implies(self, antecedent: Any, consequent: Any) -> dict[str, Any]:
        """Is `antecedent -> consequent` valid under the base constraints?

        Returns `status` in {proved, refuted, unknown, error}; a refutation
        carries the counterexample model so the caller can show why.
        """
        with _deep_recursion():
            negation = self.z3.And(
                self._compile_bool(antecedent), self.z3.Not(self._compile_bool(consequent))
            )
        return self._prove(negation)

    def prove_equivalent(self, lhs: Any, rhs: Any) -> dict[str, Any]:
        """Is `lhs <-> rhs` valid under the base constraints?"""
        try:
            with _deep_recursion():
                negation = self.z3.Not(self._compile_bool(lhs) == self._compile_bool(rhs))
        except (ConstraintIRError, Z3BackendError, TypeError, ValueError) as exc:
            return {"status": "error", "model": {}, "reason": str(exc)}
        return self._prove(negation)

    def _prove(self, negation: Any) -> dict[str, Any]:
        solver = self.base_solver
        solver.push()
        try:
            solver.add(negation)
            with self._watchdog(solver):
                check = solver.check()
            if check == self.z3.unsat:
                return {"status": "proved", "model": {}, "reason": ""}
            if check == self.z3.sat:
                return {"status": "refuted", "model": self.abstract_model(solver.model()), "reason": "counterexample"}
            return {"status": "unknown", "model": {}, "reason": solver.reason_unknown() or "unknown"}
        except (ConstraintIRError, Z3BackendError, TypeError, ValueError) as exc:
            return {"status": "error", "model": {}, "reason": str(exc)}
        finally:
            solver.pop()

    def _build_base_solver(self) -> tuple[Any, dict[str, str]]:
        solver = self.z3.Solver()
        self._apply_limits(solver)
        labels: dict[str, str] = {}
        self._recording = []
        try:
            with _deep_recursion():
                self._add_base_domains(solver, labels)
                self._add_derived_constraints(solver, labels)
                self._add_contract_constraints(solver, labels)
        finally:
            self._base_assertions = self._recording
            self._recording = None
        return solver, labels

    def _replace_base_solver(self) -> Any:
        """Start the base solver over from the assertions it was built from.

        A query that exhausts its budget can leave the solver refusing to do any
        further work: every later query comes straight back `canceled` in a few
        milliseconds. That reads as thousands of solved-but-unknown queries when
        really only the first few were ever attempted. Rebuilding costs the
        preprocessing again but keeps each verdict honestly its own.

        Only the z3 solver object is rebuilt -- the compiled expressions are
        reused, so this does not repeat the expensive part.
        """
        solver = self.z3.Solver()
        self._apply_limits(solver)
        labels: dict[str, str] = {}
        for expr, label in self._base_assertions:
            self._assert_tracked(solver, expr, label, labels)
        self.base_solver, self.base_labels = solver, labels
        return solver

    def model_satisfies(self, model: dict[str, Any], expr: dict[str, Any]) -> bool:
        fast = self.fast_model_satisfies(model, expr)
        if fast is not None:
            return fast
        z3 = self.z3
        solver = z3.Solver()
        self._apply_limits(solver)
        labels: dict[str, str] = {}
        try:
            self._add_base_domains(solver, labels)
            self._add_derived_constraints(solver, labels)
            self._add_contract_constraints(solver, labels)
            for var_id, value in sorted(model.items()):
                if var_id in self.variables and not self.variables[var_id].get("derived"):
                    solver.add(self.symbols[var_id] == self._value(var_id, value))
            solver.add(self._compile_bool(expr))
            with self._watchdog(solver):
                return solver.check() == z3.sat
        except (ConstraintIRError, Z3BackendError, TypeError, ValueError):
            return False

    def fast_model_satisfies(self, model: dict[str, Any], expr: dict[str, Any]) -> bool | None:
        try:
            return bool(self._eval_bool_from_model(model, expr))
        except (KeyError, TypeError, ValueError, ConstraintIRError, Z3BackendError, ZeroDivisionError):
            return None

    def _eval_bool_from_model(self, model: dict[str, Any], expr: Any) -> bool:
        expr = normalize_expr(expr, self._norm_memo)
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
        expr = normalize_expr(expr, self._norm_memo)
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
            if spec.get("derived") and not self._is_exposed_derived(var_id):
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

    def _is_exposed_derived(self, var_id: str) -> bool:
        return bool(self.exposed_derived_prefixes) and var_id.startswith(self.exposed_derived_prefixes)

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
            expr = normalize_expr(definition, self._norm_memo)
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
        return self._memoised(expr, self._bool_memo, self._compile_bool_uncached)

    def _memoised(self, expr: Any, memo: dict, build: Any) -> Any:
        """Compile `expr` once per distinct node.

        The expression is a DAG -- a guard reached along several paths is one
        shared node, not a copy. Recursing without remembering turns it back
        into a tree, and for the widest dimensions that tree has more nodes
        than there are atoms in anything: they never finish compiling, and
        exhaust memory on the way. Sharing is what keeps them at five figures.

        Keyed on identity, which is sound only while the nodes stay alive: the
        IR holds them, and `_memo_keep` holds anything normalisation created,
        so no id can be recycled underneath the table. Bool and value contexts
        get separate tables because the same node compiles to different sorts
        in each.
        """
        if not isinstance(expr, (dict, list)):
            return build(expr)
        key = id(expr)
        hit = memo.get(key)
        if hit is not None:
            return hit
        out = build(expr)
        memo[key] = out
        self._memo_keep.append(expr)
        return out

    def _compile_bool_uncached(self, expr: Any) -> Any:
        z3 = self.z3
        expr = normalize_expr(expr, self._norm_memo)
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
        return self._memoised(expr, self._value_memo, self._compile_value_uncached)

    def _compile_value_uncached(self, expr: Any) -> Any:
        z3 = self.z3
        if isinstance(expr, bool):
            return z3.BoolVal(expr)
        if isinstance(expr, int):
            return z3.IntVal(expr)
        if isinstance(expr, dict) and "var" in expr and "op" not in expr:
            return self._symbol(str(expr["var"]))
        expr = normalize_expr(expr, self._norm_memo)
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
            cond_z3 = self._compile_bool(expr["condition"])
            t_val = expr.get("then")
            e_val = expr.get("else")
            t_z3 = self._coerce_branch(t_val)
            e_z3 = self._coerce_branch(e_val)
            return z3.If(cond_z3, t_z3, e_z3)
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

    def _coerce_branch(self, value: Any) -> Any:
        if isinstance(value, dict):
            return self._compile_value(value)
        if isinstance(value, bool):
            return self.z3.BoolVal(value)
        if isinstance(value, int):
            return self.z3.IntVal(value)
        if isinstance(value, str):
            for var_id, mapping in self.enum_value_to_int.items():
                if str(value) in mapping:
                    return self.z3.IntVal(mapping[str(value)])
            try:
                return self.z3.IntVal(int(value))
            except ValueError:
                return value
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
            try:
                return parse_bool_literal(value)
            except ConstraintIRError as exc:
                # Naming the variable is the difference between a report that
                # points at the declaration to fix and one that says only that
                # some literal somewhere was not a boolean.
                raise Z3BackendError(f"{exc} (comparing {var_id})") from exc
        return int(value)

    def _assert_tracked(self, solver: Any, expr: Any, label: str, labels: dict[str, str]) -> None:
        base = "LBL_" + "".join(ch if ch.isalnum() else "_" for ch in label)
        # Two assertions sharing a marker is not two assertions: the second
        # replaces the first in the core, and the query silently loses a term.
        safe = base
        seq = 1
        while safe in labels:
            seq += 1
            safe = f"{base}__{seq}"
        marker = self.z3.Bool(safe)
        labels[safe] = label
        if self._recording is not None:
            self._recording.append((expr, label))
        solver.assert_and_track(expr, marker)

    def _generalize_away_all_ones(
        self,
        solver: Any,
        labels: dict[str, str],
        expr: dict[str, Any],
        abstract: dict[str, Any],
    ) -> dict[str, Any]:
        """If many free shape/csv ints are 1, try one more SAT model that breaks the all-1 cube."""
        del expr  # target already on solver stack from solve_expr
        if not self.generalize_prefixes and not self.generalize_suffixes:
            return abstract
        shape_like = [
            key
            for key, value in abstract.items()
            if isinstance(value, int)
            and value == 1
            and (
                (self.generalize_prefixes and key.startswith(self.generalize_prefixes))
                or (self.generalize_suffixes and key.endswith(self.generalize_suffixes))
            )
            and key in self.variables
            and not self.variables[key].get("derived")
        ]
        if len(shape_like) < 2:
            return abstract
        solver.push()
        try:
            ors = [self.symbols[var] > 1 for var in shape_like if var in self.symbols]
            if not ors:
                return abstract
            self._assert_tracked(solver, self.z3.Or(ors), "generalize:not_all_ones", labels)
            with self._watchdog(solver):
                verdict = solver.check()
            if verdict == self.z3.sat:
                return self.abstract_model(solver.model())
        except (ConstraintIRError, Z3BackendError, TypeError, ValueError):
            return abstract
        finally:
            solver.pop()
        return abstract
