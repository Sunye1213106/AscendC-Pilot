# -*- coding: utf-8 -*-
"""Expand LLM fill-in (tg-plan-fill/v1) into canonical tg-plan/v3.

The Owner names what to observe, how to cut, which combinations conflict, and
why. The engine writes predicates, coverage scaffolding, classifier/controls,
and untestable rows from init.
"""
from __future__ import annotations

from typing import Any

import yaml

FILL_SCHEMA = "tg-plan-fill/v1"
PLAN_SCHEMA = "tg-plan/v3"
_PREFIXES = ("case.", "replay.", "probe.")


class AssembleError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = [str(e) for e in errors if str(e).strip()]
        super().__init__("; ".join(self.errors) or "plan fill assemble failed")


class _FillLoader(yaml.SafeLoader):
    """Treat unknown `!tag` scalars as plain strings so unquoted `!cond` reasons parse."""


def _unknown_tag(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
        return f"!{suffix} {value}".strip() if value else f"!{suffix}"
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None


_FillLoader.add_multi_constructor("!", _unknown_tag)


def load_yaml(text: str) -> dict[str, Any]:
    blob = (text or "").strip()
    if blob.endswith("```"):
        blob = blob[: blob.rfind("```")].rstrip()
    doc = yaml.load(blob, Loader=_FillLoader) or {}
    return doc if isinstance(doc, dict) else {}


def is_fill(doc: Any) -> bool:
    if not isinstance(doc, dict):
        return False
    schema = str(doc.get("schema") or doc.get("version") or "").strip()
    if schema == FILL_SCHEMA:
        return True
    return bool(doc.get("target")) and "targets" not in doc and schema != PLAN_SCHEMA


def ensure_v3(doc: dict[str, Any] | None, init: dict[str, Any] | None = None) -> dict[str, Any]:
    """Identity for v3; assemble fill-in. Raises AssembleError on bad fill."""
    if not isinstance(doc, dict) or not doc:
        return doc or {}
    if str(doc.get("schema") or "") == PLAN_SCHEMA:
        return doc
    if is_fill(doc):
        return assemble_plan(doc, init)
    return doc


def assemble_plan(fill: dict[str, Any], init: dict[str, Any] | None = None) -> dict[str, Any]:
    errors: list[str] = []
    target_fill = fill.get("target") if isinstance(fill.get("target"), dict) else {}
    evidence, t_id, r_id = _target_evidence(target_fill, fill, errors)
    dims_out: list[dict[str, Any]] = []
    for raw in fill.get("dimensions") or []:
        if not isinstance(raw, dict):
            errors.append("dimension is not a mapping")
            continue
        dims_out.append(_assemble_dimension(raw, t_id, errors))
    guards_out: list[dict[str, Any]] = []
    for raw in fill.get("guards") or []:
        if not isinstance(raw, dict):
            errors.append("guard is not a mapping")
            continue
        guards_out.append(_assemble_guard(raw, t_id, errors))
    l1 = _assemble_l1(fill.get("l1") or fill.get("L1") or [])
    exclusions = _assemble_exclusions(fill.get("exclusions") or [], errors)
    if errors:
        raise AssembleError(errors)
    req_text = fill.get("requirement")
    if isinstance(req_text, dict):
        req_id = str(req_text.get("id") or r_id)
        req_body = str(req_text.get("text") or "")
    else:
        req_id = r_id
        req_body = str(req_text or "")
    oracle = _assemble_oracle(fill.get("oracle"))
    untestable = list(fill.get("untestable") or [])
    if not untestable:
        untestable = _untestable_from_init(init)
        for item in fill.get("opaque") or []:
            if isinstance(item, dict):
                untestable.append(item)
    dim_ids = [str(d.get("id") or "") for d in dims_out if d.get("id")]
    guard_ids = [str(g.get("id") or "") for g in guards_out if g.get("id")]
    env = fill.get("environment") if isinstance(fill.get("environment"), dict) else {}
    constraints = fill.get("constraints")
    if constraints is None:
        constraints = []
    out: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "requirement": {"id": req_id, "text": req_body},
        "targets": [{"id": t_id, "evidence": evidence}],
        "dimensions": dims_out,
        "guards": guards_out,
        "coverage": {
            "L0": {"dimensions": dim_ids},
            "L1": {"combinations": l1},
            "L2": {"mode": "full_cross", "exclusions": exclusions},
            "L3": {"guards": guard_ids},
        },
        "oracle": oracle,
        "constraints": constraints,
        "environment": env,
        "untestable": untestable,
    }
    gap = fill.get("test_harness_gap")
    if isinstance(gap, dict) and gap:
        out["test_harness_gap"] = gap
    return out


