# -*- coding: utf-8 -*-
"""TilingData field domain probe + static over-approx coverage.

Production consumes ``views/tilingdata.yaml`` from the finalized ``.uo``.
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

DOC_NOTE = (
    "TilingData R requires scrape/dump capability in log_protocol or driver. "
    "Without it, coverage is static over-approx from writers×witness keys; "
    "over_approximated=true and fields are never excluded into E."
)
_VALUE_PREFIXES = ("", "log_", "state_", "td_", "tilingdata_")
_STATE_LINE = re.compile(r"^###STATE\s+(?P<name>\w+)\s*=\s*(?P<value>-?\d+)")


def _arch() -> str:
    for _name in ("UO_ARCH", "ASCENDC_ARCH"):
        _raw = (os.environ.get(_name) or "").strip()
        if _raw:
            return _raw
    raise ValueError("ARCHITECTURE_MISSING_IN_RUN_STATE: architecture required")


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return doc if isinstance(doc, dict) else {}


def load_tilingdata_view(ws: W.Workspace | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    ws = (ws or W.default_workspace()).ensure()
    try:
        from testcase_agent import product_uo
        p = product_uo.product(ws.root, architecture=_arch())
        doc = product_uo.view(ws.root, "views/tilingdata.yaml", architecture=_arch())
        if isinstance(doc, dict) and doc:
            return doc, {"kind": "uo", "path": str(p), "view": "views/tilingdata.yaml"}
    except Exception as exc:
        product_error = f"uo_product:{type(exc).__name__}:{exc}"[:180]
    else:
        product_error = "views/tilingdata.yaml missing from .uo"
    return {}, {"kind": "missing", "path": "", "reason": product_error}


def probe_scrape_capability(ws: W.Workspace | None = None) -> dict[str, Any]:
    ws = (ws or W.default_workspace()).ensure()
    capable = False
    reasons: list[str] = []
    try:
        from replay.package_data import resolve_adapter_file, package_file
        path = resolve_adapter_file("log_protocol.yaml") or package_file("log_protocol.yaml")
        protocol = _load_yaml(path)
    except Exception as exc:
        reasons.append(f"log_protocol_unavailable:{exc}"); protocol = {}
    for scrape in list(protocol.get("scrapes") or []):
        into = str(scrape.get("into") or "").lower()
        when = " ".join(str(x) for x in (scrape.get("when") or [])).lower()
        if "tilingdata" in into or "tiling_data" in into or "tilingdata" in when:
            capable = True; reasons.append("scrape_rule_tilingdata")
    for name in dict(protocol.get("marks") or {}):
        if "tilingdata" in str(name).lower() or "tiling_data" in str(name).lower():
            capable = True; reasons.append(f"mark:{name}")
    try:
        from replay.package_data import resolve_adapter_file, package_file
        man_path = resolve_adapter_file("operator.yaml") or package_file("operator.yaml")
        man = _load_yaml(man_path)
        caps = man.get("capabilities") or man.get("closure") or {}
        if isinstance(caps, dict) and caps.get("tilingdata_scrape"):
            capable = True; reasons.append("operator.yaml:capabilities.tilingdata_scrape")
    except Exception:
        pass
    if not capable and not reasons:
        reasons.append("no_tilingdata_scrape_rule")
    return {"capable": capable, "over_approximated": not capable, "reasons": reasons, "note": DOC_NOTE}


def observed_values(ws: W.Workspace | None = None) -> dict[str, set[str]]:
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
            name = str(col); base = name
            for prefix in _VALUE_PREFIXES:
                if prefix and name.startswith(prefix):
                    base = name[len(prefix):]; break
            if not base or base.startswith("_"):
                continue
            values = {str(v).strip() for v in frame[col].tolist() if str(v).strip() not in {"", "nan", "None"}}
            if values:
                out.setdefault(base, set()).update(values)
    return out


def writer_keys(field: dict[str, Any], keys: list[int]) -> tuple[list[int], bool]:
    from testcase_agent.closure import finite_predicate as FP
    from testcase_agent.closure import kernel_domain as KD
    writers = [w for w in (field.get("writers") or []) if isinstance(w, dict)]
    if not writers:
        return [], False
    hits: set[int] = set(); approximated = False
    for writer in writers:
        guard = writer.get("finite_predicate") or writer.get("predicate")
        dims = list(writer.get("dimensions") or [])
        if not guard and not dims:
            approximated = True; hits.update(keys); continue
        for k in keys:
            try:
                inst = W.decode(int(k))
            except Exception:
                continue
            ev = KD.evaluate_branch({**writer, "dimensions": dims}, inst)
            if ev.result is FP.Truth.TRUE:
                hits.add(int(k))
            elif ev.result in (FP.Truth.UNSUPPORTED, FP.Truth.UNKNOWN):
                approximated = True; hits.add(int(k))
    return sorted(hits), approximated


def load_tilingdata_fields(uo: Path | None = None, *, ws: W.Workspace | None = None) -> list[dict[str, Any]]:
    del uo
    doc, _ = load_tilingdata_view(ws)
    fields: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for st in doc.get("structs") or []:
        if not isinstance(st, dict):
            continue
        for fld in st.get("fields") or []:
            if isinstance(fld, dict):
                row = dict(fld); row["_struct"] = st.get("name")
                fields.append(row); seen.add((str(st.get("name") or ""), str(row.get("name") or "")))
    defects = doc.get("defects") or {}
    if isinstance(defects, dict):
        by_name = {str(f.get("name") or ""): f for f in fields}
        for kind in ("no_writer", "no_reader"):
            for name in defects.get(kind) or []:
                s = str(name)
                if s in by_name:
                    by_name[s].setdefault("closure", {})["defect"] = kind
                    continue
                fields.append({"name": s, "closure": {"defect": kind, "status": "defect"}, "writers": [], "readers": []})
    return fields


def compute_tilingdata_coverage(ws: W.Workspace | None = None, *, write: bool = True) -> dict[str, Any]:
    ws = (ws or W.default_workspace()).ensure()
    probe = probe_scrape_capability(ws)
    _, source = load_tilingdata_view(ws)
    fields = load_tilingdata_fields(ws=ws)
    Rset = ledger.load_R(ws)
    rows: list[list[Any]] = []; field_summaries: list[dict[str, Any]] = []; defects: list[dict[str, Any]] = []; fields_by_key: dict[int, list[str]] = {}
    keys = sorted(Rset); observed = observed_values(ws) if probe["capable"] else {}
    for fld in fields:
        name = str(fld.get("name") or ""); writers = list(fld.get("writers") or []); readers = list(fld.get("readers") or []); closure = dict(fld.get("closure") or {})
        defect = closure.get("defect")
        if not defect:
            if not writers and readers: defect = "no_writer"
            elif writers and not readers: defect = "no_reader"
        hits, approximated = writer_keys(fld, keys)
        if probe["capable"] and name in observed:
            status = "observed"; r_count = len(observed[name]); approximated = False
        elif probe["capable"]:
            status = "scrape_capable_no_observation"; r_count = 0
        elif hits:
            status = "over_approx_witnessed"; r_count = len(hits)
        elif writers:
            status = "has_writer_no_R"; r_count = 0
        else:
            status = "no_writer"; r_count = 0
        for k in hits:
            fields_by_key.setdefault(int(k), []).append(name)
        if defect:
            defects.append({"field": name, "defect": defect})
        approx = bool(probe["over_approximated"] or approximated)
        field_summaries.append({"name": name, "struct": fld.get("_struct"), "status": status, "R_count": r_count, "writers": len(writers), "readers": len(readers), "defect": defect, "observed_values": sorted(observed.get(name, []))[:20] or None, "over_approximated": approx, "exclude": False})
        rows.append([name, fld.get("_struct") or "", status, r_count, len(writers), len(readers), defect or "", approx, ";".join(str(v) for v in sorted(observed.get(name, []))[:20])])
    path = ""
    if write:
        path = str(ws.report("tilingdata_coverage.csv"))
        with open(path, "w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh); w.writerow(["field", "struct", "status", "R_count", "writers", "readers", "defect", "over_approximated", "observed_values"]); w.writerows(rows)
    any_approx = any(bool(f.get("over_approximated")) for f in field_summaries)
    return {"ok": True, "source": source, "established": source.get("kind") not in {None, "", "missing"}, "probe": probe, "fields": len(fields), "defects": defects, "tilingdata_fields": field_summaries, "observed_fields": sorted(observed), "fields_by_key": {k: sorted(v) for k, v in fields_by_key.items()}, "over_approximated": bool(probe["over_approximated"] or any_approx), "path": path, "note": DOC_NOTE}
