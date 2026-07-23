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
from uo.scripts._ir_io import stable_id, write_yaml

BOOL_DECL_RE = re.compile(r"ASCENDC_TPL_BOOL_DECL\s*\(\s*([A-Za-z0-9_]+)\s*,\s*([^)]+)\)")
UINT_DECL_RE = re.compile(
    r"ASCENDC_TPL_UINT_DECL\s*\(\s*([A-Za-z0-9_]+)\s*,\s*([^,]+)\s*,\s*[^,]+,\s*([^)]+)\)"
)
SEL_RE = re.compile(r"ASCENDC_TPL_ARGS_SEL\s*\(")
# Generic: using Alias = Qual::ClassName<true/false, ...>;
TEMPLATE_ALIAS_RE = re.compile(
    r"using\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"
    r"((?:[A-Za-z_][A-Za-z0-9_:]*::)*[A-Za-z_][A-Za-z0-9_]*)"
    r"\s*<\s*((?:true|false)(?:\s*,\s*(?:true|false))*)\s*>\s*;",
    re.MULTILINE,
)
TEMPLATE_BOOL_CLASS_RE = re.compile(
    r"template\s*<([^>]+)>\s*(?:class|struct)\s+([A-Za-z_][A-Za-z0-9_]*)\b",
    re.MULTILINE,
)
BOOL_PARAM_NAME_RE = re.compile(r"(?:const\s+)?bool\s+([A-Za-z_][A-Za-z0-9_]*)")
INCLUDE_LOCAL_RE = re.compile(r'#\s*include\s+"([^"]+)"')
GET_KEY_BIT_RE = re.compile(
    r"(?:\(\s*([A-Za-z0-9_]+)\s*>>\s*(\d+)\s*\)\s*&\s*(0x[0-9A-Fa-f]+|\d+))|([A-Za-z0-9_]+)\s*=\s*\(\s*(?:key|tilingKey|k)\s*>>\s*(\d+)\s*\)\s*&\s*(0x[0-9A-Fa-f]+|\d+)",
    re.IGNORECASE,
)


