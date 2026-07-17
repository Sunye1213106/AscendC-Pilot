from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo.scripts._ir_io import write_yaml

FUNC_CANDIDATES = (
    "attentionScoreWithGrad",
    "golden",
    "cpu_golden",
    "reference",
)
INPUT_CASE_RE = re.compile(
    r"""(?:ctx\.)?input_case\s*(?:\[\s*['"]([A-Za-z0-9_]+)['"]\s*\]|\.get\s*\(\s*['"]([A-Za-z0-9_]+)['"])"""
)


def extract_golden(repo_root: Path, op_name: str) -> dict[str, Any]:
    files = _discover_cpu_impl(repo_root, op_name)
    unresolved: list[dict[str, Any]] = []
    if not files:
        unresolved.append(
            {
                "id": "UNRES_GOLDEN_FILE",
                "kind": "golden_missing",
                "message": "cpu_impl.py not found",
                "file_path": "",
                "snippet": "",
            }
        )
        return {"version": 1, "op_name": op_name, "status": "missing", "nodes": [], "edges": [], "unresolved": unresolved}

    best: dict[str, Any] | None = None
    helpers: list[dict[str, Any]] = []
    for path in files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel = path.relative_to(repo_root).as_posix()
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None
        for fname in FUNC_CANDIDATES:
            func_node = _find_func(tree, fname) if tree is not None else None
            if func_node is None and not re.search(rf"def\s+{fname}\s*\(", text):
                continue
            start_line = int(getattr(func_node, "lineno", 0) or (text.split(f"def {fname}")[0].count("\n") + 1))
            end_line = int(getattr(func_node, "end_lineno", 0) or start_line)
            body_text = "\n".join(text.splitlines()[start_line - 1 : end_line])
            keys = _input_case_keys(body_text, func_node)
            defaults = _input_case_defaults(body_text)
            calls = _direct_calls(func_node) if func_node is not None else _regex_calls(body_text)
            returns = _return_names(func_node) if func_node is not None else []
            ctx_writes = _ctx_assigns(func_node) if func_node is not None else []
            dtype_layout = _literal_domains(body_text)
            helpers = _helper_catalog(tree, calls, rel) if tree is not None else []
            best = {
                "function": fname,
                "file_path": rel,
                "start_line": start_line,
                "end_line": end_line,
                "signature": _signature_from_ast(func_node) if func_node is not None else _signature(text, fname),
                "annotated_args": _annotated_args(func_node) if func_node is not None else [],
                "doc": ast.get_docstring(func_node) if func_node is not None else "",
                "role": "numeric_oracle",
                "pipeline": {
                    "datagen": [c for c in calls if c.lower() in {"datagen", "data_gen"}],
                    "forward": [c for c in calls if "forward" in c.lower()],
                    "backward": [c for c in calls if "backward" in c.lower()],
                    "other_helpers": [
                        c
                        for c in calls
                        if c.lower() not in {"datagen", "data_gen"}
                        and "forward" not in c.lower()
                        and "backward" not in c.lower()
                    ],
                },
                "direct_calls": calls,
                "input_case_keys": keys,
                "input_case_defaults": defaults,
                "dtype_layout_literals": dtype_layout,
                "ctx_tensor_writes": ctx_writes,
                "return_tensors": returns or ["dq_golden", "dk_golden", "dv_golden"],
                "outputs": _outputs_from_returns(returns),
                "helpers": helpers,
            }
            break
        if best:
            break

    if best is None:
        unresolved.append(
            {
                "id": "UNRES_GOLDEN_FUNC",
                "kind": "golden_function_missing",
                "message": "No golden-like function found in cpu_impl.py",
                "file_path": files[0].relative_to(repo_root).as_posix(),
                "snippet": "",
            }
        )
        return {
            "version": 1,
            "op_name": op_name,
            "status": "missing_function",
            "nodes": [],
            "edges": [],
            "unresolved": unresolved,
        }

    nodes = [
        {
            "id": "NUM_GOLDEN",
            "layer": "host",
            "node_type": "GoldenFunction",
            "name": best["function"],
            "qualified_name": f"{best['file_path']}::{best['function']}",
            "file_path": best["file_path"],
            "start_line": best["start_line"],
            "end_line": best["end_line"],
            "signature": best["signature"],
            "input_case_keys": best["input_case_keys"],
            "return_tensors": best["return_tensors"],
            "outputs": best["outputs"],
            "role": "numeric_oracle",
        }
    ]
    edges = []
    for helper in helpers:
        hid = f"NUM_GOLDEN_HELPER_{helper['name'].upper()}"
        nodes.append(
            {
                "id": hid,
                "layer": "host",
                "node_type": "GoldenHelper",
                "name": helper["name"],
                "qualified_name": f"{helper['file_path']}::{helper['name']}",
                "file_path": helper["file_path"],
                "start_line": helper["start_line"],
                "end_line": helper["end_line"],
                "signature": helper["signature"],
                "role": helper.get("role") or "helper",
            }
        )
        edges.append({"id": f"E_GOLDEN_CALLS_{helper['name'].upper()}", "type": "calls", "source": "NUM_GOLDEN", "target": hid})

    return {
        "version": 1,
        "op_name": op_name,
        "status": "ok",
        "golden": best,
        "nodes": nodes,
        "edges": edges,
        "unresolved": unresolved,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract golden/cpu reference function metadata")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    payload = extract_golden(repo_root, op_name)
    if args.write:
        write_yaml(existing_operator_root(repo_root, op_name) / "ir" / "golden.yaml", payload)
    g = payload.get("golden") or {}
    print(
        f"golden status={payload.get('status')} "
        f"fn={g.get('function')} lines={g.get('start_line')}-{g.get('end_line')} "
        f"keys={len(g.get('input_case_keys') or [])} helpers={len(g.get('helpers') or [])}"
    )
    return 0


def _discover_cpu_impl(repo_root: Path, op_name: str) -> list[Path]:
    candidates = list(repo_root.glob(f"**/{op_name}/tests/**/cpu_impl.py"))
    candidates += list(repo_root.glob("**/tests/**/cpu_impl.py"))
    candidates += list(repo_root.glob("**/cpu_impl.py"))
    seen: set[str] = set()
    files: list[Path] = []
    for path in candidates:
        key = path.resolve().as_posix()
        if key in seen:
            continue
        seen.add(key)
        files.append(path)
    # Prefer op-scoped pytest impl first.
    files.sort(key=lambda p: (0 if op_name in p.as_posix() else 1, 0 if "pytest" in p.as_posix() else 1, p.as_posix()))
    return files


def _find_func(tree: ast.AST | None, name: str) -> ast.FunctionDef | None:
    if tree is None:
        return None
    for node in getattr(tree, "body", []) or []:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _signature(text: str, func_name: str) -> str:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        match = re.search(rf"def\s+{func_name}\s*\((.*?)\)\s*:", text, re.DOTALL)
        return f"def {func_name}({match.group(1).strip()})" if match else func_name
    node = _find_func(tree, func_name)
    return _signature_from_ast(node) if node is not None else func_name


def _signature_from_ast(node: ast.FunctionDef) -> str:
    args = []
    for a in node.args.args:
        ann = ast.unparse(a.annotation) if a.annotation is not None else ""
        args.append(f"{a.arg}: {ann}" if ann else a.arg)
    ret = ast.unparse(node.returns) if node.returns is not None else ""
    sig = f"def {node.name}({', '.join(args)})"
    return f"{sig} -> {ret}" if ret else sig


def _annotated_args(node: ast.FunctionDef) -> list[dict[str, str]]:
    out = []
    for a in node.args.args:
        out.append(
            {
                "name": a.arg,
                "annotation": ast.unparse(a.annotation) if a.annotation is not None else "",
            }
        )
    return out


def _input_case_keys(body_text: str, func_node: ast.FunctionDef | None) -> list[str]:
    keys = set()
    for m in INPUT_CASE_RE.finditer(body_text):
        keys.add(m.group(1) or m.group(2))
    if func_node is not None:
        for n in ast.walk(func_node):
            if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Attribute) and n.value.attr == "input_case":
                key = _const_str(n.slice)
                if key:
                    keys.add(key)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get":
                if isinstance(n.func.value, ast.Attribute) and n.func.value.attr == "input_case" and n.args:
                    key = _const_str(n.args[0])
                    if key:
                        keys.add(key)
    return sorted(k for k in keys if k)


