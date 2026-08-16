# -*- coding: utf-8 -*-
"""Closure workspace and the finalized kernel-declared key domain.

Durable D/decode information comes from the CodeMap ``.uo`` legal-key index.
The replay TPL parser remains a runtime implementation detail for generating
new cases and a fallback for tests that intentionally have no product.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ENV_ARTIFACTS = "TG_CLOSURE_ARTIFACTS"
ENV_STATE = "TG_CLOSURE_STATE"
WIDE_GLOB = "*key_cases*.csv"
CORPUS_GLOBS = (
    "*key_cases*.csv",
    "rounds/**/*key_cases*.csv",
    "rounds/**/*.csv",
    "corpus/**/*.csv",
)


@dataclass(frozen=True)
class Workspace:
    root: Path
    artifacts: Path
    state: Path

    @property
    def r_path(self) -> Path:
        return self.state / "R.txt"

    @property
    def e_path(self) -> Path:
        return self.state / "excluded.txt"

    @property
    def e_why_path(self) -> Path:
        return self.state / "excluded_why.csv"

    @property
    def open_path(self) -> Path:
        return self.state / "open.txt"

    def report(self, name: str) -> Path:
        self.state.mkdir(parents=True, exist_ok=True)
        return self.state / name

    def ensure(self) -> "Workspace":
        self.state.mkdir(parents=True, exist_ok=True)
        return self


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _operator_root(explicit: str | Path | None = None) -> Path:
    snap = (os.environ.get("ASCENDC_SNAPSHOT_WORKSPACE") or "").strip()
    if explicit is None and snap:
        return Path(snap).expanduser().resolve()
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    state_env = os.environ.get(ENV_STATE)
    if state_env:
        p = Path(state_env).expanduser().resolve()
        for parent in p.parents:
            if parent.name == ".ascendc-pilot":
                return parent.parent
    for name in ("ASCENDC_PROJECT_ROOT", "UO_OP_DIR"):
        raw = os.environ.get(name)
        if raw:
            return Path(raw).expanduser().resolve()
    raise ValueError(
        "closure workspace root unresolved: pass root= / set ASCENDC_PROJECT_ROOT "
        "or UO_OP_DIR or TG_CLOSURE_STATE"
    )


def _arch_name() -> str:
    for _name in ("UO_ARCH", "ASCENDC_ARCH"):
        _raw = (os.environ.get(_name) or "").strip()
        if _raw:
            return _raw
    raise ValueError("ARCHITECTURE_MISSING_IN_RUN_STATE: architecture required")


def default_workspace(root: str | Path | None = None) -> Workspace:
    base = _operator_root(root)
    artifacts_env = os.environ.get(ENV_ARTIFACTS)
    artifacts = Path(artifacts_env) if artifacts_env else _manifest_cache(base)
    state_env = os.environ.get(ENV_STATE)
    if state_env:
        state = Path(state_env)
    else:
        try:
            from ascendc_pilot.paths import tg_root
            state = tg_root(base, arch=_arch_name()) / "closure"
        except Exception:
            state = base / ".ascendc-pilot" / _arch_name() / "tg" / "closure"
    return Workspace(root=base, artifacts=artifacts, state=state)


def _manifest_cache(base: Path) -> Path:
    try:
        runner = _replay().default()
        cache = Path(runner.cache)
        if not cache.is_absolute():
            try:
                from ascendc_pilot.paths import agent_root
                return agent_root(base, _arch_name()) / cache
            except Exception:
                return base / ".ascendc-pilot" / _arch_name() / cache
        return cache
    except Exception:
        try:
            from ascendc_pilot.paths import tg_root
            return tg_root(base, arch=_arch_name()) / "replay"
        except Exception:
            return base / ".ascendc-pilot" / _arch_name() / "tg" / "replay"


@lru_cache(maxsize=1)
def _replay():
    import sys
    scripts = _repo_root() / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from replay import runner
    return runner


def replay_runner():
    """Configured runner, with bundled runtime bootstrap on production Hosts."""
    runner = _replay().default()
    # Import through the same scripts package as runner.py. CI/synthetic runs
    # are explicitly skipped inside ensure_runner, so this has no machine side
    # effects in pure tests.
    from replay.bootstrap import ensure_runner

    ready = ensure_runner(runner)
    if not ready.get("ok"):
        raise RuntimeError(
            f"REPLAY_BOOTSTRAP_FAILED:{ready.get('error') or 'unknown'}:"
            f"{ready.get('stderr') or ready.get('stdout') or ''}"[:1200]
        )
    return runner


@lru_cache(maxsize=1)
def replay_inputs():
    import sys
    scripts = _repo_root() / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from replay import inputs
    return inputs


def schema():
    """Runtime TPL schema, used only when case construction needs it."""
    return _replay().default().schema()


def _product_rows() -> list[dict]:
    try:
        from testcase_agent import product_uo
        root = _operator_root()
        return product_uo.legal_key_rows(
            root,
            op_name=os.environ.get("UO_OPERATOR") or "",
            architecture=_arch_name(),
        )
    except Exception:
        return []


def _row_key(row: dict) -> int | None:
    raw = row.get("tiling_key") if row.get("tiling_key") is not None else row.get("key")
    try:
        return int(str(raw), 0)
    except (TypeError, ValueError):
        return None


def dim_names() -> list[str]:
    """Dimension order from product rows; TPL fallback for no-product tests."""
    rows = _product_rows()
    for row in rows:
        dims = row.get("dims")
        if isinstance(dims, dict) and dims:
            return [str(name) for name in dims]
    return [d.name for d in schema().dims]


def rule_book(*, refresh: bool = False):
    import sys
    scripts = _repo_root() / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from replay import rule_engine
    return rule_engine.default_book(refresh=refresh)


def declared() -> frozenset[int]:
    """D from ``.uo`` without requiring WSL, CANN, replay or a local TPL parse."""
    try:
        root = str(_operator_root())
    except ValueError:
        root = ""
    try:
        arch = _arch_name()
    except ValueError:
        arch = ""
    return _declared_for(
        root,
        arch,
        os.environ.get("TG_CLOSURE_CI") or "",
        os.environ.get("UO_OPERATOR") or "",
    )


@lru_cache(maxsize=16)
def _declared_for(root: str, arch: str, ci: str, op: str) -> frozenset[int]:
    del op
    uo_keys = _declared_from_uo()
    if uo_keys is not None:
        return frozenset(uo_keys)
    if ci == "1":
        from uo_init.tpl_dsl import expand_legal_instances
        sch = schema()
        fallback = {d.name: (list(d.value_domain) or ["0"])[0] for d in sch.dims}
        keys: set[int] = set()
        for inst in expand_legal_instances(sch):
            full = {name: str(inst.get(name, fallback[name])) for name in fallback}
            try:
                keys.add(int(sch.encode_tiling_key(full)))
            except (ValueError, KeyError):
                continue
        return frozenset(keys)
    return frozenset()


def _declared_from_uo() -> set[int] | None:
    rows = _product_rows()
    if not rows:
        return None
    out = {key for key in (_row_key(row) for row in rows) if key is not None}
    return out or None


def decode(key: int) -> dict[str, str]:
    """Decode from the product legal-key index; TPL fallback if unavailable."""
    want = int(key)
    for row in _product_rows():
        if _row_key(row) != want:
            continue
        dims = row.get("dims")
        if isinstance(dims, dict):
            return {str(k): str(v) for k, v in dims.items()}
    return schema().decode_tiling_key(want)


def encode(inst: dict[str, str]) -> int:
    """Encode exact legal rows from the product before consulting replay TPL."""
    want = {str(k): str(v) for k, v in inst.items()}
    rows = _product_rows()
    if rows:
        for row in rows:
            dims = row.get("dims")
            if not isinstance(dims, dict):
                continue
            normalized = {str(k): str(v) for k, v in dims.items()}
            if all(normalized.get(k) == v for k, v in want.items()):
                key = _row_key(row)
                if key is not None:
                    return key
    return int(schema().encode_tiling_key(inst))


def decode_many(keys) -> list[dict[str, str]]:
    out = []
    for k in keys:
        try:
            out.append(decode(int(k)))
        except (ValueError, KeyError, IndexError):
            continue
    return out
