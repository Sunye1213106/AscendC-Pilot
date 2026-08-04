# -*- coding: utf-8 -*-
"""Deterministic engines for the tk-cover workflow.

Only `mine_recipe` is a subagent action; everything here is CLI-driven so a
weak model can still advance the pipeline by running `acp run-action`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

# Why U_sound − R cannot yet reach ∅. Composer must not invent exclusions
# to paper over these; they need HostIR / model work first.
RESIDUAL_BLOCKERS: list[dict[str, str]] = [
    {
        "id": "VAR_INIT_bandIdx",
        "symbol": "fBaseParams.bandIdx",
        "why": (
            "guards_cover is sat: reads under sparseMode∈{7,8} do not share "
            "the attenMask write guard; force-closing would be unsound"
        ),
    },
    {
        "id": "VAR_INIT_blockOuter",
        "symbol": "fBaseParams.blockOuter",
        "why": "cyclic dependence with deterSparseType; do not force-close",
    },
    {
        "id": "VAR_LOOPELEM_invalidS1Array",
        "symbol": "invalidS1Array[j]",
        "why": (
            "HostIR writers_of(invalidS1Array)=0; interval_union_covers "
            "cannot attach until array write events exist (float32 Varlen "
            "must stay refused)"
        ),
    },
    {
        "id": "VAR_UNDECIDED_CheckExceedL2Cache",
        "symbol": "CheckExceedL2Cache()",
        "why": "needs an L2 footprint / cardinality model; used for swizzle",
    },
    {
        "id": "VAR_AUX_deterSparseType",
        "symbol": "fBaseParams.deterSparseType",
        "why": "tied to DeterType leaf-collapse demotion; keep overapproximated",
    },
]


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
    """Reuse an existing fag_derive.json; do not re-run Clang in the workflow gate."""
    uo = _uo(project_root, ctx)
    probe = Path(project_root) / ".probe_cache" / "fag_derive.json"
    if not probe.is_file():
        doc = {"ok": False, "error": f"missing {probe}; run scripts/_probe_derive.py --refresh"}
        _dump(uo / "tk" / "derive_fields.yaml", doc)
        return doc
    data = json.loads(probe.read_text(encoding="utf-8"))
    hd = data.get("host_derivation") or {}
    totals = hd.get("totals") or data.get("totals") or {}
    fields = hd.get("fields") or data.get("fields") or []
    free = totals.get("free_vars")
    if free is None:
        # Fall back: unique free_vars across fields.
        seen: set[str] = set()
        for f in fields:
            for v in f.get("free_vars") or []:
                seen.add(str(v))
        free = len(seen)
    closed = totals.get("closed") or totals.get("derived")
    if closed is None:
        closed = sum(1 for f in fields if (f.get("exactness") or "") in ("exact", "constant"))
    doc = {
        "ok": True,
        "source": str(probe),
        "fields": len(fields),
        "free_vars": free,
        "closed": closed,
    }
    _dump(uo / "tk" / "derive_fields.yaml", doc)
    return {"ok": True, "engine": "derive_fields", **doc}


def export_codemap(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    uo = _uo(project_root, ctx)
    bundle = Path(project_root) / ".probe_cache" / "fag_bundle.pkl"
    if not bundle.is_file():
        doc = {"ok": False, "error": f"missing {bundle}"}
        _dump(uo / "tk" / "export_codemap.yaml", doc)
        return doc
    from uo_init.host_codemap import export_codemap_from_bundle

    result = export_codemap_from_bundle(bundle, uo)
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
    # Keep an existing mined part; only seed a placeholder when missing.
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
    """Run the runtime counterexample gate and record residual blockers."""
    uo = _uo(project_root, ctx)
    scripts = Path(project_root) / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    cache = Path(project_root) / ".probe_cache" / "replay"
    closure_path = cache / "coverage_closure.yaml"

    # Prefer invoking the gate script so corpus + declared stay one source of truth.
    env = os.environ.copy()
    env["PYTHONPATH"] = ";".join([
        str(scripts),
        str(Path(project_root) / "engines" / "understand-operator" / "src"),
        str(Path(project_root) / "engines" / "common" / "src"),
        env.get("PYTHONPATH", ""),
    ])
    env.setdefault("UO_REPLAY_DISTRO", "Ubuntu-2204")
    gate_ok = False
    gate_err = ""
    try:
        proc = subprocess.run(
            [sys.executable, str(scripts / "replay_runtime_counterexample_gate.py")],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=180,
        )
        gate_ok = proc.returncode == 0
        if not gate_ok:
            gate_err = (proc.stdout or "")[-800:] + (proc.stderr or "")[-400:]
    except Exception as exc:  # noqa: BLE001
        gate_err = str(exc)

    closure: dict[str, Any] = {}
    if closure_path.is_file():
        closure = yaml.safe_load(closure_path.read_text(encoding="utf-8")) or {}

    gap = int(closure.get("open_gap_sound") or closure.get("open_gap") or -1)
    complete = bool(gate_ok and gap == 0)
    summary: dict[str, Any] = {
        "ok": bool(gate_ok),
        "engine": "coverage_gate",
        "complete": complete,
        "gate_pass": gate_ok,
        "declared": closure.get("declared"),
        "R_declared": closure.get("R_declared"),
        "upper_U_sound": closure.get("upper_U_sound"),
        "excluded_sound": closure.get("excluded_sound"),
        "open_gap_sound": gap,
        "upper_U_reviewed": closure.get("upper_U_reviewed"),
        "excluded_reviewed": closure.get("excluded_reviewed"),
        "open_gap_reviewed": closure.get("open_gap_reviewed"),
        "closure_path": str(closure_path),
        "residual_blockers": RESIDUAL_BLOCKERS if gap != 0 else [],
        "note": (
            "U_sound - R = empty only when open_gap_sound == 0. "
            "Residual blockers are HostIR/model gaps, not recipe misses."
            if gap != 0
            else "Full sound coverage."
        ),
    }
    if gate_err and not gate_ok:
        summary["error"] = gate_err[:1000]
    _dump(uo / "tk" / "coverage_gate.yaml", summary)
    _dump(uo / "tk" / "residual.yaml", {
        "open_gap_sound": gap,
        "complete": complete,
        "blockers": RESIDUAL_BLOCKERS if gap != 0 else [],
    })
    return summary


TK_ENGINES: dict[str, Any] = {
    "env_probe": env_probe,
    "derive_fields": derive_fields,
    "export_codemap": export_codemap,
    "mine_recipe": mine_recipe,
    "apply_recipe": apply_recipe,
    "coverage_gate": coverage_gate,
}
