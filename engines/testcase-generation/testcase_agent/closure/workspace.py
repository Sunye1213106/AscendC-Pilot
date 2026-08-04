# -*- coding: utf-8 -*-
"""Where the closure reads and writes, and what the kernel declares.

The exploration that produced the first closure kept all of this in
`.probe_cache/`: the ledger files, the corpus, and an absolute path to a CSV of
declared keys someone had generated earlier. None of that survives a change of
machine, so none of it belongs in the engine.

Two things are separated here that were previously one directory:

  artifacts   batches, logs and wide tables a replay wrote. The operator
              manifest already says where these go, so the manifest is asked.
  state       the ledger itself -- R, E, the open set. This is a conclusion
              rather than a raw observation, so it lives with the other
              Pilot artifacts under `.ascendc-pilot/`.

The declared set D is parsed from the kernel's tiling-key header. It used to be
read from a generated CSV, which meant the closure could silently be judged
against a stale D.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

#: Overrides, so a caller can point the closure at a saved corpus without
#: touching the manifest.
ENV_ARTIFACTS = "TG_CLOSURE_ARTIFACTS"
ENV_STATE = "TG_CLOSURE_STATE"

#: Wide tables a replay batch appends to. Operator-agnostic; the manifest may
#: narrow it.
WIDE_GLOB = "*key_cases*.csv"


@dataclass(frozen=True)
class Workspace:
    """Resolved locations for one operator's closure run."""

    root: Path
    artifacts: Path
    state: Path

    # -- ledger files ------------------------------------------------------
    @property
    def r_path(self) -> Path:
        """Witness set: one `key,provenance` line per key a real run produced."""
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
        """A generated report, e.g. `residual.csv`."""
        self.state.mkdir(parents=True, exist_ok=True)
        return self.state / name

    def ensure(self) -> "Workspace":
        self.state.mkdir(parents=True, exist_ok=True)
        return self


def _repo_root() -> Path:
    """The AscendC-Pilot checkout — only for ``sys.path`` injection of ``scripts/``.

    Must never be used as the default product root.
    """
    return Path(__file__).resolve().parents[4]


def _operator_root(explicit: str | Path | None = None) -> Path:
    """Resolve the analysed operator source directory that owns products."""
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    # Prefer TG_CLOSURE_STATE's parent chain when set.
    state_env = os.environ.get(ENV_STATE)
    if state_env:
        # .../.ascendc-pilot/<arch>/tg/closure → op_src
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
        "or UO_OP_DIR or TG_CLOSURE_STATE (must be the operator source directory, "
        "not the AscendC-Pilot checkout)"
    )


def _arch_name() -> str:
    return (os.environ.get("UO_ARCH") or os.environ.get("ASCENDC_ARCH") or "arch35").strip()


def default_workspace(root: str | Path | None = None) -> Workspace:
    """Locations for the operator the environment currently names.

    `artifacts` follows the operator manifest so a replay and the ledger that
    reads it never disagree about where a batch landed. Products live under
    ``<op_src>/.ascendc-pilot/<arch>/tg/closure``.
    """
    base = _operator_root(root)

    artifacts_env = os.environ.get(ENV_ARTIFACTS)
    if artifacts_env:
        artifacts = Path(artifacts_env)
    else:
        artifacts = _manifest_cache(base)

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
    """The replay cache the active operator manifest declares."""
    try:
        runner = _replay().default()
        cache = Path(runner.cache)
        if not cache.is_absolute():
            # Relative caches are under <op_src>/.ascendc-pilot/<arch>/
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


# -- the replay engine ----------------------------------------------------
#
# It lives under `scripts/replay/` rather than in this package: twenty-odd
# scripts and its own test suite import it from there, and the driver protocol
# is operator-plumbing rather than test generation. Reached through one
# function so the closure modules carry no path arithmetic.

@lru_cache(maxsize=1)
def _replay():
    import sys

    scripts = _repo_root() / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from replay import runner  # noqa: PLC0415 - deferred by design

    return runner


def replay_runner():
    """The configured `ReplayRunner` (drives the host, decodes the key)."""
    return _replay().default()


@lru_cache(maxsize=1)
def replay_inputs():
    """The active operator's input semantics: `Case`, `describe`, the enums."""
    import sys

    scripts = _repo_root() / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from replay import inputs  # noqa: PLC0415

    return inputs


def schema():
    """The kernel's tiling-key schema: dimensions, packing, legal selections."""
    return _replay().default().schema()


def dim_names() -> list[str]:
    return [d.name for d in schema().dims]


def rule_book(*, refresh: bool = False):
    """Proof and derived rules for the active operator."""
    import sys

    scripts = _repo_root() / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from replay import rule_engine  # noqa: PLC0415

    return rule_engine.default_book(refresh=refresh)


@lru_cache(maxsize=1)
def declared() -> frozenset[int]:
    """D, expanded from the kernel's `ASCENDC_TPL_ARGS_SEL` groups.

    Every legal template instantiation packs to one key, so the selection
    groups *are* the declared set. Deriving it here rather than reading a
    generated CSV means D cannot go stale relative to the kernel.
    """
    from uo_init.tpl_dsl import expand_legal_instances  # noqa: PLC0415

    sch = schema()
    fallback = {d.name: (list(d.value_domain) or ["0"])[0] for d in sch.dims}
    keys: set[int] = set()
    for inst in expand_legal_instances(sch):
        full = {name: str(inst.get(name, fallback[name])) for name in fallback}
        try:
            keys.add(int(sch.encode_tiling_key(full)))
        except (ValueError, KeyError):
            # A selection naming a value outside the declared domain is a
            # kernel/schema disagreement, not a key. Skipping it keeps D to
            # what can actually be packed.
            continue
    return frozenset(keys)


def decode(key: int) -> dict[str, str]:
    return schema().decode_tiling_key(int(key))


def encode(inst: dict[str, str]) -> int:
    return int(schema().encode_tiling_key(inst))


def decode_many(keys) -> list[dict[str, str]]:
    """Decoded instances, skipping keys this schema cannot express."""
    sch = schema()
    out = []
    for k in keys:
        try:
            out.append(sch.decode_tiling_key(int(k)))
        except (ValueError, KeyError, IndexError):
            continue
    return out
