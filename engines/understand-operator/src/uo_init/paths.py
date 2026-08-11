# -*- coding: utf-8 -*-
"""Where the external trees live: CANN headers and the operator sources.

Neither tree ships with this repository, and their location differs per
checkout. Previously each caller hard-coded one developer's layout, so on any
other machine the CANN-dependent tests skipped silently and the suite still
reported green. Resolution now goes explicit argument, then environment, then a
short list of layouts relative to the repository -- and when nothing matches,
`explain()` says what was tried so the failure is actionable instead of silent.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

#: Written by `scripts/cann_slim.py` once the trimmed tree has been proven to
#: parse the host translation units. Only a tree carrying it is auto-selected;
#: an unverified trim would fail in confusing ways deep inside clang.
#:
#: The marker records the digest of the spec that decided what to copy. What it
#: guards against is a trimmed tree that parses one operator and is missing
#: headers the next one needs: that tree looks verified, gets preferred over the
#: full one, and the shortfall surfaces much later as an unexplained parse
#: error. Comparing digests catches the stale tree at resolution time instead.
SLIM_MARKER = ".slim-verified"

CANN_ENV_VARS = ("UO_CANN_ROOT", "ASCEND_CANN_PACKAGE_PATH", "CANN_ROOT")
OPS_ENV_VARS = ("UO_OPS_ROOT", "OPS_ROOT", "OPS_TRANSFORMER_ROOT")
OP_DIR_ENV_VARS = ("ASCENDC_PROJECT_ROOT", "UO_OP_DIR")


def repo_root() -> Path:
    """The AscendC-Pilot checkout root."""
    # .../engines/understand-operator/src/uo_init/paths.py
    return Path(__file__).resolve().parents[4]


def _env(names: tuple[str, ...]) -> Path | None:
    for name in names:
        raw = os.environ.get(name)
        if raw:
            return Path(raw).expanduser()
    return None


def _cann_candidates() -> list[Path]:
    repo = repo_root()
    roots = [repo.parent, repo.parent.parent]
    out: list[Path] = []
    for base in roots:
        # A verified slim tree is cheaper to read and is preferred.
        out.append(base / "_cann" / "slim")
        out.append(base / "_cann" / "pkg")
    return out


def _ops_candidates() -> list[Path]:
    repo = repo_root()
    return [
        repo.parent / "ops-transformer",
        repo.parent / "TEST" / "ops-transformer",
        repo.parent.parent / "ops-transformer",
        repo.parent.parent / "TEST" / "ops-transformer",
    ]


def spec_path() -> Path:
    """The build context that decides which headers a trimmed tree must hold."""
    return repo_root() / "engines" / "understand-operator" / "spec" / "build_context.yaml"


def spec_digest() -> str | None:
    try:
        return hashlib.sha256(spec_path().read_bytes()).hexdigest()
    except OSError:
        return None


def slim_status(path: Path) -> str | None:
    """Why `path` is not a usable trimmed tree, or None when it is.

    Read by `explain()` so a skipped trim is reported rather than silently
    stepped over.
    """
    marker = path / SLIM_MARKER
    if not marker.exists():
        return "no verification marker; run scripts/cann_slim.py"
    try:
        record = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Markers written before they carried a digest. Those trees predate the
        # completeness check and cannot be shown to match the current spec.
        return "verification marker predates spec pinning; re-run scripts/cann_slim.py"
    want = spec_digest()
    got = record.get("spec_digest")
    if want is not None and got != want:
        return f"built from a different build_context.yaml ({got} != {want})"
    return None


def _looks_like_cann(path: Path) -> bool:
    """A CANN root holds the sub-packages side by side, not a single include/."""
    if not path.is_dir():
        return False
    return any((path / name).is_dir() for name in ("cann-metadef", "cann-asc-devkit"))


def _looks_like_ops(path: Path) -> bool:
    return path.is_dir() and (path / "common" / "include").is_dir()


def cann_root(explicit: str | os.PathLike[str] | None = None) -> Path | None:
    """The extracted CANN tree, or None when it cannot be located."""
    if explicit:
        got = Path(explicit).expanduser()
        return got if got.is_dir() else None
    got = _env(CANN_ENV_VARS)
    if got is not None:
        return got if got.is_dir() else None
    for cand in _cann_candidates():
        if not _looks_like_cann(cand):
            continue
        if cand.name == "slim" and slim_status(cand) is not None:
            continue
        return cand
    return None


def ops_root(explicit: str | os.PathLike[str] | None = None) -> Path | None:
    """The operator source/dependency checkout, or None."""
    if explicit:
        got = Path(explicit).expanduser()
        return got if got.is_dir() else None
    got = _env(OPS_ENV_VARS)
    if got is not None:
        return got if got.is_dir() else None
    for cand in _ops_candidates():
        if _looks_like_ops(cand):
            return cand
    return None


def op_dir(
    explicit: str | os.PathLike[str] | None = None,
    *,
    relative: str,
) -> Path | None:
    """One operator's directory inside a source/dependency root.

    `relative` has no default: which operator is under analysis is an input to
    this tool, never a property of it.
    """
    if explicit:
        got = Path(explicit).expanduser()
        return got if got.is_dir() else None
    got = _env(OP_DIR_ENV_VARS)
    if got is not None:
        return got if got.is_dir() else None
    ops = ops_root()
    if ops is None:
        return None
    cand = ops.joinpath(*relative.split("/"))
    return cand if cand.is_dir() else None


@dataclass(frozen=True)
class Resolution:
    name: str
    value: Path | None
    env_vars: tuple[str, ...]
    tried: tuple[Path, ...]

    def explain(self) -> str:
        if self.value is not None:
            return f"{self.name}: {self.value}"
        env = " or ".join(self.env_vars)
        tried = "\n".join(f"    {p}" for p in self.tried)
        return f"{self.name}: NOT FOUND (set {env})\n  looked in:\n{tried}"


def resolve_all() -> list[Resolution]:
    """Everything this repository needs from outside, for diagnostics."""
    return [
        Resolution("cann_root", cann_root(), CANN_ENV_VARS, tuple(_cann_candidates())),
        Resolution("ops_root", ops_root(), OPS_ENV_VARS, tuple(_ops_candidates())),
    ]


def explain() -> str:
    lines = [r.explain() for r in resolve_all()]
    for cand in _cann_candidates():
        if cand.name != "slim" or not cand.is_dir():
            continue
        why = slim_status(cand)
        if why is not None:
            lines.append(f"  skipped trimmed tree {cand}: {why}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    print(f"repo_root: {repo_root()}")
    print(explain())
    for relative in sys.argv[1:]:
        print(f"op_dir({relative}): {op_dir(relative=relative)}")
