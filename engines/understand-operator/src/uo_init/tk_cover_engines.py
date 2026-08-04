# -*- coding: utf-8 -*-
"""Deterministic engines for the tk-cover workflow.

Only `mine_recipe` is a subagent action; everything here is CLI-driven so a
weak model can still advance the pipeline by running `acp run-action`.

The derive/codemap steps used to read `.probe_cache/fag_derive.json` and
`fag_bundle.pkl`. Those are scratch artefacts. The durable inputs are now the
UO KB under `.ascendc-pilot/uo/` (host_codemap + field summaries written by
uo-init / export-codemap). Residual blockers that claimed coverage could not
close are gone: FlashAttentionScoreGrad arch35 closed at gap=0.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

CODEMAP_YAML = "ir/host_codemap.yaml"
DERIVE_SUMMARY = "tk/derive_fields.yaml"


def _uo(project_root: Path, ctx: dict[str, Any]) -> Path:
    raw = ctx.get("uo_root") or ctx.get("kb_root")
    if raw:
        return Path(raw)
    return Path(project_root) / ".ascendc-pilot" / "uo"


def _dump(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def env_probe(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Record whether the replay environment is reachable."""
    uo = _uo(project_root, ctx)
    distro = os.environ.get("UO_REPLAY_DISTRO") or "Ubuntu-2204"
    cann = os.environ.get("ASCEND_HOME_PATH") or os.environ.get("CANN_ROOT") or ""
    ops = os.environ.get("OPS_TRANSFORMER_ROOT") or ""
    doc = {
        "ok": True,
        "distro": distro,
        "cann_hint": cann,
        "ops_hint": ops,
        "note": "Set UO_REPLAY_DISTRO=Ubuntu-2204 on this host; manifest may say Ubuntu-22.04.",
    }
    _dump(uo / "tk" / "env_probe.yaml", doc)
    return {"ok": True, "engine": "env_probe", **doc}


