# -*- coding: utf-8 -*-
"""Cache clang -ast-dump fold results by instance signature (P4).

Storage: ``<project>/.ascendc-pilot/<arch>/uo/cache/fold/<key>.pkl``

Disable with ``UO_FOLD_CACHE=0``.
"""
from __future__ import annotations

import hashlib
import os
import pickle
import threading
from pathlib import Path
from typing import Any, Iterable

from uo_init.tu_cache import sha256_bytes, uo_cache_root

CACHE_VERSION = 1
_ENV = "UO_FOLD_CACHE"
_STATS = {"hit": 0, "miss": 0, "store": 0, "bypass": 0}
_LOCK = threading.Lock()


def cache_enabled() -> bool:
    raw = os.environ.get(_ENV, "1").strip().lower()
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


def fold_cache_dir(op_dir: str | Path | None, arch: str | None = None) -> Path:
    return uo_cache_root(op_dir, arch) / "fold"


def instance_signature(
    *,
    harness_source: bytes | str,
    entry: str,
    kernel_args: Iterable[str],
    logical_file: str = "",
    clang_exe: str = "",
) -> str:
    if isinstance(harness_source, str):
        src_sha = sha256_bytes(harness_source.encode("utf-8"))
    else:
        src_sha = sha256_bytes(harness_source)
    args = "\0".join(str(a) for a in kernel_args)
    payload = "\0".join(
        [
            f"v{CACHE_VERSION}",
            src_sha,
            f"entry={entry}",
            f"logical={logical_file}",
            f"clang={clang_exe}",
            args,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def signature_for_path(
    path: str | Path,
    ctx: Any,
    *,
    entry: str,
    logical_file: str = "",
    clang_exe: str = "",
) -> str:
    p = Path(path)
    src = p.read_bytes() if p.is_file() else b""
    try:
        args = list(ctx.kernel_args(dtype_variant=None))
    except Exception:  # noqa: BLE001
        args = []
    return instance_signature(
        harness_source=src,
        entry=entry,
        kernel_args=args,
        logical_file=logical_file,
        clang_exe=clang_exe or "",
    )


def _path(op_dir: str | Path | None, arch: str | None, key: str) -> Path:
    return fold_cache_dir(op_dir, arch) / f"{key}.pkl"


def load_fold_controls(
    key: str,
    *,
    op_dir: str | Path | None,
    arch: str | None = None,
) -> list | None:
    if not cache_enabled():
        _bump("bypass")
        return None
    path = _path(op_dir, arch, key)
    if not path.is_file():
        _bump("miss")
        return None
    try:
        with open(path, "rb") as fh:
            payload = pickle.load(fh)
        if not isinstance(payload, dict) or int(payload.get("version") or 0) != CACHE_VERSION:
            _bump("miss")
            return None
        controls = payload.get("controls")
        if not isinstance(controls, list):
            _bump("miss")
            return None
        _bump("hit")
        return list(controls)
    except Exception:  # noqa: BLE001
        _bump("miss")
        return None


def store_fold_controls(
    key: str,
    controls: list,
    *,
    op_dir: str | Path | None,
    arch: str | None = None,
) -> Path | None:
    if not cache_enabled():
        _bump("bypass")
        return None
    path = _path(op_dir, arch, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".pkl.tmp")
        with open(tmp, "wb") as fh:
            pickle.dump(
                {"version": CACHE_VERSION, "controls": list(controls)},
                fh,
                protocol=pickle.HIGHEST_PROTOCOL,
            )
        tmp.replace(path)
        _bump("store")
        return path
    except Exception:  # noqa: BLE001
        return None


__all__ = [
    "cache_enabled",
    "fold_cache_dir",
    "instance_signature",
    "signature_for_path",
    "load_fold_controls",
    "store_fold_controls",
    "reset_stats",
    "stats",
]
