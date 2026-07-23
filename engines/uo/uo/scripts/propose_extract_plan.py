"""Propose generic extract_plan candidates (no operator-specific hardcoding).

Deterministic heuristics only — LLM confirms into ir/extract_plan.yaml.

P0: brace-bounded function bodies (no fixed-line swallow).
P1: one-hop callees from helper definitions enter writer_candidates.
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
from uo.scripts.cbm_client import CbmClient
from uo.scripts.extract_kernel_subgraph import TDF_ASSIGN_RE
from uo.scripts.function_body import extract_callee_names, iter_function_defs, resolve_helper_body
from uo.scripts.resolve_entrypoints import entrypoint_units, load_entrypoint_graph, nodes_for_role
from uo.scripts.source_path import to_repo_relative

# Generic: any identifier that receives set_field
RECV_SET_RE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*(?:->|\.)\s*set_([A-Za-z_][A-Za-z0-9_]*)\s*\("
)
SET_FIELD_RE = re.compile(r"\bset_([A-Za-z_][A-Za-z0-9_]*)\s*\(")
TILING_ASSIGN_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:tilingData|tiling_data)(?:->|\.)\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*=",
    re.IGNORECASE,
)
GETATTR_RE = re.compile(r"\bGetAttr(?:Optional)?\s*<")
NOISE_CALLS = frozenset(
    {
        "if",
        "for",
        "while",
        "switch",
        "return",
        "sizeof",
        "typeof",
        "static_cast",
        "dynamic_cast",
        "const_cast",
        "reinterpret_cast",
        "nullptr",
        "true",
        "false",
        "std",
        "GetAttr",
        "GetAttrOptional",
        "GetInputDesc",
        "GetInputShape",
        "GetInputDtype",
        "GetOptionalInputDesc",
        "GetOptionalInputShape",
        "OP_LOGI",
        "OP_LOGD",
        "OP_LOGW",
        "OP_LOGE",
        "ASCENDC_ASSERT",
    }
)
WEAK_NAME_HINT_RE = re.compile(r"(tiling|workspace|blockdim|block_dim)", re.IGNORECASE)

MAX_WRITERS = 40
MAX_RECEIVERS = 40
MAX_ALIASES = 60
MAX_NON_SINK = 30
MAX_EXTRA = 20
MAX_ONE_HOP = 30
MAX_SINK_SCAN_FILES = 12
MAX_KERNEL_ALIAS_FILES = 80


def propose_extract_plan(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
) -> dict[str, Any]:
    uo_root = existing_operator_root(repo_root, op_name)
    graph = load_entrypoint_graph(uo_root)
    seed_nodes = _seed_entrypoint_nodes(graph)

    writers: dict[str, dict[str, Any]] = {}
    receivers: dict[str, dict[str, Any]] = {}
    aliases: dict[tuple[str, str], dict[str, Any]] = {}
    set_recv_roots: set[str] = set()
    assign_lhs_roots: set[str] = set()

    client = CbmClient(uo_root)
    chain_items: list[dict[str, Any]] = []
    # Prefer a callable host entry over registration-only nodes for body seeding.
    primary_node = next(
        (n for n in seed_nodes if str(n.get("role") or "") in {
            "public_host_entry", "normal_impl", "varlen_impl", "empty_impl", "host_tiling_entry",
        }),
        seed_nodes[0] if seed_nodes else {},
    )
    primary = _item_from_ep_node(primary_node) if primary_node else {}

    for node in seed_nodes:
        item = _item_from_ep_node(node)
        if not item.get("name"):
            continue
        role = str(item.get("role") or node.get("role") or "")
        if role in {
            "operator_registration",
            "public_kernel_entry",
            "concrete_kernel_impl",
            "kernel_family",
        }:
            continue
        if not any(_writer_identity_key(x) == _writer_identity_key(item) for x in chain_items):
            chain_items.append(item)

    if primary.get("name"):
        entry_body, _, _ = resolve_helper_body(repo_root, primary, prefer_definition=True)
        for helper_name in extract_callee_names(entry_body, noise=NOISE_CALLS):
            _append_chain_item(chain_items, helper_name, primary, client, architecture)
        if client.available and primary.get("qualified_name"):
            root = client.resolve_qn(str(primary["qualified_name"]), file_contains=architecture)
            if root is None and primary.get("name"):
                root = client.resolve_qn(str(primary["name"]), file_contains=architecture)
            if root is not None:
                keep = {str(x.get("name") or "").casefold() for x in chain_items if x.get("name")}
                traced = client.bounded_trace(root, keep_names=keep or None, max_depth=4, max_nodes=40)
                for sym in traced:
                    child = sym.as_dict()
                    if not any(_writer_identity_key(item) == _writer_identity_key(child) for item in chain_items):
                        chain_items.append(child)

    body_by_key: dict[str, tuple[str, int, int, dict[str, Any]]] = {}
    for item in chain_items:
        _ingest_writer(
            repo_root,
            item,
            writers,
            receivers,
            aliases,
            set_recv_roots,
            assign_lhs_roots,
            body_by_key,
            evidence_extra=None,
        )

    # P1: one-hop callees from scored helpers' definition bodies
    hop_budget = MAX_ONE_HOP
    hop_seeds = sorted(
        body_by_key.items(),
        key=lambda kv: float(writers.get(kv[0], {}).get("score") or 0),
        reverse=True,
    )
    for key, (body, _s, _e, parent_item) in hop_seeds:
        if hop_budget <= 0:
            break
        parent_name = str(parent_item.get("name") or "")
        for callee in extract_callee_names(body, noise=NOISE_CALLS):
            if hop_budget <= 0:
                break
            if callee.casefold() == parent_name.casefold():
                continue
            writer_names = {str(w.get("name") or "").casefold() for w in writers.values()}
            if callee.casefold() in writer_names:
                continue
            child = _resolve_item(callee, parent_item, client, architecture)
            _ingest_writer(
                repo_root,
                child,
                writers,
                receivers,
                aliases,
                set_recv_roots,
                assign_lhs_roots,
                body_by_key,
                evidence_extra=["one_hop_callee"],
            )
            hop_budget -= 1

    # Sink-closure: same files that already have receivers — any def with recv->set_
    # becomes a writer candidate (covers GetWorkspaceSize-style writers off the entry hop).
    _discover_writers_by_sink_sets(
        repo_root,
        writers,
        receivers,
        aliases,
        set_recv_roots,
        assign_lhs_roots,
        body_by_key,
        client,
        architecture,
    )

    # Kernel-side TDF assign aliases (host may never see layoutType = tilingData->layout)
    _collect_kernel_aliases(repo_root, architecture, aliases)

    non_sink: list[dict[str, Any]] = []
    for root in sorted(assign_lhs_roots - set_recv_roots):
        if not root or root.casefold() in {"tilingdata", "tiling_data", "this"}:
            continue
        non_sink.append(
            {
                "name": root,
                "file_path": "",
                "start_line": 0,
                "snippet": f"{root} = ... (assign LHS only)",
                "score": 0.4,
                "evidence": ["assign_lhs_only"],
            }
        )

    extra: list[dict[str, Any]] = []
    seen_extra: set[str] = set()
    cand_path = uo_root / "ir" / "entrypoint_candidates.yaml"
    if cand_path.is_file():
        cands = read_yaml(cand_path)
        role_cands = cands.get("role_candidates") if isinstance(cands.get("role_candidates"), dict) else {}
        host_cands = list(role_cands.get("public_host_entry") or []) + list(
            role_cands.get("host_tiling_entry") or []
        )
        # Legacy candidates shape (roles.*.candidates) — ignore selected.
        legacy_host = ((cands.get("roles") or {}).get("host_tiling_entry") or {}).get("candidates") or []
        host_cands.extend(legacy_host if isinstance(legacy_host, list) else [])
        primary_name = str(primary.get("name") or "")
        primary_file = str(primary.get("file_path") or "").replace("\\", "/")
        for c in host_cands:
            if not isinstance(c, dict):
                continue
            n = str(c.get("name") or "").strip()
            if not n or n == primary_name:
                continue
            conf = float(c.get("confidence") or 0)
            fp = str(c.get("file_path") or "").replace("\\", "/")
            key = _writer_identity_key(
                {
                    "name": n,
                    "qualified_name": c.get("qualified_name") or n,
                    "file_path": fp,
                    "class_or_namespace": c.get("class_or_namespace") or "",
                }
            )
            if key in seen_extra:
                continue
            if conf < 0.7 and (not fp or fp == primary_file):
                continue
            if conf < 0.55:
                continue
            seen_extra.add(key)
            extra.append(
                {
                    "name": n,
                    "file_path": fp,
                    "start_line": int(c.get("start_line") or 0),
                    "snippet": snippet(str(c.get("signature_snippet") or "")),
                    "score": conf,
                    "evidence": ["entrypoint_candidate"],
                }
            )

    client.close()

    writer_list = _top_scored(list(writers.values()), MAX_WRITERS)
    receiver_list = _top_scored(list(receivers.values()), MAX_RECEIVERS)
    alias_list = list(aliases.values())[:MAX_ALIASES]
    return {
        "version": 1,
        "op_name": op_name,
        "architecture": architecture,
        "status": "candidates",
        "writer_candidates": writer_list,
        "receiver_candidates": receiver_list,
        "alias_candidates": alias_list,
        "non_sink_root_candidates": non_sink[:MAX_NON_SINK],
        "extra_entry_candidates": extra[:MAX_EXTRA],
        "counts": {
            "writers": len(writer_list),
            "receivers": len(receiver_list),
            "aliases": len(alias_list),
            "non_sink_roots": min(len(non_sink), MAX_NON_SINK),
            "extra_entries": min(len(extra), MAX_EXTRA),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Propose generic extract_plan candidates")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--architecture", default="arch35")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    payload = propose_extract_plan(repo_root, op_name, architecture=args.architecture)
    if args.write:
        write_yaml(
            existing_operator_root(repo_root, op_name) / "ir" / "extract_plan_candidates.yaml",
            payload,
        )
    c = payload["counts"]
    print(
        f"extract_plan candidates writers={c['writers']} receivers={c['receivers']} "
        f"aliases={c['aliases']} non_sink={c['non_sink_roots']} extra={c['extra_entries']}"
    )
    return 0


def _seed_entrypoint_nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Seed from extraction_units + public_host_entry / impl nodes (not selected)."""
    by_id = {str(n.get("id")): n for n in (graph.get("nodes") or []) if isinstance(n, dict) and n.get("id")}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(node: dict[str, Any] | None) -> None:
        if not isinstance(node, dict):
            return
        nid = str(node.get("id") or "")
        if nid and nid in seen:
            return
        if nid:
            seen.add(nid)
        out.append(node)

    for unit in entrypoint_units(graph):
        if not isinstance(unit, dict):
            continue
        root = by_id.get(str(unit.get("entry_root") or ""))
        role = str((root or {}).get("role") or "")
        # Skip pure kernel units for host extract-plan seeding.
        if role in {"public_kernel_entry", "concrete_kernel_impl", "kernel_family"}:
            continue
        _add(root)
        for mid in unit.get("member_nodes") or []:
            member = by_id.get(str(mid))
            mrole = str((member or {}).get("role") or "")
            if mrole in {
                "operator_registration",
                "public_kernel_entry",
                "concrete_kernel_impl",
                "kernel_family",
            }:
                continue
            _add(member)

    for role in (
        "public_host_entry",
        "normal_impl",
        "varlen_impl",
        "empty_impl",
        "get_tiling_key",
        "save_tiling_data",
        "init_tiling_data",
    ):
        for node in nodes_for_role(graph, role):
            _add(node)
    return out


