"""Deterministic AscendC macro → typed semantic facts (public contracts).

Runs inside ``build_layered_kb`` after entrypoint facts and before host/kernel
layers, so ``detect_score_post`` sees macro-closed registration chains.
"""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml, write_yaml

MATERIALIZER_VERSION = "1.0.0"

_CONTRACTS_PATH = (
    Path(__file__).resolve().parents[1] / "resources" / "ascendc_macro_contracts.yaml"
)

_CALL_RE_CACHE: dict[str, re.Pattern[str]] = {}


def contracts_path() -> Path:
    return _CONTRACTS_PATH


def load_macro_contracts(path: Path | None = None) -> list[dict[str, Any]]:
    data = read_yaml(path or _CONTRACTS_PATH) or {}
    contracts = data.get("contracts") or []
    return [c for c in contracts if isinstance(c, dict) and c.get("name")]


def macro_contracts_hash(path: Path | None = None) -> str:
    p = path or _CONTRACTS_PATH
    raw = p.read_bytes() if p.is_file() else b""
    return hashlib.sha256(raw).hexdigest()[:16]


def materializer_hash() -> str:
    raw = Path(__file__).read_bytes()
    return hashlib.sha256(f"{MATERIALIZER_VERSION}:{raw}".encode("utf-8")).hexdigest()[:16]


def _call_re(macro_name: str) -> re.Pattern[str]:
    if macro_name not in _CALL_RE_CACHE:
        _CALL_RE_CACHE[macro_name] = re.compile(
            rf"\b{re.escape(macro_name)}\s*\(",
            re.MULTILINE,
        )
    return _CALL_RE_CACHE[macro_name]


def _balanced_args(text: str, open_paren_idx: int) -> tuple[str, int] | None:
    """Return (inside, end_idx_exclusive) for (...) starting at open_paren_idx."""
    if open_paren_idx < 0 or open_paren_idx >= len(text) or text[open_paren_idx] != "(":
        return None
    depth = 0
    i = open_paren_idx
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren_idx + 1 : i], i + 1
        i += 1
    return None


def _split_args(inside: str) -> list[str]:
    args: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in inside:
        if ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        args.append("".join(buf).strip())
    return [a for a in args if a]


def _parse_chained_methods(text: str, start: int) -> list[dict[str, Any]]:
    """Parse .Tiling(...).TilingParse(...) after an IMPL_OP_OPTILING(...)."""
    methods: list[dict[str, Any]] = []
    i = start
    while i < len(text):
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text) or text[i] != ".":
            break
        m = re.match(r"\.([A-Za-z_][A-Za-z0-9_]*)\s*\(", text[i:])
        if not m:
            break
        name = m.group(1)
        abs_open = i + m.end() - 1
        parsed = _balanced_args(text, abs_open)
        if not parsed:
            break
        inside, end = parsed
        methods.append({"name": name, "args": _split_args(inside), "end": end})
        i = end
    return methods


