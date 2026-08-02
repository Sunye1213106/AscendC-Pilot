# -*- coding: utf-8 -*-
"""What the operator declares about itself, before any code runs.

Two files state it, in different shapes:

`op_host/*_def.cpp` lists each parameter's dtypes as a *column*. The lists are
read down, not across: entry `i` of every parameter together forms one
supported combination, so the twenty-odd entries are the legal combinations,
not a set of independently choosable types. That distinction is the whole
value of this file -- a query in FLOAT8 goes with a key in FLOAT8, and no
amount of per-parameter type information says so.

`op_graph/*_proto.h` lists the same parameters with their dtypes as a *set*,
which cannot express the pairing. It is read anyway, to check the two agree:
they are maintained by hand and drift.

Both also fix the parameter order, which is the only thing connecting host
tiling -- which reads inputs by position, `GetInputDesc(4)` -- to the API
layer, which reads them by name.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from uo_init.variable_model import ParamDecl, parse_opdef

# `.INPUT(query, TensorType({DT_FLOAT16, DT_BF16}))`, and the optional form.
REG_TENSOR_RE = re.compile(
    r"\.(INPUT|OPTIONAL_INPUT|DYNAMIC_INPUT|OUTPUT|DYNAMIC_OUTPUT)\s*\(\s*"
    r"(\w+)\s*,\s*TensorType\s*\(\s*\{([^}]*)\}"
)
# `.ATTR(seed, Int, 0)` / `.REQUIRED_ATTR(head_num, Int)`
REG_ATTR_RE = re.compile(r"\.(REQUIRED_ATTR|ATTR)\s*\(\s*(\w+)\s*,\s*(\w+)\s*([^)]*)\)")
REG_OP_RE = re.compile(r"\bREG_OP\s*\(\s*(\w+)\s*\)")


@dataclass
class DtypeCombination:
    """One legal assignment of dtypes across all parameters at once."""

    index: int
    by_param: dict[str, str] = field(default_factory=dict)


@dataclass
class ProtoParam:
    kind: str  # input | output | attr
    name: str
    index: int
    optional: bool = False
    dtypes: list[str] = field(default_factory=list)
    value_type: str = ""
    default: str = ""


@dataclass
class DeclFacts:
    """The declared interface of one operator."""

    op_name: str = ""
    params: list[ParamDecl] = field(default_factory=list)
    combinations: list[DtypeCombination] = field(default_factory=list)
    proto: list[ProtoParam] = field(default_factory=list)
    disagreements: list[str] = field(default_factory=list)

    def by_name(self, name: str) -> ParamDecl | None:
        want = str(name).lower()
        return next((p for p in self.params if p.name.lower() == want), None)

    def index_of(self, name: str, kind: str = "input") -> int | None:
        p = self.by_name(name)
        return p.index if p is not None and p.kind == kind else None

    def optional_inputs(self) -> list[str]:
        return [p.name for p in self.params if p.kind == "input" and p.is_optional]

    def attr_defaults(self) -> dict[str, str]:
        return {
            p.name: p.default
            for p in self.params
            if p.kind == "attr" and p.default != ""
        }

    def dtypes_of(self, name: str) -> list[str]:
        """Which dtypes one parameter may take, over all combinations."""
        seen: list[str] = []
        for combo in self.combinations:
            got = combo.by_param.get(name)
            if got and got not in seen:
                seen.append(got)
        return seen

    def to_dict(self) -> dict:
        return {
            "op_name": self.op_name,
            "params": [
                {
                    "kind": p.kind,
                    "name": p.name,
                    "index": p.index,
                    "param_type": p.param_type,
                    "value_type": p.value_type,
                    "default": p.default,
                }
                for p in self.params
            ],
            "combinations": [
                {"index": c.index, "by_param": dict(c.by_param)}
                for c in self.combinations
            ],
            "attr_defaults": self.attr_defaults(),
            "optional_inputs": self.optional_inputs(),
            "disagreements": list(self.disagreements),
        }


def _combinations(params: list[ParamDecl], notes: list[str]) -> list[DtypeCombination]:
    """Read the dtype lists down rather than across.

    Every tensor parameter must list the same number of entries for the columns
    to line up. When one does not, the file has been edited without updating
    the rest, and pairing entry `i` across parameters of different lengths
    would invent combinations the operator never claimed.
    """
    tensors = [
        p for p in params if p.kind in ("input", "output") and p.dtype_row
    ]
    if not tensors:
        return []
    width = max(len(p.dtype_row) for p in tensors)
    # A parameter that lists one dtype for a whole row of combinations means it
    # every time; that is how these files are written, and it is not ragged.
    ragged = [p for p in tensors if len(p.dtype_row) not in (1, width)]
    if ragged:
        notes.append(
            "opdef_dtype_lists_ragged: expected 1 or %d entries, got %s"
            % (width, ", ".join(f"{p.name}={len(p.dtype_row)}" for p in ragged))
        )
        return []
    return [
        DtypeCombination(
            index=i,
            by_param={
                p.name: p.dtype_row[i if len(p.dtype_row) > 1 else 0] for p in tensors
            },
        )
        for i in range(width)
    ]


def parse_proto(path: str | Path) -> tuple[str, list[ProtoParam]]:
    """Parameters as `REG_OP` declares them."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    found = REG_OP_RE.search(text)
    op_name = found.group(1) if found else ""

    out: list[ProtoParam] = []
    counts: dict[str, int] = {}

    def take(kind: str, **kw) -> None:
        n = counts.get(kind, 0)
        counts[kind] = n + 1
        out.append(ProtoParam(kind=kind, index=n, **kw))

    for m in REG_TENSOR_RE.finditer(text):
        tag, name, types = m.group(1), m.group(2), m.group(3)
        kind = "output" if "OUTPUT" in tag else "input"
        take(
            kind,
            name=name,
            optional=tag.startswith("OPTIONAL"),
            dtypes=[t.strip().split("::")[-1] for t in types.split(",") if t.strip()],
        )
    for m in REG_ATTR_RE.finditer(text):
        tag, name, vtype, rest = m.groups()
        default = rest.strip().lstrip(",").strip()
        take(
            "attr",
            name=name,
            optional=tag == "ATTR",
            value_type=vtype,
            default=default,
        )
    return op_name, out


