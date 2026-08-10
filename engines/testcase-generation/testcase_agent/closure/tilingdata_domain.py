# -*- coding: utf-8 -*-
"""TilingData field domain probe + static over-approx coverage.

When log_protocol / driver cannot scrape tiling-data dumps, coverage is a
static over-approximation from writers vs witness keys (``over_approximated=
true``) and must **never** exclude. Defects ``no_writer`` / ``no_reader`` come
from UO ``views/tilingdata.yaml``.
"""
from __future__ import annotations

import csv
import os
import re
from pathlib import Path
from typing import Any

import yaml

from testcase_agent.closure import ledger
from testcase_agent.closure import workspace as W

# Short note embedded in reports / receipt for operators.
DOC_NOTE = (
    "TilingData R requires scrape/dump capability in log_protocol or driver. "
    "Without it, coverage is static over-approx from writers×witness keys; "
    "over_approximated=true and fields are never excluded into E."
)


def _uo_root(ws: W.Workspace) -> Path | None:
    arch = (os.environ.get("UO_ARCH") or os.environ.get("ASCENDC_ARCH") or "arch35").strip()
    try:
        from ascendc_pilot.paths import uo_root

        return uo_root(ws.root, arch=arch)
    except Exception:
        cand = ws.root / ".ascendc-pilot" / arch / "uo"
        return cand if cand.is_dir() else None


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return doc if isinstance(doc, dict) else {}


def probe_scrape_capability(ws: W.Workspace | None = None) -> dict[str, Any]:
    """Check whether log_protocol / manifest can scrape tiling data dumps."""
    ws = (ws or W.default_workspace()).ensure()
    capable = False
    reasons: list[str] = []
    protocol: dict[str, Any] = {}
    try:
        from replay.package_data import resolve_adapter_file, package_file

        path = resolve_adapter_file("log_protocol.yaml") or package_file("log_protocol.yaml")
        protocol = _load_yaml(path)
    except Exception as exc:  # noqa: BLE001
        reasons.append(f"log_protocol_unavailable:{exc}")
        protocol = {}

    scrapes = list(protocol.get("scrapes") or [])
    marks = dict(protocol.get("marks") or {})
    # Capability signals: explicit tilingdata scrape, or dump-oriented marks.
    for scrape in scrapes:
        into = str(scrape.get("into") or "").lower()
        when = " ".join(str(x) for x in (scrape.get("when") or [])).lower()
        if "tilingdata" in into or "tiling_data" in into or "tilingdata" in when:
            capable = True
            reasons.append("scrape_rule_tilingdata")
    for name in marks:
        if "tilingdata" in str(name).lower() or "tiling_data" in str(name).lower():
            capable = True
            reasons.append(f"mark:{name}")
    # Manifest capability flag (optional).
    try:
        from replay.package_data import resolve_adapter_file, package_file

        man_path = resolve_adapter_file("operator.yaml") or package_file("operator.yaml")
        man = _load_yaml(man_path)
        caps = man.get("capabilities") or man.get("closure") or {}
        if isinstance(caps, dict) and caps.get("tilingdata_scrape"):
            capable = True
            reasons.append("operator.yaml:capabilities.tilingdata_scrape")
    except Exception:
        pass

    if not capable and not reasons:
        reasons.append("no_tilingdata_scrape_rule")

    return {
        "capable": capable,
        "over_approximated": not capable,
        "reasons": reasons,
        "note": DOC_NOTE,
    }


#: Column / mark spellings a scraped field value may arrive under.
_VALUE_PREFIXES = ("", "log_", "state_", "td_", "tilingdata_")

_STATE_LINE = re.compile(r"^###STATE\s+(?P<name>\w+)\s*=\s*(?P<value>-?\d+)")