def _slug(field: str) -> str:
    bare = str(field or "target").split(".")[-1].strip() or "target"
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in bare)


def _target_evidence(
    target: dict[str, Any],
    fill: dict[str, Any],
    errors: list[str],
) -> tuple[dict[str, Any], str, str]:
    field = str(target.get("field") or "").strip()
    t_id = str(target.get("id") or fill.get("target_id") or (f"T-{_slug(field)}" if field else "T-main"))
    r_id = str(fill.get("requirement_id") or f"R-{_slug(field) if field else 'main'}")
    if not field:
        errors.append("target.field is required")
        return {"kind": "replay_field", "field": "replay.unknown", "expected": 1}, t_id, r_id
    field = _qualify(field, default="replay")
    if "expected" in target and target.get("in") is None and target.get("op") is None:
        return {"kind": "replay_field", "field": field, "expected": target.get("expected")}, t_id, r_id
    if target.get("in") is not None:
        return {
            "kind": "derived",
            "predicate": {"op": "in", "field": field, "values": list(target.get("in") or [])},
        }, t_id, r_id
    op = str(target.get("op") or "gt").strip()
    pred: dict[str, Any] = {"op": op, "field": field}
    if "value" in target:
        pred["value"] = target.get("value")
    if "values" in target:
        pred["values"] = target.get("values")
    return {"kind": "derived", "predicate": pred}, t_id, r_id


def _qualify(name: Any, *, default: str = "case") -> str:
    raw = str(name or "").strip()
    if not raw:
        return raw
    if raw.startswith(_PREFIXES):
        return raw
    prefix = default if default in {"case", "replay", "probe"} else "case"
    return f"{prefix}.{raw}"


def _bare(name: Any) -> str:
    raw = str(name or "").strip()
    if raw.startswith(_PREFIXES):
        return raw.split(".", 1)[-1]
    return raw


def _resolve_field(name: Any, cuts: list[str]) -> str:
    raw = str(name or "").strip()
    if raw.startswith(_PREFIXES):
        return raw
    if not raw and len(cuts) == 1:
        return cuts[0]
    suffix = raw.split(".")[-1]
    for cut in cuts:
        if cut.split(".")[-1] == suffix or cut == raw:
            return cut
    if len(cuts) == 1:
        return cuts[0]
    return _qualify(raw)


def _cuts_of(dim: dict[str, Any]) -> list[str]:
    raw = dim.get("cuts")
    items = raw if isinstance(raw, list) else ([raw] if raw not in (None, "") else [])
    out: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        if text.startswith(_PREFIXES):
            out.append(text)
        else:
            out.append(f"case.{text}")
    return out


