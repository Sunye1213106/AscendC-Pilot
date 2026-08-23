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
BIND_COLUMN_CHUNK_SIZE = 20
_MAPPING_CELLS = ("role", "uo_id", "encoding", "evidence")


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


def chunk_column_names(
    names: list[str], size: int = BIND_COLUMN_CHUNK_SIZE
) -> list[list[str]]:
    clean = [str(n).strip() for n in names if str(n).strip()]
    if not clean:
        return [[]]
    n = max(1, int(size or BIND_COLUMN_CHUNK_SIZE))
    return [clean[i : i + n] for i in range(0, len(clean), n)]


def bind_chunk_slice_id(index: int) -> str:
    return f"bind{int(index)}"


def bind_chunk_filename(index: int) -> str:
    return f"{bind_chunk_slice_id(index)}.yaml"


def is_bind_chunk_id(slice_id: str) -> bool:
    token = str(slice_id or "").strip()
    return token.startswith("bind") and token[4:].isdigit()


def bind_part_column_names(parts_dir: Path) -> list[str]:
    parts = Path(parts_dir)
    for rel in (Path("bind.yaml"), Path(".engine") / "bind.owned.yaml"):
        path = parts / rel
        if not path.is_file():
            continue
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        cols = doc.get("columns") or doc.get("mapping_keys") or []
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
        mapping = doc.get("mapping") if isinstance(doc.get("mapping"), dict) else {}
        if mapping:
            return [str(k) for k in mapping if str(k).strip()]
    return []


def list_bind_chunk_paths(parts_dir: Path) -> list[Path]:
    parts = Path(parts_dir)
    if not parts.is_dir():
        return []
    found: list[Path] = []
    for path in parts.glob("bind*.yaml"):
        if is_bind_chunk_id(path.stem):
            found.append(path)
    return sorted(found, key=lambda p: int(p.stem[4:]))


def _chunk_has_llm_semantics(doc: dict[str, Any]) -> bool:
    if bool(doc.get(LLM_EDIT_KEY)):
        return True
    call = doc.get("call") if isinstance(doc.get("call"), dict) else {}
    if str(call.get("kind") or "").strip():
        return True
    if doc.get("call_args"):
        return True
    mapping = doc.get("mapping") if isinstance(doc.get("mapping"), dict) else {}
    for row in mapping.values():
        if isinstance(row, dict) and str(row.get("role") or "").strip():
            return True
    return False


def expand_bind_fanout_axes(
    axes_spec: list[dict[str, Any]],
    *,
    columns: list[str],
    run_id: str,
    chunk_size: int = BIND_COLUMN_CHUNK_SIZE,
) -> list[dict[str, Any]]:
    """Turn the bind axis template into bind0..bindN (≤ chunk_size columns each)."""
    chunks = chunk_column_names(columns, chunk_size)
    out: list[dict[str, Any]] = []
    run = str(run_id or "").strip() or "current"
    for row in axes_spec:
        if not isinstance(row, dict):
            continue
        axis_id = str(row.get("id") or "").strip()
        if axis_id != "bind":
            out.append(dict(row))
            continue
        size = int(row.get("chunk_size") or chunk_size or BIND_COLUMN_CHUNK_SIZE)
        chunks = chunk_column_names(columns, size)
        count = len(chunks)
        for index, names in enumerate(chunks):
            shard = dict(row)
            sid = bind_chunk_slice_id(index)
            shard["id"] = sid
            shard["chunk_index"] = index
            shard["chunk_count"] = count
            shard["column_names"] = list(names)
            shard["refs_ns"] = "bind"
            shard["prompt_alias"] = "bind"
            shard["method_filename"] = "method_bind.md"
            shard["artifact"] = (
                f"runs/{run}/actions/bind_init/parts/{bind_chunk_filename(index)}"
            )
            listed = ", ".join(names) if names else "(无列)"
            shard["focus"] = (
                f"parts/{bind_chunk_filename(index)}（call / mapping / domains；"
                f"本路 {len(names)} 列：{listed}）"
            )
            out.append(shard)
    return out


