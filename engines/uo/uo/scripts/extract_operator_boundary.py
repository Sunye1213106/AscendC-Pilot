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

OP_ADD_INPUT_RE = re.compile(
    r"""\.Input\s*\(\s*["']([^"']+)["']\s*\)""",
    re.MULTILINE,
)
OP_ADD_OPTIONAL_RE = re.compile(
    r"""\.OptionalInput\s*\(\s*["']([^"']+)["']\s*\)""",
    re.MULTILINE,
)
OP_ADD_ATTR_RE = re.compile(
    r"""\.Attr\s*\(\s*["']([^"']+)["']\s*\)""",
    re.MULTILINE,
)
OP_ADD_OUTPUT_RE = re.compile(
    r"""\.Output\s*\(\s*["']([^"']+)["']\s*\)""",
    re.MULTILINE,
)
GET_INPUT_SHAPE_RE = re.compile(r"Get(?:Optional)?InputShape\s*\(\s*(\d+)\s*\)")
GET_INPUT_DESC_RE = re.compile(r"Get(?:Optional)?InputDesc\s*\(\s*(\d+)\s*\)")
GET_ATTR_RE = re.compile(
    r"""GetAttr(?:Pointer)?\s*\(\s*(?:["']([^"']+)["']|(\d+))\s*\)"""
)
ATTR_DEFAULT_RE = re.compile(
    r"""\.Attr\s*\(\s*["']([^"']+)["']\s*\)[^;]*?\.AttrDefault\s*\(([^\)]*)\)""",
    re.DOTALL,
)


def extract_operator_boundary(repo_root: Path, op_name: str, *, architecture: str = "arch35") -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    files = _confirmed_sources(uo_root)
    inputs: list[dict[str, Any]] = []
    outputs: list[dict[str, Any]] = []
    attributes: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    optional_states: dict[str, str] = {}

    slot = 0
    for rel in files:
        if not arch_compatible(rel, architecture) and "/op_host/" not in rel and "reg" not in rel.lower():
            # Still scan registration files even if arch-neutral.
            if "reg" not in Path(rel).name.lower() and "op_host" not in rel:
                continue
        path = repo_root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in OP_ADD_INPUT_RE.finditer(text):
            name = match.group(1)
            inputs.append(
                {
                    "slot": slot,
                    "name": name,
                    "optional": False,
                    "dtype_constraints": [],
                    "format_constraints": [],
                    "host_accessors": [],
                    "binding_status": "verified",
                    "evidence": [{"file_path": rel, "line": text.count("\n", 0, match.start()) + 1, "macro": "Input"}],
                }
            )
            slot += 1
        for match in OP_ADD_OPTIONAL_RE.finditer(text):
            name = match.group(1)
            inputs.append(
                {
                    "slot": slot,
                    "name": name,
                    "optional": True,
                    "dtype_constraints": [],
                    "format_constraints": [],
                    "host_accessors": [],
                    "binding_status": "verified",
                    "evidence": [{"file_path": rel, "line": text.count("\n", 0, match.start()) + 1, "macro": "OptionalInput"}],
                }
            )
            optional_states[name] = "unknown"
            slot += 1
        for match in OP_ADD_OUTPUT_RE.finditer(text):
            outputs.append(
                {
                    "name": match.group(1),
                    "evidence": [{"file_path": rel, "line": text.count("\n", 0, match.start()) + 1}],
                }
            )
        defaults = {m.group(1): m.group(2).strip() for m in ATTR_DEFAULT_RE.finditer(text)}
        for match in OP_ADD_ATTR_RE.finditer(text):
            name = match.group(1)
            attributes.append(
                {
                    "slot_or_name": name,
                    "type": "",
                    "default": defaults.get(name),
                    "host_accessors": [],
                    "binding_status": "verified",
                    "evidence": [{"file_path": rel, "line": text.count("\n", 0, match.start()) + 1, "macro": "Attr"}],
                }
            )

    by_slot = {int(i["slot"]): i for i in inputs}
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
                # Keep positional slot without guessing a name.
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

    # Optional input state vocabulary (values filled later by provenance when evidence exists).
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
