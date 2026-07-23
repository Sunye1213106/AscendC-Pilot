"""Resolve operator entrypoint graph (replaces single-role ``selected``).

Unique fact source: ``ir/entrypoint_graph.yaml``.
Statuses: located → verified → linked → closed | unresolved.
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
from uo.scripts._ir_io import read_yaml, snippet, write_yaml
from uo.scripts.arch_path import arch_compatible, architecture_of_path, path_family_of
from uo.scripts.cbm_client import CbmClient, read_source_snippet
from uo.scripts.semantic_identity import make_locator, mint_edge_id, mint_symbol_identity


def _path_has_dir(rel: str, dirname: str) -> bool:
    """True when *dirname* is a path segment (works for repo-relative roots)."""
    parts = rel.replace("\\", "/").strip("/").split("/")
    return dirname in parts


ROLE_PATTERNS: dict[str, tuple[str, ...]] = {
    # Public API keys kept for no-hardcode tests / op-derived pattern checks.
    "host_tiling_entry": ("DoOpTiling", "DoTiling"),
    "get_tiling_key": ("GetTilingKey",),
    "save_tiling_data": ("SaveToTilingData",),
    "init_tiling_data": ("InitTilingData",),
    "kernel_entry": ("KernelEntry", "Invoke"),
}
# Internal graph roles (used when materializing entrypoint_graph nodes).
GRAPH_ROLE_PATTERNS: dict[str, tuple[str, ...]] = {
    "public_host_entry": ROLE_PATTERNS["host_tiling_entry"],
    "get_tiling_key": ROLE_PATTERNS["get_tiling_key"],
    "save_tiling_data": ROLE_PATTERNS["save_tiling_data"],
    "init_tiling_data": ROLE_PATTERNS["init_tiling_data"],
    "public_kernel_entry": ROLE_PATTERNS["kernel_entry"],
}
EXACT_PREFERRED = {
    "host_tiling_entry": ("DoOpTiling",),
    "get_tiling_key": ("GetTilingKey",),
    "save_tiling_data": ("SaveToTilingData",),
    "init_tiling_data": ("InitTilingData",),
    "kernel_entry": ("KernelEntry",),
}
GRAPH_EXACT_PREFERRED = {
    "public_host_entry": EXACT_PREFERRED["host_tiling_entry"],
    "get_tiling_key": EXACT_PREFERRED["get_tiling_key"],
    "save_tiling_data": EXACT_PREFERRED["save_tiling_data"],
    "init_tiling_data": EXACT_PREFERRED["init_tiling_data"],
    "public_kernel_entry": EXACT_PREFERRED["kernel_entry"],
}

# Legacy role aliases used by older fixtures/tests — mapped into graph roles.
_LEGACY_ROLE_MAP = {
    "host_tiling_entry": "public_host_entry",
    "kernel_entry": "public_kernel_entry",
}

REGISTER_TILING_RE = re.compile(
    r"REGISTER_TILING_TEMPLATE(?:_WITH_ARCH)?\s*\(\s*([^,]+)\s*,\s*([^,\)]+)",
    re.MULTILINE,
)
REG_OP_RE = re.compile(r"\bREG_OP\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)")
IMPL_OP_RE = re.compile(r"\bIMPL_OP_OPTILING\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)")
# Fluent: IMPL_OP_OPTILING(Op).Tiling(Class) / chained same-statement .Tiling(...)
IMPL_OP_TILING_FLUENT_RE = re.compile(
    r"\bIMPL_OP_OPTILING\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)\s*"
    r"(?:\.\s*[A-Za-z_][A-Za-z0-9_]*\s*\([^;]*?\))*?"
    r"\.\s*Tiling\s*\(\s*([A-Za-z_][A-Za-z0-9_:]*)\s*\)",
    re.MULTILINE | re.DOTALL,
)
GET_TPL_RE = re.compile(r"\bGET_TPL_TILING_KEY\s*\(")
CLASS_RE = re.compile(r"\b(?:class|struct)\s+([A-Za-z_][A-Za-z0-9_]*)")

# Verification tiers (④) — closure only accepts source_verified | semantic_verified | verified
_VERIFIED_EDGE = frozenset({"verified", "source_verified", "semantic_verified"})


def _edge_is_verified(edge: dict[str, Any]) -> bool:
    return str(edge.get("confidence") or "").strip().casefold() in _VERIFIED_EDGE


def _snake_to_pascal(name: str) -> str:
    parts = [p for p in str(name or "").replace("-", "_").split("_") if p]
    return "".join(p[:1].upper() + p[1:] for p in parts)


def _role_patterns_for_op(op_name: str) -> dict[str, tuple[str, ...]]:
    patterns = {role: tuple(pats) for role, pats in ROLE_PATTERNS.items()}
    pascal = _snake_to_pascal(op_name)
    if pascal:
        patterns["kernel_entry"] = patterns["kernel_entry"] + (f"{pascal}Kernel", pascal)
    return patterns


def _exact_preferred_for_op(op_name: str) -> dict[str, tuple[str, ...]]:
    preferred = {role: tuple(pats) for role, pats in EXACT_PREFERRED.items()}
    pascal = _snake_to_pascal(op_name)
    if pascal:
        preferred["kernel_entry"] = (f"{pascal}Kernel", pascal) + preferred["kernel_entry"]
    return preferred


def _graph_role_patterns_for_op(op_name: str) -> dict[str, tuple[str, ...]]:
    legacy = _role_patterns_for_op(op_name)
    return {
        "public_host_entry": legacy["host_tiling_entry"],
        "get_tiling_key": legacy["get_tiling_key"],
        "save_tiling_data": legacy["save_tiling_data"],
        "init_tiling_data": legacy["init_tiling_data"],
        "public_kernel_entry": legacy["kernel_entry"],
    }


def _graph_exact_preferred_for_op(op_name: str) -> dict[str, tuple[str, ...]]:
    legacy = _exact_preferred_for_op(op_name)
    return {
        "public_host_entry": legacy["host_tiling_entry"],
        "get_tiling_key": legacy["get_tiling_key"],
        "save_tiling_data": legacy["save_tiling_data"],
        "init_tiling_data": legacy["init_tiling_data"],
        "public_kernel_entry": legacy["kernel_entry"],
    }


def collect_entrypoint_candidates(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
    auto_confirm_high_confidence: bool = True,
) -> dict[str, Any]:
    """Build entrypoint_graph (+ intermediate candidate listing for LLM patches)."""
    uo_root = existing_operator_root(repo_root, op_name)
    client = CbmClient(uo_root)
    confirmed_files = _confirmed_source_files(uo_root)
    role_patterns = _graph_role_patterns_for_op(op_name)
    exact_preferred = _graph_exact_preferred_for_op(op_name)

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    role_candidates: dict[str, list[dict[str, Any]]] = {role: [] for role in role_patterns}

    for role, patterns in role_patterns.items():
        for pattern in patterns:
            if client.available:
                for name_pat in (pattern, f"%{pattern}", f"%{pattern}%"):
                    # ⑩ confirmed scope is the hard boundary; op_name ranks only (no hard filter).
                    for hit in client.search_symbols(
                        name_pattern=name_pat,
                        file_contains=None,
                        prefer_file_contains=op_name or None,
                        architecture=architecture,
                        limit=40,
                    ):
                        if confirmed_files and not _path_in_confirmed(hit.file_path, confirmed_files):
                            continue
                        if not arch_compatible(hit.file_path, architecture):
                            continue
                        conf = _confidence(
                            role,
                            hit.name,
                            hit.file_path,
                            op_name,
                            architecture,
                            role_patterns=role_patterns,
                            exact_preferred=exact_preferred,
                        )
                        if conf < 0.45:
                            continue
                        cand = {
                            **hit.as_dict(),
                            "role": role,
                            "pattern": pattern,
                            "confidence": conf,
                            "signature_snippet": snippet(
                                read_source_snippet(repo_root, hit.file_path, hit.start_line, hit.start_line + 8)
                            ),
                        }
                        role_candidates[role].append(cand)
            for path in _scan_paths(repo_root, confirmed_files, architecture, role):
                text = path.read_text(encoding="utf-8", errors="ignore")
                for match in re.finditer(rf"\b({re.escape(pattern)})\b", text):
                    name = match.group(1)
                    rel = path.relative_to(repo_root).as_posix()
                    if not arch_compatible(rel, architecture):
                        continue
                    conf = _confidence(
                        role,
                        name,
                        rel,
                        op_name,
                        architecture,
                        role_patterns=role_patterns,
                        exact_preferred=exact_preferred,
                    )
                    if conf < 0.45:
                        continue
                    line = text.count("\n", 0, match.start()) + 1
                    cls = _enclosing_class(text, match.start())
                    role_candidates[role].append(
                        {
                            "node_id": 0,
                            "name": name,
                            "qualified_name": f"{cls + '::' if cls else ''}{name}" if cls else f"{rel}::{name}",
                            "file_path": rel,
                            "start_line": line,
                            "end_line": line,
                            "label": "filesystem",
                            "role": role,
                            "pattern": pattern,
                            "class_or_namespace": cls,
                            "confidence": conf,
                            "signature_snippet": snippet("\n".join(text.splitlines()[max(0, line - 1) : line + 6])),
                        }
                    )
        if role == "public_kernel_entry":
            role_candidates[role].extend(
                _scan_global_kernels(
                    repo_root,
                    confirmed_files,
                    op_name,
                    architecture,
                    role_patterns=role_patterns,
                    exact_preferred=exact_preferred,
                )
            )
        role_candidates[role] = _dedupe_candidates(role_candidates[role])

    # Materialize verified nodes from high-confidence candidates (multi-keep).
    for role, cands in role_candidates.items():
        preferred = exact_preferred.get(role) or ()
        kept = [
            c
            for c in cands
            if float(c.get("confidence") or 0) >= 0.8 and (c.get("name") in preferred or role == "public_kernel_entry")
        ]
        if not kept:
            kept = [c for c in cands if float(c.get("confidence") or 0) >= 0.9]
        # Keep ALL exact preferred hits (Normal/Varlen/Empty) — no single-winner ranking.
        if any(c.get("name") in preferred for c in cands):
            kept = [c for c in cands if c.get("name") in preferred and float(c.get("confidence") or 0) >= 0.7] or kept
        for cand in kept:
            node = _node_from_candidate(cand, role=role, status="verified" if float(cand.get("confidence") or 0) >= 0.85 else "located")
            nodes[node["id"]] = node

    # Registration / dispatch macros → typed edges
    macro_nodes, macro_edges, templates = _scan_registration_graph(
        repo_root, confirmed_files, architecture, nodes
    )
    nodes.update(macro_nodes)
    edges.extend(macro_edges)

    # Link public host entries to matching template implementations by class/name proximity
    edges.extend(_link_host_to_templates(nodes, templates, architecture))
    edges.extend(_link_kernel_dispatch(nodes, architecture))

    # Advance status: linked / closed / unresolved
    _apply_link_status(nodes, edges)
    closure = _evaluate_closure(nodes, edges, architecture)
    extraction_units = _build_extraction_units(nodes, edges, architecture)
    roots = [n["id"] for n in nodes.values() if n.get("role") in {"operator_registration", "public_host_entry", "public_kernel_entry"}]

    graph = {
        "version": 2,
        "op_name": op_name,
        "architecture": architecture,
        "nodes": sorted(nodes.values(), key=lambda n: (n.get("role") or "", n.get("id") or "")),
        "edges": edges,
        "roots": roots,
        "extraction_units": extraction_units,
        "closure": closure,
        "tiling_templates": templates,
        "cbm_available": client.available,
        "cbm_project": client.project,
    }
    client.close()

    # Intermediate candidate listing (not a confirmation fact source).
    candidates_doc = {
        "version": 2,
        "op_name": op_name,
        "architecture": architecture,
        "cbm_available": graph["cbm_available"],
        "role_candidates": {
            role: [
                {
                    "name": c.get("name"),
                    "qualified_name": c.get("qualified_name"),
                    "file_path": c.get("file_path"),
                    "start_line": c.get("start_line"),
                    "end_line": c.get("end_line"),
                    "confidence": c.get("confidence"),
                    "class_or_namespace": c.get("class_or_namespace"),
                    "signature_snippet": c.get("signature_snippet") or "",
                    "label": c.get("label"),
                    "pattern": c.get("pattern"),
                    "evidence_classes": c.get("evidence_classes") or [],
                }
                for c in items
            ]
            for role, items in role_candidates.items()
        },
        "entrypoint_graph_ref": "ir/entrypoint_graph.yaml",
        "llm_required": closure.get("host_main_chain") != "closed" or closure.get("kernel_main_chain") != "closed",
        "auto_confirm_high_confidence": auto_confirm_high_confidence,
    }
    # Attach graph for callers that only invoke collect_*
    candidates_doc["entrypoint_graph"] = graph
    return candidates_doc


def build_entrypoint_graph(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
    confirmation_patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    doc = collect_entrypoint_candidates(repo_root, op_name, architecture=architecture)
    graph = doc.get("entrypoint_graph") or {}
    if confirmation_patch:
        graph = apply_entrypoint_confirmation(doc, confirmation_patch)
    return graph


def apply_entrypoint_confirmation(candidates_doc: dict[str, Any], confirmation: dict[str, Any]) -> dict[str, Any]:
    """Merge human/LLM patch into entrypoint_graph (add/verify nodes & edges)."""
    graph = dict(candidates_doc.get("entrypoint_graph") or {})
    nodes = {n["id"]: dict(n) for n in graph.get("nodes") or []}
    edges = [dict(e) for e in graph.get("edges") or []]

    # Patch may supply nodes/edges directly (preferred).
    for node in confirmation.get("nodes") or []:
        nid = node.get("id")
        if not nid:
            role = _normalize_role(str(node.get("role") or "public_host_entry"))
            built = _node_from_candidate(node, role=role, status=str(node.get("status") or "verified"))
            nid = built["id"]
            node = {**built, **node, "id": nid}
        nodes[nid] = {**nodes.get(nid, {}), **node}
    for edge in confirmation.get("edges") or []:
        edges.append(
            {
                "id": edge.get("id")
                or mint_edge_id(str(edge.get("type") or "dispatches_to"), str(edge.get("source")), str(edge.get("target"))),
                "type": edge.get("type") or "dispatches_to",
                "source": edge.get("source"),
                "target": edge.get("target"),
                "evidence": edge.get("evidence") or [],
                "confidence": edge.get("confidence") or "candidate",
            }
        )

    # Legacy confirmation shape roles.<role>.{qualified_name,name} — promote to graph nodes only.
    for role, conf_item in (confirmation.get("roles") or {}).items():
        if not isinstance(conf_item, dict):
            continue
        if not (conf_item.get("qualified_name") or conf_item.get("name")):
            continue
        role_n = _normalize_role(role)
        built = _node_from_candidate({**conf_item, "role": role_n}, role=role_n, status="verified")
        nodes[built["id"]] = built

    _apply_link_status(nodes, edges)
    architecture = str(graph.get("architecture") or candidates_doc.get("architecture") or "arch35")
    closure = _evaluate_closure(nodes, edges, architecture)
    extraction_units = _build_extraction_units(nodes, edges, architecture)
    roots = [n["id"] for n in nodes.values() if n.get("role") in {"operator_registration", "public_host_entry", "public_kernel_entry"}]
    return {
        "version": 2,
        "op_name": graph.get("op_name") or candidates_doc.get("op_name"),
        "architecture": architecture,
        "nodes": sorted(nodes.values(), key=lambda n: (n.get("role") or "", n.get("id") or "")),
        "edges": edges,
        "roots": roots,
        "extraction_units": extraction_units,
        "closure": closure,
        "tiling_templates": graph.get("tiling_templates") or [],
        "source": "entrypoint_confirmation",
    }


def entrypoint_units(graph: dict[str, Any]) -> list[dict[str, Any]]:
    return list(graph.get("extraction_units") or [])


def nodes_for_role(graph: dict[str, Any], role: str) -> list[dict[str, Any]]:
    role_n = _normalize_role(role)
    return [n for n in graph.get("nodes") or [] if _normalize_role(str(n.get("role") or "")) == role_n]


def load_entrypoint_graph(uo_root: Path) -> dict[str, Any]:
    graph = read_yaml(uo_root / "ir" / "entrypoint_graph.yaml")
    if graph:
        return graph
    # No silent selected fallback — empty graph forces rebuild.
    return {}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build typed entrypoint_graph (no single selected entry)")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--architecture", default="arch35")
    parser.add_argument("--write", action="store_true", help="Write ir/entrypoint_graph.yaml (+ candidates listing)")
    parser.add_argument("--confirm-patch", help="Optional confirmation YAML merged into entrypoint_graph")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    uo_root = existing_operator_root(repo_root, op_name)
    candidates = collect_entrypoint_candidates(repo_root, op_name, architecture=args.architecture)
    graph = candidates.get("entrypoint_graph") or {}
    if args.confirm_patch:
        patch = read_yaml(Path(args.confirm_patch))
        graph = apply_entrypoint_confirmation(candidates, patch)
    if args.write:
        write_yaml(uo_root / "ir" / "entrypoint_candidates.yaml", {k: v for k, v in candidates.items() if k != "entrypoint_graph"})
        write_yaml(uo_root / "ir" / "entrypoint_graph.yaml", graph)
        # Remove obsolete single-entry artifact if present.
        legacy = uo_root / "ir" / "entrypoints.yaml"
        if legacy.exists():
            legacy.unlink()
    closure = graph.get("closure") or {}
    print(
        f"entrypoint_nodes={len(graph.get('nodes') or [])} "
        f"edges={len(graph.get('edges') or [])} "
        f"host_chain={closure.get('host_main_chain')} "
        f"kernel_chain={closure.get('kernel_main_chain')}"
    )
    return 0


def _normalize_role(role: str) -> str:
    return _LEGACY_ROLE_MAP.get(role, role)


def _node_from_candidate(cand: dict[str, Any], *, role: str, status: str) -> dict[str, Any]:
    rel = str(cand.get("file_path") or "").replace("\\", "/")
    name = str(cand.get("name") or "")
    qn = str(cand.get("qualified_name") or f"{rel}::{name}")
    cls = str(cand.get("class_or_namespace") or "")
    if not cls and "::" in qn:
        cls = qn.rsplit("::", 1)[0]
        if "/" in cls:
            cls = ""
    path_family = path_family_of(rel)
    # Infer impl role from path family when this is a DoOpTiling-like host method.
    role_n = role
    if role in {"public_host_entry", "host_tiling_entry"} and path_family in {"normal", "varlen", "empty"}:
        role_n = f"{path_family}_impl"
    elif role in {"public_host_entry", "host_tiling_entry"} and architecture_of_path(rel) == "neutral":
        role_n = "public_host_entry"
    ident = mint_symbol_identity(
        kind="entrypoint",
        name=name,
        file_path=rel,
        qualified_name=qn,
        signature=str(cand.get("signature_snippet") or "")[:120],
        class_or_namespace=cls,
        architecture=architecture_of_path(rel),
        template_family=str(cand.get("template_family") or path_family),
        path_family=path_family,
        prefix="EP",
    )
    locator = make_locator(
        rel,
        start_line=int(cand.get("start_line") or 0),
        end_line=int(cand.get("end_line") or cand.get("start_line") or 0),
        text=str(cand.get("signature_snippet") or ""),
    )
    return {
        "id": ident.stable_id,
        "role": role_n,
        "architecture": ident.architecture,
        "path_family": ident.path_family,
        "template_family": ident.template_family,
        "status": status,
        "name": name,
        "symbol_ref": ident.as_dict(),
        "locator": locator.as_dict(),
        "confidence": float(cand.get("confidence") or 0),
    }


def _enclosing_class(text: str, pos: int) -> str:
    # Heuristic: nearest preceding class/struct declaration.
    window = text[max(0, pos - 4000) : pos]
    matches = list(CLASS_RE.finditer(window))
    return matches[-1].group(1) if matches else ""


def _scan_registration_graph(
    repo_root: Path,
    confirmed_files: list[str],
    architecture: str,
    existing_nodes: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    templates: list[dict[str, Any]] = []
    for rel in confirmed_files:
        if not arch_compatible(rel, architecture):
            continue
        path = repo_root / rel
        if not path.exists() or path.suffix not in {".h", ".hpp", ".cpp", ".cc", ".c"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in REG_OP_RE.finditer(text):
            op_type = match.group(1)
            line = text.count("\n", 0, match.start()) + 1
            ident = mint_symbol_identity(
                kind="registration",
                name=op_type,
                file_path=rel,
                qualified_name=f"REG_OP::{op_type}",
                architecture=architecture_of_path(rel),
                path_family=path_family_of(rel),
                prefix="EP",
            )
            node = {
                "id": ident.stable_id,
                "role": "operator_registration",
                "architecture": ident.architecture,
                "path_family": ident.path_family,
                "template_family": "shared",
                "status": "verified",
                "name": op_type,
                "symbol_ref": ident.as_dict(),
                "locator": make_locator(rel, start_line=line, end_line=line, text=match.group(0)).as_dict(),
                "macro": "REG_OP",
            }
            nodes[node["id"]] = node
        for match in IMPL_OP_RE.finditer(text):
            name = match.group(1)
            line = text.count("\n", 0, match.start()) + 1
            ident = mint_symbol_identity(
                kind="registration",
                name=name,
                file_path=rel,
                qualified_name=f"IMPL_OP_OPTILING::{name}",
                architecture=architecture_of_path(rel),
                path_family=path_family_of(rel),
                prefix="EP",
            )
            node = {
                "id": ident.stable_id,
                "role": "public_host_entry",
                "architecture": ident.architecture,
                "path_family": ident.path_family,
                "template_family": "shared",
                "status": "verified",
                "name": name,
                "symbol_ref": ident.as_dict(),
                "locator": make_locator(rel, start_line=line, end_line=line, text=match.group(0)).as_dict(),
                "macro": "IMPL_OP_OPTILING",
                "verification_source": "source",
            }
            nodes[node["id"]] = node
            # Link registration → public host when both present
            for reg in list(nodes.values()) + list(existing_nodes.values()):
                if reg.get("role") == "operator_registration":
                    edges.append(
                        {
                            "id": mint_edge_id("registers", reg["id"], node["id"]),
                            "type": "registers",
                            "source": reg["id"],
                            "target": node["id"],
                            "evidence": [{"file_path": rel, "line": line, "macro": "IMPL_OP_OPTILING"}],
                            "confidence": "source_verified",
                            "verification_source": "source",
                        }
                    )
            # Fluent .Tiling(X) — X may be class, free function, or other callable.
            # Start as neutral callable; specialize only when source evidence exists.
            window = text[match.start() : match.start() + 400]
            fluent = IMPL_OP_TILING_FLUENT_RE.search(window) or IMPL_OP_TILING_FLUENT_RE.search(text[match.start() :])
            if fluent and fluent.group(1) == name:
                tiling_target = fluent.group(2).split("::")[-1]
                tiling_line = text.count("\n", 0, match.start() + fluent.start()) + 1
                # Neutral callable first; specialize from source evidence in this file.
                if re.search(rf"\b(?:class|struct)\s+{re.escape(tiling_target)}\b", text):
                    kind, role = "tiling_class", "template_registration"
                    evidence_reason = "class_or_struct_decl"
                elif re.search(
                    rf"\b(?:ge::graphStatus|graphStatus|Status|void|bool|auto)\s+(?:\w+::)*{re.escape(tiling_target)}\s*\(",
                    text,
                ) or re.search(
                    rf"\b{re.escape(tiling_target)}\s*\([^;{{]*\)\s*(?:const)?\s*\{{",
                    text,
                ):
                    kind, role = "tiling_fn", "public_host_entry"
                    evidence_reason = "function_decl"
                else:
                    kind, role = "tiling_callable", "tiling_callable"
                    evidence_reason = "fluent_tiling_untyped"
                tgt_ident = mint_symbol_identity(
                    kind=kind,
                    name=tiling_target,
                    file_path=rel,
                    qualified_name=f"IMPL_OP_OPTILING.Tiling::{tiling_target}",
                    class_or_namespace=tiling_target if kind == "tiling_class" else "",
                    architecture=architecture_of_path(rel),
                    path_family=path_family_of(rel),
                    prefix="EP",
                )
                tgt_node = {
                    "id": tgt_ident.stable_id,
                    "role": role,
                    "architecture": tgt_ident.architecture,
                    "path_family": tgt_ident.path_family,
                    "template_family": path_family_of(rel),
                    "status": "verified" if kind != "tiling_callable" else "located",
                    "name": tiling_target,
                    "symbol_ref": tgt_ident.as_dict(),
                    "locator": make_locator(
                        rel, start_line=tiling_line, end_line=tiling_line, text=fluent.group(0)[:120]
                    ).as_dict(),
                    "macro": "IMPL_OP_OPTILING.Tiling",
                    "verification_source": "source",
                    "callable_kind": kind,
                }
                nodes[tgt_node["id"]] = tgt_node
                edges.append(
                    {
                        "id": mint_edge_id("dispatches_to", node["id"], tgt_node["id"], tiling_target),
                        "type": "dispatches_to",
                        "source": node["id"],
                        "target": tgt_node["id"],
                        "evidence": [
                            {
                                "file_path": rel,
                                "line": tiling_line,
                                "macro": "IMPL_OP_OPTILING.Tiling",
                                "reason": "fluent_tiling",
                                "callable_kind": kind,
                                "evidence_reason": evidence_reason,
                            }
                        ],
                        "confidence": "source_verified",
                        "verification_source": "source",
                    }
                )
                edges.append(
                    {
                        "id": mint_edge_id("registers", node["id"], tgt_node["id"], tiling_target),
                        "type": "registers",
                        "source": node["id"],
                        "target": tgt_node["id"],
                        "evidence": [
                            {
                                "file_path": rel,
                                "line": tiling_line,
                                "macro": "IMPL_OP_OPTILING.Tiling",
                                "reason": "fluent_tiling",
                                "callable_kind": kind,
                            }
                        ],
                        "confidence": "source_verified",
                        "verification_source": "source",
                    }
                )
        for match in REGISTER_TILING_RE.finditer(text):
            op_type = match.group(1).strip()
            cls = match.group(2).strip()
            line = text.count("\n", 0, match.start()) + 1
            family = path_family_of(rel)
            if "varlen" in cls.lower():
                family = "varlen"
            elif "empty" in cls.lower():
                family = "empty"
            elif "normal" in cls.lower():
                family = "normal"
            ident = mint_symbol_identity(
                kind="tiling_template",
                name=cls,
                file_path=rel,
                qualified_name=f"REGISTER_TILING_TEMPLATE::{cls}",
                class_or_namespace=cls,
                architecture=architecture_of_path(rel),
                template_family=family,
                path_family=family,
                prefix="EP",
            )
            role = {
                "normal": "normal_impl",
                "varlen": "varlen_impl",
                "empty": "empty_impl",
            }.get(family, "template_registration")
            node = {
                "id": ident.stable_id,
                "role": role,
                "architecture": ident.architecture if ident.architecture != "neutral" else architecture,
                "path_family": family,
                "template_family": family,
                "status": "verified",
                "name": cls,
                "symbol_ref": ident.as_dict(),
                "locator": make_locator(rel, start_line=line, end_line=line, text=match.group(0)).as_dict(),
                "macro": "REGISTER_TILING_TEMPLATE",
                "op_type": op_type,
            }
            nodes[node["id"]] = node
            templates.append(
                {
                    "op_type": op_type,
                    "template_class": cls,
                    "file_path": rel,
                    "line": line,
                    "architecture_hint": architecture if architecture in rel else architecture_of_path(rel),
                    "path_family": family,
                    "node_id": node["id"],
                }
            )
            # registry node (file-level)
            reg_ident = mint_symbol_identity(
                kind="tiling_registry",
                name=f"registry_{Path(rel).stem}",
                file_path=rel,
                qualified_name=f"{rel}::tiling_registry",
                architecture=architecture_of_path(rel),
                path_family=family,
                prefix="EP",
            )
            reg_node = {
                "id": reg_ident.stable_id,
                "role": "tiling_registry",
                "architecture": reg_ident.architecture,
                "path_family": family,
                "template_family": family,
                "status": "verified",
                "name": Path(rel).stem,
                "symbol_ref": reg_ident.as_dict(),
                "locator": make_locator(rel, start_line=line, end_line=line).as_dict(),
            }
            nodes[reg_node["id"]] = reg_node
            edges.append(
                {
                    "id": mint_edge_id("registers", reg_node["id"], node["id"], cls),
                    "type": "registers",
                    "source": reg_node["id"],
                    "target": node["id"],
                    "evidence": [{"file_path": rel, "line": line, "macro": "REGISTER_TILING_TEMPLATE"}],
                    "confidence": "source_verified",
                    "verification_source": "source",
                }
            )
        if GET_TPL_RE.search(text):
            # mark file as having host key writer site (occurrence only)
            pass
    return nodes, edges, templates


def _path_in_confirmed(file_path: str, confirmed_files: list[str]) -> bool:
    fp = file_path.replace("\\", "/")
    for rel in confirmed_files:
        r = rel.replace("\\", "/")
        if fp == r or fp.endswith("/" + r) or r.endswith("/" + fp) or fp.endswith(r) or r.endswith(fp):
            return True
    return False


def _link_host_to_templates(
    nodes: dict[str, dict[str, Any]],
    templates: list[dict[str, Any]],
    architecture: str,
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    publics = [n for n in nodes.values() if n.get("role") == "public_host_entry"]
    impls = [n for n in nodes.values() if n.get("role") in {"normal_impl", "varlen_impl", "empty_impl", "template_registration"}]
    registries = [n for n in nodes.values() if n.get("role") == "tiling_registry"]
    for pub in publics:
        for reg in registries:
            # Neutral public entry dispatches via registry when arch evidence exists on registry/impl
            edges.append(
                {
                    "id": mint_edge_id("dispatches_to", pub["id"], reg["id"]),
                    "type": "dispatches_to",
                    "source": pub["id"],
                    "target": reg["id"],
                    "evidence": [{"reason": "public_host_to_registry"}],
                    "confidence": "candidate",
                }
            )
        for impl in impls:
            if impl.get("architecture") not in {"neutral", architecture} and architecture_of_path(
                str((impl.get("locator") or {}).get("file_path") or "")
            ) not in {"neutral", architecture}:
                continue
            edges.append(
                {
                    "id": mint_edge_id("selects", pub["id"], impl["id"]),
                    "type": "selects",
                    "source": pub["id"],
                    "target": impl["id"],
                    "evidence": [{"reason": "host_to_impl_candidate", "path_family": impl.get("path_family")}],
                    "confidence": "candidate",
                }
            )
    # template list also drives edges
    for tpl in templates:
        nid = tpl.get("node_id")
        if not nid or nid not in nodes:
            continue
        for pub in publics:
            edges.append(
                {
                    "id": mint_edge_id("instantiates", pub["id"], nid, tpl.get("template_class") or ""),
                    "type": "instantiates",
                    "source": pub["id"],
                    "target": nid,
                    "evidence": [{"file_path": tpl.get("file_path"), "line": tpl.get("line")}],
                    "confidence": "source_verified",
                    "verification_source": "source",
                }
            )
    return edges


def _link_kernel_dispatch(nodes: dict[str, dict[str, Any]], architecture: str) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    publics = [n for n in nodes.values() if n.get("role") == "public_kernel_entry"]
    concretes = [
        n
        for n in nodes.values()
        if n.get("role") in {"concrete_kernel_impl", "kernel_family", "template_dispatcher", "public_kernel_entry"}
        and n.get("architecture") in {architecture, "neutral"}
    ]
    for pub in publics:
        if pub.get("architecture") == "neutral":
            for other in concretes:
                if other["id"] == pub["id"]:
                    continue
                if other.get("architecture") == architecture:
                    edges.append(
                        {
                            "id": mint_edge_id("dispatches_to", pub["id"], other["id"]),
                            "type": "dispatches_to",
                            "source": pub["id"],
                            "target": other["id"],
                            "evidence": [{"reason": "neutral_kernel_to_arch_impl"}],
                            "confidence": "candidate",
                        }
                    )
        # Promote arch-local kernel entries to concrete_kernel_impl role marker via edge to self family
        if pub.get("architecture") == architecture:
            pub["role"] = "concrete_kernel_impl" if pub.get("role") == "public_kernel_entry" and "entry" not in str(pub.get("name") or "").lower() else pub["role"]
    return edges


def _apply_link_status(nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    incoming = {n: 0 for n in nodes}
    outgoing = {n: 0 for n in nodes}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s in outgoing:
            outgoing[s] += 1
        if t in incoming:
            incoming[t] += 1
    for nid, node in nodes.items():
        status = str(node.get("status") or "located")
        if status in {"located"} and node.get("symbol_ref"):
            status = "verified"
        if status == "verified" and (incoming.get(nid, 0) + outgoing.get(nid, 0)) > 0:
            status = "linked"
        node["status"] = status


def _evaluate_closure(nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]], architecture: str) -> dict[str, Any]:
    """Closure requires verified edges only — candidate edges never close main chains."""
    by_role: dict[str, list[dict[str, Any]]] = {}
    for n in nodes.values():
        by_role.setdefault(str(n.get("role")), []).append(n)

    def has_verified_edge(types: set[str], src_roles: set[str], dst_roles: set[str]) -> bool:
        src_ids = {n["id"] for r in src_roles for n in by_role.get(r, [])}
        dst_ids = {n["id"] for r in dst_roles for n in by_role.get(r, [])}
        for e in edges:
            if (
                e.get("type") in types
                and e.get("source") in src_ids
                and e.get("target") in dst_ids
                and _edge_is_verified(e)
            ):
                return True
        return False

    blocking: list[dict[str, Any]] = []
    host_ok = True
    if not by_role.get("operator_registration") and not by_role.get("public_host_entry"):
        host_ok = False
        blocking.append(_block("entrypoint_host_registration_or_public_missing", "missing REG_OP / public host entry"))
    if by_role.get("public_host_entry") or by_role.get("operator_registration"):
        impl_roles = {"normal_impl", "varlen_impl", "empty_impl", "template_registration", "tiling_callable"}
        if not any(by_role.get(r) for r in impl_roles) and not by_role.get("tiling_registry"):
            host_ok = False
            blocking.append(_block("entrypoint_host_impl_missing", "no tiling registry/template implementation"))
        elif not (
            has_verified_edge(
                {"registers", "dispatches_to", "selects", "instantiates"},
                {"operator_registration", "public_host_entry"},
                impl_roles | {"tiling_registry"},
            )
            or has_verified_edge({"registers"}, {"tiling_registry"}, impl_roles)
        ):
            host_ok = False
            blocking.append(
                _block(
                    "entrypoint_host_dispatch_missing",
                    "public host not linked to registry/impl via verified edge "
                    "(candidate dispatches_to/selects cannot close)",
                )
            )

    kernel_ok = True
    kern = by_role.get("public_kernel_entry") or by_role.get("concrete_kernel_impl") or by_role.get("kernel_family") or []
    if not kern:
        kernel_ok = False
        blocking.append(_block("entrypoint_kernel_missing", "no public/concrete kernel entry"))
    else:
        if not any(n.get("architecture") in {architecture, "neutral"} for n in kern):
            kernel_ok = False
            blocking.append(_block("entrypoint_kernel_arch_missing", f"no kernel entry compatible with {architecture}"))

    if host_ok:
        for role in ("operator_registration", "public_host_entry", "tiling_registry", "normal_impl", "varlen_impl", "empty_impl", "template_registration"):
            for n in by_role.get(role, []):
                if n.get("status") == "linked":
                    n["status"] = "closed"
    if kernel_ok:
        for role in ("public_kernel_entry", "template_dispatcher", "kernel_family", "concrete_kernel_impl"):
            for n in by_role.get(role, []):
                if n.get("status") in {"linked", "verified"}:
                    n["status"] = "closed"

    return {
        "host_main_chain": "closed" if host_ok else "unresolved",
        "kernel_main_chain": "closed" if kernel_ok else "unresolved",
        "blocking_unresolved": blocking,
    }


def _block(code: str, reason: str) -> dict[str, Any]:
    return {
        "severity": "blocking",
        "code": code,
        "related_symbols": [],
        "candidate_files": [],
        "evidence_present": [],
        "evidence_missing": ["dispatch_or_registration_evidence"],
        "reason": reason,
    }


def _build_extraction_units(
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    architecture: str,
) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    impls = [
        n
        for n in nodes.values()
        if n.get("role") in {"normal_impl", "varlen_impl", "empty_impl", "concrete_kernel_impl", "public_host_entry", "public_kernel_entry"}
    ]
    seen: set[str] = set()
    for node in impls:
        arch = node.get("architecture") or architecture
        if arch not in {architecture, "neutral"}:
            continue
        # Neutral public entries become shared units; arch impls are separate.
        key = f"{architecture}|{node.get('path_family')}|{node.get('template_family')}|{node['id']}"
        if key in seen:
            continue
        seen.add(key)
        members = {node["id"]}
        for e in edges:
            if e.get("source") == node["id"]:
                members.add(str(e.get("target")))
            if e.get("target") == node["id"]:
                members.add(str(e.get("source")))
        units.append(
            {
                "id": "UNIT_" + mint_edge_id("unit", architecture, str(node.get("path_family")), node["id"])[-16:],
                "architecture": architecture if arch == "neutral" else arch,
                "path_family": node.get("path_family") or "unknown",
                "template_family": node.get("template_family") or "unknown",
                "entry_root": node["id"],
                "member_nodes": sorted(members),
            }
        )
    return units


def _confidence(
    role: str,
    name: str,
    file_path: str,
    op_name: str,
    architecture: str,
    *,
    role_patterns: dict[str, tuple[str, ...]] | None = None,
    exact_preferred: dict[str, tuple[str, ...]] | None = None,
) -> float:
    patterns = role_patterns or _role_patterns_for_op(op_name)
    preferred_map = exact_preferred or _exact_preferred_for_op(op_name)
    score = 0.2
    file_path = file_path.replace("\\", "/")
    if op_name and op_name in file_path:
        score += 0.2
    # Boost target-arch *implementations*, but do NOT penalize neutral public entries.
    arch_of = architecture_of_path(file_path)
    if arch_of == architecture:
        score += 0.15
    elif arch_of != "neutral" and architecture and arch_of != architecture:
        score -= 0.5
    preferred = preferred_map.get(role) or ()
    if name in preferred:
        score += 0.45
    elif any(name == pat for pat in patterns.get(role, ())):
        score += 0.3
    elif any(name.endswith(pat) for pat in patterns.get(role, ())):
        score += 0.15
    else:
        score -= 0.1
    if role in {"public_host_entry", "get_tiling_key", "save_tiling_data", "init_tiling_data"}:
        if _path_has_dir(file_path, "op_host"):
            score += 0.15
        if _path_has_dir(file_path, "op_kernel"):
            score -= 0.4
    if role == "public_kernel_entry":
        if _path_has_dir(file_path, "op_kernel"):
            score += 0.2
        if _path_has_dir(file_path, "op_host"):
            score -= 0.4
        if name.endswith("Kernel"):
            score += 0.25
        if "entry" in name.lower() or "entry" in file_path:
            score += 0.25
        if "kernel_base" in file_path or file_path.endswith("kernel.h"):
            score += 0.15
        if "template_tiling_key" in file_path or "tiling_data" in file_path:
            score -= 0.5
        # Naming style is ranking-only: do NOT exclude legitimate snake_case
        # __global__ entries. Soft demotion for known non-entry helpers only.
        if name in {"pipe", "dqGm", "Init", "Process"}:
            score -= 0.45
        elif name[:1].islower() and not name.endswith(("_entry", "_kernel", "kernel", "entry")):
            # Soft ranking only — keep above materialization floor when other
            # kernel evidence (op_kernel path / global_kernel) is present.
            score -= 0.05
    return max(0.0, min(1.0, score))


def _dedupe_candidates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for item in items:
        cls = item.get("class_or_namespace") or ""
        key = f"{item.get('qualified_name')}|{item.get('file_path')}|{cls}|{item.get('name')}"
        prev = best.get(key)
        if prev is None or item.get("confidence", 0) > prev.get("confidence", 0):
            best[key] = item
    return sorted(
        best.values(),
        key=lambda x: (-float(x.get("confidence") or 0), x.get("file_path") or "", x.get("name") or ""),
    )


def _confirmed_source_files(uo_root: Path) -> list[str]:
    import json

    for path in sorted((uo_root / "runs").glob("*/scope/scope_confirmed.yaml"), reverse=True):
        data = read_yaml(path)
        files = data.get("confirmed_source_files") or data.get("confirmed_file_list")
        if isinstance(files, list) and files:
            return [str(item.get("path") if isinstance(item, dict) else item).replace("\\", "/") for item in files]
    meta_path = uo_root / "cbm" / "index_meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        files = meta.get("indexed_files") or []
        return [str(item.get("path") if isinstance(item, dict) else item).replace("\\", "/") for item in files]
    return []


def _scan_paths(repo_root: Path, confirmed_files: list[str], architecture: str, role: str) -> list[Path]:
    paths: list[Path] = []
    for rel in confirmed_files:
        if not arch_compatible(rel, architecture):
            continue
        if role == "public_kernel_entry" and not _path_has_dir(rel, "op_kernel"):
            continue
        if role != "public_kernel_entry" and not _path_has_dir(rel, "op_host") and "template_tiling_key" not in rel:
            continue
        path = repo_root / rel
        if path.exists() and path.suffix in {".h", ".hpp", ".cpp", ".cc", ".c"}:
            paths.append(path)
    if paths:
        return paths
    if role == "public_kernel_entry":
        # Include neutral kernel wrappers plus target arch.
        return list(repo_root.glob("**/op_kernel/**/*.h"))[:40] + list(repo_root.glob(f"**/{architecture}/**/*kernel*.h"))[:40]
    return (
        list(repo_root.glob("**/op_host/**/*tiling*.cpp"))[:40]
        + list(repo_root.glob(f"**/{architecture}/**/*tiling*.cpp"))[:40]
        + list(repo_root.glob(f"**/{architecture}/**/*tiling*.h"))[:40]
    )


def _scan_global_kernels(
    repo_root: Path,
    confirmed_files: list[str],
    op_name: str,
    architecture: str,
    *,
    role_patterns: dict[str, tuple[str, ...]] | None = None,
    exact_preferred: dict[str, tuple[str, ...]] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    global_re = re.compile(r"__global__\s+[^=;{]*?\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
    for rel in confirmed_files:
        rel_n = rel.replace("\\", "/")
        if not _path_has_dir(rel_n, "op_kernel"):
            continue
        if not arch_compatible(rel_n, architecture):
            continue
        path = repo_root / rel
        if not path.exists() or path.suffix not in {".h", ".hpp", ".cpp", ".cc", ".c"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in global_re.finditer(text):
            name = match.group(1)
            line = text.count("\n", 0, match.start()) + 1
            conf = (
                _confidence(
                    "public_kernel_entry",
                    name,
                    rel_n,
                    op_name,
                    architecture,
                    role_patterns=role_patterns,
                    exact_preferred=exact_preferred,
                )
                + 0.1
            )
            # __global__ is strong evidence — naming style must not exclude it.
            conf = max(float(conf), 0.85)
            out.append(
                {
                    "node_id": 0,
                    "name": name,
                    "qualified_name": f"{rel_n}::{name}",
                    "file_path": rel_n,
                    "start_line": line,
                    "end_line": line,
                    "label": "global_kernel",
                    "role": "public_kernel_entry",
                    "pattern": "__global__",
                    "confidence": min(1.0, conf),
                    "signature_snippet": snippet("\n".join(text.splitlines()[max(0, line - 1) : line + 5])),
                    "evidence_classes": ["global_kernel_declaration", "confirmed_kernel_file"],
                }
            )
    for rel in confirmed_files:
        rel_n = rel.replace("\\", "/")
        if not arch_compatible(rel_n, architecture) or "entry" not in Path(rel_n).name.lower():
            continue
        if not _path_has_dir(rel_n, "op_kernel"):
            continue
        path = repo_root / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in re.finditer(r"\b([A-Za-z_][A-Za-z0-9_]*Entry[A-Za-z0-9_]*)\b", text):
            name = match.group(1)
            line = text.count("\n", 0, match.start()) + 1
            conf = (
                _confidence(
                    "public_kernel_entry",
                    name,
                    rel_n,
                    op_name,
                    architecture,
                    role_patterns=role_patterns,
                    exact_preferred=exact_preferred,
                )
                + 0.2
            )
            out.append(
                {
                    "node_id": 0,
                    "name": name,
                    "qualified_name": f"{rel_n}::{name}",
                    "file_path": rel_n,
                    "start_line": line,
                    "end_line": line,
                    "label": "entry_symbol",
                    "role": "public_kernel_entry",
                    "pattern": "Entry",
                    "confidence": min(1.0, conf),
                    "signature_snippet": snippet("\n".join(text.splitlines()[max(0, line - 1) : line + 5])),
                }
            )
    return out


# ROLE_PATTERNS already uses host_tiling_entry / kernel_entry keys for tests.


if __name__ == "__main__":
    raise SystemExit(main())
