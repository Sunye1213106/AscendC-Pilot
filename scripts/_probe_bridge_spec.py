# -*- coding: utf-8 -*-
"""Export the bridge spec from the derivation, rather than asserting it.

Run this after a derivation refresh. It reads what the fields and premises
actually consult, resolves each variable to the operand it names, and writes
the result to the operator package. Nothing here decides what the mapping
*should* be: a variable resolves because the operator definition contains a
name that slugs to it, or it does not resolve and is written down as unbound.

    python scripts/_probe_bridge_spec.py --write
    python scripts/_probe_bridge_spec.py --check    # CI: is it still current?
"""

from __future__ import annotations

import argparse
import json
import pickle
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import yaml  # noqa: E402

from replay import bridge_spec as S  # noqa: E402

DERIVE = ROOT / ".probe_cache" / "fag_derive.json"
BUNDLE = ROOT / ".probe_cache" / "fag_bundle.pkl"

#: `VAR_<prefix>_<slug>` -> how that variable reads its operand. Longest
#: prefix wins, so VAR_ELEM_ELEM_ is tried before VAR_ELEM_.
PREFIX_KIND = {
    "VAR_OPT_": S.TENSOR_PRESENCE,
    "VAR_RANK_": S.TENSOR_RANK,
    "VAR_DTYPE_": S.TENSOR_DTYPE,
    "VAR_VALUE_": S.TENSOR_VALUES,
    "VAR_ELEM_ELEM_": S.TENSOR_VALUE_LAST,
    "VAR_ELEM_BACK_": S.TENSOR_VALUE_LAST,
    "VAR_ELEM_SECOND_": S.TENSOR_VALUE_SECOND,
    "VAR_REDUCE_MAX_": S.TENSOR_VALUE_MAX,
    "VAR_ATTR_": S.ATTR,
    "VAR_SHAPE_": S.TENSOR_NUMEL,   # unless an axis suffix says otherwise
}

#: Roots whose values the host works out partway through tiling. No input
#: sets them, which is a fact about the operator rather than a gap here.
HOST_STATE_ROOTS = frozenset({"TILING_DATA", "TILING_KEY", "LOOP_INDUCTION",
                              "LOOP_DERIVED", "KERNEL_BUILTIN"})

#: Roots that describe the machine rather than the case.
CONTEXT_ROOTS = frozenset({
    "PLATFORM_ARCH", "PLATFORM_CORE_COUNT", "PLATFORM_MEMORY_SIZE",
    "PLATFORM_L2_SIZE", "PLATFORM_AIV_COUNT", "SESSION_OPTION",
    "COMPILE_INFO", "COMPILE_DEFINE",
})

#: `VAR_ELEM_SECOND_QUERY` reads the second element of *something*, and which
#: something depends on the root. Under INPUT_SHAPE the elements are the
#: dimensions; under INPUT_VALUE they are the numbers the host reads out of
#: the buffer. Same spelling, two different readings.
SHAPE_READING = {
    S.TENSOR_VALUE_SECOND: (S.TENSOR_AXIS, 1),
    S.TENSOR_VALUE_LAST: (S.TENSOR_AXIS_LAST, None),
}

#: The derivation names optional inputs after the C++ index enum, which
#: carries a suffix the operator definition does not.
INDEX_SUFFIX = "_IDX"

_AXIS = re.compile(r"^(?P<head>.*)_D(?P<axis>\d+)$")


def _squash(text: str) -> str:
    """Compare names without caring how they are punctuated.

    The operator definition spells a tensor `actual_seq_qlen` and the
    derivation slugs the C++ enum to `ACTUAL_SEQ_Q_LEN`. They are the same
    tensor; only the separators moved.
    """
    return re.sub(r"[^a-z0-9]", "", text.lower())


def read_variables(doc: dict) -> dict[str, str]:
    """Every variable the derivation consults, with its root bucket."""
    hd = doc["host_derivation"]
    out: dict[str, str] = {}
    for field in hd["fields"]:
        for var, root in (field.get("var_roots") or {}).items():
            out.setdefault(var, root)
    for premise in hd.get("premises") or []:
        for var, root in (premise.get("var_roots") or {}).items():
            out.setdefault(var, root)
    return out