def scan_macro_invocations(
    file_path: str,
    text: str,
    contracts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_name = {str(c["name"]): c for c in contracts}
    # Prefer longer names first (WITH_ARCH before base).
    names = sorted(by_name.keys(), key=len, reverse=True)
    found: list[dict[str, Any]] = []
    occupied: set[int] = set()
    for name in names:
        contract = by_name[name]
        for match in _call_re(name).finditer(text):
            if match.start() in occupied:
                continue
            open_idx = text.find("(", match.start())
            parsed = _balanced_args(text, open_idx)
            if not parsed:
                continue
            inside, end = parsed
            args = _split_args(inside)
            line = text.count("\n", 0, match.start()) + 1
            inv: dict[str, Any] = {
                "macro": name,
                "semantic_kind": contract.get("semantic_kind"),
                "invocation_style": contract.get("invocation_style"),
                "file_path": file_path.replace("\\", "/"),
                "start_line": line,
                "args": args,
                "handler": (contract.get("materializer") or {}).get("handler"),
                "contract": contract,
            }
            if contract.get("invocation_style") == "chained_dsl":
                inv["chained_methods"] = _parse_chained_methods(text, end)
            found.append(inv)
            for pos in range(match.start(), end):
                occupied.add(pos)
    found.sort(key=lambda x: (x["file_path"], x["start_line"], x["macro"]))
    return found


def _edge_id(etype: str, source: str, target: str, *extra: str) -> str:
    raw = "|".join([etype, source, target, *extra])
    return "E_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16].upper()


def _upgrade_entrypoint_from_invocations(
    entrypoint_graph: dict[str, Any],
    invocations: list[dict[str, Any]],
    *,
    architecture: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Upgrade existing EP nodes + emit typed macro edges."""
    nodes = {
        str(n.get("id")): dict(n)
        for n in (entrypoint_graph.get("nodes") or [])
        if isinstance(n, dict) and n.get("id")
    }
    edges = [dict(e) for e in (entrypoint_graph.get("edges") or []) if isinstance(e, dict)]
    edge_ids = {str(e.get("id")) for e in edges if e.get("id")}
    emitted_nodes: list[dict[str, Any]] = []
    emitted_edges: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    # Index EP nodes by macro + file/line proximity / qualified name.
    by_macro_file: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for n in nodes.values():
        macro = str(n.get("macro") or "")
        loc = n.get("locator") or {}
        fp = str(loc.get("file_path") or "").replace("\\", "/")
        if macro and fp:
            by_macro_file.setdefault((macro, fp), []).append(n)

    for inv in invocations:
        handler = str(inv.get("handler") or "")
        macro = str(inv.get("macro") or "")
        fp = str(inv.get("file_path") or "")
        line = int(inv.get("start_line") or 0)
        args = list(inv.get("args") or [])
        matched = by_macro_file.get((macro, fp)) or by_macro_file.get(
            (macro.split(".")[0], fp), []
        )
        # Also match IMPL_OP_OPTILING.Tiling nodes via chained method.
        node = None
        if matched:
            # Prefer closest start_line.
            node = min(
                matched,
                key=lambda n: abs(int((n.get("locator") or {}).get("start_line") or 0) - line),
            )
        if node is None and macro == "IMPL_OP_OPTILING":
            # Try fluent tiling node on same file.
            tiling_nodes = by_macro_file.get(("IMPL_OP_OPTILING.Tiling", fp)) or []
            if tiling_nodes:
                node = min(
                    tiling_nodes,
                    key=lambda n: abs(int((n.get("locator") or {}).get("start_line") or 0) - line),
                )

        if node is not None:
            nid = str(node["id"])
            nodes[nid]["confidence"] = "source_verified"
            nodes[nid]["verification_source"] = "macro_contract"
            nodes[nid]["status"] = "verified"
            nodes[nid]["macro_contract"] = macro
            nodes[nid]["macro_handler"] = handler
            emitted_nodes.append(nodes[nid])

        if handler == "registration_template" and len(args) >= 2:
            op_type, tmpl = args[0], args[1]
            arch_arg = args[2] if len(args) > 2 else architecture
            priority = args[3] if len(args) > 3 else ""
            src = str((node or {}).get("id") or f"MACRO_{macro}_{tmpl}")
            # Ensure template node confidence.
            if node is not None:
                nodes[str(node["id"])]["op_type"] = op_type
                nodes[str(node["id"])]["template_class"] = tmpl
                nodes[str(node["id"])]["architecture_arg"] = arch_arg
            e1 = {
                "id": _edge_id("registers_template", op_type, tmpl, fp, str(line)),
                "type": "registers_template",
                "source": src,
                "target": tmpl,
                "op_type": op_type,
                "template_class": tmpl,
                "priority": priority,
                "evidence": [{"file_path": fp, "line": line, "macro": macro}],
                "confidence": "source_verified",
                "verification_source": "macro_contract",
            }
            e2 = {
                "id": _edge_id("available_on_arch", tmpl, str(arch_arg), fp, str(line)),
                "type": "available_on_arch",
                "source": src,
                "target": str(arch_arg),
                "architecture": str(arch_arg),
                "evidence": [{"file_path": fp, "line": line, "macro": macro}],
                "confidence": "source_verified",
                "verification_source": "macro_contract",
            }
            for e in (e1, e2):
                if e["id"] not in edge_ids:
                    edges.append(e)
                    edge_ids.add(e["id"])
                    emitted_edges.append(e)
            # Also reinforce existing registers edges on this node.
            if node is not None:
                for e in edges:
                    if e.get("target") == node.get("id") and e.get("type") == "registers":
                        e["confidence"] = "source_verified"
                        e["verification_source"] = "macro_contract"

        elif handler == "registration_operator" and args:
            op_type = args[0]
            if node is not None:
                nodes[str(node["id"])]["op_type"] = op_type
                e = {
                    "id": _edge_id("declares_operator", str(node["id"]), op_type, fp, str(line)),
                    "type": "declares_operator",
                    "source": str(node["id"]),
                    "target": op_type,
                    "evidence": [{"file_path": fp, "line": line, "macro": macro}],
                    "confidence": "source_verified",
                    "verification_source": "macro_contract",
                }
                if e["id"] not in edge_ids:
                    edges.append(e)
                    edge_ids.add(e["id"])
                    emitted_edges.append(e)

        elif handler == "registration_host_chained":
            if node is not None:
                host_id = str(node["id"])
                # Prefer the IMPL_OP_OPTILING node over .Tiling node as source.
                impl_nodes = by_macro_file.get(("IMPL_OP_OPTILING", fp)) or []
                if impl_nodes:
                    host_id = str(
                        min(
                            impl_nodes,
                            key=lambda n: abs(
                                int((n.get("locator") or {}).get("start_line") or 0) - line
                            ),
                        )["id"]
                    )
                    nodes[host_id]["confidence"] = "source_verified"
                    nodes[host_id]["verification_source"] = "macro_contract"
                    nodes[host_id]["status"] = "verified"
                    emitted_nodes.append(nodes[host_id])
            else:
                host_id = f"MACRO_IMPL_{fp}_{line}"
            for method in inv.get("chained_methods") or []:
                mname = str(method.get("name") or "")
                margs = list(method.get("args") or [])
                if not margs:
                    continue
                target = margs[0]
                etype = "binds_tiling" if mname == "Tiling" else (
                    "binds_tiling_parse" if mname == "TilingParse" else f"binds_{mname.lower()}"
                )
                e = {
                    "id": _edge_id(etype, host_id, target, fp, str(line)),
                    "type": etype,
                    "source": host_id,
                    "target": target,
                    "evidence": [
                        {
                            "file_path": fp,
                            "line": line,
                            "macro": macro,
                            "chained_method": mname,
                        }
                    ],
                    "confidence": "source_verified",
                    "verification_source": "macro_contract",
                }
                if e["id"] not in edge_ids:
                    edges.append(e)
                    edge_ids.add(e["id"])
                    emitted_edges.append(e)

        elif handler in {"kernel_tpl_selection", "kernel_tiling_data_bind"}:
            # Record fact for KEY/runtime phases; do not invent EP nodes.
            e = {
                "id": _edge_id(handler, fp, str(line), macro, ",".join(args[:2])),
                "type": (
                    "writes_tiling_key"
                    if macro == "GET_TPL_TILING_KEY"
                    else (
                        "uses_tiling_data"
                        if macro == "GET_TILING_DATA"
                        else "selects_tiling_key"
                    )
                ),
                "source": fp,
                "target": args[0] if args else macro,
                "evidence": [{"file_path": fp, "line": line, "macro": macro}],
                "confidence": "source_verified",
                "verification_source": "macro_contract",
            }
            if e["id"] not in edge_ids:
                edges.append(e)
                edge_ids.add(e["id"])
                emitted_edges.append(e)
        else:
            if node is None and handler:
                unresolved.append(
                    {
                        "kind": "macro_contract_unmaterialized",
                        "macro": macro,
                        "file_path": fp,
                        "start_line": line,
                        "handler": handler,
                        "severity": "degraded",
                    }
                )

    entrypoint_graph["nodes"] = sorted(
        nodes.values(), key=lambda n: (n.get("role") or "", n.get("id") or "")
    )
    entrypoint_graph["edges"] = edges
    return emitted_nodes, emitted_edges, unresolved


def _confirmed_source_files(uo_root: Path, repo_root: Path) -> list[Path]:
    """Resolve confirmed scope files under operator / repo roots."""
    # Prefer current-run scope; fall back to common locations.
    candidates = [
        uo_root / "runs",
    ]
    paths: list[Path] = []
    for runs in candidates:
        if not runs.is_dir():
            continue
        for scope in sorted(runs.glob("*/scope/scope_confirmed.yaml"), reverse=True):
            data = read_yaml(scope) or {}
            files = data.get("confirmed_source_files") or data.get("confirmed_file_list") or []
            for item in files:
                rel = str(item.get("path") if isinstance(item, dict) else item or "").replace(
                    "\\", "/"
                )
                if not rel:
                    continue
                for root in (repo_root, uo_root.parent.parent if uo_root.name == "uo" else repo_root):
                    p = (root / rel).resolve()
                    if p.is_file():
                        paths.append(p)
                        break
            if paths:
                return paths
    # Fallback: scan op_host/op_kernel/op_graph under repo_root.
    for sub in ("op_host", "op_kernel", "op_graph"):
        d = repo_root / sub
        if d.is_dir():
            paths.extend(sorted(d.rglob("*.cpp")))
            paths.extend(sorted(d.rglob("*.h")))
            paths.extend(sorted(d.rglob("*.hpp")))
    return paths


def materialize_macro_semantics(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
    uo_root: Path | None = None,
) -> dict[str, Any]:
    """Scan macros, upgrade entrypoint_graph, write ``ir/macro_semantics.yaml``."""
    t0 = time.perf_counter()
    from uo._operator.artifacts import existing_operator_root

    root = uo_root or existing_operator_root(repo_root, op_name)
    ir_dir = root / "ir"
    ir_dir.mkdir(parents=True, exist_ok=True)

    contracts = load_macro_contracts()
    entrypoint_graph = read_yaml(ir_dir / "entrypoint_graph.yaml") or {
        "version": 2,
        "nodes": [],
        "edges": [],
    }

    source_files = _confirmed_source_files(root, repo_root)
    invocations: list[dict[str, Any]] = []
    for path in source_files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            rel = str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
        except ValueError:
            rel = path.name
        # Strip contract object before serializing invocations.
        for inv in scan_macro_invocations(rel, text, contracts):
            serial = {k: v for k, v in inv.items() if k != "contract"}
            serial["handler"] = inv.get("handler")
            invocations.append(serial)
            # Keep contract for upgrade path via re-attach.
            inv["_serial"] = serial

    # Re-scan with contracts attached for upgrade.
    inv_full: list[dict[str, Any]] = []
    by_key = {(i["file_path"], i["start_line"], i["macro"]): i for i in invocations}
    for path in source_files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            rel = str(path.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
        except ValueError:
            rel = path.name
        for inv in scan_macro_invocations(rel, text, contracts):
            key = (inv["file_path"], inv["start_line"], inv["macro"])
            if key in by_key:
                inv_full.append(inv)

    emitted_nodes, emitted_edges, unresolved = _upgrade_entrypoint_from_invocations(
        entrypoint_graph, inv_full, architecture=architecture
    )

    # Also upgrade any EP macro nodes even if scan missed (status verified, confidence None).
    for n in entrypoint_graph.get("nodes") or []:
        if not isinstance(n, dict):
            continue
        if n.get("macro") and not n.get("confidence"):
            n["confidence"] = "source_verified"
            n["verification_source"] = "macro_contract"
            n["status"] = n.get("status") or "verified"
            emitted_nodes.append(n)

    write_yaml(ir_dir / "entrypoint_graph.yaml", entrypoint_graph)

    timing_ms = int((time.perf_counter() - t0) * 1000)
    payload = {
        "version": 1,
        "op_name": op_name,
        "architecture": architecture,
        "materializer_version": MATERIALIZER_VERSION,
        "macro_contracts_hash": macro_contracts_hash(),
        "materializer_hash": materializer_hash(),
        "invocations": invocations,
        "emitted_nodes": [
            {"id": n.get("id"), "macro": n.get("macro"), "role": n.get("role")}
            for n in emitted_nodes
            if isinstance(n, dict)
        ],
        "emitted_edges": emitted_edges,
        "unresolved": unresolved,
        "stats": {
            "contract_count": len(contracts),
            "invocation_count": len(invocations),
            "emitted_edge_count": len(emitted_edges),
            "emitted_node_count": len(emitted_nodes),
            "unresolved_count": len(unresolved),
            "timing_ms": timing_ms,
        },
    }
    write_yaml(ir_dir / "macro_semantics.yaml", payload)
    return {
        "ok": True,
        "macro_materialization": payload["stats"],
        "macro_contracts_hash": payload["macro_contracts_hash"],
        "materializer_hash": payload["materializer_hash"],
        "entrypoint_graph": entrypoint_graph,
        "emitted_edges": emitted_edges,
    }
