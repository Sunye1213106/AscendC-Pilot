"""Classify KEY/KVAR input-derivability via Host graph walk.

Compact product (no per-KEY full chain dump):
- input_derivable: true | false | unsolved
- host_parent: one-hop writer / set_by symbol
- derivation_roots: input-face nodes when true
- graph_markers: determined_by / reaches_input edges for KB graph overlay

LLM gap patches: ir/input_derivable_patch.yaml → applied before emit.
Gaps report: ir/input_derivable_gaps.yaml for unsolved leftovers.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo.scripts._ir_io import read_yaml, stable_id, write_yaml

INPUT_ROOT_TYPES = frozenset(
    {
        "Attribute",
        "Input",
        "OptionalInputPresence",
        "OptionalInput",
        "InputShape",
        "InputDType",
        "InputLayout",
    }
)
# Platform / compile-time: terminal but not "CSV-facing" roots alone.
COMPILE_ROOT_TYPES = frozenset({"PlatformInfo", "CompileTimeConfig"})

KERNEL_LOCAL_RE = re.compile(
    r"(?i)^(blockId|taskId|coreIdx|coreId|loopIdx|innerIdx|outerIdx|"
    r"bufferId|queueId|pingPong|roundId|tileIdx|waveIdx)$"
)

IDENT_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")

WALK_EDGE_TYPES = frozenset(
    {
        "writes",
        "derives",
        "contains",
        "predicate_of",
        "branch_selects",
        "calls",
        "uses",
        "determined_by",
    }
)


def classify_and_write(
    uo_root: Path,
    graph: dict[str, Any] | None = None,
    *,
    max_depth: int = 12,
) -> dict[str, Any]:
    """Classify keys, write ir/input_derivable.yaml + gaps; return payload."""
    uo_root = Path(uo_root)
    if graph is None:
        graph = read_yaml(uo_root / "ir" / "operator_graph.yaml")
    if not isinstance(graph, dict):
        graph = {}

    patch = read_yaml(uo_root / "ir" / "input_derivable_patch.yaml")
    patch_by_key = _index_patch(patch)

    # KEY hard reject on closing patches (empty-only / missing triage+receipt)
    rejected_patches: list[dict[str, str]] = []
    blocked_patch_keys: set[str] = set()
    try:
        from ascendc_harness.gates import reject_key_patch_batch

        # uo_root is <repo>/.ascendc-agent/uo → project is parent.parent
        project_root = uo_root.parent.parent
        items: list[dict[str, Any]] = []
        for kid, item in list(patch_by_key.items()):
            row = dict(item)
            row.setdefault("id", kid)
            row.setdefault("key_id", kid)
            items.append(row)
        rejected_patches = reject_key_patch_batch(project_root, uo_root, items)
        blocked_patch_keys = {str(r.get("id") or "") for r in rejected_patches}
        for kid in blocked_patch_keys:
            patch_by_key.pop(kid, None)
    except ImportError:
        rejected_patches = []

    nodes_by_id = {
        str(n.get("id")): n
        for n in (graph.get("nodes") or [])
        if isinstance(n, dict) and n.get("id")
    }
    reverse_adj, forward_writes = _build_adjacency(graph)

    key_cards = _load_key_cards(uo_root)
    dimensions = ((graph.get("tilingkey") or {}).get("dimensions")) or []
    key_ids: list[str] = []
    for dim in dimensions:
        name = str(dim.get("name") or "")
        if name:
            key_ids.append(stable_id("KEY_", name))
    for nid, node in nodes_by_id.items():
        if node.get("node_type") == "TilingKey" and nid not in key_ids:
            key_ids.append(nid)
    for kid in key_cards:
        if kid not in key_ids:
            key_ids.append(kid)

    keys_out: dict[str, Any] = {}
    markers: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []

    for key_id in sorted(set(key_ids)):
        if key_id in patch_by_key:
            entry = _entry_from_patch(key_id, patch_by_key[key_id])
        else:
            entry = _classify_one(
                key_id,
                nodes_by_id=nodes_by_id,
                reverse_adj=reverse_adj,
                forward_writes=forward_writes,
                key_card=key_cards.get(key_id) or {},
                max_depth=max_depth,
            )
        keys_out[key_id] = entry
        parent = entry.get("host_parent")
        if parent:
            markers.append(
                {
                    "source": key_id,
                    "target": str(parent),
                    "type": "determined_by",
                    "evidence": entry.get("host_parent_evidence") or "",
                }
            )
        for root in entry.get("derivation_roots") or []:
            markers.append({"source": key_id, "target": str(root), "type": "reaches_input"})

        if entry.get("input_derivable") == "unsolved":
            gaps.append(
                {
                    "id": f"IDGAP_{key_id}",
                    "target": key_id,
                    "gap_kind": entry.get("gap_kind") or "chain_incomplete",
                    "status": "unresolved",
                    "confidence": "low",
                    "reason": entry.get("reason")
                    or "图回溯未接到 Host 输入根；需 uo-key-resolve / CBM 补边或确认 not_input_derivable",
                    "evidence": [entry.get("host_parent_evidence")] if entry.get("host_parent_evidence") else [],
                    "host_parent": parent,
                    "tried_frontier": entry.get("tried_frontier") or [],
                }
            )
            entry["gap_ref"] = f"IDGAP_{key_id}"

    # Kernel variables: mark obvious locals
    kvar_marks: dict[str, Any] = {}
    for nid, node in nodes_by_id.items():
        if node.get("node_type") != "KernelVariable":
            continue
        name = str(node.get("name") or node.get("canonical_name") or "")
        if KERNEL_LOCAL_RE.match(name) or _looks_kernel_local(name):
            kvar_marks[nid] = {
                "input_derivable": False,
                "not_input_derivable": True,
                "needs_binding": False,
                "host_parent": None,
                "reason": "kernel_local_batch_or_loop_index",
            }

    payload = {
        "version": 1,
        "op_name": graph.get("op_name"),
        "keys": keys_out,
        "kvars": kvar_marks,
        "graph_markers": markers,
        "rejected_patches": rejected_patches,
        "stats": {
            "true": sum(1 for v in keys_out.values() if v.get("input_derivable") is True),
            "false": sum(1 for v in keys_out.values() if v.get("input_derivable") is False),
            "unsolved": sum(1 for v in keys_out.values() if v.get("input_derivable") == "unsolved"),
            "rejected_patches": len(rejected_patches),
        },
    }
    write_yaml(uo_root / "ir" / "input_derivable.yaml", payload)
    write_yaml(
        uo_root / "ir" / "input_derivable_gaps.yaml",
        {
            "version": 1,
            "status": "closed" if not gaps else "open",
            "gaps": gaps,
        },
    )
    return payload


def apply_input_derivable_patch(uo_root: Path) -> dict[str, Any]:
    """Re-run classify (patch file is auto-consumed)."""
    return classify_and_write(uo_root)


def _classify_one(
    key_id: str,
    *,
    nodes_by_id: dict[str, dict[str, Any]],
    reverse_adj: dict[str, list[tuple[str, str]]],
    forward_writes: dict[str, list[str]],
    key_card: dict[str, Any],
    max_depth: int,
) -> dict[str, Any]:
    set_by = key_card.get("set_by") if isinstance(key_card.get("set_by"), dict) else {}
    set_status = str(set_by.get("status") or "")
    expr_raw = str(set_by.get("expr_raw") or "")
    evidence = ""
    if set_by.get("file_path"):
        evidence = f"{set_by.get('file_path')}:{set_by.get('start_line') or 0}"

    writers = list(forward_writes.get(key_id) or [])
    # reverse_adj: target -> [(source, etype)] where edge source -etype-> target
    # For writes Helper -> KEY, reverse gives Helper as parent
    rev_writers = [src for src, et in reverse_adj.get(key_id) or [] if et == "writes"]
    host_parent = None
    if rev_writers:
        host_parent = rev_writers[0]
    elif writers:
        host_parent = writers[0]
    else:
        # Parse first call-like ident from expr as parent hint
        idents = [m.group(1) for m in IDENT_RE.finditer(expr_raw)]
        skip = {"static_cast", "uint32_t", "int32_t", "true", "false", "nullptr"}
        for ident in idents:
            if ident in skip:
                continue
            # Prefer call-like / camelCase helpers over ALL_CAPS macros.
            if ident.startswith("Get") or (not ident.isupper()):
                host_parent = f"SYM::{ident}"
                break
        if host_parent is None:
            for ident in idents:
                if ident not in skip:
                    host_parent = f"SYM::{ident}"
                    break

    if set_status == "missing" and not rev_writers and not writers:
        return {
            "input_derivable": "unsolved",
            "confidence": "low",
            "needs_binding": True,
            "not_input_derivable": False,
            "host_parent": host_parent,
            "host_parent_evidence": evidence,
            "derivation_roots": [],
            "gap_kind": "set_by_missing",
            "reason": "key_card.set_by missing 且无 writes 边",
            "tried_frontier": [],
        }

    roots: set[str] = set()
    frontier_seen: list[str] = []
    hit_kernel_only = False
    hit_gap = False

    start_nodes = [key_id]
    if host_parent:
        start_nodes.append(str(host_parent))
    # Seed from expr idents mapped to graph nodes by name
    for ident in IDENT_RE.findall(expr_raw)[:12]:
        for nid, node in nodes_by_id.items():
            if str(node.get("name") or "") == ident or nid.endswith("_" + ident.upper()):
                start_nodes.append(nid)

    visited: set[str] = set()
    q: deque[tuple[str, int]] = deque()
    for s in start_nodes:
        q.append((s, 0))
        visited.add(s)

    while q:
        nid, depth = q.popleft()
        frontier_seen.append(nid)
        node = nodes_by_id.get(nid) or {}
        ntype = str(node.get("node_type") or "")
        name = str(node.get("name") or "")

        if (
            ntype in INPUT_ROOT_TYPES
            or nid.startswith("HOST_ATTR_")
            or nid.startswith("HOST_OPT_")
            or nid.startswith("HOST_START_")
        ):
            roots.add(nid)
            continue
        if ntype in COMPILE_ROOT_TYPES or nid.startswith("HOST_PLAT_"):
            # Platform / compile-time alone is not a CSV-facing input root.
            continue
        if KERNEL_LOCAL_RE.match(name) or _looks_kernel_local(name):
            hit_kernel_only = True
            continue
        if depth >= max_depth:
            hit_gap = True
            continue

        neighbors = reverse_adj.get(nid) or []
        if not neighbors and nid != key_id and nid not in roots:
            # dangling mid — gap unless already a root-like stub
            if not (nid.startswith("HOST_") or ntype in INPUT_ROOT_TYPES | COMPILE_ROOT_TYPES):
                hit_gap = True
            continue
        for src, _etype in neighbors:
            if src not in visited:
                visited.add(src)
                q.append((src, depth + 1))

    if roots:
        return {
            "input_derivable": True,
            "confidence": "high",
            "needs_binding": True,
            "not_input_derivable": False,
            "host_parent": host_parent,
            "host_parent_evidence": evidence,
            "derivation_roots": sorted(roots)[:16],
            "gap_kind": None,
            "reason": "",
            "tried_frontier": frontier_seen[:24],
        }

    if hit_kernel_only and not hit_gap and not rev_writers:
        return {
            "input_derivable": False,
            "confidence": "high",
            "needs_binding": False,
            "not_input_derivable": True,
            "host_parent": host_parent,
            "host_parent_evidence": evidence,
            "derivation_roots": [],
            "gap_kind": None,
            "reason": "仅核内局部/分批符号，无 Host 输入祖先",
            "tried_frontier": frontier_seen[:24],
        }

    return {
        "input_derivable": "unsolved",
        "confidence": "low",
        "needs_binding": True,
        "not_input_derivable": False,
        "host_parent": host_parent,
        "host_parent_evidence": evidence,
        "derivation_roots": [],
        "gap_kind": "missing_edge" if hit_gap else "chain_incomplete",
        "reason": "回溯未闭合到输入根（缺边或 optional 未实例化）",
        "tried_frontier": frontier_seen[:24],
    }


def _build_adjacency(
    graph: dict[str, Any],
) -> tuple[dict[str, list[tuple[str, str]]], dict[str, list[str]]]:
    """reverse_adj[target] = [(source, type)]; forward_writes[target]=[source] for writes."""
    reverse_adj: dict[str, list[tuple[str, str]]] = defaultdict(list)
    forward_writes: dict[str, list[str]] = defaultdict(list)
    aliases = {"write": "writes", "derive": "derives"}
    for edge in graph.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        src = str(edge.get("source") or edge.get("source_id") or "")
        tgt = str(edge.get("target") or edge.get("target_id") or "")
        et = aliases.get(str(edge.get("type") or edge.get("edge_type") or "").lower(), "")
        if not et:
            et = str(edge.get("type") or edge.get("edge_type") or "").lower()
        if not src or not tgt:
            continue
        if et not in WALK_EDGE_TYPES:
            continue
        reverse_adj[tgt].append((src, et))
        if et == "writes":
            forward_writes[tgt].append(src)
    return reverse_adj, forward_writes


def _load_key_cards(uo_root: Path) -> dict[str, dict[str, Any]]:
    cards: dict[str, dict[str, Any]] = {}
    cards_dir = uo_root / "tiling" / "key_cards"
    if cards_dir.is_dir():
        for path in sorted(cards_dir.glob("KEY_*.yaml")):
            doc = read_yaml(path)
            if isinstance(doc, dict) and doc.get("id"):
                cards[str(doc["id"])] = doc
    return cards


def _index_patch(patch: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(patch, dict):
        return out
    for item in patch.get("keys") or patch.get("resolutions") or []:
        if not isinstance(item, dict):
            continue
        kid = str(item.get("key_id") or item.get("target") or item.get("id") or "")
        if kid:
            out[kid] = item
    for kid, item in (patch.get("by_key") or {}).items():
        if isinstance(item, dict):
            out[str(kid)] = item
    return out


def _entry_from_patch(key_id: str, item: dict[str, Any]) -> dict[str, Any]:
    conf = str(item.get("confidence") or "").lower()
    status = str(item.get("status") or item.get("input_derivable") or "").lower()
    if status in {"not_input_derivable", "false"} or item.get("not_input_derivable") is True:
        if conf and conf != "high":
            # low confidence patch cannot force false — keep unsolved
            return {
                "input_derivable": "unsolved",
                "confidence": "low",
                "needs_binding": True,
                "not_input_derivable": False,
                "host_parent": item.get("host_parent"),
                "host_parent_evidence": item.get("evidence") or item.get("host_parent_evidence") or "",
                "derivation_roots": [],
                "gap_kind": "chain_incomplete",
                "reason": item.get("reason") or "patch confidence 非 high，未采纳 not_input_derivable",
            }
        return {
            "input_derivable": False,
            "confidence": "high",
            "needs_binding": False,
            "not_input_derivable": True,
            "host_parent": item.get("host_parent"),
            "host_parent_evidence": _evidence_str(item),
            "derivation_roots": [],
            "gap_kind": None,
            "reason": item.get("reason") or "patch: not_input_derivable",
        }
    if status in {"resolved", "true", "input_derivable"} or item.get("input_derivable") is True:
        if conf and conf != "high":
            return {
                "input_derivable": "unsolved",
                "confidence": "low",
                "needs_binding": True,
                "not_input_derivable": False,
                "host_parent": item.get("host_parent"),
                "host_parent_evidence": _evidence_str(item),
                "derivation_roots": list(item.get("derivation_roots") or [])[:16],
                "gap_kind": "chain_incomplete",
                "reason": "patch 声称可推导但 confidence 非 high",
            }
        roots = list(item.get("derivation_roots") or [])
        if not roots:
            return {
                "input_derivable": "unsolved",
                "confidence": "low",
                "needs_binding": True,
                "not_input_derivable": False,
                "host_parent": item.get("host_parent"),
                "host_parent_evidence": _evidence_str(item),
                "derivation_roots": [],
                "gap_kind": "chain_incomplete",
                "reason": "patch 缺 derivation_roots",
            }
        return {
            "input_derivable": True,
            "confidence": "high",
            "needs_binding": True,
            "not_input_derivable": False,
            "host_parent": item.get("host_parent"),
            "host_parent_evidence": _evidence_str(item),
            "derivation_roots": roots[:16],
            "gap_kind": None,
            "reason": item.get("reason") or "patch: high-confidence closure",
        }
    return {
        "input_derivable": "unsolved",
        "confidence": "low",
        "needs_binding": True,
        "not_input_derivable": False,
        "host_parent": item.get("host_parent"),
        "host_parent_evidence": _evidence_str(item),
        "derivation_roots": [],
        "gap_kind": str(item.get("gap_kind") or "chain_incomplete"),
        "reason": item.get("reason") or f"patch 未闭合 {key_id}",
    }


def _evidence_str(item: dict[str, Any]) -> str:
    ev = item.get("host_parent_evidence") or item.get("evidence")
    if isinstance(ev, list) and ev:
        return str(ev[0])
    return str(ev or "")


def _looks_kernel_local(name: str) -> bool:
    low = name.lower()
    return any(x in low for x in ("blockid", "taskid", "loopidx", "pingpong", "waveidx", "tileidx"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify KEY input-derivability (compact parent + graph markers)")
    parser.add_argument("repo", type=Path)
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--max-depth", type=int, default=12)
    args = parser.parse_args(argv)
    op = safe_op_name(args.op_name, args.repo)
    uo_root = existing_operator_root(args.repo, op)
    payload = classify_and_write(uo_root, max_depth=args.max_depth)
    stats = payload.get("stats") or {}
    print(
        f"input_derivable: true={stats.get('true')} false={stats.get('false')} "
        f"unsolved={stats.get('unsolved')} → {uo_root / 'ir' / 'input_derivable.yaml'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