def _atom_predicate(atom: dict[str, Any], cuts: list[str], owner: str, errors: list[str]) -> dict[str, Any]:
    if isinstance(atom.get("predicate"), dict):
        return dict(atom["predicate"])
    field_hint = atom.get("field")
    if "all" in atom:
        args = [_atom_predicate(x, cuts, owner, errors) for x in (atom.get("all") or []) if isinstance(x, dict)]
        if not args:
            errors.append(f"{owner}: empty all")
            return {"op": "eq", "field": cuts[0] if cuts else "case.unknown", "value": 0}
        return args[0] if len(args) == 1 else {"op": "and", "args": args}
    if "eq" in atom:
        eq = atom["eq"]
        if isinstance(eq, dict):
            args = []
            for key, val in eq.items():
                args.append({"op": "eq", "field": _resolve_field(key, cuts), "value": val})
            return args[0] if len(args) == 1 else {"op": "and", "args": args}
        field = _resolve_field(field_hint, cuts) if field_hint or cuts else ""
        if not field:
            errors.append(f"{owner}: eq needs cuts or field")
            field = "case.unknown"
        return {"op": "eq", "field": field, "value": eq}
    if "mod" in atom:
        field = _resolve_field(field_hint, cuts) if field_hint or cuts else ""
        if not field:
            errors.append(f"{owner}: mod needs cuts or field")
            field = "case.unknown"
        return {
            "op": "mod_eq",
            "field": field,
            "divisor": int(atom.get("divisor") or 2),
            "value": atom.get("mod"),
        }
    if "not_in" in atom:
        field = _resolve_field(field_hint, cuts) if field_hint or cuts else _qualify(field_hint or "")
        return {"op": "not_in", "field": field, "values": list(atom.get("not_in") or [])}
    if "in" in atom:
        field = _resolve_field(field_hint, cuts) if field_hint or cuts else _qualify(field_hint or "")
        return {"op": "in", "field": field, "values": list(atom.get("in") or [])}
    op = str(atom.get("op") or "").strip()
    if op:
        field = _resolve_field(field_hint, cuts) if (field_hint or cuts) else _qualify(field_hint or "")
        pred: dict[str, Any] = {"op": op, "field": field}
        if "value" in atom:
            pred["value"] = atom.get("value")
        if "values" in atom:
            pred["values"] = atom.get("values")
        return pred
    errors.append(f"{owner}: arm needs eq, mod, op, in, not_in, all, or predicate")
    return {"op": "eq", "field": cuts[0] if cuts else "case.unknown", "value": 0}


def _pred_case_columns(pred: dict[str, Any]) -> list[str]:
    cols: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            field = str(node.get("field") or node.get("left") or "")
            if field.startswith("case."):
                cols.append(field.split(".", 1)[1])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(pred)
    seen: set[str] = set()
    out: list[str] = []
    for c in cols:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _assemble_dimension(raw: dict[str, Any], target_id: str, errors: list[str]) -> dict[str, Any]:
    did = str(raw.get("id") or "").strip()
    if not did:
        errors.append("dimension missing id")
        did = "D-unnamed"
    cuts = _cuts_of(raw)
    if not cuts:
        errors.append(f"{did}: cuts is required")
    arms = raw.get("arms") or raw.get("partitions") or []
    if len(arms) < 2:
        errors.append(f"{did}: need >=2 arms")
    partitions: list[dict[str, Any]] = []
    for i, arm in enumerate(arms):
        if not isinstance(arm, dict):
            errors.append(f"{did}: arm {i} is not a mapping")
            continue
        pid = str(arm.get("id") or f"p-{i}").strip()
        pred = _atom_predicate(arm, cuts, f"{did}.{pid}", errors)
        partitions.append({"id": pid, "predicate": pred})
    extra = [str(c).strip() for c in (raw.get("extra_controls") or []) if str(c).strip()]
    extra = [_bare(c) for c in extra]
    cut_cols = [_bare(c) for c in cuts if c.startswith("case.")]
    pred_cols: list[str] = []
    for p in partitions:
        pred_cols.extend(_pred_case_columns(p.get("predicate") or {}))
    controls: list[str] = []
    for c in cut_cols + extra + pred_cols:
        if c and c not in controls:
            controls.append(c)
    out: dict[str, Any] = {
        "id": did,
        "target": str(raw.get("target") or target_id),
        "controls": controls,
        "classifier": {"requires": list(cuts)},
        "partitions": partitions,
    }
    hint_cols = raw.get("construct_hint")
    if isinstance(hint_cols, dict):
        out["construct_hint"] = hint_cols
    elif extra:
        out["construct_hint"] = {"columns": extra}
    return out


