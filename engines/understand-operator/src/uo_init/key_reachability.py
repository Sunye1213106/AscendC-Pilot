"""Which TilingKey combinations the host can actually produce.

The template's Cartesian product says which keys are *spellable*. It says
nothing about which ones a host run can reach: the 19 dimensions are computed
from shared roots, so most combinations are contradictions. This module puts
all 19 `value_expr` trees into one solver context and asks, per key, whether
those roots can be assigned so that every dimension lands on its target.

The classification is deliberately one-sided, because our expressions are
over-approximations. Where a guard could not be resolved, `derive_key_fields`
replaced it with a free variable, which makes the expression's feasible set a
*superset* of the real one. So:

- UNSAT is trustworthy. No assignment satisfies the dimensions even with the
  softened guards free to move, so no real host run can either — `unreachable`.
- SAT is not. The witness may live in the slack we introduced, so the honest
  answer is `unknown` unless every dimension involved was `exact`/`constant`
  and driven by controllable inputs, in which case it is `reachable`.

Two things are therefore never allowed to happen quietly, both of which the
old hand-written invariants in `materialize_tiling` did:

1. Calling a key reachable without a solver ever running. Absent a derivation
   every key is `underivable`, which downstream reads as "no information",
   not as "fine".
2. Letting an expression we could not compile silently drop out of the
   conjunction. A dropped dimension only removes constraints, so it can only
   turn a real UNSAT into a SAT — but it also means the SAT covers fewer
   dimensions than the caller thinks. Omitted dimensions are recorded per key
   (`participating`) and force the SAT verdict down to `unknown`.

On symbolic constants: a dimension is omitted rather than compiled when any
constant in its tree cannot be folded to a number from `named_constants`. The
shared backend would accept the bare string and coerce it by scanning *other*
variables' enum encodings, which can silently give two unrelated symbols the
same integer. That is exactly the failure mode that would fabricate an UNSAT,
so unfoldable symbols are treated as "cannot compile this dimension".
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .predicate import VALUE_KIND_STRING

__all__ = [
    "R_REACHABLE",
    "R_UNREACHABLE",
    "R_UNKNOWN",
    "R_UNDERIVABLE",
    "LAYER_SOLVER",
    "LAYER_NONE",
    "LAYER_TEMPLATE",
    "DIM_PREFIX",
    "KeyVerdict",
    "KeyReachability",
]

#: Label a query puts on "this dimension takes this value", so that an unsat
#: core can name the values that clashed rather than the definitions the proof
#: happened to walk through.
_ASKED = "asked:"

R_REACHABLE = "reachable"
R_UNREACHABLE = "unreachable"
R_UNKNOWN = "unknown"
R_UNDERIVABLE = "underivable"

LAYER_SOLVER = "host_solver"
LAYER_NONE = "no_derivation"
#: Decided before the solver was reached — the template cannot spell this key,
#: or nothing bound it to an encode site.
LAYER_TEMPLATE = "template"

#: A boolean literal cannot stand alone where the IR expects a proposition, so
#: it is spelled as a comparison against a variable pinned to true.
TRUE_VAR = "UO_CONST_TRUE"
NULL_SUFFIX = "__IS_NULL"
DIM_PREFIX = "VAR_KEYDIM_"

_BOOL_OPS = frozenset(
    {
        "eq",
        "ne",
        "lt",
        "le",
        "gt",
        "ge",
        "in",
        "not_in",
        "and",
        "or",
        "not",
        "implies",
        "requires",
        "mutex",
        "aligned",
    }
)

#: Ops whose operands must each be a proposition rather than a value.
_CONNECTIVES = frozenset({"and", "or", "not", "implies", "requires", "mutex"})

#: Tiling arithmetic is full of division and remainder, so the compiled system
#: is nonlinear integer arithmetic -- undecidable, and in practice a solver that
#: does not come back. A bounded budget turns that into an honest `unknown`,
#: which the caller already handles; without one, a single key takes the run
#: down. `rlimit` counts solver steps, so a verdict does not change with the
#: machine it ran on; the wall clock is only there to catch what rlimit misses.
DEFAULT_RLIMIT = 2_000_000
DEFAULT_HARD_TIMEOUT_MS = 20_000

#: Keys under which a string is a name rather than a value, so it must not be
#: folded to a number.
_NAME_KEYS = frozenset({"var", "op", "id", "kind", "reason", "value_kind"})

#: Variables whose id stands for several distinct values — see
#: `VarSpec.identity_merged`. `VAR_SHAPE_GETSTORAGESHAPE` covers *every*
#: `GetStorageShape()...GetDim(i)` in the operator, so one dimension uses it as
#: the D axis while another uses it as "some axis is 0". Within a single
#: dimension that merge is a harmless over-approximation; across dimensions it
#: is an equality nobody proved, and equalities invent contradictions — so these
#: are renamed per dimension before the trees meet.
#: Separates a variable from the dimension it was isolated into.
ISOLATE_MARK = "@"

#: Marks the symbol-comparison half of a merged variable — see `_Domains`.
SYMBOL_MARK = "#sym"

#: Stands in for a name the guard reader left unexpanded -- a loop induction
#: variable, a tiling intermediate, a reduction. Dropping the dimension instead
#: was the conservative reading of "we do not know this value", but it is the
#: expensive one: the dimension stops constraining anything at all. An
#: unconstrained variable says the same thing and keeps the rest of the tree,
#: because a free variable admits every value the real one could take.
#:
#: Isolated per dimension by `_Isolator`. Sharing one across dimensions would
#: assert an equality nobody proved, and equalities are what invent UNSAT.
LOCAL_PREFIX = "VAR_LOCAL_"

_NOT_IDENT = re.compile(r"[^0-9A-Za-z_]+")

_GETTER_MARK = re.compile(r"_GET[A-Z]")


class _Unadaptable(Exception):
    """A tree we refuse to compile, with the reason to report."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _is_bool_expr(node: Any) -> bool:
    """Does this subtree denote a proposition rather than a number?"""
    if isinstance(node, bool):
        return True
    if not isinstance(node, dict):
        return False
    op = node.get("op")
    if op in _BOOL_OPS:
        return True
    if op == "lit":
        return isinstance(node.get("value"), bool)
    if op == "if_then_else":
        return _is_bool_expr(node.get("then")) or _is_bool_expr(node.get("else"))
    return False


