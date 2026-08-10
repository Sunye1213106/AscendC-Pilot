# -*- coding: utf-8 -*-
"""Per-field derive_key_fields result cache (P4).

Key = field name + bundle/source fingerprint. Warm re-derive skips work for
cached fields without changing isolate-mode semantics: hits are resolved in
the parent before any worker is spawned.

Disable with ``UO_DERIVE_CACHE=0``.
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
import threading
from pathlib import Path
from typing import Any

from uo_init.tu_cache import uo_cache_root

CACHE_VERSION = 1
_ENV = "UO_DERIVE_CACHE"
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


def derive_cache_dir(op_dir: str | Path | None, arch: str | None = None) -> Path:
    return uo_cache_root(op_dir, arch) / "derive"


def bundle_fingerprint(bundle: dict[str, Any]) -> str:
    """Cheap stable fingerprint of inputs that affect field derivation."""
    host_ir = bundle.get("host_ir")
    binding = bundle.get("binding")
    parts: list[Any] = []
    if host_ir is not None:
        writes = getattr(host_ir, "writes", None) or []
        locals_w = getattr(host_ir, "local_writes", None) or []
        controls = getattr(host_ir, "controls", None) or []
        parts.append(
            {
                "n_writes": len(writes),
                "n_local": len(locals_w),
                "n_ctrl": len(controls),
                "write_sig": [
                    (getattr(w, "path", ""), getattr(w, "line", 0), getattr(w, "rhs", "")[:80])
                    for w in list(writes)[:64]
                ],
                "ctrl_sig": [
                    (getattr(c, "id", ""), getattr(c, "condition", "")[:80])
                    for c in list(controls)[:64]
                ],
            }
        )
    if binding is not None:
        site = getattr(binding, "site", None)
        bindings = getattr(binding, "bindings", None) or []
        parts.append(
            {
                "site": getattr(site, "to_dict", lambda: str(site))()
                if site is not None
                else {},
                "dims": [
                    (getattr(getattr(b, "decl", None), "name", ""), getattr(b, "index", -1), str(getattr(b, "host_expr", ""))[:120])
                    for b in bindings
                ],
            }
        )
    spec = bundle.get("spec")
    if spec is not None:
        parts.append(
            {
                "op": getattr(spec, "op_name", ""),
                "arch": getattr(spec, "arch_dir", ""),
            }
        )
    raw = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def field_cache_key(
    field_name: str,
    bundle_fp: str,
    *,
    max_helper_guards: int = 4,
    kind: str = "field",
) -> str:
    payload = f"v{CACHE_VERSION}\0{kind}\0{field_name}\0{bundle_fp}\0h={max_helper_guards}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _path(op_dir: str | Path | None, arch: str | None, key: str) -> Path:
    return derive_cache_dir(op_dir, arch) / f"{key}.pkl"


def load_field_row(
    key: str,
    *,
    op_dir: str | Path | None,
    arch: str | None = None,
) -> dict[str, Any] | None:
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
        row = payload.get("row")
        if not isinstance(row, dict):
            _bump("miss")
            return None
        _bump("hit")
        return dict(row)
    except Exception:  # noqa: BLE001
        _bump("miss")
        return None


def store_field_row(
    key: str,
    row: dict[str, Any],
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
                {"version": CACHE_VERSION, "row": dict(row)},
                fh,
                protocol=pickle.HIGHEST_PROTOCOL,
            )
        tmp.replace(path)
        _bump("store")
        return path
    except Exception:  # noqa: BLE001
        return None


def expansion_cache_key(
    function: str,
    variable: str,
    *,
    program_point: str = "",
    macro_context: str = "",
    bundle_fp: str = "",
) -> str:
    """Disk key for a semantic expansion (shared across tiling-key dimensions)."""
    payload = (
        f"v{CACHE_VERSION}\0expansion\0{function}\0{variable}\0"
        f"{program_point}\0{macro_context}\0{bundle_fp}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class SemanticExpansionCache:
    """In-process cache keyed by (function, variable, program_point, macro_context).

    Persistent derive workers keep one deriver (and thus one of these) for many
    field jobs, so expansions of ``blockOuter`` / ``s1Inner`` / … are reused
    across dimensions without re-walking HostIR.
    """

    def __init__(self) -> None:
        self._mem: dict[tuple[str, str, str, str], Any] = {}
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _key(
        function: str,
        variable: str,
        program_point: str = "",
        macro_context: str = "",
    ) -> tuple[str, str, str, str]:
        return (
            str(function or ""),
            str(variable or ""),
            str(program_point or ""),
            str(macro_context or ""),
        )

    def get(
        self,
        function: str,
        variable: str,
        *,
        program_point: str = "",
        macro_context: str = "",
    ) -> Any | None:
        key = self._key(function, variable, program_point, macro_context)
        if key in self._mem:
            self.hits += 1
            return self._mem[key]
        self.misses += 1
        return None

    def put(
        self,
        function: str,
        variable: str,
        value: Any,
        *,
        program_point: str = "",
        macro_context: str = "",
    ) -> None:
        self._mem[self._key(function, variable, program_point, macro_context)] = value

    def clear(self) -> None:
        self._mem.clear()
        self.hits = 0
        self.misses = 0
