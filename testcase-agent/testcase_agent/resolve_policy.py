"""Hard gates for tg-init uo_query_resolve: high-only, chain→CSV, no opaque fn."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .expr_bind import collect_var_ids_from_expr
from .io import read_yaml, write_yaml

# Empty-tensor family may stay unresolved without blocking merge/confirm.
EMPTY_KEY_ALLOWLIST = frozenset(
    {
        "KEY_ISEMPTYTENSOR",
        "ISEMPTYTENSOR",
        "KEY_ISEMPTY",
        "ISEMPTY",
    }
)

FORBIDDEN_CONFIDENCE = frozenset({"medium", "low", "unknown", ""})

# Fake / non-executable lexicon leaves (ses_07b3 style).
PLACEHOLDER_EXPR_RE = re.compile(
    r"(?i)^(already_bound(_in_kb)?|deter_branch|needs_alignment|todo|tbd|"
    r"placeholder|not_implemented|n/?a|unknown|see_kb|pre.?bound)$"
)

OPAQUE_FN_RE = re.compile(
    r"(?i)\b("
    r"GetOptionalInputDesc|GetRequiredInputDesc|GetInputDesc|GetOutputDesc|"
    r"GetAttr|GetOptionalAttr|GetIntAttr|GetFloatAttr|GetBoolAttr|"
    r"GetWorkspaceSizes|GetTilingKey|context_\s*->"
    r")\b"
)

ALLOWED_EXPR_OPS = frozenset(
    {
        "if_then_else",
        "eq",
        "ne",
        "lt",
        "le",
        "gt",
        "ge",
        "and",
        "or",
        "not",
        "in",
        "not_in",
        "add",
        "sub",
        "mul",
        "div",
        "mod",
        "lit",
        "derived",
        "var",
        "const",
    }
)


def is_empty_allowlisted(key_id: str, doc: dict[str, Any] | None = None) -> bool:
    kid = str(key_id or "").upper()
    if kid in EMPTY_KEY_ALLOWLIST or kid.removeprefix("KEY_") in {x.removeprefix("KEY_") for x in EMPTY_KEY_ALLOWLIST}:
        return True
    if isinstance(doc, dict):
        skip = str(doc.get("skip_reason") or "").lower()
        if "empty" in skip:
            return True
    return False


def is_compile_time_terminal(node_id: str, step: dict[str, Any] | None = None) -> bool:
    text = str(node_id or "").upper()
    via = str((step or {}).get("via") or "").lower()
    if via in {"compile_time", "compile_time_constant", "platform_constant", "lit"}:
        return True
    if text.startswith("LIT_") or text.startswith("COMPILE_") or text.startswith("CONST_"):
        return True
    if (step or {}).get("compile_time") is True or (step or {}).get("constant") is True:
        return True
    return False


def is_csv_terminal(node_id: str) -> bool:
    return str(node_id or "").startswith("VAR_CSV_")


def expr_has_opaque_call(expr: Any) -> str:
    """Return reason if expr contains forbidden call ops or opaque Host API leaves."""
    if isinstance(expr, dict):
        op = str(expr.get("op") or "").lower()
        if op == "call":
            return "opaque_fn:op_call"
        if op and op not in ALLOWED_EXPR_OPS and op not in {"atom"}:
            # unknown ops that look like function application
            if op not in {"eq", "ne"}:
                pass
        for key in ("name", "fn", "func", "callee"):
            val = expr.get(key)
            if isinstance(val, str) and OPAQUE_FN_RE.search(val):
                return f"opaque_fn:{val}"
        for key in ("arg", "lhs", "rhs", "condition", "then", "else", "expr"):
            if key in expr:
                hit = expr_has_opaque_call(expr[key])
                if hit:
                    return hit
        for child in expr.get("args") or []:
            hit = expr_has_opaque_call(child)
            if hit:
                return hit
        for child in expr.get("values") or []:
            hit = expr_has_opaque_call(child)
            if hit:
                return hit
    elif isinstance(expr, str) and OPAQUE_FN_RE.search(expr):
        return f"opaque_fn:{expr[:80]}"
    return ""


def text_has_opaque_fn(text: str) -> bool:
    return bool(OPAQUE_FN_RE.search(str(text or "")))


def expr_is_placeholder(expr: Any) -> str:
    """Return reason if expr is a non-executable placeholder (not SMT-ready)."""
    if expr is None:
        return "placeholder:null_expr"
    if isinstance(expr, str):
        text = expr.strip()
        if not text:
            return "placeholder:empty_string"
        if PLACEHOLDER_EXPR_RE.match(text):
            return f"placeholder:{text}"
        if text_has_opaque_fn(text):
            return f"opaque_fn:{text[:80]}"
        return ""
    if isinstance(expr, (int, float, bool)):
        return ""
    if isinstance(expr, dict):
        op = str(expr.get("op") or "").lower()
        if op == "if_then_else" and expr.get("then") == expr.get("else") and "then" in expr:
            return "placeholder:then_eq_else"
        for key in ("expr", "value", "label", "via", "kind", "name"):
            val = expr.get(key)
            if isinstance(val, str) and PLACEHOLDER_EXPR_RE.match(val.strip()):
                return f"placeholder:{val.strip()}"
        for key in ("arg", "lhs", "rhs", "condition", "then", "else", "expr"):
            if key in expr:
                hit = expr_is_placeholder(expr[key])
                if hit:
                    return hit
        for child in expr.get("args") or []:
            hit = expr_is_placeholder(child)
            if hit:
                return hit
        for child in expr.get("values") or []:
            hit = expr_is_placeholder(child)
            if hit:
                return hit
    return ""


def chain_leaves(chain: list[Any], *, key_var: str = "", expr: Any = None) -> set[str]:
    """Collect dependency leaves from derivation_chain (+ expr vars as fallback roots)."""
    nodes: dict[str, set[str]] = {}
    for step in chain or []:
        if not isinstance(step, dict):
            continue
        sid = str(step.get("id") or "").strip()
        if not sid:
            continue
        deps = {str(d).strip() for d in (step.get("deps") or []) if str(d).strip()}
        nodes[sid] = deps
    if key_var and key_var not in nodes and isinstance(expr, dict):
        nodes[key_var] = collect_var_ids_from_expr(expr)
    if not nodes and isinstance(expr, dict):
        return collect_var_ids_from_expr(expr)

    referenced: set[str] = set()
    for deps in nodes.values():
        referenced |= deps
    # leaves = ids that appear as deps but are not defined as chain nodes with further deps,
    # plus deps that are terminals
    leaves: set[str] = set()
    defined = set(nodes)
    for sid, deps in nodes.items():
        if not deps:
            # bare node: treat as leaf candidate unless compile-time
            leaves.add(sid)
            continue
        for d in deps:
            if d not in defined:
                leaves.add(d)
            elif not nodes.get(d):
                leaves.add(d)
    # Also any expr vars not expanded
    if isinstance(expr, dict):
        for vid in collect_var_ids_from_expr(expr):
            if vid not in defined:
                leaves.add(vid)
    return leaves


def validate_chain_terminates_at_csv(
    doc: dict[str, Any],
    *,
    key_var: str = "",
) -> tuple[bool, str]:
    chain = doc.get("derivation_chain") or []
    kd = doc.get("key_derivation") if isinstance(doc.get("key_derivation"), dict) else {}
    expr = kd.get("expr") if "expr" in kd else doc.get("expr")
    if not chain:
        # Allow missing chain only when expr leaves are already all CSV / none
        if isinstance(expr, dict):
            leaves = collect_var_ids_from_expr(expr)
            bad = [v for v in leaves if not is_csv_terminal(v) and not is_compile_time_terminal(v)]
            if not bad:
                return True, "expr_csv_only"
            return False, f"missing_derivation_chain:non_csv_leaves={bad}"
        return False, "missing_derivation_chain"

    leaves = chain_leaves(chain, key_var=key_var, expr=expr)
    # Steps marked compile-time with empty deps are ok
    for step in chain:
        if isinstance(step, dict) and is_compile_time_terminal(str(step.get("id") or ""), step):
            leaves.discard(str(step.get("id") or ""))

    bad: list[str] = []
    for leaf in sorted(leaves):
        if is_csv_terminal(leaf) or is_compile_time_terminal(leaf):
            continue
        # Find step for via hint
        step = next((s for s in chain if isinstance(s, dict) and str(s.get("id")) == leaf), None)
        if step and is_compile_time_terminal(leaf, step):
            continue
        bad.append(leaf)
    if bad:
        return False, f"shape_closure_incomplete:leaves={bad}"
    return True, ""


def validate_resolved_doc(doc: dict[str, Any], *, key_id: str, key_var: str) -> tuple[bool, str, str]:
    """Return (ok, ask, reason) for a resolved KEY doc."""
    confidence = str(doc.get("confidence") or "").strip().lower()
    if confidence != "high":
        return False, "confidence_not_high", f"confidence={confidence or 'missing'} (high required)"

    shape_expr = str(doc.get("shape_expr") or "")
    if text_has_opaque_fn(shape_expr):
        return False, "opaque_fn_leaf", f"shape_expr has opaque Host API: {shape_expr[:120]}"
    if PLACEHOLDER_EXPR_RE.match(shape_expr.strip()):
        return False, "placeholder_expr", f"shape_expr placeholder: {shape_expr}"

    kd = doc.get("key_derivation") if isinstance(doc.get("key_derivation"), dict) else {}
    expr = kd.get("expr") if "expr" in kd else doc.get("expr")
    ph = expr_is_placeholder(expr)
    if ph:
        return False, "placeholder_expr", ph
    opaque = expr_has_opaque_call(expr)
    if opaque:
        return False, "opaque_fn_leaf", opaque

    ok, reason = validate_chain_terminates_at_csv(doc, key_var=key_var)
    if not ok:
        ask = "shape_closure_incomplete" if "closure" in reason or "leaves" in reason else "shape_closure_incomplete"
        return False, ask, reason
    return True, "", ""


def require_high_only(out_root: Path) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    resolve_dir = Path(out_root) / "realization" / "uo_query_resolve"
    if not resolve_dir.is_dir():
        return {"status": "pass", "detail": "no uo_query_resolve dir", "issues": []}
    for path in sorted(resolve_dir.glob("KEY_*.yaml")):
        doc = read_yaml(path)
        if not isinstance(doc, dict):
            continue
        status = str(doc.get("status") or "").lower()
        if status != "resolved":
            continue
        conf = str(doc.get("confidence") or "").lower()
        if conf != "high":
            issues.append({"file": path.name, "confidence": conf or "missing"})
    return {"status": "fail" if issues else "pass", "issues": issues}


def require_chains_terminate_at_csv(out_root: Path) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    resolve_dir = Path(out_root) / "realization" / "uo_query_resolve"
    if not resolve_dir.is_dir():
        return {"status": "pass", "detail": "no uo_query_resolve dir", "issues": []}
    for path in sorted(resolve_dir.glob("KEY_*.yaml")):
        doc = read_yaml(path)
        if not isinstance(doc, dict):
            continue
        if str(doc.get("status") or "").lower() != "resolved":
            continue
        key_id = str(doc.get("key_id") or path.stem)
        kd = doc.get("key_derivation") if isinstance(doc.get("key_derivation"), dict) else {}
        key_var = str(kd.get("id") or f"VAR_{key_id}" if key_id.startswith("KEY_") else f"VAR_KEY_{key_id}")
        ok, reason = validate_chain_terminates_at_csv(doc, key_var=key_var)
        if not ok:
            issues.append({"file": path.name, "reason": reason})
        opaque = expr_has_opaque_call(kd.get("expr") if "expr" in kd else doc.get("expr"))
        if opaque or text_has_opaque_fn(str(doc.get("shape_expr") or "")):
            issues.append({"file": path.name, "reason": opaque or "opaque_shape_expr"})
    return {"status": "fail" if issues else "pass", "issues": issues}


def require_no_nonempty_unresolved(out_root: Path, empty_allowlist: frozenset[str] | None = None) -> dict[str, Any]:
    allow = empty_allowlist or EMPTY_KEY_ALLOWLIST
    issues: list[dict[str, Any]] = []
    resolve_dir = Path(out_root) / "realization" / "uo_query_resolve"
    if not resolve_dir.is_dir():
        return {"status": "pass", "detail": "no uo_query_resolve dir", "issues": [], "ask": ""}
    for path in sorted(resolve_dir.glob("KEY_*.yaml")):
        doc = read_yaml(path)
        if not isinstance(doc, dict):
            continue
        key_id = str(doc.get("key_id") or path.stem)
        status = str(doc.get("status") or "").lower()
        if status not in {"unresolved", "needs_human", "not_csv_realizable"} and doc.get("not_csv_realizable") is not True:
            continue
        if is_empty_allowlisted(key_id, doc) or key_id.upper() in allow:
            continue
        issues.append(
            {
                "file": path.name,
                "key_id": key_id,
                "status": status or "unresolved",
                "reason": doc.get("unresolved_reason") or doc.get("rationale") or "nonempty_unresolved",
            }
        )
    return {"status": "fail" if issues else "pass", "issues": issues, "ask": "key_unresolved" if issues else ""}


def collect_kernel_unbound_symbols(out_root: Path, *, limit: int = 64) -> dict[str, Any]:
    """Aggregate abstract branch unbound symbols for tg-init kernel pass Tasks."""
    map_path = Path(out_root) / "realization" / "realization_map.yaml"
    rmap = read_yaml(map_path) if map_path.is_file() else {}
    if not isinstance(rmap, dict):
        rmap = {}
    ignore_reasons = {"LOOP_LOCAL", "PLATFORM_MACRO", "PARSE_FAIL"}
    keep_sources = {
        "TilingKey",
        "KernelVariable",
        "TilingDataField",
        "UnboundTemplateSymbol",
        "KernelDerivedField",
    }
    keep_reasons = {
        "UNBOUND_ATOM",
        "UNBOUND_CMP",
        "UNBOUND_KVAR",
        "UNBOUND_CALL",
        "KEY_DERIVATION_MISSING",
        "NO_HOST_PRODUCER",
    }
    symbols: dict[str, dict[str, Any]] = {}
    for branch in rmap.get("abstract_branches") or []:
        if not isinstance(branch, dict):
            continue
        source = str(branch.get("determinant_source") or "")
        reason = str(branch.get("reason") or "")
        if source and source not in keep_sources:
            continue
        if reason in ignore_reasons:
            continue
        if reason and reason not in keep_reasons and not reason.startswith("UNBOUND"):
            continue
        for atom in branch.get("unbound_atoms") or []:
            if not isinstance(atom, dict):
                continue
            atom_reason = str(atom.get("reason") or reason)
            if atom_reason in ignore_reasons:
                continue
            name = str(atom.get("name") or atom.get("raw") or "").strip()
            if not name or "empty" in name.lower():
                continue
            entry = symbols.setdefault(
                name,
                {"name": name, "count": 0, "reasons": set(), "sources": set(), "branches": []},
            )
            entry["count"] += 1
            entry["reasons"].add(atom_reason)
            if source:
                entry["sources"].add(source)
            bref = str(branch.get("branch_ref") or branch.get("var") or "")
            if bref and len(entry["branches"]) < 5:
                entry["branches"].append(bref)

    ranked = sorted(symbols.values(), key=lambda e: (-int(e["count"]), str(e["name"])))[:limit]
    for item in ranked:
        item["reasons"] = sorted(item["reasons"])
        item["sources"] = sorted(item["sources"])
    return {"status": "ok", "symbols": ranked, "total_unique": len(symbols)}


def require_no_placeholders(out_root: Path) -> dict[str, Any]:
    """Reject already_bound_in_kb / deter_branch / then==else / null expr on resolved docs + lexicon."""
    issues: list[dict[str, Any]] = []
    resolve_dir = Path(out_root) / "realization" / "uo_query_resolve"
    if resolve_dir.is_dir():
        for path in sorted(resolve_dir.glob("KEY_*.yaml")):
            doc = read_yaml(path)
            if not isinstance(doc, dict):
                continue
            if str(doc.get("status") or "").lower() != "resolved":
                continue
            kd = doc.get("key_derivation") if isinstance(doc.get("key_derivation"), dict) else {}
            expr = kd.get("expr") if "expr" in kd else doc.get("expr")
            ph = expr_is_placeholder(expr)
            if ph:
                issues.append({"file": path.name, "where": "resolve", "reason": ph})
            if PLACEHOLDER_EXPR_RE.match(str(doc.get("shape_expr") or "").strip()):
                issues.append({"file": path.name, "where": "shape_expr", "reason": f"placeholder:{doc.get('shape_expr')}"})

    lex_path = Path(out_root) / "realization" / "binding_lexicon.yaml"
    if lex_path.is_file():
        lexicon = read_yaml(lex_path)
        if isinstance(lexicon, dict):
            for item in lexicon.get("key_derivations") or []:
                if not isinstance(item, dict):
                    continue
                if str(item.get("status") or "").lower() == "unresolved":
                    continue
                expr = item.get("expr")
                if expr is None and not item.get("locked"):
                    continue
                ph = expr_is_placeholder(expr)
                if ph:
                    issues.append({"id": item.get("id"), "where": "lexicon", "reason": ph})
    return {"status": "fail" if issues else "pass", "issues": issues, "ask": "placeholder_expr" if issues else ""}


def require_merge_artifacts(out_root: Path) -> dict[str, Any]:
    """Anti-fake gate: real merge/map/shape graph must exist (ban hand-written lexicon-only)."""
    root = Path(out_root)
    missing: list[str] = []
    checks: dict[str, Any] = {}

    merge_path = root / "realization" / "uo_merge_report.yaml"
    if not merge_path.is_file():
        missing.append("realization/uo_merge_report.yaml")
    else:
        report = read_yaml(merge_path)
        ok = isinstance(report, dict) and str(report.get("status") or "").lower() == "pass"
        checks["uo_merge_report"] = "pass" if ok else "fail"
        if not ok:
            missing.append("uo_merge_report.status!=pass")

    map_path = root / "realization" / "realization_map.yaml"
    if not map_path.is_file():
        missing.append("realization/realization_map.yaml")
    else:
        checks["realization_map"] = "pass"

    graph_path = root / "bind" / "shape_derivation_graph.yaml"
    if not graph_path.is_file():
        missing.append("bind/shape_derivation_graph.yaml")
    else:
        graph = read_yaml(graph_path)
        ok = isinstance(graph, dict) and str(graph.get("status") or "").lower() in {"built", "ok", "pass", ""}
        # empty status treated as present if closure key exists
        if isinstance(graph, dict) and ("closure" in graph or "roots" in graph):
            ok = True
        checks["shape_derivation_graph"] = "pass" if ok else "fail"
        if not ok:
            missing.append("shape_derivation_graph incomplete")

    return {
        "status": "fail" if missing else "pass",
        "missing": missing,
        "checks": checks,
        "ask": "uo_merge_required" if missing else "",
    }


def _norm_mid_name(name: str) -> str:
    text = str(name or "").strip()
    if not text:
        return ""
    if text.startswith("VAR_"):
        return text
    # Host / kernel symbols → KVAR id for Task targets
    safe = re.sub(r"[^A-Za-z0-9_]", "_", text)
    return f"VAR_KVAR_{safe}"


def collect_open_mid_symbols(out_root: Path, *, limit: int = 32) -> dict[str, Any]:
    """
    Queue of intermediate symbols that still need nested uo-query Tasks
    (ses_07c3 style: uncertain → CBM/subagent until CSV).
    """
    root = Path(out_root)
    open_syms: dict[str, dict[str, Any]] = {}

    def _add(name: str, *, source: str, reason: str) -> None:
        nid = str(name or "").strip()
        if not nid:
            return
        if is_csv_terminal(nid) or is_compile_time_terminal(nid):
            return
        if "empty" in nid.lower():
            return
        entry = open_syms.setdefault(
            nid,
            {"name": nid, "var_id": _norm_mid_name(nid), "count": 0, "sources": set(), "reasons": set()},
        )
        entry["count"] += 1
        entry["sources"].add(source)
        entry["reasons"].add(reason)

    resolve_dir = root / "realization" / "uo_query_resolve"
    if resolve_dir.is_dir():
        for path in sorted(resolve_dir.glob("*.yaml")):
            doc = read_yaml(path)
            if not isinstance(doc, dict):
                continue
            key_id = str(doc.get("key_id") or path.stem)
            kd = doc.get("key_derivation") if isinstance(doc.get("key_derivation"), dict) else {}
            key_var = str(kd.get("id") or f"VAR_{key_id}" if key_id.startswith("KEY_") else f"VAR_KEY_{key_id}")
            expr = kd.get("expr") if "expr" in kd else doc.get("expr")
            status = str(doc.get("status") or "").lower()
            if status == "resolved":
                ok, reason = validate_chain_terminates_at_csv(doc, key_var=key_var)
                if not ok and "leaves=" in reason:
                    # extract leaves from reason: shape_closure_incomplete:leaves=[...]
                    m = re.search(r"leaves=\[([^\]]*)\]", reason)
                    if m:
                        raw = m.group(1)
                        for part in re.findall(r"'([^']+)'|\"([^\"]+)\"|([A-Za-z_][\w]*)", raw):
                            leaf = part[0] or part[1] or part[2]
                            if leaf:
                                _add(leaf, source=path.name, reason="chain_leaf")
                leaves = chain_leaves(doc.get("derivation_chain") or [], key_var=key_var, expr=expr)
                for leaf in leaves:
                    if not is_csv_terminal(leaf) and not is_compile_time_terminal(leaf):
                        _add(leaf, source=path.name, reason="chain_leaf")
            elif status in {"unresolved", "needs_human"} and not is_empty_allowlisted(key_id, doc):
                # unresolved KEY itself is an open obligation
                _add(key_id, source=path.name, reason="key_unresolved")

    # Kernel abstract unbound
    kern = collect_kernel_unbound_symbols(root, limit=limit * 2)
    for item in kern.get("symbols") or []:
        _add(str(item.get("name") or ""), source="abstract_branches", reason="kernel_unbound")

    # Shape graph nodes not in closure
    graph_path = root / "bind" / "shape_derivation_graph.yaml"
    if graph_path.is_file():
        graph = read_yaml(graph_path)
        if isinstance(graph, dict):
            closure = {str(x) for x in (graph.get("closure") or [])}
            for edge in graph.get("edges") or []:
                if not isinstance(edge, dict):
                    continue
                nid = str(edge.get("id") or edge.get("to") or "").strip()
                if nid and nid not in closure and not is_csv_terminal(nid):
                    _add(nid, source="shape_graph", reason="not_in_closure")
            for unbound in graph.get("unbound") or graph.get("open_nodes") or []:
                if isinstance(unbound, str):
                    _add(unbound, source="shape_graph", reason="graph_unbound")
                elif isinstance(unbound, dict):
                    _add(str(unbound.get("id") or unbound.get("name") or ""), source="shape_graph", reason="graph_unbound")

    ranked = sorted(open_syms.values(), key=lambda e: (-int(e["count"]), str(e["name"])))[:limit]
    for item in ranked:
        item["sources"] = sorted(item["sources"])
        item["reasons"] = sorted(item["reasons"])
    return {
        "status": "ok",
        "symbols": ranked,
        "total_unique": len(open_syms),
        "ask": "mid_symbol_tasks" if ranked else "",
        "next": (
            "Spawn Task Follow uo-query per open mid-symbol (CBM) → append derivation_chain → --merge-uo-resolve"
            if ranked
            else "no open mid-symbols"
        ),
    }


def write_mid_symbol_queue(out_root: Path, *, limit: int = 32) -> dict[str, Any]:
    """Persist open mid-symbol Task queue for parent orchestration."""
    doc = collect_open_mid_symbols(out_root, limit=limit)
    doc["version"] = 1
    path = Path(out_root) / "realization" / "mid_symbol_queue.yaml"
    write_yaml(path, doc)
    doc["path"] = path.as_posix()
    return doc


def require_full_csv_closure(out_root: Path) -> dict[str, Any]:
    """
    Strong verification: every closable variable must close to VAR_CSV_*.
    Combines chain gates, placeholders, merge artifacts, and open mid-symbol queue.
    """
    root = Path(out_root)
    gates = {
        "merge_artifacts": require_merge_artifacts(root),
        "high_only": require_high_only(root),
        "chain_to_csv": require_chains_terminate_at_csv(root),
        "no_placeholders": require_no_placeholders(root),
        "nonempty_unresolved": require_no_nonempty_unresolved(root),
    }
    open_mids = collect_open_mid_symbols(root)
    gates["open_mid_symbols"] = {
        "status": "fail" if open_mids.get("symbols") else "pass",
        "count": len(open_mids.get("symbols") or []),
        "symbols": [s.get("name") for s in (open_mids.get("symbols") or [])[:20]],
    }

    # Lexicon expr vars must be CSV or appear in shape closure
    lex_issues: list[dict[str, Any]] = []
    closure: set[str] = set()
    graph_path = root / "bind" / "shape_derivation_graph.yaml"
    if graph_path.is_file():
        graph = read_yaml(graph_path)
        if isinstance(graph, dict):
            closure = {str(x) for x in (graph.get("closure") or [])}
    lex_path = root / "realization" / "binding_lexicon.yaml"
    if lex_path.is_file():
        lexicon = read_yaml(lex_path)
        if isinstance(lexicon, dict):
            for item in lexicon.get("key_derivations") or []:
                if not isinstance(item, dict):
                    continue
                if str(item.get("status") or "").lower() == "unresolved":
                    continue
                expr = item.get("expr")
                if expr is None:
                    continue
                for vid in collect_var_ids_from_expr(expr):
                    if is_csv_terminal(vid) or is_compile_time_terminal(vid):
                        continue
                    if closure and vid not in closure:
                        lex_issues.append({"id": item.get("id"), "var": vid, "reason": "expr_var_not_in_shape_closure"})
                    elif not closure and not is_csv_terminal(vid):
                        # no graph yet — still flag non-CSV leaves
                        lex_issues.append({"id": item.get("id"), "var": vid, "reason": "expr_non_csv_without_closure"})
    gates["lexicon_csv_closure"] = {
        "status": "fail" if lex_issues else "pass",
        "issues": lex_issues[:50],
    }

    failed = [k for k, v in gates.items() if str(v.get("status") or "").lower() == "fail"]
    ask = ""
    if "merge_artifacts" in failed:
        ask = "uo_merge_required"
    elif "open_mid_symbols" in failed or "chain_to_csv" in failed or "lexicon_csv_closure" in failed:
        ask = "shape_closure_incomplete"
    elif "no_placeholders" in failed:
        ask = "placeholder_expr"
    elif "high_only" in failed:
        ask = "confidence_not_high"
    elif "nonempty_unresolved" in failed:
        ask = "key_unresolved"

    return {
        "status": "fail" if failed else "pass",
        "failed_gates": failed,
        "gates": gates,
        "open_mid_symbols": open_mids,
        "ask": ask,
        "next": (
            "PARENT: tg-init-audit → --confirm"
            if not failed
            else "PARENT: auto Task Follow uo-query on open mid-symbols → --merge-uo-resolve → --verify-csv-closure (do NOT ask user)"
        ),
    }