@dataclass(frozen=True)
class KeyVerdict:
    """One key's answer, with enough evidence to check it by hand."""

    status: str
    reason: str = ""
    layer: str = LAYER_SOLVER
    #: Root assignment that produces this key. Only set for SAT results; the
    #: values are an existence proof, not a recommended test input, since we
    #: assert no domain bounds on the roots.
    witness: dict[str, Any] = field(default_factory=dict)
    #: Labels of the base assertions Z3 needed for the contradiction. Reads as
    #: `derived:VAR_KEYDIM_<dim>`, i.e. which dimensions disagree.
    unsat_core: tuple[str, ...] = ()
    #: Dimensions that entered the conjunction. Anything missing was omitted
    #: (uncompilable) or absent from the key.
    participating: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status, "layer": self.layer}
        if self.reason:
            out["reason"] = self.reason
        if self.witness:
            out["witness"] = dict(self.witness)
        if self.unsat_core:
            out["unsat_core"] = list(self.unsat_core)
        if self.participating:
            out["participating"] = list(self.participating)
        return out


class KeyReachability:
    """A solver context holding every dimension's expression at once.

    Build it once per operator; `verdict` is then a `push`/`pop` on the shared
    solver, so the 19 trees are compiled a single time rather than per key.
    """

    def __init__(
        self,
        *,
        backend: Any | None,
        dims: Mapping[str, dict[str, Any]],
        omitted: Mapping[str, str],
        total_dims: int,
        layer: str = LAYER_SOLVER,
        unavailable: str = "",
        isolated: Iterable[str] = (),
        shared: Iterable[str] = (),
        blockers: Mapping[str, Mapping[str, str]] | None = None,
    ) -> None:
        self._backend = backend
        self._dims = dict(dims)
        self._omitted = dict(omitted)
        self._total = total_dims
        self._layer = layer
        self._unavailable = unavailable
        self._isolated = sorted(isolated)
        self._shared = sorted(shared)
        self._blockers = {k: dict(v) for k, v in (blockers or {}).items()}
        self._groups = _independent_groups(self._dims)
        #: One entry per distinct combination a group takes, not per key.
        self._group_cache: dict[tuple[tuple[str, Any], ...], dict[str, Any]] = {}
        #: Minimal contradictions already proved, as dimension names -> the
        #: value tuples that clash. UNSAT is monotone: if these few dimensions
        #: cannot hold together, no assignment containing them can, whatever
        #: the other dimensions do. Once the trees share real input variables a
        #: group spans most of the key, so its combinations rarely repeat and
        #: the cache above stops paying; the contradiction underneath is much
        #: smaller and repeats constantly.
        self._conflicts: dict[tuple[str, ...], set[tuple[Any, ...]]] = {}

    # -- construction ------------------------------------------------------
    @classmethod
    def unavailable(cls, reason: str) -> KeyReachability:
        """A context that answers `underivable` for everything.

        Used when there is no host derivation, or no solver. The point is that
        the caller cannot accidentally get a `reachable` out of it.
        """
        return cls(
            backend=None,
            dims={},
            omitted={},
            total_dims=0,
            layer=LAYER_NONE,
            unavailable=reason or "no derivation",
        )

    @classmethod
    def from_derivation(
        cls,
        derivation: Any,
        var_model: Any,
        *,
        timeout_ms: int = 5000,
        rlimit: int = DEFAULT_RLIMIT,
        hard_timeout_ms: int = DEFAULT_HARD_TIMEOUT_MS,
        only: Iterable[str] | None = None,
    ) -> KeyReachability:
        """Compile every dimension we soundly can into one solver context.

        `only` restricts which dimensions get compiled. Handing the solver a
        formula it will never be asked about still costs the whole compile, and
        the big dimensions cost minutes between them, so a question about three
        of them should not pay for nineteen. Every tree is still *read* first --
        symbol folding groups constants per variable across all of them, and
        reading fewer would regroup them and could change a verdict.

        Leaving a dimension out only removes constraints, which widens the
        feasible set: a UNSAT that survives is still a UNSAT, and a SAT was
        never trusted on its own. Anything omitted this way is reported through
        `omitted` so a caller cannot mistake it for a compiled one.
        """
        fields = list(getattr(derivation, "fields", None) or [])
        if not fields:
            return cls.unavailable("derivation has no fields")
        wanted = None if only is None else set(only)

        symbols = _Symbols(_named_constants(var_model))
        variables: list[dict[str, Any]] = [{"id": TRUE_VAR, "type": "bool"}]
        constraints: list[dict[str, Any]] = [
            {"id": "const_true", "expr": {"op": "eq", "var": TRUE_VAR, "value": True}}
        ]
        dims: dict[str, dict[str, Any]] = {}
        omitted: dict[str, str] = {}
        isolated: set[str] = set()
        shared: set[str] = set()

        # First pass: read every tree, so each variable's symbol group is whole
        # before any of them is given numbers.
        domains = _Domains()
        trees: list[tuple[str, Any, Any, _Isolator]] = []
        for fld in fields:
            name = str(getattr(fld, "name", "") or "")
            if not name:
                continue
            tree = getattr(fld, "value_expr", None)
            if tree is None:
                omitted[name] = "no_expression"
                continue
            rename = _Isolator(name, var_model, {})
            domains.read(tree, rename)
            trees.append((name, fld, tree, rename))
        domains.resolve(symbols)

        blockers: dict[str, dict[str, str]] = {}
        for name, fld, tree, rename in trees:
            if wanted is not None and name not in wanted:
                omitted[name] = "not_requested"
                continue
            rewrite = _Rewrite(symbols, rename, domains)
            try:
                adapted = rewrite.run(tree)
            except _Unadaptable as exc:
                omitted[name] = f"{exc.code}({exc.detail})" if exc.detail else exc.code
                survey = _Rewrite(symbols, rename, domains, survey=True)
                try:
                    survey.run(tree)
                except _Unadaptable:  # pragma: no cover - survey should not raise
                    pass
                blockers[name] = dict(survey.blocked)
                continue
            decls = []
            support: set[str] = set()
            for var_id in sorted(_collect_vars(adapted)):
                if var_id == TRUE_VAR:
                    continue
                support.add(var_id)
                decls.append(
                    _declare(var_id, rename.origin_of(var_id), rewrite.nulls)
                )
            isolated.update(rename.isolated)
            shared.update(rename.shared)
            dim_var = DIM_PREFIX + name
            is_bool = _is_bool_expr(adapted)
            variables.extend(decls)
            variables.append(
                {
                    "id": dim_var,
                    "type": "bool" if is_bool else "int",
                    "derived": True,
                    "definition": adapted,
                }
            )
            dims[name] = {
                "var": dim_var,
                "bool": is_bool,
                # A dimension standing on a free variable cannot be exact,
                # whatever the derivation said: the variable admits values the
                # host never produces, so only its `unknown` answers mean
                # anything. Grading it exact would let a SAT result be read as
                # `reachable`.
                "exact": bool(getattr(fld, "input_derivable", False))
                and not rewrite.minted,
                "assumed": sorted(rewrite.assumed),
                "minted": sorted(rewrite.minted),
                "support": frozenset(support),
            }

        variables = _dedupe(variables)
        if not dims:
            return cls.unavailable("no dimension could be compiled")
        try:
            from acp_common.z3_backend import SolveConfig, Z3Backend

            backend = Z3Backend(
                {"variables": variables, "constraints": constraints},
                SolveConfig(
                    timeout_ms=timeout_ms,
                    rlimit=rlimit,
                    hard_timeout_ms=hard_timeout_ms,
                ),
            )
            # Show the dimension values in a witness. They are derived, so the
            # backend hides them by default, but they are the part a reader
            # checks first: the witness must reproduce the key it explains.
            backend.exposed_derived_prefixes = (DIM_PREFIX,)
        except Exception as exc:  # noqa: BLE001 - any backend failure is fatal here
            return cls.unavailable(f"solver unavailable: {type(exc).__name__}: {exc}")
        return cls(
            backend=backend,
            dims=dims,
            omitted=omitted,
            total_dims=len(fields),
            layer=LAYER_SOLVER,
            isolated=isolated,
            shared=shared,
            blockers=blockers,
        )

    # -- query -------------------------------------------------------------
    @property
    def omitted(self) -> dict[str, str]:
        """Dimension name -> why its expression is not in the conjunction."""
        return dict(self._omitted)

    @property
    def blockers(self) -> dict[str, dict[str, str]]:
        """Dropped dimension -> every symbol it trips over, not just the first.

        `omitted` names where the rewrite stopped, which is whichever blocker
        the tree happened to reach first. This is the set that has to be closed
        before the dimension compiles.
        """
        return {k: dict(v) for k, v in self._blockers.items()}

    @property
    def available(self) -> bool:
        return self._backend is not None

    def summary(self) -> dict[str, Any]:
        return {
            "layer": self._layer,
            "dimensions_total": self._total,
            "dimensions_compiled": len(self._dims),
            "dimensions_exact": sum(1 for d in self._dims.values() if d["exact"]),
            "omitted": dict(self._omitted),
            # Every symbol a dropped dimension trips over. `omitted` names only
            # the first, which understates what closing the dimension takes.
            "blockers": {k: dict(v) for k, v in self._blockers.items()},
            # Dimension -> names standing in as free variables. These compile,
            # but only their `unreachable` answers carry weight.
            "softened": {
                name: list(d["minted"])
                for name, d in sorted(self._dims.items())
                if d.get("minted")
            },
            "blockers": {k: dict(v) for k, v in self._blockers.items()},
            # Variables the guard reader named after a getter. They are isolated
            # per dimension, so they carry no cross-dimension information; the
            # count is how much conflict detection we are giving up.
            #: Dimensions that share no free variable can be solved apart; see
            #: `_independent_groups`. Large groups are what make a run slow.
            "groups": [list(g) for g in self._groups],
            "identity_isolated": list(self._isolated),
            #: Variables that do link dimensions together. If this is empty the
            #: solver can only rule out values dimension by dimension.
            "identity_shared": list(self._shared),
            #: Symbols we gave invented values so their dimension could be
            #: solved. A contradiction that needs one of them is downgraded to
            #: `unknown`; see `_Symbols`.
            "assumed_distinct": sorted(
                {s for d in self._dims.values() for s in d["assumed"]}
            ),
            "unavailable": self._unavailable,
        }

    def verdict(self, key_dims: Mapping[str, Any]) -> KeyVerdict:
        """Classify one key, given its dimension values from the template."""
        return self._answer(key_dims, subset=False)

    def joint_verdict(self, asked: Mapping[str, Any]) -> KeyVerdict:
        """Whether these few dimensions can hold together, others left free.

        `verdict` answers about a whole key, so a dimension it cannot see is a
        gap that keeps a SAT from being read as `reachable`. Here the unnamed
        dimensions are deliberately unconstrained -- the question is only
        whether this combination is self-contradictory -- so their absence is
        not a caveat. Everything else is the same, including the refusal to
        call a contradiction `unreachable` when it leans on invented symbols.

        Asking two dimensions at a time is what turns the derivation into
        rules: an `unreachable` here says the pair excludes each other, whatever
        the rest of the key does.
        """
        return self._answer(asked, subset=True)

    def _answer(self, key_dims: Mapping[str, Any], *, subset: bool) -> KeyVerdict:
        if self._backend is None:
            return KeyVerdict(
                status=R_UNDERIVABLE, reason=self._unavailable, layer=LAYER_NONE
            )

        taking: list[str] = []
        unfolded: list[str] = []
        asked: dict[str, Any] = {}
        for name, target in sorted(key_dims.items()):
            spec = self._dims.get(name)
            if spec is None:
                continue
            value = _target_value(target)
            if value is None:
                unfolded.append(name)
                continue
            if spec["bool"] and value not in (0, 1, True, False):
                # A boolean dimension asked for a third value. That needs no
                # solver: the expression cannot produce it.
                return KeyVerdict(
                    status=R_UNREACHABLE,
                    reason=f"{name}={target} is outside a boolean dimension",
                    layer=self._layer,
                    participating=(name,),
                )
            taking.append(name)
            asked[name] = value

        if not asked:
            return KeyVerdict(
                status=R_UNDERIVABLE,
                reason="no dimension of this key has a compiled expression",
                layer=self._layer,
            )

        try:
            if subset:
                # One conjunction over exactly what was asked. The group split
                # is an optimisation for whole keys, where a group's values
                # repeat across thousands of them; a two-dimension question
                # would only be split into halves that answer nothing.
                result = self._solve_group(tuple(sorted(asked.items())))
            else:
                result = self._solve_by_group(asked)
        except Exception as exc:  # noqa: BLE001 - report, never crash the export
            return KeyVerdict(
                status=R_UNKNOWN,
                reason=f"solver error: {type(exc).__name__}: {exc}",
                layer=self._layer,
                participating=tuple(taking),
            )

        status = str(result.get("status") or "unknown")
        if status == "unsat":
            core = tuple(str(x) for x in result.get("unsat_core") or ())
            guessed = self._assumed_in(core, taking)
            if guessed:
                # The contradiction rests on symbols whose values we invented.
                # Two of them could be spellings of the same value, in which
                # case the conflict is ours, not the operator's.
                return KeyVerdict(
                    status=R_UNKNOWN,
                    reason=(
                        "conflict depends on symbols we could not read: "
                        f"{sorted(guessed)[:4]}"
                    ),
                    layer=self._layer,
                    unsat_core=core,
                    participating=tuple(taking),
                )
            return KeyVerdict(
                status=R_UNREACHABLE,
                reason="dimensions cannot hold together in any host run",
                layer=self._layer,
                unsat_core=core,
                participating=tuple(taking),
            )
        if status != "sat":
            return KeyVerdict(
                status=R_UNKNOWN,
                reason=str(result.get("reason") or "solver gave up"),
                layer=self._layer,
                participating=tuple(taking),
            )

        seen = dict(asked) if subset else key_dims
        gaps = self._sat_caveats(taking, seen, unfolded)
        if gaps:
            return KeyVerdict(
                status=R_UNKNOWN,
                reason="; ".join(gaps),
                layer=self._layer,
                witness=dict(result.get("model") or {}),
                participating=tuple(taking),
            )
        return KeyVerdict(
            status=R_REACHABLE,
            layer=self._layer,
            witness=dict(result.get("model") or {}),
            participating=tuple(taking),
        )

    def _solve_by_group(self, asked: Mapping[str, Any]) -> dict[str, Any]:
        """Answer one key as a question per independent group of dimensions.

        The groups share no free variable (`_independent_groups`), so the key
        holds exactly when all of them do. Splitting is worth doing because the
        answer depends only on the values inside a group, and across the legal
        keys a group takes far fewer distinct combinations than there are keys
        -- so most of these are cache hits. A group that comes back unsat
        settles the key immediately; the rest need not be asked.
        """
        combined: dict[str, Any] = {"status": "sat", "model": {}, "unsat_core": [], "reason": ""}
        weakest = "sat"
        for group in self._groups:
            values = tuple((name, asked[name]) for name in group if name in asked)
            if not values:
                continue
            hit = self._group_cache.get(values)
            if hit is None:
                hit = self._replay_conflict(values)
                if hit is None:
                    hit = self._solve_group(values)
                    self._learn_conflict(values, hit)
                self._group_cache[values] = hit
            status = str(hit.get("status") or "unknown")
            if status == "unsat":
                return hit
            if status != "sat":
                # Keep looking: another group may still be unsat, which is a
                # firmer answer than this one's "gave up".
                weakest = status
                combined["reason"] = str(hit.get("reason") or "solver gave up")
                continue
            combined["model"].update(hit.get("model") or {})
        combined["status"] = weakest
        return combined

    def _replay_conflict(self, values: tuple[tuple[str, Any], ...]) -> dict[str, Any] | None:
        """An already-proved contradiction that this combination contains."""
        asked = dict(values)
        for names, combos in self._conflicts.items():
            if not all(n in asked for n in names):
                continue
            if tuple(asked[n] for n in names) in combos:
                return {
                    "status": "unsat",
                    "unsat_core": [f"{_ASKED}{n}" for n in names]
                    + [f"derived:{self._dims[n]['var']}" for n in names],
                    "model": {},
                    "reason": "",
                }
        return None

    def _learn_conflict(
        self, values: tuple[tuple[str, Any], ...], hit: dict[str, Any]
    ) -> None:
        """Keep the few dimensions Z3 actually blamed, not the whole group."""
        if str(hit.get("status") or "") != "unsat":
            return
        asked = dict(values)
        blamed = sorted(n for n in self._core_dims(hit.get("unsat_core") or ()) if n in asked)
        # No usable core: the whole combination is all we can claim.
        names = tuple(blamed) or tuple(sorted(asked))
        self._conflicts.setdefault(names, set()).add(tuple(asked[n] for n in names))

    def _core_dims(self, core: Iterable[str]) -> set[str]:
        """Dimensions an unsat core blames.

        `asked:<dim>` is the value this query put on a dimension, so a core
        containing it says that value was needed for the contradiction — the
        question actually being asked. `derived:<var>` is the dimension's
        definition, which the proof may use for reasons having nothing to do
        with the value asked for, so it is only read when nothing better is
        there.
        """
        core = [item for item in core if isinstance(item, str)]
        asked = {
            item.split(":", 1)[1] for item in core if item.startswith(_ASKED)
        }
        if asked:
            return {n for n in self._dims if n in asked}
        named = {
            item.split(":", 1)[1]
            for item in core
            if item.startswith("derived:") and ":" in item
        }
        return {n for n, spec in self._dims.items() if spec["var"] in named}

    def _solve_group(self, values: tuple[tuple[str, Any], ...]) -> dict[str, Any]:
        """Ask the group, naming each dimension's value separately.

        Named, the unsat core says which of these values the contradiction
        needed. Joined into one `And` it could only say "the key", and the
        blame had to be guessed from which *definitions* Z3 happened to use —
        which is not the same question and does not always give the same
        answer, so the same contradiction was re-proved for every key that
        contained it.
        """
        terms = [
            (
                {"op": "eq", "var": self._dims[name]["var"], "value": value},
                f"{_ASKED}{name}",
            )
            for name, value in values
        ]
        solve_terms = getattr(self._backend, "solve_terms", None)
        if solve_terms is None:
            args = [t for t, _ in terms]
            expr = args[0] if len(args) == 1 else {"op": "and", "args": args}
            return self._backend.solve_expr(expr, label="key")
        return solve_terms(terms)

    def _assumed_in(
        self, core: Iterable[str], taking: Iterable[str]
    ) -> set[str]:
        """Invented symbols behind the dimensions Z3 blamed.

        A core entry is either the value this query asked for (`asked:<dim>`)
        or a dimension's definition (`derived:<dim var>`); both say the
        contradiction leaned on that dimension, so both count. Every one it
        names is taken, unlike `_core_dims` which prefers the sharper of the
        two — here a dimension left out is one whose invented symbols go
        unnoticed, and that turns an `unknown` into a confident `unreachable`.
        If Z3 gives no usable core, every participating dimension counts.
        """
        core = [item for item in core if isinstance(item, str)]
        named = {
            item.split(":", 1)[1]
            for item in core
            if item.startswith("derived:") and ":" in item
        }
        asked = {item.split(":", 1)[1] for item in core if item.startswith(_ASKED)}
        blamed = [
            n for n in taking if self._dims[n]["var"] in named or n in asked
        ] or list(taking)
        out: set[str] = set()
        for name in blamed:
            out.update(self._dims[name]["assumed"])
        return out

    def _sat_caveats(
        self,
        taking: Iterable[str],
        key_dims: Mapping[str, Any],
        unfolded: Iterable[str],
    ) -> list[str]:
        """Why a SAT is only `unknown`. Empty means the SAT can be trusted."""
        taking = list(taking)
        out: list[str] = []
        missing = sorted(set(key_dims) - set(taking))
        if missing:
            out.append(f"{len(missing)} dimension(s) not constrained: {missing[:4]}")
        loose = sorted(n for n in taking if not self._dims[n]["exact"])
        if loose:
            out.append(
                f"{len(loose)} dimension(s) over-approximated or not input driven: {loose[:4]}"
            )
        stray = sorted(unfolded)
        if stray:
            out.append(f"{len(stray)} target value(s) unreadable: {stray[:4]}")
        return out


