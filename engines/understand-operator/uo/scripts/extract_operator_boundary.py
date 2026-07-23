"""Operator boundary: registered IO/attr slots ↔ Host accessors.

Never guess input names from local variable identifiers. Without registration
evidence, keep ``input_slot[N]`` / ``attr_slot[N]`` and emit unresolved.

Supports generic AscendC / GE OpDef registration syntax:
multi-arg Input/OptionalInput/Output/Attr/RequiredAttr, templated accessors,
literal / named / constexpr indices — only with explicit source evidence.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo.scripts._ir_io import read_yaml, write_yaml
from uo.scripts.arch_path import arch_compatible
from uo.scripts.resolve_entrypoints import load_entrypoint_graph

# First string literal in a multi-arg OpDef call is the registered name.
_OP_CALL_RE = re.compile(
    r"""\.(?P<macro>Input|OptionalInput|Output|Attr|RequiredAttr)\s*\((?P<args>[^;]*?)\)""",
    re.MULTILINE | re.DOTALL,
)
_FIRST_STRING_RE = re.compile(r"""["']([^"']+)["']""")
_ATTR_DEFAULT_RE = re.compile(
    r"""\.Attr\s*\(\s*["']([^"']+)["']\s*(?:,[^)]*)?\)[^;]*?\.AttrDefault\s*\(([^\)]*)\)""",
    re.DOTALL,
)

# Templated / plain GetInput{Shape,Desc,Dtype}(index) — index may be int, string, or identifier.
_GET_INPUT_RE = re.compile(
    r"""\b(?P<api>Get(?:Optional)?Input(?:Shape|Desc|Dtype))\s*(?:<[^>]*>)?\s*\(\s*"""
    r"""(?P<arg>["'][^"']+["']|\d+|[A-Za-z_][A-Za-z0-9_]*)\s*\)"""
)
_GET_ATTR_RE = re.compile(
    r"""\b(?P<api>GetAttr(?:Pointer|Optional)?)\s*(?:<[^>]*>)?\s*\(\s*"""
    r"""(?P<arg>["'][^"']+["']|\d+|[A-Za-z_][A-Za-z0-9_]*)\s*\)"""
)
# constexpr / enum / #define index binders: IDX_FOO = 3 or constexpr int IDX_FOO = 3
_CONST_INDEX_RE = re.compile(
    r"""(?:constexpr\s+(?:static\s+)?(?:const\s+)?(?:int|size_t|uint32_t|int32_t)\s+|"""
    r"""#\s*define\s+|enum(?:\s+class)?\s+\w+\s*\{[^}]*?)"""
    r"""(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*(?:=\s*(?P<val>\d+)\s*[,;}]|\s+(?P<val2>\d+)\b)""",
    re.MULTILINE,
)
_ENUM_MEMBER_RE = re.compile(
    r"""\b(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<val>\d+)\s*[,}]"""
)
_UNPARSEABLE_ACCESSOR_RE = re.compile(
    r"""\bGet(?:Optional)?(?:Input(?:Shape|Desc|Dtype)|Attr(?:Pointer)?)\s*(?:<[^>]*>)?\s*\("""
)