def _item_from_ep_node(node: dict[str, Any]) -> dict[str, Any]:
    loc = node.get("locator") if isinstance(node.get("locator"), dict) else {}
    sym = node.get("symbol_ref") if isinstance(node.get("symbol_ref"), dict) else {}
    name = str(node.get("name") or "")
    qn = str(sym.get("qualified_name") or node.get("qualified_name") or name)
    cls = str(sym.get("class_or_namespace") or node.get("class_or_namespace") or "")
    if not cls and "::" in qn:
        prefix = qn.rsplit("::", 1)[0]
        if "/" not in prefix:
            cls = prefix
    return {
        "id": node.get("id"),
        "name": name or (qn.rsplit("::", 1)[-1] if qn else ""),
        "qualified_name": qn,
        "file_path": str(loc.get("file_path") or sym.get("repo_relative_path") or node.get("file_path") or "").replace(
            "\\", "/"
        ),
        "start_line": int(loc.get("start_line") or node.get("start_line") or 0),
        "end_line": int(loc.get("end_line") or node.get("end_line") or 0),
        "class_or_namespace": cls,
        "role": node.get("role"),
    }


def _writer_identity_key(item: dict[str, Any]) -> str:
    """Identity key: file_path + qualified_name + class (not bare name.casefold)."""
    fp = str(item.get("file_path") or "").replace("\\", "/").strip()
    qn = str(item.get("qualified_name") or item.get("name") or "").strip()
    cls = str(item.get("class_or_namespace") or "").strip()
    if not cls and "::" in qn:
        prefix = qn.rsplit("::", 1)[0]
        if "/" not in prefix:
            cls = prefix
    return f"{fp}|{qn}|{cls}".casefold()


