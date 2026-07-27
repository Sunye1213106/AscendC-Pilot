"""Propose generic extract_plan candidates (no operator-specific hardcoding).

Deterministic heuristics only — LLM confirms into ir/extract_plan.yaml.

P0: brace-bounded function bodies (no fixed-line swallow).
P1: one-hop callees from helper definitions enter writer_candidates.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo.scripts._ir_io import read_yaml, snippet, write_yaml
from uo.scripts.cbm_client import CbmClient, read_source_snippet
from uo.scripts.extract_kernel_subgraph import TDF_ASSIGN_RE
from uo.scripts.function_body import extract_callee_names, iter_function_defs, resolve_helper_body
from uo.scripts.resolve_entrypoints import entrypoint_units, load_entrypoint_graph, nodes_for_role
from uo.scripts.source_path import to_repo_relative

_SOURCE_WINDOW_TEXT_CAP = 8000


def _attach_source_windows(
    repo_root: Path,
    writer_list: list[dict[str, Any]],
    body_by_key: dict[str, tuple[str, int, int, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Attach brace-bounded source windows so producers can cite real code.

    Uses the same body resolution path as scoring (``resolve_helper_body`` /
    ``read_source_snippet``) — no second parser.
    """
    out: list[dict[str, Any]] = []
    for raw in writer_list:
        w = dict(raw)
        key = _writer_identity_key(w)
        packed = body_by_key.get(key)
        fp = str(w.get("file_path") or "").replace("\\", "/")
        start = int(w.get("start_line") or 0)
        end = start
        body = ""
        if packed:
            body, start, end, _item = packed
        if fp and start > 0:
            snip = read_source_snippet(repo_root, fp, start, end or start, pad=0)
            if snip.strip():
                body = snip
        if body.strip():
            full_sha = hashlib.sha256(body.encode("utf-8", errors="ignore")).hexdigest()
            text = body if len(body) <= _SOURCE_WINDOW_TEXT_CAP else body[:_SOURCE_WINDOW_TEXT_CAP]
            w["end_line"] = end or start
            w["source_window"] = {
                "file_path": fp,
                "start_line": start,
                "end_line": end or start,
                "sha256": full_sha,
                "text": text,
                "text_truncated": len(body) > _SOURCE_WINDOW_TEXT_CAP,
            }
        out.append(w)
    return out

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

EXTRACT_LIMIT_HARD_MAX = 5000

# payload key → (env var, default)
EXTRACT_LIMIT_SPECS: dict[str, tuple[str, int]] = {
    "writers": ("UO_EXTRACT_MAX_WRITERS", 200),
    "receivers": ("UO_EXTRACT_MAX_RECEIVERS", 200),
    "aliases": ("UO_EXTRACT_MAX_ALIASES", 300),
    "non_sink_roots": ("UO_EXTRACT_MAX_NON_SINK", 512),
    "extra_entries": ("UO_EXTRACT_MAX_EXTRA", 100),
    "one_hop": ("UO_EXTRACT_MAX_ONE_HOP", 240),
    "sink_scan_files": ("UO_EXTRACT_MAX_SINK_SCAN_FILES", 64),
    "kernel_alias_files": ("UO_EXTRACT_MAX_KERNEL_ALIAS_FILES", 320),
}


def _env_limit(name: str, default: int, maximum: int = EXTRACT_LIMIT_HARD_MAX) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        value = default
    return max(1, min(maximum, value))


def _pilot_params_path(repo_root: Path) -> Path:
    return Path(repo_root) / ".ascendc-pilot" / "context" / "pilot_params.yaml"


def load_extract_limit_overrides(repo_root: Path | None) -> dict[str, int]:
    """Read extract_limits from context/pilot_params.yaml (env-key or short-key)."""
    if repo_root is None or yaml is None:
        return {}
    path = _pilot_params_path(repo_root)
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(data, dict):
        return {}
    raw = data.get("extract_limits")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    env_to_key = {env: key for key, (env, _default) in EXTRACT_LIMIT_SPECS.items()}
    for k, v in raw.items():
        key = str(k).strip()
        short = env_to_key.get(key, key)
        if short not in EXTRACT_LIMIT_SPECS:
            continue
        try:
            out[short] = max(1, min(EXTRACT_LIMIT_HARD_MAX, int(v)))
        except (TypeError, ValueError):
            continue
    return out