def extract_tilingkey_space(repo_root: Path, op_name: str, *, architecture: str = "arch35") -> dict[str, Any]:
    header = _find_template_header(repo_root, op_name, architecture)
    if header is None:
        return {
            "version": 1,
            "op_name": op_name,
            "architecture": architecture,
            "status": "missing_template_header",
            "nodes": [],
            "edges": [],
            "template_blocks": [],
            "dimensions": [],
            "args_sel_count": 0,
        }
    text = header.read_text(encoding="utf-8", errors="ignore")
    rel = header.relative_to(repo_root).as_posix()
    dimensions = _parse_dimensions(text, rel)
    template_aliases = _parse_template_aliases(text, rel, header=header)
    args_sel_count = len(SEL_RE.findall(text))
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for dim in dimensions:
        node_id = stable_id("KEY_", dim["name"])
        nodes.append(
            {
                "id": node_id,
                "layer": "bridge",
                "node_type": "TilingKey",
                "name": dim["name"],
                "qualified_name": f"{rel}::{dim['name']}",
                "file_path": rel,
                "start_line": dim.get("line") or 0,
                "end_line": dim.get("line") or 0,
                "domain": dim.get("values"),
                "bit_width": dim.get("bit_width"),
                "decl_kind": dim.get("kind"),
            }
        )
    for alias in template_aliases:
        node_id = stable_id("KTPL_", alias["name"])
        nodes.append(
            {
                "id": node_id,
                "layer": "bridge",
                "node_type": "KernelTemplateArgument",
                "name": alias["name"],
                "qualified_name": f"{rel}::{alias['name']}",
                "file_path": rel,
                "start_line": alias.get("line") or 0,
                "end_line": alias.get("line") or 0,
                "template_flags": alias["flags"],
                "condition": alias["condition"],
            }
        )
        # Legal template instance → fixed KEY domain values (pruned set; not cartesian product).
        for flag_name, flag_val in (alias.get("flags") or {}).items():
            key_id = stable_id("KEY_", str(flag_name))
            edges.append(
                {
                    "source_id": node_id,
                    "target_id": key_id,
                    "edge_type": "fixes_flag",
                    "value": bool(flag_val) if isinstance(flag_val, bool) else flag_val,
                    "flag": str(flag_name),
                }
            )
    template_blocks = [
        {
            "id": stable_id("KTPL_", item["name"]),
            "name": item["name"],
            "flags": item["flags"],
            "condition": item["condition"],
            "source": rel,
        }
        for item in template_aliases
    ]
    return {
        "version": 1,
        "op_name": op_name,
        "architecture": architecture,
        "status": "ok",
        "source": rel,
        "args_sel_count": args_sel_count,
        "dimensions": dimensions,
        "template_aliases": template_aliases,
        "template_blocks": template_blocks,
        "nodes": nodes,
        "edges": edges,
        "unresolved": []
        if args_sel_count
        else [
            {
                "id": "UNRES_TPL_SEL_COUNT",
                "kind": "tilingkey_sel_missing",
                "message": "No ASCENDC_TPL_ARGS_SEL found",
                "file_path": rel,
                "snippet": "",
            }
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract tilingkey template space from ASCENDC_TPL_* macros")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--architecture", default="arch35")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    payload = extract_tilingkey_space(repo_root, op_name, architecture=args.architecture)
    if args.write:
        write_yaml(existing_operator_root(repo_root, op_name) / "ir" / "tilingkey_space.yaml", payload)
    print(f"tilingkey dims={len(payload.get('dimensions') or [])} sel={payload.get('args_sel_count')} templates={len(payload.get('template_blocks') or [])}")
    return 0


def _find_template_header(repo_root: Path, op_name: str, architecture: str) -> Path | None:
    patterns = [
        f"**/{op_name}/**/{architecture}/**/*template_tiling_key*.h",
        f"**/{architecture}/**/*template_tiling_key*.h",
        f"**/{op_name}/**/*template_tiling_key*.h",
    ]
    for pattern in patterns:
        hits = sorted(repo_root.glob(pattern))
        if hits:
            return hits[0]
    return None


def _parse_dimensions(text: str, rel: str) -> list[dict[str, Any]]:
    dims: list[dict[str, Any]] = []
    for match in BOOL_DECL_RE.finditer(text):
        name = match.group(1)
        values = [int(x.strip()) for x in match.group(2).split(",") if x.strip().isdigit()]
        dims.append(
            {
                "name": name,
                "kind": "bool",
                "bit_width": 1,
                "values": values or [0, 1],
                "line": text.count("\n", 0, match.start()) + 1,
                "file_path": rel,
            }
        )
    for match in UINT_DECL_RE.finditer(text):
        name = match.group(1)
        width_token = match.group(2).strip()
        width = _width_from_token(width_token)
        values = []
        for part in match.group(3).split(","):
            part = part.strip()
            if part.isdigit():
                values.append(int(part))
        dims.append(
            {
                "name": name,
                "kind": "uint",
                "bit_width": width,
                "values": values,
                "line": text.count("\n", 0, match.start()) + 1,
                "file_path": rel,
            }
        )
    return dims


def _parse_template_aliases(text: str, rel: str, *, header: Path | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    param_cache: dict[str, list[str]] = {}
    for match in TEMPLATE_ALIAS_RE.finditer(text):
        alias_name = match.group(1)
        qualified = match.group(2)
        class_name = qualified.rsplit("::", 1)[-1]
        bool_tokens = [tok.strip() for tok in match.group(3).split(",")]
        bool_values = [tok == "true" for tok in bool_tokens]
        param_names = param_cache.get(class_name)
        if param_names is None:
            param_names = _resolve_bool_template_params(text, class_name, header=header)
            param_cache[class_name] = param_names
        flags = _zip_bool_flags(param_names, bool_values)
        condition = ", ".join(f"{key}={value}" for key, value in flags.items())
        out.append(
            {
                "name": alias_name,
                "class_name": class_name,
                "flags": flags,
                "condition": condition,
                "line": text.count("\n", 0, match.start()) + 1,
                "file_path": rel,
            }
        )
    return out


def _zip_bool_flags(param_names: list[str], bool_values: list[bool]) -> dict[str, bool]:
    if param_names and len(param_names) == len(bool_values):
        keys = param_names
    else:
        keys = [f"arg{i}" for i in range(len(bool_values))]
    return {key: value for key, value in zip(keys, bool_values)}


def _resolve_bool_template_params(text: str, class_name: str, *, header: Path | None = None) -> list[str]:
    names = _bool_params_for_class(text, class_name)
    if names or header is None:
        return names
    seen: set[Path] = {header.resolve()}
    # Prefer local includes first (where tiling-data template classes usually live).
    for include in INCLUDE_LOCAL_RE.findall(text):
        path = (header.parent / include).resolve()
        if path in seen or not path.exists() or path.suffix not in {".h", ".hpp", ".inc"}:
            continue
        seen.add(path)
        names = _bool_params_for_class(path.read_text(encoding="utf-8", errors="ignore"), class_name)
        if names:
            return names
    # Fallback: sibling tiling-data headers in the same directory.
    for path in sorted(header.parent.glob("*tiling_data*.h")):
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        names = _bool_params_for_class(path.read_text(encoding="utf-8", errors="ignore"), class_name)
        if names:
            return names
    return []


def _bool_params_for_class(text: str, class_name: str) -> list[str]:
    for match in TEMPLATE_BOOL_CLASS_RE.finditer(text):
        if match.group(2) != class_name:
            continue
        names = BOOL_PARAM_NAME_RE.findall(match.group(1))
        if names:
            return names
    return []


def _width_from_token(token: str) -> int | None:
    mapping = {
        "ASCENDC_TPL_3_BW": 3,
        "ASCENDC_TPL_4_BW": 4,
        "ASCENDC_TPL_8_BW": 8,
        "ASCENDC_TPL_10_BW": 10,
        "ASCENDC_TPL_12_BW": 12,
    }
    if token in mapping:
        return mapping[token]
    if token.isdigit():
        return int(token)
    return None


if __name__ == "__main__":
    raise SystemExit(main())
