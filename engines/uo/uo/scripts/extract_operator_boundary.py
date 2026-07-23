"""Operator boundary: registered IO/attr slots ↔ Host accessors.

Never guess input names from local variable identifiers. Without registration
evidence, keep ``input_slot[N]`` / ``attr_slot[N]`` and emit unresolved.
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
from uo.scripts.semantic_identity import mint_edge_id

# OpDef grammar adapters (⑪) — multiple framework registration styles.
_OPDEF_SLOT_SPECS: tuple[tuple[str, str, bool], ...] = (
    # (regex pattern with name group, kind, optional)
    (r"""\.(?:INPUT|Input)\s*\(\s*["']([^"']+)["']\s*\)""", "input", False),
    (r"""\.(?:OPTIONAL_INPUT|OptionalInput)\s*\(\s*["']([^"']+)["']\s*\)""", "input", True),
    (r"""\.(?:OUTPUT|Output)\s*\(\s*["']([^"']+)["']\s*\)""", "output", False),
    (r"""\.(?:ATTR|Attr|REQUIRED_ATTR|RequiredAttr)\s*\(\s*["']([^"']+)["']\s*\)""", "attr", False),
)
OPDEF_SLOT_RES = tuple(
    (re.compile(pat, re.MULTILINE), kind, optional) for pat, kind, optional in _OPDEF_SLOT_SPECS
)
OP_ADD_INPUT_RE = re.compile(r"""\.(?:INPUT|Input)\s*\(\s*["']([^"']+)["']\s*\)""", re.MULTILINE)
OP_ADD_OPTIONAL_RE = re.compile(
    r"""\.(?:OPTIONAL_INPUT|OptionalInput)\s*\(\s*["']([^"']+)["']\s*\)""",
    re.MULTILINE,
)
OP_ADD_ATTR_RE = re.compile(
    r"""\.(?:ATTR|Attr|REQUIRED_ATTR|RequiredAttr)\s*\(\s*["']([^"']+)["']\s*\)""",
    re.MULTILINE,
)
OP_ADD_OUTPUT_RE = re.compile(r"""\.(?:OUTPUT|Output)\s*\(\s*["']([^"']+)["']\s*\)""", re.MULTILINE)
OP_DTYPE_RE = re.compile(r"""\.(?:DataType|DATATYPE)\s*\(\s*([^)]*)\)""")
OP_FORMAT_RE = re.compile(r"""\.(?:Format|FORMAT)\s*\(\s*([^)]*)\)""")
GET_INPUT_SHAPE_RE = re.compile(r"Get(?:Optional)?InputShape\s*\(\s*(\d+)\s*\)")
GET_INPUT_DESC_RE = re.compile(r"Get(?:Optional)?InputDesc\s*\(\s*(\d+)\s*\)")
GET_ATTR_RE = re.compile(
    r"""GetAttr(?:Pointer)?\s*\(\s*(?:["']([^"']+)["']|(\d+))\s*\)"""
)
GET_ATTR_TEMPLATE_RE = re.compile(
    r"""GetAttr\s*<[^>]+>\s*\(\s*(?:["']([^"']+)["']|(\d+))\s*\)"""
)
ATTR_DEFAULT_RE = re.compile(
    r"""\.(?:ATTR|Attr)\s*\(\s*["']([^"']+)["']\s*\)[^;]*?\.(?:AttrDefault|ATTR_DEFAULT)\s*\(([^\)]*)\)""",
    re.DOTALL,
)
REG_OP_SCOPE_RE = re.compile(r"\bREG_OP\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)")


def extract_operator_boundary(repo_root: Path, op_name: str, *, architecture: str = "arch35") -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    files = _confirmed_sources(uo_root)
    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    attributes: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    llm_hints: list[dict[str, Any]] = []
    optional_states: dict[str, str] = {}

    for rel in files:
        if not arch_compatible(rel, architecture) and "/op_host/" not in rel and "reg" not in rel.lower():
            if "reg" not in Path(rel).name.lower() and "op_host" not in rel:
                continue
        path = repo_root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        # Reset slot counters per REG_OP / file scope (⑪).
        for _inputs, _outputs, _attrs, _unres in _parse_opdef_scopes(text, rel):
            inputs.extend(_inputs)
            outputs.extend(_outputs)
            attributes.extend(_attrs)
            unresolved.extend(_unres)

    by_slot = {int(i["slot"]): i for i in inputs if i.get("slot") is not None}
    by_attr = {str(a["slot_or_name"]): a for a in attributes}

    # Bind Host accessors by index / name — never rename from locals.
    for rel in files:
        path = repo_root / rel
        if not path.is_file() or "op_host/" not in rel.replace("\\", "/"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in GET_INPUT_SHAPE_RE.finditer(text):
            idx = int(match.group(1))
            api = "GetOptionalInputShape" if "Optional" in match.group(0) else "GetInputShape"
            line = text.count("\n", 0, match.start()) + 1
            if idx in by_slot:
                by_slot[idx]["host_accessors"].append({"api": api, "index": idx, "file_path": rel, "line": line})
            else:
                placeholder = {
                    "slot": idx,
                    "name": None,
                    "optional": "Optional" in api,
                    "dtype_constraints": [],
                    "format_constraints": [],
                    "host_accessors": [{"api": api, "index": idx, "file_path": rel, "line": line}],
                    "binding_status": "unresolved",
                    "evidence": [],
                }
                inputs.append(placeholder)
                by_slot[idx] = placeholder
                unresolved.append(
                    {
                        "severity": "blocking",
                        "code": "input_slot_unbound",
                        "related_symbols": [f"input_slot[{idx}]"],
                        "candidate_files": [rel],
                        "evidence_present": [f"{api}({idx})"],
                        "evidence_missing": ["OpDef_Input_registration"],
                        "reason": f"{api}({idx}) has no registered input name",
                    }
                )
        for match in GET_INPUT_DESC_RE.finditer(text):
            idx = int(match.group(1))
            api = "GetOptionalInputDesc" if "Optional" in match.group(0) else "GetInputDesc"
            line = text.count("\n", 0, match.start()) + 1
            if idx in by_slot:
                by_slot[idx]["host_accessors"].append({"api": api, "index": idx, "file_path": rel, "line": line})
        for match in GET_ATTR_RE.finditer(text):
            name, idx = match.group(1), match.group(2)
            line = text.count("\n", 0, match.start()) + 1
            key = name if name else f"attr_slot[{idx}]"
            if name and name in by_attr:
                by_attr[name]["host_accessors"].append(
                    {"api": "GetAttrPointer" if "Pointer" in match.group(0) else "GetAttr", "name": name, "file_path": rel, "line": line}
                )
            else:
                unresolved.append(
                    {
                        "severity": "blocking" if name else "degraded",
                        "code": "attr_slot_unbound",
                        "related_symbols": [key],
                        "candidate_files": [rel],
                        "evidence_present": [match.group(0)[:80]],
                        "evidence_missing": ["OpDef_Attr_registration"],
                        "reason": f"attribute accessor {key} lacks registration evidence",
                    }
                )
        # Template GetAttr<T> / unconventional wrappers → io_slot_bind LLM hint (⑪).
        for match in GET_ATTR_TEMPLATE_RE.finditer(text):
            name, idx = match.group(1), match.group(2)
            line = text.count("\n", 0, match.start()) + 1
            key = name if name else f"attr_slot[{idx}]"
            if not (name and name in by_attr):
                llm_hints.append(
                    {
                        "type": "io_slot_bind",
                        "severity": "blocking",
                        "target": key,
                        "file_path": rel,
                        "line": line,
                        "snippet": match.group(0)[:120],
                        "reason": "template_getattr_needs_llm",
                    }
                )

    for item in inputs:
        if item.get("optional") and item.get("name"):
            optional_states.setdefault(str(item["name"]), "unknown")

    payload = {
        "version": 1,
        "op_name": op_name,
        "architecture": architecture,
        "inputs": sorted(inputs, key=lambda x: int(x.get("slot") or 0)),
        "outputs": outputs,
        "attributes": attributes,
        "optional_input_states": optional_states,
        "unresolved": unresolved,
        "llm_task_hints": llm_hints,
    }
    write_yaml(uo_root / "ir" / "operator_boundary.yaml", payload)
    if unresolved:
        _merge_unresolved(uo_root, unresolved)
    return payload


def _parse_opdef_scopes(
    text: str, rel: str
) -> list[tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]]:
    """Parse OpDef slots with per-REG_OP scope reset and DataType/Format attachment."""
    scopes: list[tuple[int, str]] = [(0, "")]
    for m in REG_OP_SCOPE_RE.finditer(text):
        scopes.append((m.start(), m.group(1)))
    scopes.append((len(text), ""))
    results: list[tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]] = []
    for i in range(len(scopes) - 1):
        start, _op = scopes[i]
        end = scopes[i + 1][0]
        chunk = text[start:end]
        results.append(_parse_opdef_chunk(chunk, rel, line_base=text.count("\n", 0, start)))
    return results


def _parse_opdef_chunk(
    chunk: str, rel: str, *, line_base: int = 0
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    attributes: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    slot = 0
    # Collect events in source order for nearest-slot DataType/Format.
    events: list[tuple[int, str, Any]] = []
    for match in OP_ADD_INPUT_RE.finditer(chunk):
        events.append((match.start(), "input", (match.group(1), False, match.group(0))))
    for match in OP_ADD_OPTIONAL_RE.finditer(chunk):
        events.append((match.start(), "input", (match.group(1), True, match.group(0))))
    for match in OP_ADD_OUTPUT_RE.finditer(chunk):
        events.append((match.start(), "output", (match.group(1), match.group(0))))
    for match in OP_ADD_ATTR_RE.finditer(chunk):
        events.append((match.start(), "attr", (match.group(1), match.group(0))))
    for match in OP_DTYPE_RE.finditer(chunk):
        events.append((match.start(), "dtype", match.group(1).strip()))
    for match in OP_FORMAT_RE.finditer(chunk):
        events.append((match.start(), "format", match.group(1).strip()))
    events.sort(key=lambda x: x[0])
    last_slot_ref: dict[str, Any] | None = None
    defaults = {m.group(1): m.group(2).strip() for m in ATTR_DEFAULT_RE.finditer(chunk)}
    for pos, kind, payload in events:
        line = line_base + chunk.count("\n", 0, pos) + 1
        if kind == "input":
            name, optional, macro = payload
            item = {
                "slot": slot,
                "name": name,
                "optional": optional,
                "dtype_constraints": [],
                "format_constraints": [],
                "host_accessors": [],
                "binding_status": "verified",
                "verification_source": "source",
                "evidence": [
                    {
                        "file_path": rel,
                        "line": line,
                        "macro": "OptionalInput" if optional else "Input",
                    }
                ],
            }
            inputs.append(item)
            last_slot_ref = item
            slot += 1
        elif kind == "output":
            name, _macro = payload
            outputs.append({"name": name, "evidence": [{"file_path": rel, "line": line}]})
        elif kind == "attr":
            name, _macro = payload
            item = {
                "slot_or_name": name,
                "type": "",
                "default": defaults.get(name),
                "host_accessors": [],
                "binding_status": "verified",
                "verification_source": "source",
                "dtype_constraints": [],
                "format_constraints": [],
                "evidence": [{"file_path": rel, "line": line, "macro": "Attr"}],
            }
            attributes.append(item)
            last_slot_ref = item
        elif kind == "dtype" and last_slot_ref is not None:
            last_slot_ref.setdefault("dtype_constraints", []).append(payload)
        elif kind == "format" and last_slot_ref is not None:
            last_slot_ref.setdefault("format_constraints", []).append(payload)
    return inputs, outputs, attributes, unresolved

def optional_state_label(*, absent: bool = False, empty: bool = False, nonempty: bool = False) -> str:
    if absent:
        return "absent"
    if empty:
        return "present_but_empty"
    if nonempty:
        return "present_and_nonempty"
    return "unknown"


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