# -- adaptation ------------------------------------------------------------
def _named_constants(var_model: Any) -> dict[str, Any]:
    consts = getattr(var_model, "named_constants", None)
    return dict(consts) if isinstance(consts, Mapping) else {}


class _Symbols:
    """Numbers for the symbolic constants an expression compares against.

    Symbols are folded per group, where a group is the variable they are
    compared with, because only that variable's own comparisons give the
    numbers meaning. Two rules follow:

    - If every symbol in a group has a definition we read, those definitions
      are used. Aliases (two spellings, one value) survive.
    - Otherwise none of them are used: the group gets numbers of its own,
      distinct from each other and below anything the source can write.

    Never both. A group holding one read value and one invented value places
    them in different encodings, which is how `"BNSD"` — a layout string an
    attribute is compared against — ended up at the integer an unrelated
    `LayoutEnum` uses for that spelling, while `"SBH"` got an invented number.
    That mixture decides comparisons the source never made.

    Inventing numbers assumes distinct spellings are distinct values, which an
    enum with aliases can break, so groups that needed it are recorded and a
    contradiction involving one is reported as `unknown`.
    """

    #: Below anything a tiling key or a shape can hold, so an invented number
    #: can never collide with a real comparison.
    FIRST = -1_000_001

    def __init__(self, consts: Mapping[str, Any]) -> None:
        self._consts = consts
        self._invented: dict[str, int] = {}
        self._plans: dict[str, dict[str, Any]] = {}
        self._guessed: set[str] = set()
        #: Only ever counts up. Sizing the next number off `len(self._invented)`
        #: hands every symbol in a group the same number once a name repeats
        #: across groups, which makes values that must differ compare equal.
        self._minted = 0

    @property
    def invented(self) -> dict[str, int]:
        return dict(self._invented)

    def read(self, value: str) -> Any | None:
        """The definition of this symbol, if the source gave us one."""
        if value in self._consts:
            return self._consts[value]
        bare = value.rsplit("::", 1)[-1]
        if bare in self._consts:
            return self._consts[bare]
        try:
            return int(value, 0)
        except (TypeError, ValueError):
            return None

    def _invent(self, name: str) -> int:
        hit = self._invented.get(name)
        if hit is None:
            hit = self.FIRST - self._minted
            self._minted += 1
            self._invented[name] = hit
        return hit

    def plan(
        self, group: str, symbols: Iterable[str], quoted: Iterable[str] = ()
    ) -> None:
        """Decide the encoding for one group. Idempotent per group."""
        if group in self._plans:
            return
        names = sorted(set(symbols))
        if names and set(names) <= set(quoted):
            # Every symbol here was a quoted string. Two different string
            # literals are different strings -- that is the language, not an
            # assumption -- so numbering them apart is exact and a
            # contradiction between them is a real one.
            #
            # The constants table is deliberately not consulted. These
            # spellings collide with unrelated names in the source: `TND` is a
            # constexpr equal to 4 while `LayoutEnum::TND` is 3, and neither has
            # anything to do with the string `"TND"`. Reading a value here would
            # encode the string as whatever that other thing happens to be.
            self._plans[group] = {name: self._invent(name) for name in names}
            return
        read = {name: self.read(name) for name in names}
        if all(value is not None for value in read.values()):
            self._plans[group] = read
            return
        self._plans[group] = {name: self._invent(name) for name in names}
        self._guessed.add(group)

    def fold(self, group: str, value: str) -> tuple[Any, bool]:
        """(number, assumed). `assumed` marks a group we invented values for."""
        plan = self._plans.get(group)
        if plan is None or value not in plan:
            # A group planned without this symbol cannot absorb it now without
            # breaking the all-or-nothing rule above.
            raise _Unadaptable("symbol_outside_group", f"{value} in {group}")
        return plan[value], group in self._guessed


