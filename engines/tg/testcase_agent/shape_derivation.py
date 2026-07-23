"""Build shape_determined closure along CSV → KEY/KVAR assignment chains."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .expr_bind import collect_var_ids_from_expr
from .io import read_json, read_yaml, write_yaml

OUT_OF_SCOPE_MARKERS = (
    "LOOP_LOCAL",
    "PLATFORM_MACRO",
    "NO_HOST_PRODUCER",
    "PLATFORM",
    "COMPILE_MACRO",
)

SHAPEISH_COLUMNS = {
    "B",
    "N",
    "N1",
    "N2",
    "S",
    "S1",
    "S2",
    "D",
    "D_V",
    "G",
    "H",
    "T",
}


def build_and_write_shape_derivation(
    out_root: Path,
    *,
    lexicon: dict[str, Any] | None = None,
    rmap: dict[str, Any] | None = None,
    resolve_files: list[Path] | None = None,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build derivation graph + write bind artifacts. Returns graph doc."""
    out_root = Path(out_root)
    realization = out_root / "realization"
    if lexicon is None:
        lex_path = realization / "binding_lexicon.yaml"
        lexicon = read_yaml(lex_path) if lex_path.is_file() else {}
    if not isinstance(lexicon, dict):
        lexicon = {}
    if rmap is None:
        map_path = realization / "realization_map.yaml"
        rmap = read_yaml(map_path) if map_path.is_file() else {}
    if not isinstance(rmap, dict):
        rmap = {}
    if resolve_files is None:
        resolve_dir = realization / "uo_query_resolve"
        resolve_files = sorted(resolve_dir.glob("KEY_*.yaml")) if resolve_dir.is_dir() else []
    if snapshot is None:
        snapshot = _load_snapshot(out_root)

    graph = build_shape_derivation_graph(
        lexicon=lexicon,
        rmap=rmap,
        resolve_files=resolve_files,
        snapshot=snapshot,
    )
    _write_shape_artifacts(out_root, graph)
    return graph