def _input_case_defaults(body_text: str) -> dict[str, str]:
    defaults: dict[str, str] = {}
    # pattern: ctx.input_case.get("x", DEFAULT) or ternary with "x" in input_case else DEFAULT
    for m in re.finditer(
        r"""input_case\.get\(\s*['"]([A-Za-z0-9_]+)['"]\s*,\s*([^)]+)\)""",
        body_text,
    ):
        defaults[m.group(1)] = " ".join(m.group(2).split())
    for m in re.finditer(
        r"""input_case\[['\"]([A-Za-z0-9_]+)['\"]\]\s+if\s+[^\n]+else\s+([^\n#]+)""",
        body_text,
    ):
        defaults.setdefault(m.group(1), " ".join(m.group(2).split()))
    return defaults


def _literal_domains(body_text: str) -> dict[str, list[str]]:
    domains: dict[str, list[str]] = {}
    for key, pattern in (
        ("dtype", r"""['"](fp16|bf16|fp32|fp8_e4m3fn|fp8_e5m2)['"]"""),
        ("input_layout", r"""['"](BSH|SBH|BSND|BNSD|TND)['"]"""),
        ("atten_mask_shape", r"""['"](SS|B1SS|BNSS|NONE)['"]"""),
    ):
        vals = sorted(set(re.findall(pattern, body_text)))
        if vals:
            domains[key] = vals
    return domains