def observed_values(ws: W.Workspace | None = None) -> dict[str, set[str]]:
    """Field → the values a real run actually reported.

    Two sources, unioned: ``###STATE name=value`` lines the driver printed, and
    per-field columns in the wide corpus. Only rows the driver accepted count —
    a value read off a rejected case is not an observation of anything.

    Empty when the driver never dumped tiling data; callers must then fall back
    to the static over-approximation rather than treat "no values" as "no
    coverage".
    """
    ws = (ws or W.default_workspace()).ensure()
    out: dict[str, set[str]] = {}

    for path in sorted(Path(ws.artifacts).glob("*_log.txt")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            m = _STATE_LINE.match(line.strip())
            if m:
                out.setdefault(m.group("name"), set()).add(m.group("value"))

    try:
        from testcase_agent.closure import corpus as C

        df = C.load(ws)
    except Exception:
        df = None
    if df is not None and not df.empty:
        frame = df[df.get("ok") == 1] if "ok" in df.columns else df
        for col in frame.columns:
            name = str(col)
            base = name
            for prefix in _VALUE_PREFIXES:
                if prefix and name.startswith(prefix):
                    base = name[len(prefix):]
                    break
            if not base or base.startswith("_"):
                continue
            values = {
                str(v).strip()
                for v in frame[col].tolist()
                if str(v).strip() not in {"", "nan", "None"}
            }
            if values:
                out.setdefault(base, set()).update(values)
    return out


def writer_keys(field: dict[str, Any], keys: list[int]) -> tuple[list[int], bool]:
    """Which witness keys can reach a writer of this field.

    A writer whose guard names key dimensions is evaluated on each key with the
    same four-valued evaluator the kernel domain uses. A writer with no readable
    guard is taken to apply to every key — an over-approximation, reported as
    one, never used to exclude.
    """
    from testcase_agent.closure import finite_predicate as FP
    from testcase_agent.closure import kernel_domain as KD

    writers = [w for w in (field.get("writers") or []) if isinstance(w, dict)]
    if not writers:
        return [], False
    hits: set[int] = set()
    approximated = False
    for writer in writers:
        guard = writer.get("finite_predicate") or writer.get("predicate")
        dims = list(writer.get("dimensions") or [])
        if not guard and not dims:
            approximated = True
            hits.update(keys)
            continue
        for k in keys:
            try:
                inst = W.decode(int(k))
            except Exception:
                continue
            ev = KD.evaluate_branch({**writer, "dimensions": dims}, inst)
            if ev.result is FP.Truth.TRUE:
                hits.add(int(k))
            elif ev.result in (FP.Truth.UNSUPPORTED, FP.Truth.UNKNOWN):
                approximated = True
                hits.add(int(k))
    return sorted(hits), approximated


def _load_tilingdata_doc(uo: Path) -> dict[str, Any]:
    """YAML on disk first, then the DB view blob (DB is the product authority)."""
    doc = _load_yaml(uo / "views" / "tilingdata.yaml")
    if doc:
        return doc
    db = uo / "indexes" / "kb_graph.sqlite"
    if db.is_file():
        try:
            from uo_init.kb_index import load_view_blob

            blob = load_view_blob(db, "views/tilingdata.yaml")
            if isinstance(blob, dict) and blob:
                return blob
        except Exception:
            pass
    return {}


def load_tilingdata_fields(uo: Path | None) -> list[dict[str, Any]]:
    if uo is None:
        return []
    doc = _load_tilingdata_doc(uo)
    fields: list[dict[str, Any]] = []
    for st in doc.get("structs") or []:
        for fld in st.get("fields") or []:
            if isinstance(fld, dict):
                row = dict(fld)
                row["_struct"] = st.get("name")
                fields.append(row)
    # Defects map may list fields without structs.
    defects = doc.get("defects") or {}
    if isinstance(defects, dict):
        for kind in ("no_writer", "no_reader"):
            for name in defects.get(kind) or []:
                fields.append({
                    "name": name,
                    "closure": {"defect": kind, "status": "defect"},
                    "writers": [],
                    "readers": [],
                })
    return fields


def compute_tilingdata_coverage(
    ws: W.Workspace | None = None,
    *,
    write: bool = True,
) -> dict[str, Any]:
    """Static over-approx coverage + defect report. Never writes E exclusions."""
    ws = (ws or W.default_workspace()).ensure()
    probe = probe_scrape_capability(ws)
    uo = _uo_root(ws)
    from testcase_agent.closure.kernel_domain import view_source

    source = view_source(uo, "views/tilingdata.yaml")
    fields = load_tilingdata_fields(uo)
    Rset = ledger.load_R(ws)
    rows: list[list[Any]] = []
    field_summaries: list[dict[str, Any]] = []
    defects: list[dict[str, Any]] = []
    fields_by_key: dict[int, list[str]] = {}
    keys = sorted(Rset)
    observed = observed_values(ws) if probe["capable"] else {}

    for fld in fields:
        name = str(fld.get("name") or "")
        writers = list(fld.get("writers") or [])
        readers = list(fld.get("readers") or [])
        closure = dict(fld.get("closure") or {})
        defect = closure.get("defect")
        if not defect:
            if not writers and readers:
                defect = "no_writer"
            elif writers and not readers:
                defect = "no_reader"

        hits, approximated = writer_keys(fld, keys)
        if probe["capable"] and name in observed:
            # Real-machine口径: the values the driver actually dumped.
            status = "observed"
            r_count = len(observed[name])
            approximated = False
        elif probe["capable"]:
            status = "scrape_capable_no_observation"
            r_count = 0
        elif hits:
            status = "over_approx_witnessed"
            r_count = len(hits)
        elif writers:
            status = "has_writer_no_R"
            r_count = 0
        else:
            status = "no_writer"
            r_count = 0
        for k in hits:
            fields_by_key.setdefault(int(k), []).append(name)
        if defect:
            defects.append({"field": name, "defect": defect})
        field_summaries.append({
            "name": name,
            "struct": fld.get("_struct"),
            "status": status,
            "R_count": r_count,
            "writers": len(writers),
            "readers": len(readers),
            "defect": defect,
            "observed_values": sorted(observed.get(name, []))[:20] or None,
            "over_approximated": bool(probe["over_approximated"] or approximated),
            "exclude": False,  # never exclude
        })
        rows.append([
            name, fld.get("_struct") or "", status, r_count,
            len(writers), len(readers), defect or "",
            bool(probe["over_approximated"] or approximated),
            ";".join(str(v) for v in sorted(observed.get(name, []))[:20]),
        ])

    path = ""
    if write:
        path = str(ws.report("tilingdata_coverage.csv"))
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow([
                "field", "struct", "status", "R_count", "writers", "readers",
                "defect", "over_approximated", "observed_values",
            ])
            w.writerows(rows)
        note_path = ws.report("tilingdata_domain_note.txt")
        Path(note_path).write_text(DOC_NOTE + "\n", encoding="utf-8")

    any_approx = any(bool(f.get("over_approximated")) for f in field_summaries)
    return {
        "ok": True,
        "source": source,
        # False means "no input", not "this operator has no tiling data".
        "established": source.get("kind") != "missing",
        "probe": probe,
        "fields": len(fields),
        "defects": defects,
        "tilingdata_fields": field_summaries,
        "observed_fields": sorted(observed),
        # key → fields a writer can reach under it, for the closure rows.
        "fields_by_key": {k: sorted(v) for k, v in fields_by_key.items()},
        "over_approximated": bool(probe["over_approximated"] or any_approx),
        "path": path,
        "note": DOC_NOTE,
    }
