#!/usr/bin/env python3
"""Fail-closed: deterministic engines may only read declared run-state fields.

Runtime always injects identity (run_id / op_name / architecture / workflow_id
plus test_script_root / level / focus). Any other run-state field the engine
reads via ``ctx.get`` / ``ctx[...]`` must appear on the Action's
``consumes_state``. Optional knobs (budget, seed, …) are ignored.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENGINES_PY = REPO / "pilot" / "ascendc_pilot" / "actions" / "engines.py"

IDENTITY_CTX_KEYS = frozenset(
    {
        "run_id",
        "op_name",
        "architecture",
        "workflow_id",
        "test_script_root",
        "level",
        "focus",
        "action_id",
    }
)
STATE_CTX_KEYS = frozenset(
    {
        "pr_url",
        "intent",
        "description",
        "targets",
        "constraints",
        "pinned_digest",
        "uo_path",
    }
)
STATE_ALIASES = {"description": "intent"}


def _const_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _ctx_keys_from_node(node: ast.AST) -> set[str]:
    keys: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            if (
                isinstance(child.func.value, ast.Name)
                and child.func.value.id == "ctx"
                and child.func.attr == "get"
                and child.args
            ):
                key = _const_str(child.args[0])
                if key:
                    keys.add(key)
        elif isinstance(child, ast.Subscript) and isinstance(child.value, ast.Name):
            if child.value.id == "ctx":
                key = _const_str(child.slice)
                if key:
                    keys.add(key)
    return keys


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }


def _called_names(fn: ast.FunctionDef) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(fn):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
            names.add(child.func.id)
    return names


def _collect_ctx_keys(fn: ast.FunctionDef, funcs: dict[str, ast.FunctionDef], *, depth: int = 2) -> set[str]:
    keys = _ctx_keys_from_node(fn)
    if depth <= 0:
        return keys
    for name in _called_names(fn):
        callee = funcs.get(name)
        if callee is None:
            continue
        keys |= _collect_ctx_keys(callee, funcs, depth=depth - 1)
    return keys


def _registry_entries(tree: ast.Module) -> list[tuple[str, str, str]]:
    """Return (workflow_id, action_id, engine_fn_name) for Name-bound engines."""
    rows: list[tuple[str, str, str]] = []
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign) and not isinstance(node, ast.Assign):
            continue
        target = node.target if isinstance(node, ast.AnnAssign) else (
            node.targets[0] if node.targets else None
        )
        if not isinstance(target, ast.Name) or target.id != "ENGINE_REGISTRY":
            continue
        value = node.value
        if not isinstance(value, ast.Dict):
            continue
        for key_node, val_node in zip(value.keys, value.values):
            if not isinstance(key_node, ast.Tuple) or len(key_node.elts) != 2:
                continue
            wid = _const_str(key_node.elts[0])
            aid = _const_str(key_node.elts[1])
            if not wid or not aid:
                continue
            if isinstance(val_node, ast.Name):
                rows.append((wid, aid, val_node.id))
    return rows


def audit(repo: Path | None = None) -> list[str]:
    repo = (repo or REPO).expanduser().resolve()
    engines_py = repo / "pilot" / "ascendc_pilot" / "actions" / "engines.py"
    tree = ast.parse(engines_py.read_text(encoding="utf-8"), filename=str(engines_py))
    funcs = _functions(tree)
    registry = _registry_entries(tree)

    sys.path.insert(0, str(repo / "pilot"))
    from ascendc_pilot.workflows import WORKFLOWS  # noqa: WPS433

    errors: list[str] = []
    for wid, aid, fn_name in registry:
        fn = funcs.get(fn_name)
        if fn is None:
            continue
        used = _collect_ctx_keys(fn, funcs) & STATE_CTX_KEYS
        # description is an alias of CE intent only when the engine also reads intent.
        if "description" in used and "intent" not in used:
            used.discard("description")
        normalized: set[str] = set()
        for key in used:
            normalized.add(STATE_ALIASES.get(key, key))
        meta = WORKFLOWS.get(wid) or {}
        action = next(
            (
                row
                for row in (meta.get("actions") or [])
                if isinstance(row, dict) and str(row.get("id") or "") == aid
            ),
            None,
        )
        if action is None:
            errors.append(f"{wid}/{aid}: ENGINE_REGISTRY action missing from Workflow Spec")
            continue
        declared = {
            STATE_ALIASES.get(str(k), str(k))
            for k in (action.get("consumes_state") or [])
        }
        extra = sorted(declared - STATE_CTX_KEYS)
        if extra:
            errors.append(
                f"{wid}/{aid}: consumes_state {extra} not in known run-state schema"
            )
        missing = sorted(normalized - declared)
        if missing:
            errors.append(
                f"{wid}/{aid}: engine reads state {missing} but consumes_state={sorted(declared)}"
            )
    return errors


def main() -> int:
    errs = audit(REPO)
    if errs:
        print("ENGINE_CONTEXT_CONTRACT:")
        for err in errs:
            print(f"  - {err}")
        return 1
    print("engine_context_ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