def persist_extract_limits(repo_root: Path, limits_by_key: dict[str, int]) -> Path | None:
    """Merge raised limits into context/pilot_params.yaml (survives agent bash fence)."""
    if yaml is None or not limits_by_key:
        return None
    path = _pilot_params_path(repo_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except Exception:  # noqa: BLE001
        data = {}
    if not isinstance(data, dict):
        data = {}
    section = data.get("extract_limits")
    if not isinstance(section, dict):
        section = {}
    for key, value in limits_by_key.items():
        spec = EXTRACT_LIMIT_SPECS.get(key)
        if not spec:
            continue
        env_name, _default = spec
        try:
            section[env_name] = max(1, min(EXTRACT_LIMIT_HARD_MAX, int(value)))
        except (TypeError, ValueError):
            continue
    data["extract_limits"] = section
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def resolve_extract_limits(repo_root: Path | None = None) -> dict[str, int]:
    """Precedence: process env > pilot_params.yaml > built-in defaults."""
    overrides = load_extract_limit_overrides(repo_root)
    out: dict[str, int] = {}
    for key, (env_name, default) in EXTRACT_LIMIT_SPECS.items():
        if os.environ.get(env_name) not in (None, ""):
            out[key] = _env_limit(env_name, default)
        elif key in overrides:
            out[key] = overrides[key]
        else:
            out[key] = default
    return out


def apply_extract_limits_to_environ(limits_by_key: dict[str, int]) -> None:
    for key, value in limits_by_key.items():
        spec = EXTRACT_LIMIT_SPECS.get(key)
        if not spec:
            continue
        os.environ[spec[0]] = str(int(value))


def _sync_module_limit_globals(limits: dict[str, int]) -> None:
    global MAX_WRITERS, MAX_RECEIVERS, MAX_ALIASES, MAX_NON_SINK, MAX_EXTRA
    global MAX_ONE_HOP, MAX_SINK_SCAN_FILES, MAX_KERNEL_ALIAS_FILES
    MAX_WRITERS = limits["writers"]
    MAX_RECEIVERS = limits["receivers"]
    MAX_ALIASES = limits["aliases"]
    MAX_NON_SINK = limits["non_sink_roots"]
    MAX_EXTRA = limits["extra_entries"]
    MAX_ONE_HOP = limits["one_hop"]
    MAX_SINK_SCAN_FILES = limits["sink_scan_files"]
    MAX_KERNEL_ALIAS_FILES = limits["kernel_alias_files"]


def _auto_raise_extract_limits(
    raw_counts: dict[str, int],
    limits: dict[str, int],
) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """Raise limits to fit raw counts (within hard max). Returns (limits, raised, still_over)."""
    new_limits = dict(limits)
    raised: dict[str, int] = {}
    still_over: dict[str, int] = {}
    for key in ("writers", "receivers", "aliases", "non_sink_roots", "extra_entries"):
        raw = int(raw_counts.get(key) or 0)
        lim = int(new_limits.get(key) or 0)
        if raw <= lim:
            continue
        if raw > EXTRACT_LIMIT_HARD_MAX:
            still_over[key] = raw - EXTRACT_LIMIT_HARD_MAX
            new_limits[key] = EXTRACT_LIMIT_HARD_MAX
            raised[key] = EXTRACT_LIMIT_HARD_MAX
            continue
        new_limits[key] = raw
        raised[key] = raw
    return new_limits, raised, still_over


# Defaults (env-aware at import) — tests may import MAX_NON_SINK.
_LIMITS0 = resolve_extract_limits(None)
MAX_WRITERS = _LIMITS0["writers"]
MAX_RECEIVERS = _LIMITS0["receivers"]
MAX_ALIASES = _LIMITS0["aliases"]
MAX_NON_SINK = _LIMITS0["non_sink_roots"]
MAX_EXTRA = _LIMITS0["extra_entries"]
MAX_ONE_HOP = _LIMITS0["one_hop"]
MAX_SINK_SCAN_FILES = _LIMITS0["sink_scan_files"]
MAX_KERNEL_ALIAS_FILES = _LIMITS0["kernel_alias_files"]


def propose_extract_plan(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
) -> dict[str, Any]:
    repo_root = Path(repo_root).resolve()
    limits = resolve_extract_limits(repo_root)
    apply_extract_limits_to_environ(limits)
    _sync_module_limit_globals(limits)

    uo_root = existing_operator_root(repo_root, op_name)
    graph = load_entrypoint_graph(uo_root)
    if not graph or not (graph.get("nodes") or graph.get("extraction_units")):
        return {
            "version": 1,
            "op_name": op_name,
            "architecture": architecture,
            "status": "blocked",
            "ok": False,
            "reason": "entrypoint_graph_missing_or_empty",
            "message": (
                "ir/entrypoint_graph.yaml missing or has no nodes/extraction_units; "
                "run resolve_entrypoints / boundary extract before propose_extract_plan"
            ),
            "writer_candidates": [],
            "receiver_candidates": [],
            "alias_candidates": [],
            "non_sink_root_candidates": [],
            "extra_entry_candidates": [],
            "counts": {"writers": 0, "receivers": 0, "aliases": 0, "non_sink_roots": 0, "extra_entries": 0},
        }
    boundary_path = uo_root / "ir" / "operator_boundary.yaml"
    if not boundary_path.is_file():
        return {
            "version": 1,
            "op_name": op_name,
            "architecture": architecture,
            "status": "blocked",
            "ok": False,
            "reason": "operator_boundary_missing",
            "message": (
                "ir/operator_boundary.yaml missing; run extract_operator_boundary before scoring extract plan"
            ),
            "writer_candidates": [],
            "receiver_candidates": [],
            "alias_candidates": [],
            "non_sink_root_candidates": [],
            "extra_entry_candidates": [],
            "counts": {"writers": 0, "receivers": 0, "aliases": 0, "non_sink_roots": 0, "extra_entries": 0},
        }
    seed_nodes = _seed_entrypoint_nodes(graph)
    if not seed_nodes:
        return {
            "version": 1,
            "op_name": op_name,
            "architecture": architecture,
            "status": "blocked",
            "ok": False,
            "reason": "entrypoint_seeds_empty",
            "message": "entrypoint_graph has no seed host nodes for extract scoring",
            "writer_candidates": [],
            "receiver_candidates": [],
            "alias_candidates": [],
            "non_sink_root_candidates": [],
            "extra_entry_candidates": [],
            "counts": {"writers": 0, "receivers": 0, "aliases": 0, "non_sink_roots": 0, "extra_entries": 0},
        }

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
            pcls = str(primary.get("class_or_namespace") or "")
            root = client.resolve_qn(
                str(primary["qualified_name"]),
                file_contains=architecture,
                class_qn=pcls or None,
            )
            if root is None and primary.get("name"):
                root = client.resolve_qn(
                    str(primary["name"]),
                    file_contains=architecture,
                    class_qn=pcls or None,
                )
            if root is not None:
                keep = {str(x.get("name") or "").casefold() for x in chain_items if x.get("name")}
                traced = client.bounded_trace(
                    root, keep_names=keep or None,
                    max_depth=_env_limit("UO_EXTRACT_TRACE_MAX_DEPTH", 6, 12),
                    max_nodes=_env_limit("UO_EXTRACT_TRACE_MAX_NODES", 240),
                )
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

    # Obvious assign-LHS noise (not functions): single-char / trivial words.
    _NON_SINK_LHS_NOISE = frozenset(
        {
            "begin",
            "end",
            "length",
            "first",
            "last",
            "tmp",
            "temp",
            "i",
            "j",
            "k",
            "n",
            "m",
            "x",
            "y",
            "z",
        }
    )
    non_sink: list[dict[str, Any]] = []
    for root in sorted(assign_lhs_roots - set_recv_roots):
        if not root or root.casefold() in {"tilingdata", "tiling_data", "this"}:
            continue
        if len(root) <= 1 or root.casefold() in _NON_SINK_LHS_NOISE:
            continue
        non_sink.append(
            {
                "name": root,
                "file_path": "",
                "start_line": 0,
                "snippet": f"{root} = ... (assign LHS only)",
                "score": 0.4,
                "evidence": ["assign_lhs_only"],
                "is_tiling_sink_suggested": False,
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

    raw_counts = {
        "writers": len(writers),
        "receivers": len(receivers),
        "aliases": len(aliases),
        "non_sink_roots": len(non_sink),
        "extra_entries": len(extra),
    }
    limits = {
        "writers": MAX_WRITERS,
        "receivers": MAX_RECEIVERS,
        "aliases": MAX_ALIASES,
        "non_sink_roots": MAX_NON_SINK,
        "extra_entries": MAX_EXTRA,
    }
    truncated = {
        name: raw_counts[name] - lim for name, lim in limits.items() if raw_counts[name] > lim
    }
    limits_auto_raised: dict[str, int] = {}
    limits_persisted: str = ""
    if truncated:
        # Fundamental fix (ses_0662): raise within hard max + persist to pilot_params so
        # agents need not inject shell env through the bash fence.
        new_limits, raised, still_over = _auto_raise_extract_limits(raw_counts, limits)
        if raised:
            persisted = persist_extract_limits(repo_root, raised)
            apply_extract_limits_to_environ(raised)
            limits = dict(new_limits)
            full = resolve_extract_limits(repo_root)
            full.update(limits)
            _sync_module_limit_globals(full)
            limits_auto_raised = {
                EXTRACT_LIMIT_SPECS[k][0]: v for k, v in raised.items() if k in EXTRACT_LIMIT_SPECS
            }
            limits_persisted = persisted.as_posix() if persisted else ""
            truncated = {
                name: raw_counts[name] - lim
                for name, lim in limits.items()
                if raw_counts[name] > lim
            }
            # still_over means raw > HARD_MAX — keep those as truncated
            for key, over in still_over.items():
                truncated[key] = over

    writer_list = _attach_source_windows(
        repo_root,
        _top_scored(list(writers.values()), MAX_WRITERS),
        body_by_key,
    )
    receiver_list = _top_scored(list(receivers.values()), MAX_RECEIVERS)
    alias_list = list(aliases.values())[:MAX_ALIASES]
    suggested_env = {
        EXTRACT_LIMIT_SPECS[k][0]: int(raw_counts[k])
        for k in ("writers", "receivers", "aliases", "non_sink_roots", "extra_entries")
        if raw_counts.get(k, 0) > limits.get(k, 0)
    }
    recovery_cli = ""
    if truncated and suggested_env:
        parts = " ".join(f"--set {k}={v}" for k, v in suggested_env.items())
        recovery_cli = f"acp run-action extract_plan {parts}".strip()
    recovery: Any
    if truncated:
        recovery = {
            "message": (
                "candidate truncation is never treated as a complete FAG graph; "
                "raise limits then retry prepare"
            ),
            "message_zh": (
                "候选预算仍超硬上限，请用 acp --set 抬高后重试（勿在 bash 里拼 $env；"
                "变量名是 UO_EXTRACT_MAX_NON_SINK 不是 *_NON_SINK_ROOTS）"
            ),
            "env": suggested_env,
            "cli": recovery_cli or "acp run-action extract_plan --raise-extract-limits",
        }
    elif limits_auto_raised:
        recovery = {
            "message": "candidate limits auto-raised to fit raw graph; persisted to pilot_params",
            "message_zh": "已自动抬高候选预算并写入 context/pilot_params.yaml，无需设置 shell 环境变量",
            "env": limits_auto_raised,
            "persisted": limits_persisted,
            "cli": "",
        }
    else:
        recovery = ""
    payload = {
        "version": 1,
        "op_name": op_name,
        "architecture": architecture,
        "status": "blocked" if truncated else "candidates",
        "ok": not bool(truncated),
        "reason": "candidate_budget_exhausted" if truncated else "",
        "writer_candidates": writer_list,
        "receiver_candidates": receiver_list,
        "alias_candidates": alias_list,
        "non_sink_root_candidates": non_sink[:MAX_NON_SINK],
        "extra_entry_candidates": extra[:MAX_EXTRA],
        "receiver_binding_candidates": [],
        "counts": {
            "writers": len(writer_list),
            "receivers": len(receiver_list),
            "aliases": len(alias_list),
            "non_sink_roots": min(len(non_sink), MAX_NON_SINK),
            "extra_entries": min(len(extra), MAX_EXTRA),
            "receiver_bindings": 0,
        },
        "raw_counts": raw_counts,
        "candidate_limits": limits,
        "truncated": truncated,
        "limits_auto_raised": limits_auto_raised,
        "limits_persisted": limits_persisted,
        "recovery": recovery,
        "recovery_cli": recovery_cli,
    }
    # Collect receiver bindings from writer/InitTilingData bodies already scanned.
    try:
        from uo.scripts.extract_plan_autofill import stamp_candidate_ids
        from uo.scripts.receiver_binding import (
            binding_candidate_id,
            extract_receiver_bindings_from_text,
        )

        binding_by_recv: dict[str, dict] = {}
        for _key, packed in body_by_key.items():
            body, start, _end, item = packed
            fp = str(item.get("file_path") or "").replace("\\", "/")
            cls = str(item.get("class_or_namespace") or "")
            for b in extract_receiver_bindings_from_text(
                body,
                file_path=fp,
                class_or_namespace=cls,
                extraction_unit=cls,
                start_line=int(start or 0),
            ):
                recv = str(b.get("receiver") or "")
                if not recv:
                    continue
                b["candidate_id"] = binding_candidate_id(b)
                prev = binding_by_recv.get(recv)
                if prev is None or float(b.get("score") or 0) >= float(prev.get("score") or 0):
                    binding_by_recv[recv] = b
        binding_list = list(binding_by_recv.values())
        payload["receiver_binding_candidates"] = binding_list
        payload["counts"]["receiver_bindings"] = len(binding_list)
        stamp_candidate_ids(payload)
    except Exception:
        pass
    return payload


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
    c = payload.get("counts") or {}
    print(
        f"extract_plan status={payload.get('status')} writers={c.get('writers', 0)} "
        f"receivers={c.get('receivers', 0)} aliases={c.get('aliases', 0)} "
        f"non_sink={c.get('non_sink_roots', 0)} extra={c.get('extra_entries', 0)}"
    )
    if payload.get("ok") is False or str(payload.get("status") or "") == "blocked":
        return 2
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
    """Identity key: identity_key or file|qn|class|sig|tpl (not bare name)."""
    if item.get("identity_key"):
        return str(item["identity_key"]).casefold()
    fp = str(item.get("file_path") or "").replace("\\", "/").strip()
    qn = str(item.get("qualified_name") or item.get("name") or "").strip()
    cls = str(item.get("class_or_namespace") or "").strip()
    if not cls and "::" in qn:
        prefix = qn.rsplit("::", 1)[0]
        if "/" not in prefix:
            cls = prefix
    sig = str(item.get("normalized_signature") or item.get("signature") or "").strip()
    tpl = str(item.get("template_arity_or_signature") or "").strip()
    return f"{fp}|{qn}|{cls}|{sig}|{tpl}".casefold()


def _append_chain_item(
    chain_items: list[dict[str, Any]],
    helper_name: str,
    parent: dict[str, Any],
    client: CbmClient,
    architecture: str,
) -> None:
    child = _resolve_item(helper_name, parent, client, architecture)
    if any(_writer_identity_key(x) == _writer_identity_key(child) for x in chain_items):
        return
    chain_items.append(child)


def _resolve_item(
    helper_name: str,
    parent: dict[str, Any],
    client: CbmClient,
    architecture: str,
) -> dict[str, Any]:
    parent_cls = str(parent.get("class_or_namespace") or "").strip()
    if client.available:
        hit, candidates = client.resolve_qn_or_ambiguous(
            helper_name,
            file_contains=architecture,
            class_qn=parent_cls or None,
        )
        if hit is not None:
            return hit.as_dict()
        if candidates:
            return {
                "name": helper_name,
                "qualified_name": helper_name,
                "file_path": parent.get("file_path") or "",
                "start_line": parent.get("start_line") or 0,
                "end_line": parent.get("end_line") or 0,
                "class_or_namespace": parent_cls,
                "resolution_status": "candidate_set",
                "candidate_symbols": [c.as_dict() for c in candidates],
            }
    return {
        "name": helper_name,
        "qualified_name": helper_name,
        "file_path": parent.get("file_path") or "",
        "start_line": parent.get("start_line") or 0,
        "end_line": parent.get("end_line") or 0,
        "class_or_namespace": parent_cls,
        "resolution_status": "unresolved",
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
            "role_suggested": _suggest_writer_role(name, evidence),
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


def _suggest_writer_role(name: str, evidence: list[str]) -> str:
    """Heuristic role for LLM confirm; plan.writers[].role may override."""
    ev = {str(x) for x in evidence}
    n = (name or "").casefold()
    # Dimension helpers (e.g. GetDeterSparseTilingKey) are not final key writers.
    if (
        ("key" in n or "tilingkey" in n)
        and any(tok in n for tok in ("deter", "sparse", "dim", "axis", "layout", "dtype"))
        and "gettilingkey" not in n
    ):
        return "key_dimension_source"
    if "has_set_field" in ev or "recv_set_call" in ev or "sink_set_writer" in ev:
        if "key" in n or "tilingkey" in n or "blockdim" in n:
            return "key_writer"
        if "workspace" in n or "worksize" in n:
            return "workspace_writer"
        return "tiling_writer"
    if "gettilingkey" in n or n.endswith("tilingkey"):
        return "key_writer"
    if "key" in n or "tilingkey" in n:
        # Generic *Key* helpers without GET_TPL / final pack → dimension source.
        if "get" in n and "tilingkey" not in n.replace("gettilingkey", ""):
            return "key_dimension_source"
        if "gettilingkey" not in n:
            return "key_dimension_source"
        return "key_writer"
    if "workspace" in n:
        return "workspace_writer"
    if "tilingdata_assign" in ev or "has_getattr" in ev:
        return "provenance_helper"
    return "ignore"


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
            # Discovered via recv->set_* ⇒ tiling sink by default; LLM may override.
            "is_tiling_sink_suggested": True,
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
                hit = client.resolve_qn(
                    name,
                    file_contains=architecture,
                    class_qn=str(item.get("class_or_namespace") or "") or None,
                )
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
