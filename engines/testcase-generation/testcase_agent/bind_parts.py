# -*- coding: utf-8 -*-
"""Emit / restore bind_init part YAML from schemas/tg field ownership."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_SCHEMA_DIR = Path(__file__).resolve().parents[3] / "schemas" / "tg"
_SCHEMA_FILES = {
    "bind-part": "bind-part-v1.yaml",
    "harness-part": "harness-part-v1.yaml",
    "init": "init-v1.yaml",
}
_CANNOT_DEFAULT = (
    "empty_tensor",
    "scalar",
    "inf_nan",
    "align_plus_1",
    "illegal_range",
)
_CALL_KINDS = frozenset({"pta", "aclnn", "mixed"})
_ROLES = frozenset({"api_arg", "feature", "script_meta", "result_sink", ""})
LLM_EDIT_KEY = "llm_edit"


def load_schema(kind: str) -> dict[str, Any]:
    name = _SCHEMA_FILES.get(kind)
    if not name:
        raise ValueError(f"unknown tg schema {kind!r}")
    path = _SCHEMA_DIR / name
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(doc, dict):
        raise ValueError(f"invalid schema file {path}")
    doc.setdefault("engine_owned", [])
    doc.setdefault("llm_owned", [])
    return doc


def dump_part(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


_dump = dump_part


def is_llm_edited(path: Path) -> bool:
    """Fanout skip: explicit llm_edit=false is still a skeleton; missing key means done."""
    target = Path(path)
    if not target.is_file():
        return False
    if target.suffix.lower() not in {".yaml", ".yml"}:
        return True
    try:
        doc = yaml.safe_load(target.read_text(encoding="utf-8"))
    except Exception:
        return True
    if not isinstance(doc, dict):
        return True
    if LLM_EDIT_KEY not in doc:
        return True
    return bool(doc.get(LLM_EDIT_KEY))


def mark_llm_edited(path: Path) -> None:
    """Engine flips the flag after an LLM write; also stamps the owned snapshot."""
    target = Path(path)
    if not target.is_file():
        return
    try:
        doc = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except Exception:
        return
    if not isinstance(doc, dict):
        return
    doc[LLM_EDIT_KEY] = True
    dump_part(target, doc)
    owned = target.parent / ".engine" / f"{target.stem}.owned.yaml"
    if not owned.is_file():
        return
    try:
        snap = yaml.safe_load(owned.read_text(encoding="utf-8")) or {}
    except Exception:
        snap = {}
    if isinstance(snap, dict):
        snap[LLM_EDIT_KEY] = True
        dump_part(owned, snap)


def _stamp(doc: dict[str, Any], identity: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(doc)
    ident = dict(identity or {})
    if ident:
        out["artifact_identity"] = dict(ident)
        for key in ("run_id", "workflow_id", "action_id", "actor_id"):
            if ident.get(key):
                out[key] = ident[key]
    return out


def _column_names(scan: dict[str, Any]) -> list[str]:
    contract = scan.get("contract") if isinstance(scan.get("contract"), dict) else {}
    cols = list(contract.get("columns") or [])
    names: list[str] = []
    for item in cols:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
        else:
            name = str(item or "").strip()
        if name:
            names.append(name)
    if names:
        return names
    inventory = scan.get("inventory") if isinstance(scan.get("inventory"), dict) else {}
    for table in inventory.get("tables") or []:
        if not isinstance(table, dict):
            continue
        for col in table.get("columns") or []:
            name = str(col or "").strip()
            if name and name not in names:
                names.append(name)
        if names:
            break
    return names


def _table_kind(scan: dict[str, Any]) -> str:
    inventory = scan.get("inventory") if isinstance(scan.get("inventory"), dict) else {}
    kinds = [
        str(t.get("kind") or "")
        for t in (inventory.get("tables") or [])
        if isinstance(t, dict)
    ]
    if "xlsx" in kinds:
        return "xlsx"
    if "xls" in kinds:
        return "xls"
    return "csv"


def _profiles(scan: dict[str, Any]) -> dict[str, Any]:
    inventory = scan.get("inventory") if isinstance(scan.get("inventory"), dict) else {}
    for table in inventory.get("tables") or []:
        if not isinstance(table, dict):
            continue
        profile = table.get("profile") if isinstance(table.get("profile"), dict) else {}
        cols = profile.get("columns") if isinstance(profile.get("columns"), dict) else {}
        if cols:
            return cols
    return {}


def _candidates(scan: dict[str, Any]) -> list[dict[str, Any]]:
    contract = scan.get("contract") if isinstance(scan.get("contract"), dict) else {}
    raw = contract.get("mode_candidates") or (contract.get("modes") or {}).get("candidates") or []
    out: list[dict[str, Any]] = []
    for row in raw:
        if isinstance(row, dict) and str(row.get("flag") or "").strip():
            out.append(
                {
                    "flag": str(row.get("flag") or ""),
                    "values": list(row.get("values") or []),
                    "slot": "",
                }
            )
        elif str(row or "").strip():
            out.append({"flag": str(row), "values": [], "slot": ""})
    return out


def _empty_mapping_row() -> dict[str, str]:
    return {"role": "", "uo_id": "", "encoding": "", "evidence": ""}


def emit_bind_parts(
    parts_dir: Path,
    *,
    scan: dict[str, Any],
    identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parts = Path(parts_dir)
    kind = str(scan.get("kind") or (scan.get("contract") or {}).get("kind") or "default_input")
    contract = scan.get("contract") if isinstance(scan.get("contract"), dict) else {}
    columns = _column_names(scan)
    profiles = _profiles(scan)
    bind = _stamp(
        {
            "schema": "tg-bind-part/v1",
            "kind": kind,
            "table_kind": _table_kind(scan),
            "entry": str(contract.get("entry") or ""),
            "case_arg": str(contract.get("case_arg") or ""),
            "call": {"kind": "", "api": "", "site": ""},
            "call_args": [],
            "columns": [{"name": name} for name in columns],
            "mapping": {name: _empty_mapping_row() for name in columns},
            "domains": {
                name: {
                    "profile": profiles.get(name) or {},
                    "operator": "",
                    "compare": "",
                }
                for name in columns
            },
            "findings": [],
            LLM_EDIT_KEY: False,
        },
        identity,
    )
    schema = load_schema("harness-part")
    cannot_keys = [str(x) for x in (schema.get("cannot_keys") or _CANNOT_DEFAULT)]
    harness = _stamp(
        {
            "schema": "tg-harness-part/v1",
            "kind": kind,
            "entry": str(contract.get("entry") or ""),
            "case_arg": str(contract.get("case_arg") or ""),
            "golden": {"match": "", "mismatch": "", "gaps": ""},
            "compare": {"how": "", "atol_rtol": ""},
            "modes": {
                "precision": [],
                "perf": [],
                "candidates": _candidates(scan),
            },
            "generate_inputs": {
                "can": [],
                "cannot": {key: "" for key in cannot_keys},
            },
            "findings": [],
            LLM_EDIT_KEY: False,
        },
        identity,
    )
    _dump(parts / "bind.yaml", bind)
    _dump(parts / "harness.yaml", harness)
    owned = parts / ".engine"
    _dump(owned / "bind.owned.yaml", _owned_bind_snapshot(bind))
    _dump(owned / "harness.owned.yaml", _owned_harness_snapshot(harness))
    return {
        "ok": True,
        "bind": str((parts / "bind.yaml").as_posix()),
        "harness": str((parts / "harness.yaml").as_posix()),
    }


def _owned_bind_snapshot(bind: dict[str, Any]) -> dict[str, Any]:
    mapping = bind.get("mapping") if isinstance(bind.get("mapping"), dict) else {}
    domains = bind.get("domains") if isinstance(bind.get("domains"), dict) else {}
    return {
        "schema": bind.get("schema"),
        "run_id": bind.get("run_id"),
        "workflow_id": bind.get("workflow_id"),
        "action_id": bind.get("action_id"),
        "actor_id": bind.get("actor_id"),
        "artifact_identity": dict(bind.get("artifact_identity") or {}),
        "kind": bind.get("kind"),
        "table_kind": bind.get("table_kind"),
        "entry": bind.get("entry"),
        "case_arg": bind.get("case_arg"),
        "columns": list(bind.get("columns") or []),
        "mapping_keys": list(mapping),
        "domains_keys": list(domains),
        "domains_profile": {
            key: dict(row.get("profile") or {})
            for key, row in domains.items()
            if isinstance(row, dict)
        },
        LLM_EDIT_KEY: bool(bind.get(LLM_EDIT_KEY)),
    }


def _owned_harness_snapshot(harness: dict[str, Any]) -> dict[str, Any]:
    modes = harness.get("modes") if isinstance(harness.get("modes"), dict) else {}
    gen = harness.get("generate_inputs") if isinstance(harness.get("generate_inputs"), dict) else {}
    cannot = gen.get("cannot") if isinstance(gen.get("cannot"), dict) else {}
    return {
        "schema": harness.get("schema"),
        "run_id": harness.get("run_id"),
        "workflow_id": harness.get("workflow_id"),
        "action_id": harness.get("action_id"),
        "actor_id": harness.get("actor_id"),
        "artifact_identity": dict(harness.get("artifact_identity") or {}),
        "kind": harness.get("kind"),
        "entry": harness.get("entry"),
        "case_arg": harness.get("case_arg"),
        "modes_candidates": list(modes.get("candidates") or []),
        "cannot_keys": list(cannot),
        LLM_EDIT_KEY: bool(harness.get(LLM_EDIT_KEY)),
    }


def _restore_identity(doc: dict[str, Any], owned: dict[str, Any]) -> None:
    for key in (
        "schema",
        "run_id",
        "workflow_id",
        "action_id",
        "actor_id",
        "kind",
        "table_kind",
        "entry",
        "case_arg",
        LLM_EDIT_KEY,
    ):
        if owned.get(key) not in (None, ""):
            doc[key] = owned[key]
    if owned.get("artifact_identity"):
        doc["artifact_identity"] = dict(owned["artifact_identity"])


def restore_bind(doc: dict[str, Any], owned: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    out = dict(doc) if isinstance(doc, dict) else {}
    errors: list[str] = []
    _restore_identity(out, owned)
    columns = list(owned.get("columns") or out.get("columns") or [])
    out["columns"] = columns
    names = []
    for item in columns:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
        else:
            name = str(item or "").strip()
        if name:
            names.append(name)
    if owned.get("mapping_keys"):
        names = [str(x) for x in owned["mapping_keys"] if str(x).strip()]
    raw_map_src = out.get("mapping")
    if isinstance(raw_map_src, dict):
        raw_map = raw_map_src
    else:
        from .products import mapping_as_dict

        raw_map = mapping_as_dict(raw_map_src)
    mapping: dict[str, Any] = {}
    for name in names:
        row = raw_map.get(name) if isinstance(raw_map.get(name), dict) else {}
        if row:
            mapping[name] = dict(row)
            mapping[name].pop("evidence_window_sha256", None)
            mapping[name].pop("snippet", None)
            mapping[name].pop("evidence_snippet", None)
        else:
            mapping[name] = _empty_mapping_row()
    out["mapping"] = mapping
    profiles = owned.get("domains_profile") if isinstance(owned.get("domains_profile"), dict) else {}
    raw_dom = out.get("domains") if isinstance(out.get("domains"), dict) else {}
    domains: dict[str, Any] = {}
    for name in names:
        row = raw_dom.get(name) if isinstance(raw_dom.get(name), dict) else {}
        domains[name] = {
            "profile": profiles.get(name) if isinstance(profiles.get(name), dict) else {},
            "operator": str(row.get("operator") or ""),
            "compare": str(row.get("compare") or ""),
        }
    out["domains"] = domains
    call = out.get("call") if isinstance(out.get("call"), dict) else {}
    kind = str(call.get("kind") or "").strip()
    if kind and kind not in _CALL_KINDS:
        errors.append(f"call.kind {kind!r} not in pta|aclnn|mixed")
    for row in mapping.values():
        role = str(row.get("role") or "").strip()
        if role and role not in _ROLES:
            errors.append(f"mapping role {role!r} invalid")
    return out, errors


def restore_harness(doc: dict[str, Any], owned: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    out = dict(doc) if isinstance(doc, dict) else {}
    _restore_identity(out, owned)
    modes = out.get("modes") if isinstance(out.get("modes"), dict) else {}
    modes = dict(modes)
    if owned.get("modes_candidates") is not None:
        modes["candidates"] = list(owned.get("modes_candidates") or [])
    modes.setdefault("precision", [])
    modes.setdefault("perf", [])
    out["modes"] = modes
    gen = out.get("generate_inputs") if isinstance(out.get("generate_inputs"), dict) else {}
    gen = dict(gen)
    keys = [str(x) for x in (owned.get("cannot_keys") or _CANNOT_DEFAULT)]
    cannot = gen.get("cannot")
    if isinstance(cannot, dict):
        gen["cannot"] = {key: cannot.get(key, "") for key in keys}
    elif isinstance(cannot, list):
        gen["cannot"] = {key: ("yes" if key in cannot else "") for key in keys}
    else:
        gen["cannot"] = {key: "" for key in keys}
    gen.setdefault("can", [])
    out["generate_inputs"] = gen
    return out, []


def restore_and_dump_parts(parts_dir: Path) -> dict[str, Any]:
    parts = Path(parts_dir)
    errors: list[str] = []
    bind_path = parts / "bind.yaml"
    harness_path = parts / "harness.yaml"
    owned_bind = yaml.safe_load((parts / ".engine" / "bind.owned.yaml").read_text(encoding="utf-8")) or {}
    owned_harness = yaml.safe_load((parts / ".engine" / "harness.owned.yaml").read_text(encoding="utf-8")) or {}
    bind = yaml.safe_load(bind_path.read_text(encoding="utf-8")) or {}
    harness = yaml.safe_load(harness_path.read_text(encoding="utf-8")) or {}
    bind, bind_err = restore_bind(bind if isinstance(bind, dict) else {}, owned_bind)
    harness, harness_err = restore_harness(
        harness if isinstance(harness, dict) else {}, owned_harness
    )
    errors.extend(bind_err)
    errors.extend(harness_err)
    if errors:
        return {"ok": False, "errors": errors}
    _dump(bind_path, bind)
    _dump(harness_path, harness)
    mark_llm_edited(bind_path)
    mark_llm_edited(harness_path)
    return {"ok": True, "errors": []}