def _compare(params: list[ParamDecl], proto: list[ProtoParam]) -> list[str]:
    """Where the two declarations disagree.

    Reported rather than reconciled: which one is right is not something this
    can know, and a silent pick would put the wrong default into every sample.
    """
    notes: list[str] = []
    by_kind_def: dict[str, list[ParamDecl]] = {}
    for p in params:
        by_kind_def.setdefault(p.kind, []).append(p)
    by_kind_proto: dict[str, list[ProtoParam]] = {}
    for p in proto:
        by_kind_proto.setdefault(p.kind, []).append(p)

    for kind in sorted(set(by_kind_def) | set(by_kind_proto)):
        left = [p.name for p in by_kind_def.get(kind, ())]
        right = [p.name for p in by_kind_proto.get(kind, ())]
        if left != right:
            only_def = [n for n in left if n not in right]
            only_proto = [n for n in right if n not in left]
            if only_def or only_proto:
                notes.append(
                    f"{kind}_names_differ: def-only={only_def} proto-only={only_proto}"
                )
            elif left != right:
                notes.append(f"{kind}_order_differs: def={left} proto={right}")

    proto_attr = {p.name: p for p in proto if p.kind == "attr"}
    for p in params:
        if p.kind != "attr" or p.name not in proto_attr:
            continue
        theirs = proto_attr[p.name].default.strip().rstrip("f")
        ours = p.default.strip().rstrip("f")
        if theirs and ours and theirs != ours:
            notes.append(
                f"attr_default_differs: {p.name} def={p.default} proto="
                f"{proto_attr[p.name].default}"
            )
    return notes


def extract_decl_facts(
    opdef: str | Path | None, proto_path: str | Path | None = None
) -> DeclFacts:
    """Everything the declarations say, with their disagreements listed."""
    facts = DeclFacts()
    if opdef and Path(opdef).is_file():
        facts.params = parse_opdef(opdef)
        facts.combinations = _combinations(facts.params, facts.disagreements)
    if proto_path and Path(proto_path).is_file():
        facts.op_name, facts.proto = parse_proto(proto_path)
        if facts.params:
            facts.disagreements.extend(_compare(facts.params, facts.proto))
    return facts