def _direct_calls(func_node: ast.FunctionDef) -> list[str]:
    names = set()
    for n in ast.walk(func_node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            names.add(n.func.id)
    # Drop builtins / noise
    noise = {"len", "range", "sum", "min", "max", "abs", "print", "enumerate", "zip", "sorted", "list", "dict", "set", "tuple"}
    return sorted(n for n in names if n not in noise)


def _regex_calls(body_text: str) -> list[str]:
    return sorted(set(re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", body_text)))


def _return_names(func_node: ast.FunctionDef) -> list[str]:
    names: list[str] = []
    for n in ast.walk(func_node):
        if not isinstance(n, ast.Return) or n.value is None:
            continue
        if isinstance(n.value, ast.Tuple):
            for elt in n.value.elts:
                if isinstance(elt, ast.Name):
                    names.append(elt.id)
        elif isinstance(n.value, ast.Name):
            names.append(n.value.id)
    # preserve order, unique
    out: list[str] = []
    for name in names:
        if name not in out:
            out.append(name)
    return out


def _ctx_assigns(func_node: ast.FunctionDef) -> list[str]:
    names: list[str] = []
    for n in ast.walk(func_node):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "ctx":
                    if t.attr not in names:
                        names.append(t.attr)
    return names


def _outputs_from_returns(returns: list[str]) -> list[str]:
    mapping = {
        "dq_golden": "dq",
        "dk_golden": "dk",
        "dv_golden": "dv",
        "dq_rope_golden": "dq_rope",
        "dk_rope_golden": "dk_rope",
    }
    out = []
    for name in returns:
        out.append(mapping.get(name, name.replace("_golden", "")))
    return out or ["dq", "dk", "dv"]


def _helper_catalog(tree: ast.AST, calls: list[str], rel: str) -> list[dict[str, Any]]:
    wanted = {"DataGen", "tforward", "tbackward", "get_drop_mask", "run_unpad"}
    selected = [c for c in calls if c in wanted] or [c for c in calls if c[0].islower() is False or c.startswith("t")]
    # Prefer the key pipeline helpers when present.
    order = ["DataGen", "tforward", "tbackward", "get_drop_mask", "run_unpad"]
    ranked = [n for n in order if n in calls] + [c for c in calls if c not in order and c in wanted]
    out = []
    for name in ranked[:8]:
        node = _find_func(tree, name)
        if node is None:
            continue
        role = "datagen" if name == "DataGen" else ("forward" if "forward" in name.lower() else ("backward" if "backward" in name.lower() else "helper"))
        out.append(
            {
                "name": name,
                "file_path": rel,
                "start_line": node.lineno,
                "end_line": int(getattr(node, "end_lineno", node.lineno) or node.lineno),
                "signature": _signature_from_ast(node),
                "role": role,
            }
        )
    return out


def _const_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


if __name__ == "__main__":
    raise SystemExit(main())