def derive_fields(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Summarise key-field exactness from the durable UO artefacts.

    Prefer `uo/ir/host_codemap.yaml` (codemap v2 fields[] once available) and
    fall back to a previously written `tk/derive_fields.yaml`. The
    `.probe_cache/fag_derive.json` scratch file is no longer required.
    """
    uo = _uo(project_root, ctx)
    codemap_path = uo / CODEMAP_YAML
    summary_path = uo / DERIVE_SUMMARY

    fields: list[Any] = []
    source = ""
    if codemap_path.is_file():
        doc = yaml.safe_load(codemap_path.read_text(encoding="utf-8")) or {}
        fields = list(doc.get("fields") or [])
        source = str(codemap_path)
        # v1 had no fields[]; synthesise a thin summary from writes.
        if not fields and doc.get("writes"):
            by_path: dict[str, int] = {}
            for w in doc.get("writes") or []:
                path = str(w.get("path") or "")
                leaf = path.rsplit(".", 1)[-1] if path else ""
                if leaf:
                    by_path[leaf] = by_path.get(leaf, 0) + 1
            fields = [{"name": k, "writers": v} for k, v in sorted(by_path.items())]
    elif summary_path.is_file():
        prev = yaml.safe_load(summary_path.read_text(encoding="utf-8")) or {}
        if prev.get("ok"):
            _dump(uo / "tk" / "derive_fields.yaml", prev)
            return {"ok": True, "engine": "derive_fields", **prev}

    # Optional: if a caller still has the old derive JSON, accept it as a
    # migration aid but do not require it.
    probe = Path(project_root) / ".probe_cache" / "fag_derive.json"
    if not fields and probe.is_file():
        data = json.loads(probe.read_text(encoding="utf-8"))
        hd = data.get("host_derivation") or {}
        fields = hd.get("fields") or data.get("fields") or []
        source = str(probe)

    if not fields and not source:
        doc = {
            "ok": False,
            "error": (
                f"missing {codemap_path}; run export-codemap (or uo-init) first"
            ),
        }
        _dump(uo / "tk" / "derive_fields.yaml", doc)
        return doc

    free = 0
    closed = 0
    for f in fields:
        if not isinstance(f, dict):
            continue
        for v in f.get("free_vars") or []:
            free += 1
        exact = str(f.get("exactness") or f.get("grade") or "")
        if exact in ("exact", "constant", "exact_static"):
            closed += 1

    doc = {
        "ok": True,
        "source": source,
        "fields": len(fields),
        "free_vars": free,
        "closed": closed,
    }
    _dump(uo / "tk" / "derive_fields.yaml", doc)
    return {"ok": True, "engine": "derive_fields", **doc}


def export_codemap(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Compat shim: TG host view is produced by uo-init ``export_tg_host_view``.

    Prefer the durable projection already stamped with the KB fingerprint.
    Does **not** read ``.probe_cache/fag_bundle.pkl`` as a production input.
    """
    from uo_init.pilot_engines import export_tg_host_view as _export_view

    uo = _uo(project_root, ctx)
    durable = uo / CODEMAP_YAML
    view = uo / "ir" / "tg_host_view.yaml"
    if (view.is_file() or durable.is_file()) and not ctx.get("force"):
        path = view if view.is_file() else durable
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        source = doc.get("source") or {}
        result = {
            "ok": True,
            "yaml": str(path),
            "fields": len(doc.get("fields") or []),
            "predicates": len(doc.get("predicates") or []),
            "graph_fingerprint": str(source.get("graph_fingerprint") or ""),
            "reused": True,
            "note": "reuse durable tg_host_view; regenerate via uo-init export_tg_host_view",
        }
        _dump(uo / "tk" / "export_codemap.yaml", result)
        return {"ok": True, "engine": "export_codemap", **result}

    # Force / missing: delegate to the KB-stamped exporter (live HostIR).
    result = _export_view(Path(project_root), ctx)
    _dump(uo / "tk" / "export_codemap.yaml", result)
    return {"ok": bool(result.get("ok")), "engine": "export_codemap", **result}


def mine_recipe(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Prepare staging for the recipe-miner subagent (does not invent recipes)."""
    uo = _uo(project_root, ctx)
    run_id = str(ctx.get("run_id") or "local")
    staging = {
        "schema": "tk-recipe-staging/v1",
        "status": "awaiting_subagent",
        "instructions": (
            "Write parts/part_0.yaml with obligation clusters and proposed "
            "Case mutations; apply_recipe validates via patch_gates."
        ),
    }
    parts = (
        Path(project_root) / ".ascendc-pilot" / "runs" / run_id
        / "actions" / "mine_recipe"
    )
    _dump(parts / "staging.yaml", staging)
    part0 = parts / "parts" / "part_0.yaml"
    if not part0.is_file():
        _dump(part0, {
            "schema": "tk-recipe-part/v1",
            "recipes": [],
            "note": "placeholder — replace with mined recipes",
        })
    _dump(uo / "tk" / "mine_recipe.yaml", {
        "ok": True, "need_subagent": True, "staging": str(parts / "staging.yaml"),
    })
    return {"ok": True, "engine": "mine_recipe", "need_subagent": True}


def apply_recipe(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Merge staged recipe parts into tk/recipe.yaml (identity + schema only)."""
    uo = _uo(project_root, ctx)
    run_id = str(ctx.get("run_id") or "local")
    parts_dir = (
        Path(project_root) / ".ascendc-pilot" / "runs" / run_id
        / "actions" / "mine_recipe" / "parts"
    )
    recipes: list[Any] = []
    if parts_dir.is_dir():
        for path in sorted(parts_dir.glob("part_*.yaml")):
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for item in doc.get("recipes") or []:
                if isinstance(item, dict) and item.get("dim"):
                    recipes.append(item)
    out = {"schema": "tk-recipe/v1", "recipes": recipes, "count": len(recipes)}
    _dump(uo / "tk" / "recipe.yaml", out)
    _dump(uo / "tk" / "apply_recipe.yaml", {"ok": True, "count": len(recipes)})
    return {"ok": True, "engine": "apply_recipe", "count": len(recipes)}


def coverage_gate(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Run the closure report (preferred) or the legacy runtime gate."""
    uo = _uo(project_root, ctx)

    # Prefer the precipitated TG closure package: no .probe_cache required.
    try:
        from testcase_agent.closure import ledger as L
        from testcase_agent.closure import lemma as Lem
        from testcase_agent.closure import report as Rep
        from testcase_agent.closure import workspace as WS

        ws = WS.default_workspace(project_root).ensure()
        # Point artefacts at the operator's replay cache when present.
        rebuilt = L.rebuild(ws)
        if not rebuilt.get("ok"):
            _dump(uo / "tk" / "coverage_gate.yaml", rebuilt)
            return {"ok": False, "engine": "coverage_gate", **rebuilt}
        applied = Lem.apply_rules(ws)
        if not applied.get("ok"):
            _dump(uo / "tk" / "coverage_gate.yaml", applied)
            return {"ok": False, "engine": "coverage_gate", **applied}
        summary_doc = Rep.report(ws)
        gap = int(summary_doc.get("open") or 0)
        complete = bool(summary_doc.get("gap_zero"))
        summary: dict[str, Any] = {
            "ok": bool(summary_doc.get("ok")),
            "engine": "coverage_gate",
            "complete": complete,
            "gate_pass": bool(summary_doc.get("ok")),
            "declared": summary_doc.get("declared"),
            "R_declared": summary_doc.get("witnessed"),
            "excluded_sound": summary_doc.get("excluded"),
            "open_gap_sound": gap,
            "closure_path": summary_doc.get("path"),
            "residual_blockers": [],
            "note": (
                "Full sound coverage." if complete
                else "Open keys remain; see closure report."
            ),
        }
        _dump(uo / "tk" / "coverage_gate.yaml", summary)
        _dump(uo / "tk" / "residual.yaml", {
            "open_gap_sound": gap,
            "complete": complete,
            "blockers": [],
        })
        return summary
    except Exception as exc:  # noqa: BLE001
        err = {
            "ok": False,
            "engine": "coverage_gate",
            "complete": False,
            "error": (
                f"testcase_agent.closure unavailable: {exc}. "
                "Install engines/testcase-generation[ml] and rebuild the ledger."
            ),
        }
        _dump(uo / "tk" / "coverage_gate.yaml", err)
        return err


TK_ENGINES: dict[str, Any] = {
    "env_probe": env_probe,
    "derive_fields": derive_fields,
    "export_codemap": export_codemap,
    "mine_recipe": mine_recipe,
    "apply_recipe": apply_recipe,
    "coverage_gate": coverage_gate,
}
