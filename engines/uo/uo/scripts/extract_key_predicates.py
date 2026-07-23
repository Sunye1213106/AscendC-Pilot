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
from uo.scripts._ir_io import read_yaml, stable_id, write_yaml

ASSIGN_RE = re.compile(
    r"(?P<lhs>(?:[\w]+(?:\.|->))*?(?P<field>[A-Za-z_][A-Za-z0-9_]*))\s*=\s*(?P<rhs>[^;]+);",
    re.MULTILINE,
)


def extract_key_predicates(repo_root: Path, op_name: str, *, architecture: str = "arch35") -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    tiling = read_yaml(uo_root / "ir" / "tilingkey_space.yaml")
    dimensions = tiling.get("dimensions") or []
    template_blocks = tiling.get("template_blocks") or []
    if not dimensions:
        graph = read_yaml(uo_root / "ir" / "operator_graph.yaml")
        dimensions = ((graph.get("tilingkey") or {}).get("dimensions")) or []
        template_blocks = ((graph.get("tilingkey") or {}).get("template_blocks")) or []

    field_aliases = _dimension_aliases(dimensions)
    host_files = _host_arch_files(repo_root, op_name, architecture)
    assignments: dict[str, list[dict[str, Any]]] = {str(dim["name"]): [] for dim in dimensions if dim.get("name")}

    for path in host_files:
        rel = path.relative_to(repo_root).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in ASSIGN_RE.finditer(text):
            field = match.group("field")
            dim_name = field_aliases.get(field.casefold())
            if not dim_name:
                continue
            line = text.count("\n", 0, match.start()) + 1
            rhs = " ".join(match.group("rhs").split())
            lhs = match.group("lhs").strip()
            if len(rhs) > 400:
                rhs = rhs[:397] + "..."
            assignments.setdefault(dim_name, []).append(
                {
                    "lhs": lhs,
                    "field": field,
                    "expr_raw": rhs,
                    "file_path": rel,
                    "start_line": line,
                    "literal_false": _contains_literal_false(rhs),
                    "literals": _extract_literals(rhs),
                }
            )

    cards = []
    for dim in dimensions:
        name = str(dim.get("name") or "")
        if not name:
            continue
        key_id = stable_id("KEY_", name)
        sets = assignments.get(name) or []
        sets_sorted = sorted(sets, key=lambda s: (-len(str(s.get("expr_raw") or "")), s.get("start_line") or 0))
        primary = sets_sorted[0] if sets_sorted else None
        card = {
            "id": key_id,
            "key": name,
            "architecture": architecture,
            "domain": dim.get("values") or [],
            "decl_kind": dim.get("kind"),
            "bit_width": dim.get("bit_width"),
            "template_legal": _template_legal_for_dim(name, template_blocks),
            "set_by": {
                "status": "found" if primary else "missing",
                "expr_raw": (primary or {}).get("expr_raw"),
                "lhs": (primary or {}).get("lhs"),
                "file_path": (primary or {}).get("file_path"),
                "start_line": (primary or {}).get("start_line"),
                "literal_false": (primary or {}).get("literal_false"),
                "literals": (primary or {}).get("literals") or {},
                "all_assignments": sets_sorted[:8],
            },
            "host_reachable": {
                "status": "unknown",
                "note": "code-only skeleton; semantic reachability left for bounded LLM",
            },
            "hit_recipe": {
                "status": "unknown",
                "note": "code-only skeleton; prefer/avoid recipes left for bounded LLM",
            },
        }
        cards.append(card)

    index = {
        "version": 1,
        "op_name": op_name,
        "architecture": architecture,
        "card_count": len(cards),
        "cards_with_set_by": sum(1 for c in cards if c["set_by"]["status"] == "found"),
        "keys": [{"id": c["id"], "key": c["key"], "path": f"tiling/key_cards/{c['id']}.yaml"} for c in cards],
    }
    return {"version": 1, "op_name": op_name, "architecture": architecture, "index": index, "cards": cards}