def _bind_doc_subset(bind: dict[str, Any], names: list[str]) -> dict[str, Any]:
    mapping = bind.get("mapping") if isinstance(bind.get("mapping"), dict) else {}
    domains = bind.get("domains") if isinstance(bind.get("domains"), dict) else {}
    return {
        "schema": bind.get("schema") or "tg-bind-part/v1",
        "kind": bind.get("kind") or "",
        "table_kind": bind.get("table_kind") or "",
        "entry": bind.get("entry") or "",
        "case_arg": bind.get("case_arg") or "",
        "call": {"kind": "", "api": "", "site": ""},
        "call_args": [],
        "columns": [{"name": name} for name in names],
        "mapping": {
            name: dict(mapping.get(name) or _empty_mapping_row()) for name in names
        },
        "domains": {
            name: dict(domains.get(name) or {"profile": {}, "operator": "", "compare": ""})
            for name in names
        },
        "findings": [],
        LLM_EDIT_KEY: False,
    }


def write_bind_chunk(
    parts_dir: Path,
    *,
    bind: dict[str, Any],
    names: list[str],
    index: int,
    count: int,
    identity: dict[str, Any] | None = None,
) -> Path:
    parts = Path(parts_dir)
    doc = _stamp(_bind_doc_subset(bind, names), identity)
    doc["chunk"] = {"index": int(index), "count": int(count), "columns": list(names)}
    path = parts / bind_chunk_filename(index)
    _dump(path, doc)
    return path


def emit_bind_chunks(
    parts_dir: Path,
    bind: dict[str, Any],
    *,
    identity: dict[str, Any] | None = None,
    chunk_size: int = BIND_COLUMN_CHUNK_SIZE,
) -> list[Path]:
    parts = Path(parts_dir)
    names = []
    for item in bind.get("columns") or []:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
        else:
            name = str(item or "").strip()
        if name:
            names.append(name)
    if not names:
        mapping = bind.get("mapping") if isinstance(bind.get("mapping"), dict) else {}
        names = [str(k) for k in mapping if str(k).strip()]
    chunks = chunk_column_names(names, chunk_size)
    written: list[Path] = []
    for index, group in enumerate(chunks):
        written.append(
            write_bind_chunk(
                parts,
                bind=bind,
                names=group,
                index=index,
                count=len(chunks),
                identity=identity,
            )
        )
    for stale in list_bind_chunk_paths(parts):
        idx = int(stale.stem[4:])
        if idx >= len(chunks):
            stale.unlink()
    return written


