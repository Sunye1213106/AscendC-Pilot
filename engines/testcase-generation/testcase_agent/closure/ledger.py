# -*- coding: utf-8 -*-
"""The one place R is computed, from every artefact that records a real run.

A key is in R when some real host run produced it. Nothing else counts, and in
particular nothing a model predicted counts.

No single artefact is complete, so all of them are unioned:

  logs      `###DONE` lines, the driver's own word, but a batch that reuses a
            tag overwrites the previous batch's log
  wide      the accumulated wide tables, complete but historically mis-quoted
  results   per-arm result files a directed search wrote
  carry     whatever a previous ledger run established

Recomputing from raw artefacts rather than trusting a carried number is not
ceremony: the first time this was done it found 150 keys a previous ledger had
already produced but never counted, at no machine cost.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from testcase_agent.closure import workspace as W

DONE = re.compile(r"^###DONE (?P<cid>\S+) ok=(?P<ok>\d+) key=(?P<key>\d+)")


def from_logs(ws: W.Workspace) -> dict[int, str]:
    """Keys the driver itself reported, with the batch and case that did."""
    out: dict[int, str] = {}
    for path in sorted(Path(ws.artifacts).glob("*_log.txt")):
        src = path.name[: -len("_log.txt")]
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.startswith("###DONE"):
                    continue
                m = DONE.match(line)
                if m and m.group("ok") == "1":
                    key = int(m.group("key"))
                    if key:
                        out.setdefault(key, f"{src}:{m.group('cid')}")
    return out


def from_wide(ws: W.Workspace) -> dict[int, str]:
    """Keys from the wide tables, with the tag-split repair applied."""
    out: dict[int, str] = {}
    for path in sorted(Path(ws.artifacts).glob(W.WIDE_GLOB)):
        src = path.stem
        with open(path, encoding="utf-8", newline="") as fh:
            rows = list(csv.reader(fh))
        if not rows:
            continue
        head = rows[0]
        n = len(head)
        try:
            i_tag = head.index("tag")
            i_ok = head.index("ok")
            i_key = head.index("tiling_key")
        except ValueError:
            continue
        for r in rows[1:]:
            extra = len(r) - n
            if extra > 0:
                r = (r[:i_tag] + [",".join(r[i_tag:i_tag + 1 + extra])]
                     + r[i_tag + 1 + extra:])
            elif extra < 0:
                continue
            if r[i_ok] != "1" or not r[i_key].isdigit():
                continue
            key = int(r[i_key])
            if key:
                out.setdefault(key, f"{src}:{r[0]}")
    return out


def from_results(ws: W.Workspace) -> dict[int, str]:
    """Per-arm result files a directed search wrote."""
    out: dict[int, str] = {}
    for path in sorted(Path(ws.state).glob("*_result.csv")):
        src = path.stem
        with open(path, encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if row.get("ok") != "1":
                    continue
                actual = str(row.get("actual_key", ""))
                if actual.isdigit() and int(actual):
                    out.setdefault(int(actual), f"{src}:{row.get('case_id', '')}")
    return out


def carried(ws: W.Workspace) -> dict[int, str]:
    """R as a previous run recorded it."""
    out: dict[int, str] = {}
    if not ws.r_path.is_file():
        return out
    for line in ws.r_path.read_text(encoding="utf-8").splitlines():
        head = line.strip().split(",", 1)
        if head and head[0].isdigit():
            out.setdefault(int(head[0]), head[1] if len(head) > 1 else "carried")
    return out


def build(ws: W.Workspace | None = None) -> dict[int, str]:
    """R with provenance, unioned over every artefact that records a real run."""
    ws = ws or W.default_workspace()
    out: dict[int, str] = {}
    for source in (carried(ws), from_logs(ws), from_wide(ws), from_results(ws)):
        for key, why in source.items():
            out.setdefault(key, why)
    return out


def load_R(ws: W.Workspace | None = None) -> set[int]:
    """R, from the recorded ledger if there is one, else recomputed."""
    ws = ws or W.default_workspace()
    if not ws.r_path.is_file():
        return set(build(ws))
    return {
        int(line.split(",")[0])
        for line in ws.r_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and line.split(",")[0].strip().isdigit()
    }


def load_E(ws: W.Workspace | None = None) -> set[int]:
    """E_sound, as the last lemma application wrote it."""
    ws = ws or W.default_workspace()
    if not ws.e_path.is_file():
        return set()
    return {
        int(x) for x in ws.e_path.read_text(encoding="utf-8").splitlines()
        if x.strip().isdigit()
    }


def declared() -> set[int]:
    """D, expanded from the kernel's tiling-key header."""
    return set(W.declared())


def state(ws: W.Workspace | None = None) -> dict:
    """The three sets and the gap between them, without writing anything."""
    ws = ws or W.default_workspace()
    R, E, D = load_R(ws), load_E(ws), declared()
    return {
        "declared": len(D),
        "R": len(R),
        "R_declared": len(R & D),
        "undeclared": len(R - D),
        "E": len(E),
        "violation": len(R & E),
        "gap": len(D - (R & D) - E),
    }


def rebuild(ws: W.Workspace | None = None) -> dict:
    """Recompute R from raw artefacts and write the ledger and open set.

    Refuses to write when a key is both witnessed and excluded: that means a
    lemma contradicts a real run, and the run is what gets believed.
    """
    ws = (ws or W.default_workspace()).ensure()
    R = build(ws)
    D, E = declared(), load_E(ws)
    violation = set(R) & E
    if violation:
        return {
            "ok": False,
            "error": "soundness violation: keys are both witnessed and excluded",
            "violating": sorted(violation)[:20],
            "violating_count": len(violation),
        }

    gap = D - (set(R) & D) - E
    ws.r_path.write_text(
        "".join("%d,%s\n" % (k, R[k]) for k in sorted(R)),
        encoding="utf-8", newline="\n")
    ws.open_path.write_text(
        "".join("%d\n" % k for k in sorted(gap)),
        encoding="utf-8", newline="\n")
    return {
        "ok": True,
        "declared": len(D),
        "R": len(R),
        "R_declared": len(set(R) & D),
        "undeclared": len(set(R) - D),
        "E": len(E),
        "gap": len(gap),
        "r_path": str(ws.r_path),
        "open_path": str(ws.open_path),
    }