class _Domains:
    """Which symbols share a variable, across every dimension's tree.

    Read before any rewrite, because folding a symbol needs the whole group it
    belongs to, and the group is only complete once *all* the trees have been
    walked: a variable that survives isolation is one variable in every
    dimension, so its symbols must get one encoding for all of them.

    A variable compared against both symbols and plain numbers has no single
    encoding to offer. Where its id is a merge of several reads
    (`VAR_ATTR_GETATTRS` stands for every `GetAttrs()` in the operator) the two
    kinds of comparison are almost certainly different attributes, so they are
    split into separate variables — that drops an equality nobody proved, which
    only widens the feasible set. Where the id is genuinely one read, splitting
    would be unsound, so the symbols keep sharing it and the group falls back to
    the all-or-nothing rule in `_Symbols`.
    """

    def __init__(self) -> None:
        self._symbols: dict[str, set[str]] = {}
        self._numeric: set[str] = set()
        self._split: set[str] = set()
        #: Symbols the source quoted. Tracked per variable because the claim
        #: being made is about one comparison site, not about the spelling
        #: everywhere: the same word can be a quoted string in one place and a
        #: named constant in another.
        self._quoted: dict[str, set[str]] = {}
        #: Symbols sitting where a variable should be (`rhs: "m0Max"`). No
        #: comparison gives them a value, so each is its own group.
        self._loose: set[str] = set()

    def read(self, tree: Any, rename: _Isolator) -> None:
        self._walk(tree, rename, set())

    def resolve(self, symbols: _Symbols) -> None:
        """Fix the encodings, once every tree has been read."""
        for var, names in self._symbols.items():
            if names and var in self._numeric and ISOLATE_MARK in var:
                self._split.add(var)
        for var, names in self._symbols.items():
            symbols.plan(
                self.symbol_var(var), names, quoted=self._quoted.get(var, frozenset())
            )

    def symbol_var(self, var: str) -> str:
        """The variable a symbol comparison on `var` belongs to."""
        return var + SYMBOL_MARK if var in self._split else var

    def _walk(self, node: Any, rename: _Isolator, seen: set[int]) -> None:
        if isinstance(node, str):
            self._loose.add(node)
            return
        if isinstance(node, dict):
            if id(node) in seen:
                return
            seen.add(id(node))
            raw = node.get("var")
            var = rename(raw) if isinstance(raw, str) else ""
            for key, value in node.items():
                if key in _NAME_KEYS:
                    continue
                if key == "value" and var:
                    self._note(var, value, node.get("value_kind"))
                    continue
                self._walk(value, rename, seen)
        elif isinstance(node, list):
            if id(node) in seen:
                return
            seen.add(id(node))
            for item in node:
                self._walk(item, rename, seen)

    def _note(self, var: str, value: Any, kind: Any = None) -> None:
        if isinstance(value, str):
            self._symbols.setdefault(var, set()).add(value)
            if kind == VALUE_KIND_STRING:
                self._quoted.setdefault(var, set()).add(value)
        elif value is None:
            return  # a presence test; it becomes a boolean flag, not a number
        else:
            self._numeric.add(var)