def _append_chain_item(
    chain_items: list[dict[str, Any]],
    helper_name: str,
    parent: dict[str, Any],
    client: CbmClient,
    architecture: str,
) -> None:
    if any(str(x.get("name") or "") == helper_name for x in chain_items):
        return
    chain_items.append(_resolve_item(helper_name, parent, client, architecture))


def _resolve_item(
    helper_name: str,
    parent: dict[str, Any],
    client: CbmClient,
    architecture: str,
) -> dict[str, Any]:
    hit = None
    if client.available:
        hit = client.resolve_qn(helper_name, file_contains=architecture)
    if hit is not None:
        return hit.as_dict()
    return {
        "name": helper_name,
        "qualified_name": helper_name,
        "file_path": parent.get("file_path") or "",
        "start_line": parent.get("start_line") or 0,
        "end_line": parent.get("end_line") or 0,
        "class_or_namespace": parent.get("class_or_namespace") or "",
    }


def _ingest_writer(
    repo_root: Path,
    item: dict[str, Any],
    writers: dict[str, dict[str, Any]],
    receivers: dict[str, dict[str, Any]],
    aliases: dict[tuple[str, str], dict[str, Any]],
    set_recv_roots: set[str],
    assign_lhs_roots: set[str],
    body_by_key: dict[str, tuple[str, int, int, dict[str, Any]]],
    *,
    evidence_extra: list[str] | None,
) -> None:
    name = str(item.get("name") or "").strip()
    if not name:
        return
    body, start, end = resolve_helper_body(repo_root, item, prefer_definition=True)
    score, evidence = _score_writer(name, body)
    if evidence_extra:
        evidence = list(evidence) + list(evidence_extra)
        if "one_hop_callee" in evidence_extra:
            score = min(score + 0.05, 1.0)
        if "sink_set_writer" in evidence_extra:
            score = min(score + 0.25, 1.0)
    key = _writer_identity_key(item)
    prev = writers.get(key)
    if prev is None or score > float(prev.get("score") or 0):
        writers[key] = {
            "name": name,
            "qualified_name": str(item.get("qualified_name") or name),
            "class_or_namespace": str(item.get("class_or_namespace") or ""),
            "file_path": str(item.get("file_path") or "").replace("\\", "/"),
            "start_line": start,
            "snippet": snippet(body[:240]),
            "score": score,
            "evidence": evidence,
        }
        body_by_key[key] = (body, start, end, item)
    _collect_receivers_aliases(body, item, receivers, aliases, set_recv_roots, assign_lhs_roots, start)