def extract_operator_boundary(repo_root: Path, op_name: str, *, architecture: str = "arch35") -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    files = _confirmed_sources(uo_root)
    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    attributes: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    optional_states: dict[str, str] = {}
    const_index: dict[str, int] = {}

    slot = 0
    for rel in files:
        if not arch_compatible(rel, architecture) and "/op_host/" not in rel and "reg" not in rel.lower():
            if "reg" not in Path(rel).name.lower() and "op_host" not in rel:
                continue
        path = repo_root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        const_index.update(_collect_const_indices(text))

        for match in _OP_CALL_RE.finditer(text):
            macro = match.group("macro")
            args = match.group("args") or ""
            name_m = _FIRST_STRING_RE.search(args)
            line = text.count("\n", 0, match.start()) + 1
            if not name_m:
                unresolved.append(
                    {
                        "severity": "degraded",
                        "code": "opdef_call_unparseable",
                        "related_symbols": [macro],
                        "candidate_files": [rel],
                        "evidence_present": [match.group(0)[:120]],
                        "evidence_missing": ["string_literal_slot_name"],
                        "reason": f".{macro}(...) lacks a string-literal slot name; cannot bind without evidence",
                        "semantic_task": "opdef_slot_disambiguation",
                    }
                )
                continue
            name = name_m.group(1)
            if macro == "Input":
                inputs.append(_input_row(slot, name, False, rel, line, "Input"))
                slot += 1
            elif macro == "OptionalInput":
                inputs.append(_input_row(slot, name, True, rel, line, "OptionalInput"))
                optional_states[name] = "unknown"
                slot += 1
            elif macro == "Output":
                outputs.append(
                    {
                        "name": name,
                        "evidence": [{"file_path": rel, "line": line, "macro": "Output"}],
                    }
                )
            elif macro in {"Attr", "RequiredAttr"}:
                attributes.append(
                    {
                        "slot_or_name": name,
                        "type": "",
                        "required": macro == "RequiredAttr",
                        "default": None,
                        "host_accessors": [],
                        "binding_status": "verified",
                        "evidence": [{"file_path": rel, "line": line, "macro": macro}],
                    }
                )

        defaults = {m.group(1): m.group(2).strip() for m in _ATTR_DEFAULT_RE.finditer(text)}
        for attr in attributes:
            if attr.get("slot_or_name") in defaults and attr.get("default") is None:
                attr["default"] = defaults[attr["slot_or_name"]]

    by_slot = {int(i["slot"]): i for i in inputs}
    by_name = {str(i["name"]): i for i in inputs if i.get("name")}
    by_attr = {str(a["slot_or_name"]): a for a in attributes}

    # Bind Host accessors by index / name / constexpr — never rename from locals.
    for rel in files:
        path = repo_root / rel
        if not path.is_file() or "op_host/" not in rel.replace("\\", "/"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        const_index.update(_collect_const_indices(text))
        covered_spans: set[tuple[int, int]] = set()

        for match in _GET_INPUT_RE.finditer(text):
            covered_spans.add((match.start(), match.end()))
            api = match.group("api")
            raw = match.group("arg")
            line = text.count("\n", 0, match.start()) + 1
            idx, name_key, bind_kind = _resolve_index_arg(raw, const_index)
            if bind_kind == "unresolved":
                unresolved.append(
                    {
                        "severity": "blocking",
                        "code": "input_accessor_index_unresolved",
                        "related_symbols": [raw],
                        "candidate_files": [rel],
                        "evidence_present": [match.group(0)[:100]],
                        "evidence_missing": ["constexpr_or_literal_index"],
                        "reason": f"{api}({raw}) index cannot be resolved from source evidence",
                        "semantic_task": "accessor_index_binding",
                    }
                )
                continue
            target = None
            if idx is not None and idx in by_slot:
                target = by_slot[idx]
            elif name_key and name_key in by_name:
                target = by_name[name_key]
                idx = int(target["slot"])
            accessor = {
                "api": api,
                "index": idx,
                "name": name_key or (target.get("name") if target else None),
                "file_path": rel,
                "line": line,
                "bind_kind": bind_kind,
            }
            if target is not None:
                target["host_accessors"].append(accessor)
            else:
                placeholder = {
                    "slot": idx if idx is not None else -1,
                    "name": name_key,
                    "optional": "Optional" in api,
                    "dtype_constraints": [],
                    "format_constraints": [],
                    "host_accessors": [accessor],
                    "binding_status": "unresolved",
                    "evidence": [],
                }
                inputs.append(placeholder)
                if idx is not None:
                    by_slot[idx] = placeholder
                unresolved.append(
                    {
                        "severity": "blocking",
                        "code": "input_slot_unbound",
                        "related_symbols": [f"input_slot[{idx}]" if idx is not None else str(name_key)],
                        "candidate_files": [rel],
                        "evidence_present": [f"{api}({raw})"],
                        "evidence_missing": ["OpDef_Input_registration"],
                        "reason": f"{api}({raw}) has no registered input name",
                        "semantic_task": "opdef_slot_binding",
                    }
                )

        for match in _GET_ATTR_RE.finditer(text):
            covered_spans.add((match.start(), match.end()))
            api = match.group("api")
            raw = match.group("arg")
            line = text.count("\n", 0, match.start()) + 1
            idx, name_key, bind_kind = _resolve_index_arg(raw, const_index)
            key = name_key or (f"attr_slot[{idx}]" if idx is not None else raw)
            if name_key and name_key in by_attr:
                by_attr[name_key]["host_accessors"].append(
                    {
                        "api": api,
                        "name": name_key,
                        "index": idx,
                        "file_path": rel,
                        "line": line,
                        "bind_kind": bind_kind,
                    }
                )
            else:
                unresolved.append(
                    {
                        "severity": "blocking" if name_key else "degraded",
                        "code": "attr_slot_unbound",
                        "related_symbols": [key],
                        "candidate_files": [rel],
                        "evidence_present": [match.group(0)[:80]],
                        "evidence_missing": ["OpDef_Attr_registration"],
                        "reason": f"attribute accessor {key} lacks registration evidence",
                        "semantic_task": "attr_slot_binding",
                    }
                )

        # Catch wrapper expressions the structured regexes cannot parse.
        for match in _UNPARSEABLE_ACCESSOR_RE.finditer(text):
            span = (match.start(), match.end())
            if any(s[0] <= span[0] < s[1] for s in covered_spans):
                continue
            # Look ahead for closing paren; if arg body is complex, flag it.
            rest = text[match.end() : match.end() + 120]
            if re.match(r"""\s*(?:["'][^"']+["']|\d+|[A-Za-z_][A-Za-z0-9_]*)\s*\)""", rest):
                continue
            line = text.count("\n", 0, match.start()) + 1
            unresolved.append(
                {
                    "severity": "degraded",
                    "code": "accessor_expression_unparseable",
                    "related_symbols": [match.group(0)[:40]],
                    "candidate_files": [rel],
                    "evidence_present": [(match.group(0) + rest)[:120]],
                    "evidence_missing": ["literal_or_named_index"],
                    "reason": "complex accessor expression; emit semantic task instead of guessing",
                    "semantic_task": "accessor_expression_binding",
                    "line": line,
                }
            )

    for item in inputs:
        if item.get("optional") and item.get("name"):
            optional_states.setdefault(str(item["name"]), "unknown")

    payload = {
        "version": 1,
        "op_name": op_name,
        "architecture": architecture,
        "inputs": sorted(inputs, key=lambda x: int(x.get("slot") if x.get("slot") is not None else 10**9)),
        "outputs": outputs,
        "attributes": attributes,
        "optional_input_states": optional_states,
        "const_index_map": {k: v for k, v in sorted(const_index.items())},
        "unresolved": unresolved,
    }
    write_yaml(uo_root / "ir" / "operator_boundary.yaml", payload)
    if unresolved:
        _merge_unresolved(uo_root, unresolved)
    return payload


def optional_state_label(*, absent: bool = False, empty: bool = False, nonempty: bool = False) -> str:
    if absent:
        return "absent"
    if empty:
        return "present_but_empty"
    if nonempty:
        return "present_and_nonempty"
    return "unknown"


def _input_row(slot: int, name: str, optional: bool, rel: str, line: int, macro: str) -> dict[str, Any]:
    return {
        "slot": slot,
        "name": name,
        "optional": optional,
        "dtype_constraints": [],
        "format_constraints": [],
        "host_accessors": [],
        "binding_status": "verified",
        "evidence": [{"file_path": rel, "line": line, "macro": macro}],
    }


def _resolve_index_arg(raw: str, const_index: dict[str, int]) -> tuple[int | None, str | None, str]:
    s = (raw or "").strip()
    if len(s) >= 2 and s[0] in {"'", '"'} and s[-1] == s[0]:
        return None, s[1:-1], "string_name"
    if s.isdigit():
        return int(s), None, "literal"
    if s in const_index:
        return const_index[s], s, "constexpr"
    return None, s if re.match(r"^[A-Za-z_]", s) else None, "unresolved"


def _collect_const_indices(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for m in _CONST_INDEX_RE.finditer(text):
        name = m.group("name")
        val = m.group("val") or m.group("val2")
        if name and val is not None and name.startswith("IDX_"):
            out[name] = int(val)
    # Broader enum members that look like index constants
    for m in _ENUM_MEMBER_RE.finditer(text):
        name = m.group("name")
        if name.startswith("IDX_") or name.startswith("INPUT_") or name.startswith("ATTR_"):
            out[name] = int(m.group("val"))
    return out


def _confirmed_sources(uo_root: Path) -> list[str]:
    for path in sorted((uo_root / "runs").glob("*/scope/scope_confirmed.yaml"), reverse=True):
        data = read_yaml(path)
        files = data.get("confirmed_source_files") or data.get("confirmed_file_list") or []
        if files:
            return [str(i.get("path") if isinstance(i, dict) else i).replace("\\", "/") for i in files]
    graph = load_entrypoint_graph(uo_root)
    out = []
    for n in graph.get("nodes") or []:
        fp = str((n.get("locator") or {}).get("file_path") or "")
        if fp:
            out.append(fp)
    return sorted(set(out))


def _merge_unresolved(uo_root: Path, items: list[dict[str, Any]]) -> None:
    path = uo_root / "ir" / "unresolved.yaml"
    data = read_yaml(path)
    existing = list(data.get("items") or [])
    keys = {(x.get("code"), tuple(x.get("related_symbols") or [])) for x in existing}
    for item in items:
        key = (item.get("code"), tuple(item.get("related_symbols") or []))
        if key not in keys:
            existing.append(item)
    write_yaml(path, {"version": 1, "items": existing})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract operator boundary slot bindings")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--architecture", default="arch35")
    args = parser.parse_args(argv)
    payload = extract_operator_boundary(Path(args.repo).resolve(), args.op_name, architecture=args.architecture)
    print(f"inputs={len(payload['inputs'])} attrs={len(payload['attributes'])} unresolved={len(payload['unresolved'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