class _Rewrite:
    """One dimension's tree, rewritten into the shared IR's shape.

    Memoised on node identity: `value_expr` is a DAG, and the shared
    sub-expressions are the whole reason it is one. Walking it as a tree makes
    the rewrite exponential.
    """

    def __init__(
        self,
        symbols: _Symbols,
        rename: _Isolator,
        domains: _Domains,
        *,
        survey: bool = False,
    ) -> None:
        self._symbols = symbols
        self._rename = rename
        self._domains = domains
        self._memo: dict[int, Any] = {}
        self._prop_memo: dict[int, Any] = {}
        #: Both memos key on `id`, so every node they key on has to outlive the
        #: rewrite; a freed node's address can be handed to a later one.
        self._keep: list[Any] = []
        self.nulls: set[str] = set()
        #: Symbols whose value we invented; see `_Symbols`.
        self.assumed: set[str] = set()
        #: Diagnostic pass: keep going past what we cannot compile and record it
        #: all, instead of stopping at the first. Which name a dimension trips
        #: over first is an artefact of tree order, so reporting only that one
        #: understates the work to model the dimension -- five dimensions here
        #: each blame a single symbol while in truth needing five or six.
        #: The tree this pass builds is nonsense and must be thrown away.
        self._survey = survey
        self.blocked: dict[str, str] = {}
        #: Names replaced by a free variable. The dimension still compiles, but
        #: it no longer says anything exact, so it must not be graded as such.
        self.minted: set[str] = set()

    def run(self, node: Any) -> Any:
        if isinstance(node, bool) or isinstance(node, int) or node is None:
            return node
        if isinstance(node, str):
            return self._loose(node)
        if isinstance(node, float):
            # The IR is integer/boolean only. A float bound (the varlen
            # invalid-S1 path has them) would have to be rounded, and rounding
            # a bound is not a sound softening in either direction.
            return self._give_up("float_literal", repr(node), 0)
        hit = self._memo.get(id(node))
        if hit is not None:
            return hit
        if isinstance(node, list):
            out: Any = [self.run(x) for x in node]
        elif isinstance(node, dict):
            out = self._dict(node)
        else:
            out = self._give_up("unsupported_node", type(node).__name__, 0)
        self._memo[id(node)] = out
        return out

    def _fold(self, group: str, value: str) -> Any:
        folded, assumed = self._symbols.fold(group, value)
        if assumed:
            self.assumed.add(value)
        return folded

    def _loose(self, name: str) -> Any:
        """A bare symbol standing on its own, with no variable to compare with.

        A constant folds. Anything else is a variable the guard reader did not
        model -- `m0Max`, a loop's `i` -- and it must not be stood in as a
        number: pick one far below the real range and `x < m0Max` becomes
        false, which is the direction that invents contradictions. A free
        variable has neither problem, since it admits every value the real one
        could take, so the rest of the dimension survives.
        """
        known = self._symbols.read(name)
        if known is not None:
            return known
        var_id = LOCAL_PREFIX + _NOT_IDENT.sub("_", name).strip("_")
        renamed = self._rename(var_id)
        self.minted.add(name)
        return {"var": renamed}

    def _give_up(self, code: str, detail: str, stand_in: Any) -> Any:
        """Refuse the tree, or -- when surveying -- note it and carry on."""
        if not self._survey:
            raise _Unadaptable(code, detail)
        self.blocked[detail or code] = code
        return stand_in

    def _dict(self, node: dict[str, Any]) -> Any:
        if set(node) == {"lit"}:
            node = {"op": "lit", "value": node["lit"]}
        if "$ref" in node:
            # A reference the derivation did not resolve. Folding the target's
            # name as if it were a symbol would silently compare against a
            # number that means nothing.
            return self._give_up("unresolved_ref", str(node.get("$ref")), 0)

        var = node.get("var")
        if isinstance(var, str):
            var = self._rename(var)
            if isinstance(node.get("value"), str):
                var = self._domains.symbol_var(var)
        op = node.get("op")

        # `x == null` is a presence test, not an arithmetic one. It becomes a
        # boolean flag so the solver can still relate several tests on the same
        # pointer to each other.
        if (
            op in ("eq", "ne")
            and isinstance(var, str)
            and "value" in node
            and node["value"] is None
        ):
            flag = f"{var}{NULL_SUFFIX}"
            self.nulls.add(flag)
            return {"op": "eq", "var": flag, "value": op == "eq"}

        if op == "lit" and isinstance(node.get("value"), bool):
            return {"op": "eq", "var": TRUE_VAR, "value": bool(node["value"])}

        # `_compile_bool` reads `if_then_else` as a value, so a
        # proposition-shaped one has to be spelled with connectives instead.
        if op == "if_then_else" and _is_bool_expr(node):
            cond = self.run(node.get("condition"))
            return {
                "op": "or",
                "args": [
                    {
                        "op": "and",
                        "args": [cond, _as_prop(self.run(node.get("then")), self._prop_memo)],
                    },
                    {
                        "op": "and",
                        "args": [
                            {"op": "not", "arg": cond},
                            _as_prop(self.run(node.get("else")), self._prop_memo),
                        ],
                    },
                ],
            }

        out: dict[str, Any] = {}
        for key, value in node.items():
            if key == "value_kind":
                # Said where the value was written, which mattered when the
                # encoding was chosen. The number is now fixed and the solver
                # has no use for the provenance.
                continue
            if key == "var" and isinstance(var, str):
                out[key] = var
            elif key in _NAME_KEYS:
                out[key] = value
            elif key == "value" and isinstance(value, str) and isinstance(var, str):
                out[key] = self._fold(var, value)
            else:
                out[key] = self.run(value)

        if op in _CONNECTIVES:
            if isinstance(out.get("args"), list):
                self._keep.extend(out["args"])
                out["args"] = [_as_prop(arg, self._prop_memo) for arg in out["args"]]
            if "arg" in out:
                self._keep.append(out["arg"])
                out["arg"] = _as_prop(out["arg"], self._prop_memo)
        return out