def self_compared(doc: dict) -> set[str]:
    """Variables that only ever appear compared against themselves.

    `x >= x` is always true whatever x is, so the comparison decides nothing
    and the variable is not worth binding. It is also a sign the extraction
    collapsed two different quantities into one name, which is worth saying
    out loud rather than papering over with a value.
    """
    reflexive: set[str] = set()
    other: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        lhs, rhs = node.get("lhs"), node.get("rhs")
        if isinstance(lhs, dict) and isinstance(rhs, dict):
            a, b = lhs.get("var"), rhs.get("var")
            if a and a == b:
                reflexive.add(a)
            else:
                other.update(v for v in (a, b) if v)
        for value in node.values():
            walk(value)

    for field in doc["host_derivation"]["fields"]:
        walk(field.get("value_expr") or {})
    return reflexive - other


def operand_index(names: dict[str, list[str]]) -> dict[str, tuple[str, str]]:
    """Squashed operand name -> (name, kind)."""
    out: dict[str, tuple[str, str]] = {}
    for kind, items in names.items():
        for name in items:
            out.setdefault(_squash(name), (name, kind))
    return out


def resolve(var: str, root: str, index: dict[str, tuple[str, str]]
            ) -> tuple[str, str, int | None, str] | None:
    """Which operand this variable reads, and how.

    Returns the operand, the reading, the axis if there is one, and how the
    name was matched -- an exact match and a match that had to drop a suffix
    are both usable, but they are not equally certain, so the spec says which
    happened.
    """
    for prefix in sorted(PREFIX_KIND, key=len, reverse=True):
        if not var.startswith(prefix):
            continue
        kind = PREFIX_KIND[prefix]
        tail, axis = var[len(prefix):], None
        if kind == S.TENSOR_NUMEL:
            m = _AXIS.match(tail)
            if m:
                tail, axis = m.group("head"), int(m.group("axis"))
                kind = S.TENSOR_AXIS
        if root == "INPUT_SHAPE" and kind in SHAPE_READING:
            kind, axis = SHAPE_READING[kind]

        got, how = index.get(_squash(tail)), "exact"
        if got is None and tail.endswith(INDEX_SUFFIX):
            got, how = index.get(_squash(tail[:-len(INDEX_SUFFIX)])), \
                "index_enum_suffix"
        if got is None:
            # A prefix match with no operand behind it: try a shorter one
            # rather than claiming this variable reads a tensor that the
            # definition does not list.
            continue
        name, operand_kind = got
        if (kind == S.ATTR) != (operand_kind == "attr"):
            continue
        return name, kind, axis, how
    return None


def build(doc: dict, names: dict[str, list[str]]) -> dict[str, Any]:
    variables = read_variables(doc)
    index = operand_index(names)
    reflexive = self_compared(doc)

    bindings: dict[str, Any] = {}
    unbound: dict[str, Any] = {}

    for var in sorted(variables):
        root = variables[var]
        if root in HOST_STATE_ROOTS:
            unbound[var] = {
                "root": root,
                "reason": "tiling state: the host works this out partway "
                          "through, so no input sets it",
            }
            continue
        if var in reflexive:
            unbound[var] = {
                "root": root,
                "reason": "only ever compared against itself, which is true "
                          "whatever it holds; the extraction collapsed two "
                          "quantities into one name",
            }
            continue
        if root in CONTEXT_ROOTS:
            entry = {"root": root, "kind": S.CONTEXT}
            # The architecture is the same for every case the spec covers --
            # there is one spec per arch -- so it belongs here rather than
            # being asserted again by whoever expands the cases.
            if root == "PLATFORM_ARCH":
                digits = re.sub(r"\D", "", str(doc.get("arch", "")))
                if digits:
                    entry["value"] = int(digits)
            bindings[var] = entry
            continue

        got = resolve(var, root, index)
        if got is None:
            unbound[var] = {
                "root": root,
                "reason": "no operand in the definition slugs to this name",
            }
            continue
        name, kind, axis, how = got
        entry: dict[str, Any] = {"root": root, "kind": kind}
        entry["attr" if kind == S.ATTR else "tensor"] = name
        if axis is not None:
            entry["axis"] = axis
        if how != "exact":
            entry["matched_via"] = how
        bindings[var] = entry

    hd = doc["host_derivation"]
    return {
        "operator": doc.get("op", ""),
        "arch": doc.get("arch", ""),
        "source": {
            "derivation_timestamp": doc.get("timestamp", ""),
            "derivation_status": hd.get("status", ""),
            "encode_function": hd.get("encode_function", ""),
            "fields": len(hd.get("fields") or []),
            "premises": len(hd.get("premises") or []),
        },
        "bindings": bindings,
        "unbound": unbound,
    }


