# -*- coding: utf-8 -*-
"""Durable disk cache for libclang walk IR fragments (P2).

Caches serializable :class:`~uo_init.clang_walk.WalkResult` values — never the
clang ``TranslationUnit`` object. Key = sha256(source bytes) + build-context /
parse-flag fingerprint.

Storage layout (preferred)::

    <project>/.ascendc-pilot/<arch>/uo/cache/tu/<key>.pkl

Disable with ``UO_TU_CACHE=0``. Optional override: ``UO_CACHE_ROOT``.
"""
from __future__ import annotations

from uo_init.paths import require_architecture
import hashlib
import os
import pickle
import threading
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable

CACHE_VERSION = 2
_ENV_ENABLE = "UO_TU_CACHE"
_ENV_ROOT = "UO_CACHE_ROOT"

# Process-local hit stats for tests / timing lines.
_STATS = {"hit": 0, "miss": 0, "store": 0, "bypass": 0}
_LOCK = threading.Lock()


def cache_enabled() -> bool:
    raw = os.environ.get(_ENV_ENABLE, "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def reset_stats() -> None:
    with _LOCK:
        for k in _STATS:
            _STATS[k] = 0


def stats() -> dict[str, int]:
    with _LOCK:
        return dict(_STATS)


def _bump(key: str) -> None:
    with _LOCK:
        _STATS[key] = int(_STATS.get(key) or 0) + 1


def uo_cache_root(op_dir: str | Path | None, arch: str | None = None) -> Path:
    """Return ``…/.ascendc-pilot/<arch>/uo/cache`` (or ``UO_CACHE_ROOT``)."""
    override = os.environ.get(_ENV_ROOT, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    root = Path(op_dir or ".").expanduser().resolve()
    arch_name = require_architecture(arch)
    return root / ".ascendc-pilot" / arch_name / "uo" / "cache"


def tu_cache_dir(op_dir: str | Path | None, arch: str | None = None) -> Path:
    return uo_cache_root(op_dir, arch) / "tu"


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_context_fingerprint(
    ctx: Any,
    *,
    side: str,
    dtype_variant: str | None,
    parse_flags: Iterable[str] | None = None,
) -> str:
    """Fingerprint include roots / CANN paths / parse args that affect the walk."""
    parts: list[str] = [
        f"side={side}",
        f"dtype={dtype_variant or ''}",
        f"cann={getattr(ctx, 'cann_root', '') or ''}",
        f"ops={getattr(ctx, 'ops_root', '') or ''}",
        f"compat={getattr(ctx, 'compat_root', '') or ''}",
        f"op_dir={getattr(ctx, 'op_dir', '') or ''}",
        f"arch={getattr(ctx, 'arch_dir', '') or ''}",
    ]
    try:
        args = list(parse_flags) if parse_flags is not None else (
            ctx.host_args() if side == "host" else ctx.kernel_args(dtype_variant=dtype_variant)
        )
    except Exception:  # noqa: BLE001
        args = []
    parts.append("args=" + "\0".join(str(a) for a in args))
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def scope_fingerprint(scope: Any) -> str:
    if scope is None:
        return ""
    try:
        files = getattr(scope, "files", None) or getattr(scope, "confirmed_source_files", None)
        if files is None and hasattr(scope, "__iter__") and not isinstance(scope, (str, bytes)):
            files = list(scope)
        if not files:
            return ""
        rels = sorted(str(f).replace("\\", "/") for f in files)
        return hashlib.sha256("\0".join(rels).encode("utf-8")).hexdigest()[:32]
    except Exception:  # noqa: BLE001
        return ""


def walk_cache_key(
    path: str | Path,
    ctx: Any,
    *,
    side: str = "host",
    dtype_variant: str | None = "DT_FLOAT16",
    op_needle: str = "",
    collect_writes: bool = True,
    scope: Any = None,
    logs_rejections: bool = False,
    source_sha: str | None = None,
) -> str:
    src_sha = source_sha or sha256_file(path)
    ctx_fp = build_context_fingerprint(ctx, side=side, dtype_variant=dtype_variant)
    payload = "\0".join(
        [
            f"v{CACHE_VERSION}",
            src_sha,
            ctx_fp,
            f"needle={op_needle}",
            f"writes={int(bool(collect_writes))}",
            f"reject={int(bool(logs_rejections))}",
            f"scope={scope_fingerprint(scope)}",
            Path(path).name,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_path(op_dir: str | Path | None, arch: str | None, key: str) -> Path:
    return tu_cache_dir(op_dir, arch) / f"{key}.pkl"


def _to_plain(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_plain(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k) if isinstance(k, tuple) else k: _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(x) for x in obj]
    if isinstance(obj, set):
        return sorted(_to_plain(x) for x in obj)
    return obj


def serialize_walk_result(result: Any) -> dict[str, Any]:
    """Convert a WalkResult (or compatible) into a plain JSON/pickle-friendly dict."""
    from uo_init.clang_walk import WalkResult

    if not isinstance(result, WalkResult):
        raise TypeError(f"expected WalkResult, got {type(result)!r}")
    # Build field-by-field so tuple-keyed field_decls never go through asdict.
    decls = getattr(result, "field_decls", None) or {}
    plain = {
        "path": result.path,
        "controls": _to_plain(result.controls),
        "writes": _to_plain(result.writes),
        "local_writes": _to_plain(result.local_writes),
        "call_sites": _to_plain(result.call_sites),
        "functions": {k: _to_plain(v) for k, v in result.functions.items()},
        "diagnostics": [list(d) for d in result.diagnostics],
        "macro_idioms": int(result.macro_idioms or 0),
        "class_fields": sorted(result.class_fields),
        "field_decls": [
            {"key": [k[0], k[1]], "value": _to_plain(v)} for k, v in decls.items()
        ],
        "local_decls": _to_plain(result.local_decls),
        "type_decls": _to_plain(getattr(result, "type_decls", None) or []),
        "alias_decls": _to_plain(getattr(result, "alias_decls", None) or []),
        "base_decls": _to_plain(getattr(result, "base_decls", None) or []),
    }
    return {"version": CACHE_VERSION, "kind": "WalkResult", "data": plain}


def deserialize_walk_result(payload: dict[str, Any]) -> Any:
    from uo_init.clang_walk import (
        AliasDecl,
        BaseDecl,
        CallSite,
        CtrlNode,
        FieldDecl,
        FuncRecord,
        LocalDecl,
        PathCond,
        TypeDecl,
        WalkResult,
        WriteRecord,
    )

    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ValueError("invalid walk cache payload")

    def _pc(row: dict[str, Any]) -> PathCond:
        return PathCond(
            text=str(row.get("text") or ""),
            negated=bool(row.get("negated")),
            file=str(row.get("file") or ""),
            line=int(row.get("line") or 0),
            kind=str(row.get("kind") or "if"),
        )

    def _ctrl(row: dict[str, Any]) -> CtrlNode:
        pcs = tuple(_pc(x) for x in (row.get("path_conditions") or []) if isinstance(x, dict))
        return CtrlNode(
            id=str(row.get("id") or ""),
            kind=str(row.get("kind") or ""),
            file=str(row.get("file") or ""),
            line=int(row.get("line") or 0),
            column=int(row.get("column") or 0),
            snippet=str(row.get("snippet") or ""),
            condition=str(row.get("condition") or ""),
            function=str(row.get("function") or ""),
            universe=str(row.get("universe") or "PRODUCTION"),
            path_conditions=pcs,
            induction_vars=tuple(row.get("induction_vars") or ()),
            init_value=row.get("init_value"),
            step=row.get("step"),
        )

    def _write(row: dict[str, Any]) -> WriteRecord:
        pcs = tuple(_pc(x) for x in (row.get("path_conditions") or []) if isinstance(x, dict))
        return WriteRecord(
            path=str(row.get("path") or ""),
            line=int(row.get("line") or 0),
            rhs=str(row.get("rhs") or ""),
            file=str(row.get("file") or ""),
            function=str(row.get("function") or ""),
            path_conditions=pcs,
            kind=str(row.get("kind") or "assign"),
            column=int(row.get("column") or 0),
        )

    def _call(row: dict[str, Any]) -> CallSite:
        pcs = tuple(_pc(x) for x in (row.get("path_conditions") or []) if isinstance(x, dict))
        return CallSite(
            caller=str(row.get("caller") or ""),
            callee=str(row.get("callee") or ""),
            file=str(row.get("file") or ""),
            line=int(row.get("line") or 0),
            args=tuple(row.get("args") or ()),
            path_conditions=pcs,
            receiver=str(row.get("receiver") or ""),
            column=int(row.get("column") or 0),
            caller_usr=str(row.get("caller_usr") or ""),
            caller_qualified=str(row.get("caller_qualified") or ""),
            callee_usr=str(row.get("callee_usr") or ""),
            callee_qualified=str(row.get("callee_qualified") or ""),
            callee_decl_file=str(row.get("callee_decl_file") or ""),
            receiver_type=str(row.get("receiver_type") or ""),
            receiver_canonical_type=str(row.get("receiver_canonical_type") or ""),
        )

    def _func(name: str, row: dict[str, Any]) -> FuncRecord:
        return FuncRecord(
            name=str(row.get("name") or name),
            file=str(row.get("file") or ""),
            line=int(row.get("line") or 0),
            reads=list(row.get("reads") or []),
            writes=list(row.get("writes") or []),
            guards=list(row.get("guards") or []),
            locals=dict(row.get("locals") or {}),
            params=list(row.get("params") or []),
            out_params=list(row.get("out_params") or []),
            calls=[
                (str(c[0]), tuple(c[1]) if len(c) > 1 else ())
                for c in (row.get("calls") or [])
                if isinstance(c, (list, tuple)) and c
            ],
            returns=list(row.get("returns") or []),
            assigns=dict(row.get("assigns") or {}),
            appends={str(k): list(v) for k, v in (row.get("appends") or {}).items()},
            assign_lists={str(k): list(v) for k, v in (row.get("assign_lists") or {}).items()},
            usr=str(row.get("usr") or ""),
            qualified_name=str(row.get("qualified_name") or ""),
        )

    field_decls: dict[tuple[str, str], FieldDecl] = {}
    for item in data.get("field_decls") or []:
        if not isinstance(item, dict):
            continue
        key = item.get("key") or []
        val = item.get("value") if "value" in item else item
        if not isinstance(val, dict) or len(key) < 2:
            continue
        field_decls[(str(key[0]), str(key[1]))] = FieldDecl(
            host=str(val.get("host") or key[0]),
            name=str(val.get("name") or key[1]),
            init=val.get("init"),
            file=str(val.get("file") or ""),
            line=int(val.get("line") or 0),
            type_text=str(val.get("type_text") or ""),
            canonical_type=str(val.get("canonical_type") or ""),
            owner_qualified=str(val.get("owner_qualified") or ""),
            referenced_type_usr=str(val.get("referenced_type_usr") or ""),
            column=int(val.get("column") or 0),
        )

    local_decls = [
        LocalDecl(
            name=str(r.get("name") or ""),
            function=str(r.get("function") or ""),
            type_text=str(r.get("type_text") or ""),
            init=r.get("init"),
            file=str(r.get("file") or ""),
            line=int(r.get("line") or 0),
            column=int(r.get("column") or 0),
        )
        for r in (data.get("local_decls") or [])
        if isinstance(r, dict)
    ]

    type_decls = [
        TypeDecl(
            name=str(r.get("name") or ""),
            qualified_name=str(r.get("qualified_name") or ""),
            usr=str(r.get("usr") or ""),
            file=str(r.get("file") or ""),
            line=int(r.get("line") or 0),
            kind=str(r.get("kind") or "class"),
            column=int(r.get("column") or 0),
        )
        for r in (data.get("type_decls") or [])
        if isinstance(r, dict)
    ]
    alias_decls = [
        AliasDecl(
            name=str(r.get("name") or ""),
            qualified_name=str(r.get("qualified_name") or ""),
            target_type=str(r.get("target_type") or ""),
            canonical_type=str(r.get("canonical_type") or ""),
            target_usr=str(r.get("target_usr") or ""),
            file=str(r.get("file") or ""),
            line=int(r.get("line") or 0),
            column=int(r.get("column") or 0),
        )
        for r in (data.get("alias_decls") or [])
        if isinstance(r, dict)
    ]
    base_decls = [
        BaseDecl(
            derived_name=str(r.get("derived_name") or ""),
            derived_usr=str(r.get("derived_usr") or ""),
            base_name=str(r.get("base_name") or ""),
            base_usr=str(r.get("base_usr") or ""),
            canonical_type=str(r.get("canonical_type") or ""),
            file=str(r.get("file") or ""),
            line=int(r.get("line") or 0),
            column=int(r.get("column") or 0),
        )
        for r in (data.get("base_decls") or [])
        if isinstance(r, dict)
    ]

    functions = {
        str(k): _func(str(k), v)
        for k, v in (data.get("functions") or {}).items()
        if isinstance(v, dict)
    }
    diags = []
    for d in data.get("diagnostics") or []:
        if isinstance(d, (list, tuple)) and len(d) >= 3:
            diags.append((int(d[0]), str(d[1]), str(d[2])))

    return WalkResult(
        path=str(data.get("path") or ""),
        controls=[_ctrl(x) for x in (data.get("controls") or []) if isinstance(x, dict)],
        writes=[_write(x) for x in (data.get("writes") or []) if isinstance(x, dict)],
        local_writes=[_write(x) for x in (data.get("local_writes") or []) if isinstance(x, dict)],
        call_sites=[_call(x) for x in (data.get("call_sites") or []) if isinstance(x, dict)],
        functions=functions,
        diagnostics=diags,
        macro_idioms=int(data.get("macro_idioms") or 0),
        class_fields=set(data.get("class_fields") or []),
        field_decls=field_decls,
        local_decls=local_decls,
        type_decls=type_decls,
        alias_decls=alias_decls,
        base_decls=base_decls,
    )


def load_walk(
    key: str,
    *,
    op_dir: str | Path | None,
    arch: str | None = None,
) -> Any | None:
    if not cache_enabled():
        _bump("bypass")
        return None
    path = _cache_path(op_dir, arch, key)
    if not path.is_file():
        _bump("miss")
        return None
    try:
        with open(path, "rb") as fh:
            payload = pickle.load(fh)
        if not isinstance(payload, dict) or int(payload.get("version") or 0) != CACHE_VERSION:
            _bump("miss")
            return None
        result = deserialize_walk_result(payload)
        _bump("hit")
        return result
    except Exception:  # noqa: BLE001
        _bump("miss")
        return None


def iter_cached_walks(
    op_dir: str | Path | None,
    arch: str | None = None,
    *,
    path_substr: str = "op_kernel",
    limit: int = 64,
) -> list[Any]:
    """Load up to ``limit`` cached WalkResults whose TU path matches ``path_substr``.

    Used by Kernel Execution extraction to reuse Clang call sites already paid
    for during ``build_kernel_ir`` / host walks — no extra libclang parse.
    """
    if not cache_enabled() or op_dir is None:
        return []
    root = tu_cache_dir(op_dir, arch)
    if not root.is_dir():
        return []
    needle = str(path_substr or "").replace("\\", "/").lower()
    out: list[Any] = []
    for path in sorted(root.glob("*.pkl")):
        if path.name.endswith(".probe.pkl"):
            continue
        if len(out) >= max(1, int(limit)):
            break
        try:
            with open(path, "rb") as fh:
                payload = pickle.load(fh)
            if not isinstance(payload, dict) or int(payload.get("version") or 0) != CACHE_VERSION:
                continue
            if str(payload.get("kind") or "") not in {"", "WalkResult"}:
                continue
            result = deserialize_walk_result(payload)
            tu = str(getattr(result, "path", "") or "").replace("\\", "/").lower()
            if needle and needle not in tu:
                continue
            out.append(result)
            _bump("hit")
        except Exception:  # noqa: BLE001
            continue
    return out


def load_probe(
    key: str,
    *,
    op_dir: str | Path | None,
    arch: str | None = None,
) -> dict[str, Any] | None:
    """Diagnostics-only probe payload (plain dict, not a WalkResult)."""
    if not cache_enabled():
        _bump("bypass")
        return None
    path = _cache_path(op_dir, arch, key).with_suffix(".probe.pkl")
    if not path.is_file():
        _bump("miss")
        return None
    try:
        with open(path, "rb") as fh:
            payload = pickle.load(fh)
        if not isinstance(payload, dict) or int(payload.get("version") or 0) != CACHE_VERSION:
            _bump("miss")
            return None
        _bump("hit")
        return dict(payload.get("probe") or {})
    except Exception:  # noqa: BLE001
        _bump("miss")
        return None


def store_probe(
    key: str,
    probe: dict[str, Any],
    *,
    op_dir: str | Path | None,
    arch: str | None = None,
) -> Path | None:
    if not cache_enabled():
        _bump("bypass")
        return None
    path = _cache_path(op_dir, arch, key).with_suffix(".probe.pkl")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "wb") as fh:
            pickle.dump(
                {"version": CACHE_VERSION, "probe": dict(probe)},
                fh,
                protocol=pickle.HIGHEST_PROTOCOL,
            )
        tmp.replace(path)
        _bump("store")
        return path
    except Exception:  # noqa: BLE001
        return None


def store_walk(
    key: str,
    result: Any,
    *,
    op_dir: str | Path | None,
    arch: str | None = None,
) -> Path | None:
    if not cache_enabled():
        _bump("bypass")
        return None
    path = _cache_path(op_dir, arch, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = serialize_walk_result(result)
        tmp = path.with_suffix(".pkl.tmp")
        with open(tmp, "wb") as fh:
            pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(path)
        _bump("store")
        return path
    except Exception:  # noqa: BLE001
        return None