def _independent_groups(dims: Mapping[str, Mapping[str, Any]]) -> list[tuple[str, ...]]:
    """Split the dimensions into sets that share no free variable.

    A key asks about all dimensions at once, but if two sets of them are written
    over disjoint variables the question splits exactly: a solution to each can
    be read off separately and laid side by side, because neither constrains
    anything the other mentions. So all groups satisfiable means the key is
    satisfiable, and any group unsatisfiable means the key is not -- both
    directions, no approximation.

    That is worth a great deal here. Dimensions do not vary freely across the
    legal keys, so a group takes far fewer distinct combinations than there are
    keys, and each combination need only be asked once.

    `TRUE_VAR` is left out: it is pinned to true by a base constraint, so every
    group's solution already agrees on it and it cannot carry a disagreement
    between them.
    """
    parent: dict[str, str] = {}

    def find(item: str) -> str:
        parent.setdefault(item, item)
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for name, spec in dims.items():
        support = [v for v in spec.get("support") or () if v != TRUE_VAR]
        # The dimension itself joins its variables: they all appear in its one
        # defining equation, so they are constrained together.
        for var in support:
            union(name, var)

    groups: dict[str, list[str]] = {}
    for name in dims:
        groups.setdefault(find(name), []).append(name)
    return sorted((tuple(sorted(members)) for members in groups.values()), key=len, reverse=True)