def apply_host_reachable_from_classify(uo_root: Path) -> int:
    """Overlay compact input-derivable markers onto key_cards (no full chains)."""
    uo_root = Path(uo_root)
    id_doc = read_yaml(uo_root / "ir" / "input_derivable.yaml")
    if not isinstance(id_doc, dict):
        return 0
    updated = 0
    cards_dir = uo_root / "tiling" / "key_cards"
    for key_id, entry in (id_doc.get("keys") or {}).items():
        if not isinstance(entry, dict):
            continue
        path = cards_dir / f"{key_id}.yaml"
        if not path.is_file():
            continue
        card = read_yaml(path)
        if not isinstance(card, dict):
            continue
        idv = entry.get("input_derivable")
        if idv is True:
            host = {
                "status": "reachable",
                "host_parent": entry.get("host_parent"),
                "host_parent_evidence": entry.get("host_parent_evidence") or "",
                "derivation_roots": list(entry.get("derivation_roots") or [])[:16],
                "note": "compact: one-hop parent + roots; walk KB determined_by/reaches_input",
            }
        elif idv is False or entry.get("not_input_derivable"):
            host = {
                "status": "not_input_derivable",
                "host_parent": entry.get("host_parent"),
                "note": entry.get("reason") or "kernel-local / no host input ancestor",
            }
        else:
            host = {
                "status": "unsolved",
                "host_parent": entry.get("host_parent"),
                "gap_ref": entry.get("gap_ref"),
                "gap_kind": entry.get("gap_kind"),
                "note": entry.get("reason") or "graph gap; escalate via uo-input-derivable-escalation",
            }
        card["host_reachable"] = host
        card["input_derivable"] = idv
        card["needs_binding"] = bool(entry.get("needs_binding"))
        card["not_input_derivable"] = bool(entry.get("not_input_derivable"))
        write_yaml(path, card)
        updated += 1
    return updated


def write_key_cards(uo_root: Path, payload: dict[str, Any]) -> None:
    cards_dir = uo_root / "tiling" / "key_cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    write_yaml(
        uo_root / "tiling" / "key_predicates.yaml",
        {
            "version": 1,
            "op_name": payload.get("op_name"),
            **(payload.get("index") or {}),
            "summary_cards": [
                {
                    "id": c["id"],
                    "key": c["key"],
                    "set_by_status": c["set_by"]["status"],
                    "expr_raw": c["set_by"].get("expr_raw"),
                    "file_path": c["set_by"].get("file_path"),
                    "start_line": c["set_by"].get("start_line"),
                }
                for c in payload.get("cards") or []
            ],
        },
    )
    write_yaml(cards_dir / "index.yaml", payload.get("index") or {})
    for card in payload.get("cards") or []:
        write_yaml(cards_dir / f"{card['id']}.yaml", card)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract tiling-key set_by predicate skeletons (code-only)")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--architecture", default="arch35")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    payload = extract_key_predicates(repo_root, op_name, architecture=args.architecture)
    if args.write:
        write_key_cards(existing_operator_root(repo_root, op_name), payload)
    print(
        f"key_cards={payload['index']['card_count']} "
        f"with_set_by={payload['index']['cards_with_set_by']}"
    )
    return 0


def _dimension_aliases(dimensions: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for dim in dimensions:
        name = str(dim.get("name") or "")
        if not name:
            continue
        out[name.casefold()] = name
        if name.startswith("Is") and len(name) > 2:
            camel = name[0].lower() + name[1:]
            out[camel.casefold()] = name
            out[name[2:].casefold()] = name
        out[(name[0].lower() + name[1:]).casefold()] = name
    return out


def _host_arch_files(repo_root: Path, op_name: str, architecture: str) -> list[Path]:
    patterns = [
        f"**/{op_name}/op_host/{architecture}/**/*.cpp",
        f"**/{op_name}/op_host/{architecture}/**/*.h",
        f"**/{op_name}/**/{architecture}/**/*tiling*.cpp",
    ]
    files: list[Path] = []
    seen: set[str] = set()
    for pattern in patterns:
        for path in sorted(repo_root.glob(pattern)):
            key = path.resolve().as_posix()
            if key in seen:
                continue
            seen.add(key)
            files.append(path)
    return files


def _contains_literal_false(expr: str) -> bool:
    compact = expr.replace(" ", "")
    return bool(re.search(r"\bfalse\b", expr)) or "&&false" in compact


def _extract_literals(expr: str) -> dict[str, list[Any]]:
    nums = [int(x) for x in re.findall(r"(?<![\w.])(\d+)(?![\w.])", expr)]
    enums = re.findall(r"\b([A-Z][A-Z0-9_]{2,})\b", expr)
    compares = re.findall(r"([A-Za-z_][\w\.]*)\s*(>=|<=|==|!=|>|<)\s*(\d+)", expr)
    return {
        "numbers": sorted(set(nums))[:20],
        "enums": sorted(set(enums))[:20],
        "comparisons": [{"lhs": a, "op": b, "rhs": int(c)} for a, b, c in compares[:20]],
    }


def _template_legal_for_dim(dim_name: str, template_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flag_key = None
    if dim_name.startswith("Is") and len(dim_name) > 2:
        flag_key = dim_name[0].lower() + dim_name[1:]
    out = []
    for block in template_blocks:
        flags = block.get("flags") or {}
        if flag_key and flag_key in flags:
            out.append(
                {
                    "template": block.get("name") or block.get("id"),
                    "id": block.get("id"),
                    "flags": flags,
                    "value": 1 if flags.get(flag_key) else 0,
                }
            )
        elif not flag_key:
            out.append({"template": block.get("name") or block.get("id"), "id": block.get("id"), "flags": flags})
    return out[:20]


if __name__ == "__main__":
    raise SystemExit(main())