def build_shape_derivation_graph(
    *,
    lexicon: dict[str, Any],
    rmap: dict[str, Any],
    resolve_files: list[Path],
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    roots: set[str] = set()
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    out_of_scope: list[str] = []
    edge_keys: set[tuple[str, str]] = set()

    def add_node(nid: str, *, kind: str = "unknown", via: str = "", deps: list[str] | None = None) -> None:
        nid = _norm_id(nid)
        if not nid or _is_out_of_scope(nid):
            if nid and nid not in out_of_scope:
                out_of_scope.append(nid)
            return
        entry = nodes.setdefault(
            nid,
            {"id": nid, "kind": kind, "shape_determined": False, "deps": [], "via": via or ""},
        )
        if kind and entry.get("kind") in {"", "unknown"}:
            entry["kind"] = kind
        if via and not entry.get("via"):
            entry["via"] = via
        for dep in deps or []:
            d = _norm_id(dep)
            if d and d not in entry["deps"]:
                entry["deps"].append(d)

    def add_edge(src: str, dst: str, *, evidence: str = "") -> None:
        src, dst = _norm_id(src), _norm_id(dst)
        if not src or not dst or src == dst:
            return
        if _is_out_of_scope(src) or _is_out_of_scope(dst):
            for x in (src, dst):
                if _is_out_of_scope(x) and x not in out_of_scope:
                    out_of_scope.append(x)
            return
        key = (src, dst)
        if key in edge_keys:
            return
        edge_keys.add(key)
        edges.append({"from": src, "to": dst, "evidence": evidence})
        add_node(dst)
        if src not in nodes[dst]["deps"]:
            nodes[dst]["deps"].append(src)

    # --- roots from CSV ---
    for item in rmap.get("csv_variables") or []:
        if not isinstance(item, dict):
            continue
        vid = _norm_id(item.get("id") or "")
        col = str(item.get("column") or item.get("name") or "")
        if not vid:
            continue
        if vid.startswith("VAR_CSV_") or _is_shapeish_column(col) or _looks_like_csv_root(item):
            roots.add(vid)
            add_node(vid, kind="csv", via="csv_variables")

    # --- resolve docs ---
    for path in resolve_files:
        doc = read_yaml(path) if path.is_file() else {}
        if not isinstance(doc, dict):
            continue
        key_id = str(doc.get("key_id") or path.stem)
        evidence = f"uo_query_resolve/{path.name}"
        for vid in doc.get("shape_determined") or []:
            nid = _norm_id(vid)
            if nid:
                roots.add(nid)
                add_node(nid, kind=_kind_of(nid), via="shape_determined")
        for bind in doc.get("csv_bindings") or []:
            if isinstance(bind, str):
                nid = _norm_id(bind if bind.startswith("VAR_") else f"VAR_CSV_{bind}")
            elif isinstance(bind, dict):
                col = str(bind.get("column") or bind.get("csv") or bind.get("id") or "")
                nid = _norm_id(col if col.startswith("VAR_") else f"VAR_CSV_{col}")
            else:
                continue
            if nid:
                roots.add(nid)
                add_node(nid, kind="csv", via="csv_bindings")
        kd = doc.get("key_derivation") if isinstance(doc.get("key_derivation"), dict) else {}
        key_var = _norm_id(kd.get("id") or f"VAR_{key_id}" if key_id.startswith("KEY_") else f"VAR_KEY_{key_id}")
        expr = kd.get("expr") if "expr" in kd else doc.get("expr")
        if key_var and isinstance(expr, dict):
            deps = sorted(collect_var_ids_from_expr(expr))
            add_node(key_var, kind="key", via="key_derivation", deps=deps)
            for dep in deps:
                add_edge(dep, key_var, evidence=evidence)
        for step in doc.get("derivation_chain") or []:
            if not isinstance(step, dict):
                continue
            sid = _norm_id(step.get("id") or "")
            if not sid:
                continue
            if _is_out_of_scope(sid) or _is_out_of_scope(str(step.get("via") or "")):
                if sid not in out_of_scope:
                    out_of_scope.append(sid)
                continue
            deps = [_norm_id(d) for d in (step.get("deps") or []) if _norm_id(d)]
            via = str(step.get("via") or "derivation_chain")
            add_node(sid, kind=_kind_of(sid), via=via, deps=deps)
            if not deps:
                roots.add(sid)
            for dep in deps:
                add_edge(dep, sid, evidence=evidence)

    # --- lexicon key_derivations ---
    for item in lexicon.get("key_derivations") or []:
        if not isinstance(item, dict):
            continue
        vid = _norm_id(item.get("id") or "")
        expr = item.get("expr")
        if not vid or not isinstance(expr, dict):
            continue
        deps = sorted(collect_var_ids_from_expr(expr))
        add_node(vid, kind=_kind_of(vid), via="lexicon", deps=deps)
        for dep in deps:
            add_edge(dep, vid, evidence="binding_lexicon.key_derivations")
        for sid in item.get("shape_determined") or []:
            nid = _norm_id(sid)
            if nid:
                roots.add(nid)
                add_node(nid, kind=_kind_of(nid), via="lexicon_shape_determined")

    # --- KB snapshot supplements ---
    _add_kb_edges(snapshot, add_node, add_edge, out_of_scope)

    # --- closure ---
    closure = set(roots)
    changed = True
    while changed:
        changed = False
        for nid, node in nodes.items():
            if nid in closure or _is_out_of_scope(nid):
                continue
            deps = [_norm_id(d) for d in node.get("deps") or []]
            if not deps:
                continue
            if all(d in closure for d in deps):
                closure.add(nid)
                node["shape_determined"] = True
                changed = True

    for nid in roots:
        if nid in nodes:
            nodes[nid]["shape_determined"] = True
        else:
            add_node(nid, kind=_kind_of(nid), via="root")
            nodes[nid]["shape_determined"] = True

    derived = sorted(vid for vid in closure if not vid.startswith("VAR_CSV_"))
    return {
        "version": 1,
        "status": "built",
        "updated_at": _now(),
        "roots": sorted(roots),
        "nodes": sorted(nodes.values(), key=lambda n: str(n.get("id") or "")),
        "edges": edges,
        "closure": sorted(closure),
        "derived": derived,
        "out_of_scope": sorted(set(out_of_scope)),
    }


def load_shape_closure(out_root: Path | None) -> set[str]:
    if out_root is None:
        return set()
    path = Path(out_root) / "bind" / "shape_derivation_graph.yaml"
    if not path.is_file():
        # Fallback to shape_determined.yaml
        det = Path(out_root) / "bind" / "shape_determined.yaml"
        if not det.is_file():
            return set()
        doc = read_yaml(det)
        if not isinstance(doc, dict):
            return set()
        out: set[str] = set()
        for item in doc.get("variables") or []:
            if isinstance(item, str):
                out.add(_norm_id(item))
            elif isinstance(item, dict):
                out.add(_norm_id(item.get("id") or item.get("name") or ""))
        return {x for x in out if x}
    doc = read_yaml(path)
    if not isinstance(doc, dict):
        return set()
    return {_norm_id(x) for x in (doc.get("closure") or []) if _norm_id(x)}


def rebuild_branch_alignment(out_root: Path) -> dict[str, Any]:
    """Re-run align_branches with merged lexicon + shape closure; update realization_map."""
    out_root = Path(out_root)
    snapshot = _load_snapshot(out_root)
    if not snapshot:
        return {"status": "skipped", "reason": "no_snapshot"}

    realization = out_root / "realization"
    map_path = realization / "realization_map.yaml"
    lex_path = realization / "binding_lexicon.yaml"
    rmap = read_yaml(map_path) if map_path.is_file() else {}
    lexicon = read_yaml(lex_path) if lex_path.is_file() else {}
    if not isinstance(rmap, dict):
        rmap = {}
    if not isinstance(lexicon, dict):
        lexicon = {}

    files = snapshot.get("files") if isinstance(snapshot.get("files"), dict) else {}
    branches_doc = files.get("kernel/branches.yaml") if isinstance(files.get("kernel/branches.yaml"), dict) else {}
    if not branches_doc.get("branches"):
        # Fallback cached copy
        cached = realization / "branches_doc.yaml"
        if cached.is_file():
            branches_doc = read_yaml(cached)
        if not isinstance(branches_doc, dict) or not branches_doc.get("branches"):
            return {"status": "skipped", "reason": "no_branches"}

    columns = []
    consumer = rmap.get("consumer") if isinstance(rmap.get("consumer"), dict) else {}
    columns = [str(c) for c in (consumer.get("columns") or [])]
    if not columns:
        columns = [
            str(item.get("column") or "")
            for item in (rmap.get("csv_variables") or [])
            if isinstance(item, dict) and item.get("column")
        ]

    closure = load_shape_closure(out_root)
    from .branch_align import align_branches

    op_name = str(rmap.get("op_name") or consumer.get("op_name") or "")
    aligned = align_branches(
        branches_doc,
        snapshot,
        csv_columns=columns,
        lexicon=lexicon,
        op_name=op_name,
        shape_closure=closure,
    )
    mappings = aligned.get("branch_mappings") or []
    abstract = aligned.get("abstract_branches") or []
    report = aligned.get("alignment_report") or {}

    # Preserve derived KEY vars from lexicon; refresh branch-derived vars.
    from .binding_lexicon import apply_lexicon_key_derivations

    key_derived = apply_lexicon_key_derivations([], lexicon)
    existing_ids = {str(item.get("id") or "") for item in key_derived}
    for stub in aligned.get("stub_derived_variables") or []:
        vid = str(stub.get("id") or "")
        if vid and vid not in existing_ids:
            key_derived.append(stub)
            existing_ids.add(vid)
    branch_derived = [item["derived_variable"] for item in mappings if isinstance(item.get("derived_variable"), dict)]

    rmap["branch_mappings"] = [{k: v for k, v in item.items() if k != "derived_variable"} for item in mappings]
    rmap["abstract_branches"] = abstract
    rmap["alignment_report"] = report
    rmap["derived_variables"] = key_derived + branch_derived
    rmap["binding_lexicon_source"] = lexicon.get("source")
    write_yaml(map_path, rmap)
    write_yaml(realization / "alignment_report.yaml", report)

    return {
        "status": "rebuilt",
        "mapped": len(mappings),
        "abstract": len(abstract),
        "closure_size": len(closure),
        "alignment_report": report,
    }


def check_unbound_reducible(out_root: Path) -> dict[str, Any]:
    """Fail if abstract unbound atoms reference symbols already in shape closure."""
    out_root = Path(out_root)
    closure = load_shape_closure(out_root)
    map_path = out_root / "realization" / "realization_map.yaml"
    rmap = read_yaml(map_path) if map_path.is_file() else {}
    if not isinstance(rmap, dict):
        rmap = {}
    hits: list[dict[str, Any]] = []
    for branch in rmap.get("abstract_branches") or []:
        if not isinstance(branch, dict):
            continue
        for atom in branch.get("unbound_atoms") or []:
            if not isinstance(atom, dict):
                continue
            name = str(atom.get("name") or atom.get("raw") or "")
            candidates = {
                _norm_id(name),
                _norm_id(f"VAR_{name}"),
                _norm_id(f"VAR_KEY_{name}"),
                _norm_id(f"VAR_KVAR_{name}"),
                _candidate_var_from_name(name),
            }
            overlap = {c for c in candidates if c and c in closure}
            if overlap:
                hits.append(
                    {
                        "branch_ref": branch.get("branch_ref") or branch.get("var"),
                        "atom": name,
                        "closure_ids": sorted(overlap),
                        "reason": atom.get("reason"),
                    }
                )
    return {
        "status": "fail" if hits else "pass",
        "hits": hits,
        "closure_size": len(closure),
    }


def check_shape_graph_built(out_root: Path) -> dict[str, Any]:
    out_root = Path(out_root)
    graph_path = out_root / "bind" / "shape_derivation_graph.yaml"
    if not graph_path.is_file():
        return {"status": "fail", "detail": "missing bind/shape_derivation_graph.yaml"}
    doc = read_yaml(graph_path)
    if not isinstance(doc, dict) or str(doc.get("status") or "") != "built":
        return {"status": "fail", "detail": "graph status != built"}
    resolve_dir = out_root / "realization" / "uo_query_resolve"
    has_shape_signal = False
    if resolve_dir.is_dir():
        for path in resolve_dir.glob("KEY_*.yaml"):
            d = read_yaml(path)
            if not isinstance(d, dict):
                continue
            if d.get("shape_determined") or d.get("derivation_chain"):
                has_shape_signal = True
                break
            if str(d.get("status") or "").lower() == "resolved":
                has_shape_signal = True
                break
    closure = doc.get("closure") or []
    if has_shape_signal and not closure:
        return {"status": "fail", "detail": "resolved KEY present but closure empty"}
    return {"status": "pass", "detail": f"closure={len(closure)} roots={len(doc.get('roots') or [])}"}


def check_shape_chain_consistent(out_root: Path) -> dict[str, Any]:
    out_root = Path(out_root)
    graph_path = out_root / "bind" / "shape_derivation_graph.yaml"
    lex_path = out_root / "realization" / "binding_lexicon.yaml"
    if not graph_path.is_file():
        return {"status": "fail", "detail": "missing shape graph"}
    graph = read_yaml(graph_path)
    lexicon = read_yaml(lex_path) if lex_path.is_file() else {}
    if not isinstance(graph, dict):
        return {"status": "fail", "detail": "invalid graph"}
    if not isinstance(lexicon, dict):
        lexicon = {}
    edge_pairs = {(str(e.get("from")), str(e.get("to"))) for e in (graph.get("edges") or []) if isinstance(e, dict)}
    reachable_deps: dict[str, set[str]] = {}
    for frm, to in edge_pairs:
        reachable_deps.setdefault(to, set()).add(frm)
    missing: list[str] = []
    for item in lexicon.get("key_derivations") or []:
        if not isinstance(item, dict) or not isinstance(item.get("expr"), dict):
            continue
        vid = _norm_id(item.get("id") or "")
        deps = collect_var_ids_from_expr(item["expr"])
        known = reachable_deps.get(vid, set())
        for dep in deps:
            if dep not in known and (dep, vid) not in edge_pairs:
                # Allow CSV roots without explicit edge listing if both in closure
                closure = set(graph.get("closure") or [])
                if dep in closure and vid in closure:
                    continue
                missing.append(f"{vid} missing edge from {dep}")
    return {
        "status": "fail" if missing else "pass",
        "detail": "; ".join(missing[:8]) if missing else "ok",
        "missing": missing,
    }


def _write_shape_artifacts(out_root: Path, graph: dict[str, Any]) -> None:
    bind = out_root / "bind"
    bind.mkdir(parents=True, exist_ok=True)
    write_yaml(bind / "shape_derivation_graph.yaml", graph)
    variables = [{"id": vid, "shape_determined": True} for vid in (graph.get("derived") or [])]
    # Also include CSV roots that were explicitly shape_determined signals
    for vid in graph.get("roots") or []:
        if str(vid).startswith("VAR_CSV_"):
            continue
        if not any(v.get("id") == vid for v in variables):
            variables.append({"id": vid, "shape_determined": True})
    write_yaml(
        bind / "shape_determined.yaml",
        {
            "version": 1,
            "status": "merged",
            "variables": variables,
            "source": "shape_derivation_closure",
            "closure_size": len(graph.get("closure") or []),
        },
    )
    write_yaml(
        bind / "shape_derivation_report.yaml",
        {
            "version": 1,
            "status": graph.get("status"),
            "updated_at": graph.get("updated_at"),
            "roots": len(graph.get("roots") or []),
            "nodes": len(graph.get("nodes") or []),
            "edges": len(graph.get("edges") or []),
            "closure": len(graph.get("closure") or []),
            "derived": len(graph.get("derived") or []),
            "out_of_scope": len(graph.get("out_of_scope") or []),
        },
    )


def _add_kb_edges(
    snapshot: dict[str, Any] | None,
    add_node,
    add_edge,
    out_of_scope: list[str],
) -> None:
    if not isinstance(snapshot, dict):
        return
    files = snapshot.get("files") if isinstance(snapshot.get("files"), dict) else {}
    variables = files.get("kernel/variables.yaml") if isinstance(files.get("kernel/variables.yaml"), dict) else {}
    for item in variables.get("runtime_variables") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        vid = _norm_id(item.get("id") or (f"VAR_KVAR_{name}" if name else ""))
        classification = str(item.get("classification") or "").lower()
        if classification in {"loop_local", "platform"} or _is_out_of_scope(vid) or _is_out_of_scope(name):
            if vid and vid not in out_of_scope:
                out_of_scope.append(vid)
            continue
        set_by = item.get("set_by") if isinstance(item.get("set_by"), dict) else {}
        deps: list[str] = []
        if set_by.get("csv"):
            deps.append(_norm_id(f"VAR_CSV_{set_by['csv']}"))
        if set_by.get("key"):
            key = str(set_by["key"])
            deps.append(_norm_id(key if key.startswith("VAR_") else f"VAR_KEY_{key.removeprefix('KEY_')}"))
        if not deps:
            continue
        add_node(vid, kind="kvar", via="kb_set_by", deps=deps)
        for dep in deps:
            add_edge(dep, vid, evidence="kernel/variables.yaml")


def _load_snapshot(out_root: Path) -> dict[str, Any] | None:
    path = Path(out_root) / "snapshot" / "understand_contract.json"
    if not path.is_file():
        return None
    try:
        data = read_json(path)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _norm_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in text).strip("_")
    # Preserve VAR_*/KEY_* spelling (e.g. VAR_CSV_keep_prob); only normalize bare tokens.
    if safe.startswith("VAR_") or safe.startswith("KEY_") or safe.startswith("KVAR_"):
        return safe
    return safe


