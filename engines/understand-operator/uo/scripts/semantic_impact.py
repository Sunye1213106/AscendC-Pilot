"""Change impact over the input-rooted relation graph."""
from __future__ import annotations

from typing import Any

from uo.scripts.semantic_relations import index_entities, index_relations_by_type


def impact_from_change_set(
    graph: dict[str, Any],
    change_set: dict[str, Any] | None = None,
    *,
    touched_symbols: list[str] | None = None,
    touched_files: list[str] | None = None,
) -> dict[str, Any]:
    """Propagate change hits along relations; return affected surfaces + input roots."""
    by_ent = index_entities(graph)
    by_type = index_relations_by_type(graph)
    symbols = {str(s).strip() for s in (touched_symbols or []) if str(s).strip()}
    files = {
        str(f).replace("\\", "/").strip()
        for f in (touched_files or [])
        if str(f).strip()
    }
    if isinstance(change_set, dict):
        for s in change_set.get("symbols") or change_set.get("touched_symbols") or []:
            if s:
                symbols.add(str(s).strip())
        for f in change_set.get("files") or change_set.get("touched_files") or []:
            if f:
                files.add(str(f).replace("\\", "/").strip())

    # Seed entities whose symbol or evidence file matches.
    seeds: set[str] = set()
    for eid, ent in by_ent.items():
        sym = str(ent.get("symbol") or "")
        if sym and sym in symbols:
            seeds.add(eid)
        fp = str(ent.get("file_path") or "").replace("\\", "/")
        if fp and fp in files:
            seeds.add(eid)

    # Also seed relations whose subject/object symbols match.
    for rels in by_type.values():
        for rel in rels:
            if not isinstance(rel, dict):
                continue
            for key in ("subject", "object"):
                node = str(rel.get(key) or "")
                ent = by_ent.get(node) or {}
                sym = str(ent.get("symbol") or node.split(":")[-1])
                if sym in symbols or node in symbols:
                    seeds.add(node)

    # Forward adjacency
    forward: dict[str, set[str]] = {}
    backward: dict[str, set[str]] = {}
    for rel in graph.get("relations") or []:
        if not isinstance(rel, dict):
            continue
        sub = str(rel.get("subject") or "")
        obj = str(rel.get("object") or "")
        if sub and obj:
            forward.setdefault(sub, set()).add(obj)
            backward.setdefault(obj, set()).add(sub)
            # Also allow subject→subject for WRITES side effects via shared receivers
        t = str(rel.get("type") or "").upper()
        if t in {"WRITES", "BINDS", "COMPOSES_KEY", "GUARDS", "SELECTS_TEMPLATE", "READS"}:
            if sub:
                forward.setdefault(sub, set())
            if obj:
                forward.setdefault(obj, set())

    # BFS forward from seeds
    affected: set[str] = set(seeds)
    stack = list(seeds)
    while stack:
        cur = stack.pop()
        for nxt in forward.get(cur) or []:
            if nxt not in affected:
                affected.add(nxt)
                stack.append(nxt)

    # BFS backward to input roots
    input_deps: set[str] = set()
    stack = list(affected)
    seen_b: set[str] = set()
    while stack:
        cur = stack.pop()
        if cur in seen_b:
            continue
        seen_b.add(cur)
        ent = by_ent.get(cur) or {}
        if ent.get("kind") == "input_root" or str(cur).startswith("input_root:"):
            input_deps.add(cur)
        for prev in backward.get(cur) or []:
            stack.append(prev)
        # GROUNDED_IN edges: subject → input
        for rel in by_type.get("GROUNDED_IN") or []:
            if str(rel.get("subject") or "") == cur:
                obj = str(rel.get("object") or "")
                if obj:
                    input_deps.add(obj)

    def _collect(kind: str) -> list[dict[str, Any]]:
        out = []
        for eid in sorted(affected):
            ent = by_ent.get(eid) or {}
            if ent.get("kind") == kind or (
                kind == "tiling_field" and ent.get("kind") == "tiling_field"
            ):
                out.append({"id": eid, "symbol": ent.get("symbol"), "kind": ent.get("kind")})
        return out

    affected_fields = _collect("tiling_field")
    affected_keys = _collect("key") + _collect("key_dimension")
    affected_templates = _collect("template")
    affected_conditions = _collect("condition")
    affected_branches = _collect("branch")
    affected_kernel = _collect("local")  # aliases / derived used by kernel

    coverage_obligations = []
    for root_id in sorted(input_deps):
        ent = by_ent.get(root_id) or {}
        coverage_obligations.append(
            {
                "input_root": root_id,
                "symbol": ent.get("symbol") or str(root_id).split(":")[-1],
                "input_kind": ent.get("input_kind") or "other_input",
                "affects_fields": [x["id"] for x in affected_fields],
                "affects_keys": [x["id"] for x in affected_keys],
                "affects_templates": [x["id"] for x in affected_templates],
                "affects_conditions": [x["id"] for x in affected_conditions],
            }
        )

    return {
        "version": 1,
        "seed_count": len(seeds),
        "seeds": sorted(seeds),
        "affected_tiling_fields": affected_fields,
        "affected_key_dimensions": affected_keys,
        "affected_templates": affected_templates,
        "affected_conditions": affected_conditions,
        "affected_branches": affected_branches,
        "affected_kernel_loads": affected_kernel,
        "dependent_input_roots": [
            {
                "id": rid,
                "symbol": (by_ent.get(rid) or {}).get("symbol") or rid.split(":")[-1],
                "input_kind": (by_ent.get(rid) or {}).get("input_kind"),
            }
            for rid in sorted(input_deps)
        ],
        "coverage_obligations": coverage_obligations,
    }


__all__ = ["impact_from_change_set"]