def _as_prop(node: Any, memo: dict[int, Any] | None = None) -> Any:
    """Force a value into proposition shape, the way C reads a condition.

    A connective's operand has to be a proposition. Most already are, but a
    number in that position means `!= 0` -- which is exactly what the source
    said, since `if (x)` is how it was written. This matters once unmodelled
    names become free variables: before that they took the dimension down
    before anything could ask what shape they were.

    `memo` keys on node identity so a shared operand is converted once. The
    expressions here are graphs, not trees; converting per parent would copy
    the sharing away and leave a tree far too large to compile.
    """
    if isinstance(node, bool):
        return {"op": "eq", "var": TRUE_VAR, "value": node}
    if isinstance(node, int):
        return {"op": "eq", "var": TRUE_VAR, "value": bool(node)}
    if not isinstance(node, dict):
        return node
    if memo is not None:
        hit = memo.get(id(node))
        if hit is not None:
            return hit
    result = _as_prop_uncached(node, memo)
    if memo is not None:
        memo[id(node)] = result
    return result


def _as_prop_uncached(node: dict[str, Any], memo: dict[int, Any] | None) -> Any:
    if "var" in node and "op" not in node:
        return {"op": "ne", "var": node["var"], "value": 0}
    if node.get("op") == "if_then_else" and not _is_bool_expr(node):
        cond = node.get("condition")
        return {
            "op": "or",
            "args": [
                {"op": "and", "args": [cond, _as_prop(node.get("then"), memo)]},
                {
                    "op": "and",
                    "args": [{"op": "not", "arg": cond}, _as_prop(node.get("else"), memo)],
                },
            ],
        }
    return node