def merge_bind_chunks(parts_dir: Path) -> dict[str, Any]:
    """Fold bind0.yaml..bindN.yaml into parts/bind.yaml. No-op if no chunks."""
    parts = Path(parts_dir)
    bind_path = parts / "bind.yaml"
    chunks = list_bind_chunk_paths(parts)
    if not chunks:
        return {"ok": True, "merged": False, "chunks": 0}
    if not bind_path.is_file():
        return {"ok": False, "error": "missing_bind", "chunks": len(chunks)}
    try:
        bind = yaml.safe_load(bind_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "invalid_yaml", "detail": str(exc)}
    if not isinstance(bind, dict):
        return {"ok": False, "error": "invalid_yaml"}
    call = dict(bind.get("call") or {}) if isinstance(bind.get("call"), dict) else {}
    call_args: list[dict[str, Any]] = []
    seen_args: set[str] = set()
    for row in bind.get("call_args") or []:
        if isinstance(row, dict) and str(row.get("name") or "").strip():
            name = str(row["name"])
            if name not in seen_args:
                call_args.append(dict(row))
                seen_args.add(name)
    mapping = dict(bind.get("mapping") or {}) if isinstance(bind.get("mapping"), dict) else {}
    domains = dict(bind.get("domains") or {}) if isinstance(bind.get("domains"), dict) else {}
    findings: list[Any] = list(bind.get("findings") or []) if isinstance(bind.get("findings"), list) else []
    for chunk_path in chunks:
        try:
            doc = yaml.safe_load(chunk_path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        if not _chunk_has_llm_semantics(doc):
            continue
        ch_call = doc.get("call") if isinstance(doc.get("call"), dict) else {}
        if str(ch_call.get("kind") or "").strip() and not str(call.get("kind") or "").strip():
            call = dict(ch_call)
        for row in doc.get("call_args") or []:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            if not name or name in seen_args:
                continue
            call_args.append(dict(row))
            seen_args.add(name)
        ch_map = doc.get("mapping") if isinstance(doc.get("mapping"), dict) else {}
        meta = doc.get("chunk") if isinstance(doc.get("chunk"), dict) else {}
        chunk_names = [str(x).strip() for x in (meta.get("columns") or []) if str(x).strip()]
        if not chunk_names:
            chunk_names = [str(k) for k in ch_map if str(k).strip()]
        for name in chunk_names:
            src = ch_map.get(name)
            if not isinstance(src, dict):
                continue
            dst = dict(mapping.get(name) or _empty_mapping_row())
            for key in _MAPPING_CELLS:
                if key in src:
                    val = src.get(key)
                    dst[key] = "" if val is None else val
            mapping[name] = dst
        ch_dom = doc.get("domains") if isinstance(doc.get("domains"), dict) else {}
        for name in chunk_names:
            src = ch_dom.get(name)
            if not isinstance(src, dict):
                continue
            dst = dict(domains.get(name) or {})
            if "operator" in src:
                dst["operator"] = src.get("operator") or ""
            if "compare" in src:
                dst["compare"] = src.get("compare") or ""
            dst.setdefault("profile", {})
            domains[name] = dst
        if isinstance(doc.get("findings"), list):
            findings.extend(doc["findings"])
    bind["call"] = call
    bind["call_args"] = call_args
    bind["mapping"] = mapping
    bind["domains"] = domains
    bind["findings"] = findings
    _dump(bind_path, bind)
    return {"ok": True, "merged": True, "chunks": len(chunks)}


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
    emit_bind_chunks(parts, bind, identity=identity)
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
    merged = merge_bind_chunks(parts)
    if not merged.get("ok"):
        return {"ok": False, "errors": [merged.get("error") or "merge_bind_chunks"]}
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


def bind_fill_path(bind_path: Path) -> Path:
    target = Path(bind_path)
    return target.with_name(f"{target.stem}.fill.yaml")


def apply_bind_fill(bind_path: Path, fill_path: Path | None = None) -> dict[str, Any]:
    """Merge LLM-owned cells from bind.fill.yaml. Engine-owned keys stay locked."""
    target = Path(bind_path)
    fill_file = Path(fill_path) if fill_path is not None else bind_fill_path(target)
    if not fill_file.is_file():
        return {"ok": False, "error": "missing_fill", "path": str(fill_file)}
    try:
        bind = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        fill = yaml.safe_load(fill_file.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": "invalid_yaml", "detail": str(exc)}
    if not isinstance(bind, dict) or not isinstance(fill, dict):
        return {"ok": False, "error": "invalid_yaml"}
    if isinstance(fill.get("call"), dict):
        bind["call"] = dict(fill["call"])
    if isinstance(fill.get("call_args"), list):
        bind["call_args"] = list(fill["call_args"])
    if isinstance(fill.get("findings"), list):
        bind["findings"] = list(fill["findings"])
    fill_map = fill.get("mapping") if isinstance(fill.get("mapping"), dict) else {}
    mapping = bind.get("mapping") if isinstance(bind.get("mapping"), dict) else {}
    for name, row in list(mapping.items()):
        src = fill_map.get(name)
        if not isinstance(src, dict):
            continue
        dst = dict(row) if isinstance(row, dict) else _empty_mapping_row()
        for key in _MAPPING_CELLS:
            if key in src:
                val = src.get(key)
                dst[key] = "" if val is None else val
        mapping[name] = dst
    bind["mapping"] = mapping
    fill_dom = fill.get("domains") if isinstance(fill.get("domains"), dict) else {}
    domains = bind.get("domains") if isinstance(bind.get("domains"), dict) else {}
    for name, row in list(domains.items()):
        dst = dict(row) if isinstance(row, dict) else {}
        src = fill_dom.get(name)
        if isinstance(src, dict):
            dst["operator"] = str(src.get("operator") or "")
            dst["compare"] = str(src.get("compare") or "")
        domains[name] = dst
    bind["domains"] = domains
    owned_path = target.parent / ".engine" / "bind.owned.yaml"
    owned: dict[str, Any] = {}
    if owned_path.is_file():
        loaded = yaml.safe_load(owned_path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            owned = loaded
    restored, errors = restore_bind(bind, owned)
    if errors:
        return {"ok": False, "errors": errors}
    dump_part(target, restored)
    mark_llm_edited(target)
    return {"ok": True, "errors": []}
