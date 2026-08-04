# -*- coding: utf-8 -*-
"""What the engine is told about an operator, and how it reads a run's output.

The engine used to know an operator by having its names compiled in: a
distribution, a path under the ops tree, nineteen field names, three
intermediates, the shape of the line the tiling logs them on. None of that is
knowledge about replaying; it is knowledge about FlashAttentionScoreGrad, and
a second operator could only be added by editing the engine.

Here it is data. The two files a manifest points at are the whole of what an
operator gets to say, and the engine reads slots -- a dimension, a state, a
series, a refusal -- without knowing what fills them.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

#: Where operator packages live, relative to the repository root.
OPERATORS_DIR = "operators"

#: The four slots a log line can fill. `dim` is a value the tiling decided,
#: `state` an intermediate behind one, `series` a per-sample record, and the
#: refusal is handled apart because there is at most one.
SLOT_DIM = "dim"
SLOT_STATE = "state"
SLOT_SERIES = "series"
SLOTS = (SLOT_DIM, SLOT_STATE, SLOT_SERIES)


class ManifestError(Exception):
    """A manifest that cannot be honoured, said in terms of what to fix."""


@dataclass(frozen=True)
class Scrape:
    """One pattern that lifts values out of the operator's own log lines.

    Every scrape names the slot it fills. When the driver learns to print
    that slot directly the scrape is deleted and nothing downstream moves.
    """

    into: str
    when: tuple[str, ...]
    pairs: re.Pattern[str] | None = None
    fields: frozenset[str] = frozenset()
    each: re.Pattern[str] | None = None
    name: str = ""

    def matches(self, line: str) -> bool:
        return all(needle in line for needle in self.when)


@dataclass(frozen=True)
class LogProtocol:
    """How to turn a run's output into slots."""

    marks: Mapping[str, re.Pattern[str]]
    scrapes: tuple[Scrape, ...]
    reject_when: tuple[str, ...]
    reject_after: str
    reject_limit: int
    report_state: tuple[str, ...]
    #: Every dimension name any scrape can produce, in declaration order.
    #: The wide table's columns come from this, so the order is part of the
    #: contract rather than an implementation detail of a set.
    dim_fields: tuple[str, ...]

    @staticmethod
    def load(path: Path) -> "LogProtocol":
        doc = _read_yaml(path)
        marks = {}
        for name, pattern in (doc.get("marks") or {}).items():
            try:
                marks[name] = re.compile(pattern)
            except re.error as exc:
                raise ManifestError(f"{path}: mark {name!r} is not a regex: {exc}")

        scrapes, dim_fields = [], []
        for i, raw in enumerate(doc.get("scrapes") or []):
            scrape = _scrape(raw, path, i)
            scrapes.append(scrape)
            if scrape.into == SLOT_DIM:
                dim_fields.extend(f for f in (raw.get("fields") or []))

        reject = doc.get("reject") or {}
        return LogProtocol(
            marks=marks,
            scrapes=tuple(scrapes),
            reject_when=tuple(reject.get("when") or []),
            reject_after=str(reject.get("after") or ""),
            reject_limit=int(reject.get("limit") or 160),
            report_state=tuple(doc.get("report_state") or []),
            dim_fields=tuple(dim_fields),
        )


def _scrape(raw: Mapping[str, Any], path: Path, i: int) -> Scrape:
    into = str(raw.get("into") or "")
    if into not in SLOTS:
        raise ManifestError(
            f"{path}: scrape {i} fills {into!r}; expected one of {SLOTS}")
    if into == SLOT_SERIES and not raw.get("each"):
        raise ManifestError(
            f"{path}: scrape {i} fills the series slot and has no `each` "
            f"pattern, so it would record one entry per line and lose the "
            f"per-sample structure that is the point of a series")
    if into != SLOT_SERIES and not raw.get("pairs"):
        raise ManifestError(
            f"{path}: scrape {i} fills {into!r} and has no `pairs` pattern")
    return Scrape(
        into=into,
        when=tuple(raw.get("when") or []),
        pairs=re.compile(raw["pairs"]) if raw.get("pairs") else None,
        fields=frozenset(raw.get("fields") or []),
        each=re.compile(raw["each"]) if raw.get("each") else None,
        name=str(raw.get("name") or ""),
    )