def _score_writer(name: str, body: str) -> tuple[float, list[str]]:
    score = 0.2
    evidence: list[str] = ["on_call_chain"]
    if SET_FIELD_RE.search(body):
        score += 0.45
        evidence.append("has_set_field")
    if TILING_ASSIGN_RE.search(body):
        score += 0.35
        evidence.append("tilingdata_assign")
    if RECV_SET_RE.search(body):
        score += 0.15
        evidence.append("recv_set_call")
    if GETATTR_RE.search(body):
        score += 0.2
        evidence.append("has_getattr")
    if WEAK_NAME_HINT_RE.search(name):
        score += 0.1
        evidence.append("name_hint_weak")
    return min(score, 1.0), evidence


def _collect_receivers_aliases(
    body: str,
    item: dict[str, Any],
    receivers: dict[str, dict[str, Any]],
    aliases: dict[tuple[str, str], dict[str, Any]],
    set_recv_roots: set[str],
    assign_lhs_roots: set[str],
    start: int,
) -> None:
    file_path = str(item.get("file_path") or "").replace("\\", "/")
    for recv, field in RECV_SET_RE.findall(body):
        set_recv_roots.add(recv)
        item_recv = {
            "name": recv,
            "file_path": file_path,
            "qualified_name": f"{file_path}::{recv}",
            "class_or_namespace": item.get("class_or_namespace") or "",
            "start_line": start,
            "snippet": snippet(f"{recv}->set_{field}(...)"),
            "score": 0.7,
            "evidence": [f"set_{field}"],
        }
        key = _writer_identity_key(item_recv)
        prev = receivers.get(key)
        score = 0.7
        if prev is None or score > float(prev.get("score") or 0):
            receivers[key] = item_recv
    for m in TDF_ASSIGN_RE.finditer(body):
        local = m.group(1)
        path = m.group(2)
        leaf = path.split(".")[-1]
        aliases[(local, leaf)] = {
            "local": local,
            "tdf_leaf": leaf,
            "tdf_path": path,
            "file_path": file_path,
            "start_line": start,
            "snippet": snippet(m.group(0)),
            "score": 0.8,
            "evidence": ["tdf_assign"],
        }
    for m in re.finditer(r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\s*=", body):
        assign_lhs_roots.add(m.group(1))


def _discover_writers_by_sink_sets(
    repo_root: Path,
    writers: dict[str, dict[str, Any]],
    receivers: dict[str, dict[str, Any]],
    aliases: dict[tuple[str, str], dict[str, Any]],
    set_recv_roots: set[str],
    assign_lhs_roots: set[str],
    body_by_key: dict[str, tuple[str, int, int, dict[str, Any]]],
    client: CbmClient,
    architecture: str,
) -> None:
    """Propose helpers that write via already-discovered receivers (same-file scan)."""
    if not receivers:
        return
    recv_names = {str(v.get("name") or "") for v in receivers.values() if v.get("name")}
    files: list[str] = []
    seen_fp: set[str] = set()
    for src in list(writers.values()) + list(receivers.values()):
        fp = str(src.get("file_path") or "").replace("\\", "/")
        if not fp or fp in seen_fp:
            continue
        seen_fp.add(fp)
        files.append(fp)
        if len(files) >= MAX_SINK_SCAN_FILES:
            break

    writer_names = {str(w.get("name") or "").casefold() for w in writers.values()}
    for fp in files:
        for name, start, end, body, rel in iter_function_defs(repo_root, fp):
            if name.casefold() in writer_names:
                continue
            hits = [recv for recv, _field in RECV_SET_RE.findall(body) if recv in recv_names]
            if not hits:
                continue
            item = {
                "name": name,
                "qualified_name": name,
                "file_path": rel,
                "start_line": start,
                "end_line": end,
            }
            if client.available:
                hit = client.resolve_qn(name, file_contains=architecture)
                if hit is not None:
                    item = hit.as_dict()
                    item["file_path"] = rel
                    item["start_line"] = start
                    item["end_line"] = end
            writer_names.add(name.casefold())
            _ingest_writer(
                repo_root,
                item,
                writers,
                receivers,
                aliases,
                set_recv_roots,
                assign_lhs_roots,
                body_by_key,
                evidence_extra=["sink_set_writer", f"recv={hits[0]}"],
            )


def _collect_kernel_aliases(
    repo_root: Path,
    architecture: str,
    aliases: dict[tuple[str, str], dict[str, Any]],
) -> None:
    """Scan kernel sources for ``local = tilingData->...leaf`` assign aliases."""
    kernel_root = repo_root / "op_kernel" / architecture
    if not kernel_root.is_dir():
        kernel_root = repo_root / "op_kernel"
    if not kernel_root.is_dir():
        return
    files = list(kernel_root.rglob("*.h")) + list(kernel_root.rglob("*.cpp"))
    scanned = 0
    for path in files:
        if scanned >= MAX_KERNEL_ALIAS_FILES:
            break
        if not path.is_file():
            continue
        scanned += 1
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = to_repo_relative(repo_root, path)
        for m in TDF_ASSIGN_RE.finditer(text):
            local = re.sub(r"\s+", "", m.group(1)).split(".")[-1]
            tdf_path = m.group(2)
            leaf = tdf_path.split(".")[-1]
            key = (local, leaf)
            if key in aliases:
                continue
            line = text.count("\n", 0, m.start()) + 1
            aliases[key] = {
                "local": local,
                "tdf_leaf": leaf,
                "tdf_path": tdf_path,
                "file_path": rel,
                "start_line": line,
                "snippet": snippet(m.group(0)),
                "score": 0.85,
                "evidence": ["kernel_tdf_assign"],
            }


def _top_scored(items: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return sorted(items, key=lambda x: float(x.get("score") or 0), reverse=True)[:limit]


if __name__ == "__main__":
    raise SystemExit(main())