def _kind_of(vid: str) -> str:
    u = vid.upper()
    if u.startswith("VAR_CSV_"):
        return "csv"
    if u.startswith("VAR_KEY_") or u.startswith("KEY_"):
        return "key"
    if u.startswith("VAR_KVAR_") or u.startswith("KVAR_"):
        return "kvar"
    return "unknown"


def _is_out_of_scope(text: str) -> bool:
    u = str(text or "").upper()
    return any(m in u for m in OUT_OF_SCOPE_MARKERS)


def _is_shapeish_column(col: str) -> bool:
    return str(col or "").upper() in SHAPEISH_COLUMNS


def _looks_like_csv_root(item: dict[str, Any]) -> bool:
    role = str(item.get("role") or "").lower()
    if role in {"shape", "solver_input", "tiling"}:
        return True
    domain = item.get("domain")
    if isinstance(domain, dict) and domain.get("kind") in {"range", "values"}:
        return True
    if isinstance(domain, list) and domain:
        return True
    return False


def _candidate_var_from_name(name: str) -> str:
    leaf = str(name or "").split(".")[-1].split("::")[-1]
    leaf = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in leaf).strip("_")
    if not leaf:
        return ""
    upper = leaf.upper()
    if upper.startswith("VAR_"):
        return upper
    if upper.startswith("KEY_"):
        return f"VAR_{upper}"
    if upper.startswith("IS") or upper.startswith("HAS") or upper.startswith("ENABLE"):
        return f"VAR_KEY_{upper}"
    return f"VAR_KVAR_{upper}"


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()