@dataclass(frozen=True)
class OperatorManifest:
    """One operator on one architecture, and how to replay it."""

    name: str
    relative_path: str
    arch: str
    tiling_key_header: str
    host: str
    distro: str
    entry: str
    done_marker: str
    cache: str
    wide_glob: str
    log: LogProtocol
    #: The directory the manifest was read from, so anything else the package
    #: gains later is found beside it rather than by another search.
    package: Path = field(default=Path("."))

    @staticmethod
    def load(path: str | os.PathLike[str]) -> "OperatorManifest":
        """Read a manifest, applying whatever the environment overrides."""
        path = Path(path)
        doc = _read_yaml(path)
        op = doc.get("operator") or {}
        replay = doc.get("replay") or {}
        overrides = replay.get("overrides") or {}
        artifacts = doc.get("artifacts") or {}

        def pick(key: str, value: Any) -> Any:
            var = overrides.get(key)
            return os.environ.get(var) or value if var else value

        name = _need(op, "name", path)
        arch = _need(op, "arch", path)
        header = str(_need(doc.get("sources") or {}, "tiling_key_header", path))
        log_name = str(doc.get("log_protocol") or "log_protocol.yaml")

        return OperatorManifest(
            name=name,
            relative_path=str(_need(op, "path", path)),
            arch=arch,
            tiling_key_header=str(
                pick("tiling_key_header", header.format(op=name, arch=arch))),
            host=str(replay.get("host") or "wsl"),
            distro=str(pick("distro", replay.get("distro") or "")),
            entry=str(pick("entry", replay.get("entry") or "")),
            # No default: what the driver prints when it is finished is a
            # property of that driver, and guessing it would turn a run that
            # died halfway into one that looks merely empty.
            done_marker=str(_need(replay, "done_marker", path)),
            cache=str(artifacts.get("cache") or "tg/replay"),
            wide_glob=str(artifacts.get("wide_glob") or "*key_cases*.csv"),
            log=LogProtocol.load(path.parent / log_name),
            package=path.parent,
        )


def _need(doc: Mapping[str, Any], key: str, path: Path) -> Any:
    if key not in doc or doc[key] in (None, ""):
        raise ManifestError(f"{path}: missing required key {key!r}")
    return doc[key]


def _read_yaml(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise ManifestError(f"no manifest at {path}")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, Mapping):
        raise ManifestError(f"{path}: expected a mapping at the top level")
    return doc


def discover(root: Path, operator: str, arch: str) -> Path:
    """Where a named operator's manifest should be."""
    return root / OPERATORS_DIR / operator / arch / "operator.yaml"


def available(root: Path) -> list[tuple[str, str]]:
    """Every operator package present, as (operator, arch) pairs.

    Names starting with ``_`` are reserved for synthetic / test fixtures and
    are only selected when ``UO_OPERATOR`` is set explicitly.
    """
    base = root / OPERATORS_DIR
    if not base.is_dir():
        return []
    out = []
    for manifest in sorted(base.glob("*/*/operator.yaml")):
        op = manifest.parent.parent.name
        if op.startswith("_"):
            continue
        out.append((op, manifest.parent.name))
    return out


def slots_of(protocol: LogProtocol, lines: Iterable[str]) -> dict[str, Any]:
    """Everything the protocol recognises in one case's worth of output.

    Returned as three dictionaries rather than one so a caller can tell a
    dimension the tiling decided from an intermediate behind it, without
    consulting a list of which names are which.
    """
    dims: dict[str, int] = {}
    state: dict[str, int] = {}
    series: dict[str, list[dict[str, int]]] = {}
    reject = ""

    for line in lines:
        for scrape in protocol.scrapes:
            if not scrape.matches(line):
                continue
            if scrape.into == SLOT_SERIES:
                assert scrape.each is not None
                found = [
                    {k: int(v) for k, v in m.groupdict().items()}
                    for m in scrape.each.finditer(line)
                ]
                if found:
                    series.setdefault(scrape.name, []).extend(found)
                continue
            assert scrape.pairs is not None
            got = {k: int(v) for k, v in scrape.pairs.findall(line)
                   if not scrape.fields or k in scrape.fields}
            (dims if scrape.into == SLOT_DIM else state).update(got)
        if not reject and protocol.reject_when and \
                all(needle in line for needle in protocol.reject_when):
            text = line.split(protocol.reject_after)[-1] \
                if protocol.reject_after else line
            reject = text.strip()[:protocol.reject_limit]

    return {"dim": dims, "state": state, "series": series, "reject": reject}