def _assemble_guard(raw: dict[str, Any], target_id: str, errors: list[str]) -> dict[str, Any]:
    gid = str(raw.get("id") or "").strip() or "G-unnamed"
    field = raw.get("field")
    cuts = [_qualify(field)] if field else []
    atom = {
        k: v
        for k, v in raw.items()
        if k not in {"id", "target", "violate", "negate_hint", "controls", "construct_hint"}
    }
    pred = _atom_predicate(atom, cuts, gid, errors)
    cols = _pred_case_columns(pred)
    extra = [str(c).strip() for c in (raw.get("controls") or []) if str(c).strip()]
    extra = [_bare(c) for c in extra]
    controls: list[str] = []
    for c in cols + extra:
        if c and c not in controls:
            controls.append(c)
    violate = raw.get("violate")
    if violate is None:
        hint = raw.get("negate_hint") if isinstance(raw.get("negate_hint"), dict) else {}
    elif isinstance(violate, dict):
        hint = {_bare(k): v for k, v in violate.items()}
    else:
        key = cols[0] if cols else _bare(field or "value")
        hint = {key: violate}
    if not hint:
        errors.append(f"{gid}: violate (negate_hint) is required")
    return {
        "id": gid,
        "target": str(raw.get("target") or target_id),
        "controls": controls,
        "predicate": pred,
        "negate_hint": hint,
    }


def _assemble_l1(raw: Any) -> list[dict[str, Any]]:
    rows = raw if isinstance(raw, list) else []
    out: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        dims = item.get("dims") or item.get("dimensions") or []
        reason = str(item.get("reason") or "").strip()
        ids = [str(x).strip() for x in dims if str(x).strip()]
        if ids:
            out.append({"dims": ids, "reason": reason})
    return out


def _assemble_exclusions(raw: Any, errors: list[str]) -> list[dict[str, Any]]:
    rows = raw if isinstance(raw, list) else []
    out: list[dict[str, Any]] = []
    for i, item in enumerate(rows):
        if not isinstance(item, dict):
            errors.append(f"exclusion {i} is not a mapping")
            continue
        reason = str(item.get("reason") or "").strip()
        parts = item.get("partitions")
        if not isinstance(parts, dict):
            parts = {k: v for k, v in item.items() if k != "reason"}
        parts = {
            str(k): v
            for k, v in (parts or {}).items()
            if str(k).strip().startswith("D-")
        }
        if len(parts) < 2:
            errors.append(f"exclusion {i}: need >=2 different dimensions")
            continue
        if len(set(parts)) < 2:
            errors.append(f"exclusion {i}: same dimension listed twice")
            continue
        if not reason:
            errors.append(f"exclusion {i}: reason is required")
        out.append({"partitions": parts, "reason": reason})
    return out


def _assemble_oracle(raw: Any) -> list[dict[str, Any]]:
    if raw in (None, [], {}):
        return []
    if isinstance(raw, str):
        kind = raw.strip().lower()
        if kind in {"md5", "md5_match"}:
            return [{"kind": "md5", "fields": []}]
        if kind in {"precision", "golden"}:
            return [{"kind": "precision", "fields": []}]
        return [{"kind": kind}]
    if isinstance(raw, list):
        out: list[dict[str, Any]] = []
        for item in raw:
            if isinstance(item, dict):
                out.append(item)
            elif isinstance(item, str):
                out.extend(_assemble_oracle(item))
        return out
    if isinstance(raw, dict):
        return [raw]
    return []


def _untestable_from_init(init: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(init, dict):
        return []
    mapping = init.get("mapping") if isinstance(init.get("mapping"), dict) else {}
    out: list[dict[str, Any]] = []
    for col, row in mapping.items():
        if not isinstance(row, dict):
            continue
        conf = str(row.get("confidence") or "").strip().lower()
        control = row.get("control") if isinstance(row.get("control"), dict) else {}
        status = str(control.get("status") or "").strip().lower()
        if conf != "unresolved" or status != "active":
            continue
        name = str(col).strip()
        if not name:
            continue
        out.append(
            {
                "id": f"u-{name}",
                "kind": "control_gap",
                "reason": f"{name} 列 unresolved+active，未绑定 host 分岔",
                "needs_binding": [{"column": name, "want": "confirmed+active"}],
            }
        )
    return out