def _collect_vars(node: Any) -> set[str]:
    out: set[str] = set()
    seen: set[int] = set()

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            if id(item) in seen:
                return
            seen.add(id(item))
            name = item.get("var")
            if isinstance(name, str):
                out.add(name)
            for value in item.values():
                walk(value)
        elif isinstance(item, list):
            if id(item) in seen:
                return
            seen.add(id(item))
            for value in item:
                walk(value)

    walk(node)
    return out


def _identity_is_shared(var_id: str, spec: Any) -> bool:
    """Does this variable id denote the same thing in two different dimensions?

    The variable model records the answer as `identity_merged`, set where the
    variable is minted — an accessor-named read, or a container element at an
    index we never resolved. This only adds the checks that do not depend on
    the model having been reached: an undeclared variable says nothing about
    itself, and an accessor-shaped name is a merge however it got declared.

    Wrong answers are not symmetric. Saying "not shared" when it is shared
    loses conflict detection; saying "shared" when it is not invents
    contradictions and reports reachable keys as unreachable. So this errs
    toward not shared.
    """
    if spec is None:
        return False
    if bool(getattr(spec, "identity_merged", False)):
        return False
    return not _GETTER_MARK.search(var_id)


class _Isolator:
    """Renames the variables that must not be shared between dimensions.

    Anything the model flagged as `identity_merged` is isolated into this
    dimension, which drops a cross-dimension equality we could not justify.
    Dropping constraints only widens the feasible set, so an UNSAT that
    survives isolation is still an UNSAT.
    """

    def __init__(self, dim: str, var_model: Any, origins: dict[str, str]) -> None:
        self._dim = dim
        self._model = var_model
        self._origins = origins
        self._map: dict[str, str] = {}
        self.isolated: set[str] = set()
        self.shared: set[str] = set()

    def __call__(self, var_id: str) -> str:
        hit = self._map.get(var_id)
        if hit is not None:
            return hit
        spec = self._model.get(var_id) if hasattr(self._model, "get") else None
        if _identity_is_shared(var_id, spec):
            out = var_id
            self.shared.add(var_id)
        else:
            out = f"{var_id}{ISOLATE_MARK}{self._dim}"
            self.isolated.add(var_id)
        self._map[var_id] = out
        self._origins[out] = str(getattr(spec, "value_type", "") or "")
        return out

    def origin_of(self, renamed: str) -> str:
        """The declared value type behind a possibly-renamed variable."""
        return self._origins.get(renamed, "")


def _declare(var_id: str, value_type: str, nulls: set[str]) -> dict[str, Any]:
    """This variable's IR declaration.

    No domain is asserted on integers. A declared domain would narrow the
    feasible set, and narrowing is the direction that invents UNSAT results;
    the cost is that a witness may name a value outside the real range, which
    is why witnesses are labelled as existence proofs.

    Enums become integers rather than IR enums for the same reason: an IR enum
    needs its full value list, and asserting a list we only partly read would
    exclude spellings the host can still produce.
    """
    if var_id in nulls or value_type == "bool":
        return {"id": var_id, "type": "bool"}
    return {"id": var_id, "type": "int"}


def _dedupe(variables: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """One declaration per id, keeping the first. Derived ones are unique."""
    seen: dict[str, dict[str, Any]] = {}
    for item in variables:
        seen.setdefault(str(item["id"]), item)
    return list(seen.values())


def _target_value(target: Any) -> Any:
    """The key's value for one dimension, as the IR wants it."""
    if isinstance(target, bool):
        return target
    if isinstance(target, int):
        return target
    if isinstance(target, str):
        try:
            return int(target.strip(), 0)
        except (TypeError, ValueError):
            return None
    return None