#: Fields of an observation that name a constant rather than hold a value.
CONSTANT_FIELDS = ("when_true", "when_false")


def resolve_observations(package: Path, constants: dict[str, int]
                         ) -> list[dict[str, Any]]:
    """Read the hand-written observations and turn named constants into values.

    The file names `INPUT_FORMAT_TND`; the header says it is 4 this month.
    Resolving here rather than transcribing means a renumbered header changes
    the spec on the next export, and a renamed one fails it -- both louder
    than a stale 4 that keeps evaluating.
    """
    path = package / "observations.yaml"
    if not path.is_file():
        return []
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    out = []
    for raw in (doc.get("observations") or []):
        entry = {k: v for k, v in raw.items() if k != "note"}
        for key in CONSTANT_FIELDS:
            name = entry.get(key)
            if name is None:
                continue
            if name not in constants:
                raise SystemExit(
                    f"{path}: {entry.get('variable')} names the constant "
                    f"{name!r}, which is not among the {len(constants)} the "
                    f"analysis found in this operator's headers. Either the "
                    f"header renamed it or the bundle is stale.")
            entry[key] = constants[name]
            entry.setdefault("constant_names", {})[key] = name
        out.append(entry)
    return out


HEADER = """\
# Which case quantity sets which derivation variable.
#
# Exported by scripts/_probe_bridge_spec.py from the derivation named under
# `source`. Do not edit by hand: a value written here that the derivation
# does not read is a value nothing will ever check, and one it does read that
# is spelled wrong here fails as a missing variable rather than as an error.
#
# Every variable the derivation consults appears exactly once, under
# `bindings` or under `unbound`. There is no third outcome, and that is the
# point: an unbound variable used to be an absent dictionary key, which an
# evaluator cannot tell from a variable nobody modelled.
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true",
                    help="write the spec into the operator package")
    ap.add_argument("--check", action="store_true",
                    help="fail if the written spec differs from a fresh export")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    doc = json.loads(DERIVE.read_text(encoding="utf-8"))
    model = pickle.loads(BUNDLE.read_bytes())["var_model"]
    spec = build(doc, model.operand_names())

    out = Path(args.out) if args.out else (
        ROOT / "operators" / _package(doc) / doc.get("arch", "")
        / "bridge_spec.yaml")
    observations = resolve_observations(
        out.parent, dict(getattr(model, "named_constants", {}) or {}))
    if observations:
        spec["observations"] = observations
        named = sum(len(o.get("constant_names") or {}) for o in observations)
        print(f"{len(observations)} observations, {named} constants resolved")

    n_bound, n_unbound = len(spec["bindings"]), len(spec["unbound"])
    print(f"{n_bound + n_unbound} variables read by the derivation")
    print(f"  {n_bound} bound, {n_unbound} unbound")
    by_reason: dict[str, int] = {}
    for entry in spec["unbound"].values():
        key = entry["reason"].split(":")[0].split(",")[0]
        by_reason[key] = by_reason.get(key, 0) + 1
    for reason, n in sorted(by_reason.items(), key=lambda kv: -kv[1]):
        print(f"      {n:3d} {reason}")
        for var, entry in sorted(spec["unbound"].items()):
            if entry["reason"].startswith(reason):
                print(f"          {var}  [{entry['root']}]")

    kinds: dict[str, int] = {}
    for entry in spec["bindings"].values():
        kinds[entry["kind"]] = kinds.get(entry["kind"], 0) + 1
    print("  bound by kind:")
    for kind, n in sorted(kinds.items(), key=lambda kv: -kv[1]):
        print(f"      {n:3d} {kind}")

    text = HEADER + yaml.safe_dump(spec, sort_keys=False, allow_unicode=True,
                                   default_flow_style=False, width=88)

    if args.check:
        if not out.is_file():
            print(f"\nno spec at {out}; run with --write")
            return 1
        if out.read_text(encoding="utf-8") != text:
            print(f"\n{out} is stale; re-export with --write")
            return 1
        print(f"\n{out} matches the derivation")
        return 0

    if args.write:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="\n")
        print(f"\nwrote {out}")
    else:
        print("\n(dry run; pass --write to save)")
    return 0


def _package(doc: dict) -> str:
    """The package directory for the operator the derivation is about."""
    name = doc.get("op", "")
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


if __name__ == "__main__":
    raise SystemExit(main())
