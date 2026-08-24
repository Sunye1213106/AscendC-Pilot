# -*- coding: utf-8 -*-
"""Canonical TG products: init.yaml, plan.md, worklog.md, cases.csv/xls.

These are the only user-facing TG artifacts. Receipts stay under runs/.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .io import read_yaml, write_yaml

INIT_SCHEMA = "tg-init/v1"
PLAN_SCHEMA = "tg-plan/v3"
WORKLOG_SCHEMA = "tg-worklog/v2"

_FENCE_RE = re.compile(r"```ya?ml\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_OPEN_RE = re.compile(r"^open:\s*\[(.*?)\]\s*$", re.MULTILINE)


class ProductError(RuntimeError):
    def __init__(self, message: str, *, ask: str = "", payload: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.ask = ask or "tg_product"
        self.payload = payload or {}


def init_path(tg_root: Path) -> Path:
    return Path(tg_root) / "init.yaml"


def plan_path(tg_root: Path) -> Path:
    return Path(tg_root) / "plan.md"


def worklog_path(tg_root: Path) -> Path:
    return Path(tg_root) / "worklog.md"


def load_init(tg_root: Path) -> dict[str, Any]:
    path = init_path(tg_root)
    if not path.is_file():
        raise ProductError(
            "missing tg/init.yaml; run /tg-init",
            ask="init_required",
            payload={"path": path.as_posix(), "next": "/uo-init then /tg-init"},
        )
    doc = read_yaml(path)
    if not isinstance(doc, dict):
        raise ProductError("tg/init.yaml is not a mapping", payload={"path": path.as_posix()})
    return doc


def column_names(init_doc: dict[str, Any]) -> list[str]:
    cols = init_doc.get("columns") or []
    names: list[str] = []
    for item in cols:
        if isinstance(item, dict):
            name = str(item.get("name") or "").strip()
        else:
            name = str(item or "").strip()
        if name:
            names.append(name)
    return names


_CALL_KINDS = frozenset({"pta", "aclnn", "mixed"})
_MAPPING_WRAPPER_KEYS = frozenset({"columns", "rows", "items", "mapping"})
CONTROL_STATUSES = frozenset({"active", "fallback", "shadowed", "unwired", "result", "metadata"})
RELATIONS = frozenset(
    {"direct", "derived", "tensor_shape", "tensor_dtype", "presence"}
)
CONFIDENCES = frozenset({"confirmed", "partial", "unresolved"})
_SOLVE_BLOCKED = frozenset({"unwired", "shadowed", "fallback", "result", "metadata"})
_SOLVE_RELATIONS = frozenset(
    {"direct", "derived", "tensor_shape", "tensor_dtype", "presence"}
)
_ORACLE_EVIDENCE_FIELDS = frozenset(
    {"precision", "pricision", "md5", "accuracy", "oracle", "golden", "perf", "performance"}
)


def empty_mapping_row() -> dict[str, Any]:
    return {
        "control": {"status": ""},
        "relation": "",
        "confidence": "",
        "runtime": {"target": "", "path": []},
        "uo": {"id": "", "candidate": ""},
        "encoding": "",
        "evidence": "",
    }


def has_legacy_bind_fields(row: Any) -> bool:
    return isinstance(row, dict) and ("role" in row or "uo_id" in row)


def _control_status(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    control = row.get("control") if isinstance(row.get("control"), dict) else {}
    return str(control.get("status") or "").strip()


def _uo_id(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    uo = row.get("uo") if isinstance(row.get("uo"), dict) else {}
    return str(uo.get("id") or "").strip()


def _uo_candidate(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    uo = row.get("uo") if isinstance(row.get("uo"), dict) else {}
    return str(uo.get("candidate") or "").strip()


def _runtime_path(row: Any) -> list[str]:
    if not isinstance(row, dict):
        return []
    runtime = row.get("runtime") if isinstance(row.get("runtime"), dict) else {}
    path = runtime.get("path") or []
    if isinstance(path, list):
        return [str(x).strip() for x in path if str(x).strip()]
    text = str(path).strip()
    return [text] if text else []


def is_bound_control(row: Any) -> bool:
    if not isinstance(row, dict) or has_legacy_bind_fields(row):
        return False
    if _control_status(row) != "active":
        return False
    if str(row.get("confidence") or "").strip() != "confirmed":
        return False
    if not _uo_id(row) or _uo_candidate(row):
        return False
    return str(row.get("relation") or "").strip() in _SOLVE_RELATIONS


def is_confirmed_active(row: Any) -> bool:
    return is_bound_control(row)


def is_solve_control(row: Any) -> bool:
    if not is_bound_control(row):
        return False
    if _control_status(row) in _SOLVE_BLOCKED:
        return False
    return str(row.get("relation") or "").strip() in _SOLVE_RELATIONS


def _ingest_mapping_row(out: dict[str, Any], item: dict[str, Any], *, fallback: str = "") -> None:
    col = str(item.get("column") or fallback).strip()
    if not col:
        return
    row = dict(item)
    row.setdefault("column", col)
    out[col] = row


def _is_filled_mapping_row(row: Any) -> bool:
    if not isinstance(row, dict):
        return False
    status = _control_status(row)
    relation = str(row.get("relation") or "").strip()
    confidence = str(row.get("confidence") or "").strip()
    if status or relation or confidence:
        return True
    return False


def _drop_unfilled_mapping(out: dict[str, Any]) -> dict[str, Any]:
    """Rows without control.status / relation / confidence are not yet bound."""
    return {key: row for key, row in out.items() if _is_filled_mapping_row(row)}


def mapping_as_dict(raw: Any) -> dict[str, Any]:
    """Normalize bind mapping (list-of-rows or dict) keyed by column name.

    A wrapper list under ``columns`` / ``rows`` is not itself a column. Rows
    must use ``column=``; ``name=`` alone is dropped so it cannot become a
    garbage binding.
    """
    out: dict[str, Any] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            label = str(key or "").strip()
            if label in _MAPPING_WRAPPER_KEYS and isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        _ingest_mapping_row(out, item)
                continue
            if isinstance(value, dict):
                _ingest_mapping_row(out, value, fallback=label)
                continue
        return _drop_unfilled_mapping(out)
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                _ingest_mapping_row(out, item)
    return _drop_unfilled_mapping(out)


def _mapping_uses_name_schema(raw: Any) -> bool:
    rows: list[dict[str, Any]] = []
    if isinstance(raw, dict):
        wrapped = raw.get("columns")
        if isinstance(wrapped, list):
            rows = [item for item in wrapped if isinstance(item, dict)]
        else:
            return False
    elif isinstance(raw, list):
        rows = [item for item in raw if isinstance(item, dict)]
    else:
        return False
    return any(
        str(row.get("name") or "").strip() and not str(row.get("column") or "").strip()
        for row in rows
    )


def _iter_mapping_rows(raw: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(raw, dict):
        return [(str(name), row) for name, row in raw.items() if isinstance(row, dict)]
    if isinstance(raw, list):
        out: list[tuple[str, dict[str, Any]]] = []
        for item in raw:
            if isinstance(item, dict):
                out.append((str(item.get("column") or ""), item))
        return out
    return []


def _iter_call_args(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        items: list[dict[str, Any]] = []
        for name, value in raw.items():
            if isinstance(value, dict):
                row = dict(value)
                row.setdefault("name", name)
                items.append(row)
            else:
                items.append({"name": name})
        return items
    return []


def _validate_mapping_row(name: str, row: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    status = _control_status(row)
    relation = str(row.get("relation") or "").strip()
    confidence = str(row.get("confidence") or "").strip()
    uo_id = _uo_id(row)
    candidate = _uo_candidate(row)
    path = _runtime_path(row)
    if status and status not in CONTROL_STATUSES:
        errors.append(f"mapping.{name} control.status {status!r} invalid")
    if relation and relation not in RELATIONS:
        errors.append(f"mapping.{name} relation {relation!r} invalid")
    if confidence and confidence not in CONFIDENCES:
        errors.append(f"mapping.{name} confidence {confidence!r} invalid")
    if not status and not relation and not confidence:
        return errors
    if confidence == "confirmed":
        if status != "active":
            errors.append(f"mapping.{name} confirmed requires control.status=active")
        if relation not in _SOLVE_RELATIONS:
            errors.append(
                f"mapping.{name} confirmed requires relation in "
                "direct|derived|tensor_shape|tensor_dtype|presence"
            )
        if not uo_id or candidate:
            errors.append(f"mapping.{name} confirmed requires nonempty uo.id and empty uo.candidate")
    elif confidence == "partial":
        if uo_id:
            errors.append(f"mapping.{name} partial requires empty uo.id")
        if not candidate and not path:
            errors.append(f"mapping.{name} partial requires uo.candidate or runtime.path")
    elif confidence == "unresolved":
        if uo_id:
            errors.append(f"mapping.{name} unresolved requires empty uo.id")
    if status and status != "active":
        if uo_id:
            errors.append(f"mapping.{name} non-active requires empty uo.id")
        if confidence == "confirmed":
            errors.append(f"mapping.{name} confirmed requires control.status=active")
    return errors


def validate_bind_part(bind: Any) -> list[str]:
    """Bind legality: call kind, mapping shape, and confirmed/partial/unresolved state machine."""
    if not isinstance(bind, dict):
        return ["bind part is not a mapping"]
    errors: list[str] = []
    call = bind.get("call") if isinstance(bind.get("call"), dict) else {}
    kind = str(call.get("kind") or "").strip()
    kinds = _CALL_KINDS
    try:
        from .bind_parts import load_schema

        declared = load_schema("bind-part").get("enums", {}).get("call.kind")
        if declared:
            kinds = frozenset(str(x) for x in declared)
    except Exception:  # noqa: BLE001
        kinds = _CALL_KINDS
    if kind and kind not in kinds:
        errors.append(f"call.kind {kind!r} not in pta|aclnn|mixed")
    if _mapping_uses_name_schema(bind.get("mapping")):
        errors.append(
            "mapping.columns[].name is not a valid schema; use mapping keyed by "
            "column or a list of {column: ...}"
        )
    for name, row in _iter_mapping_rows(bind.get("mapping")):
        if "role" in row or "uo_id" in row:
            errors.append(f"mapping.{name} uses removed role/uo_id; rebind")
        errors.extend(_validate_mapping_row(name, row))
    for item in _iter_call_args(bind.get("call_args")):
        if "source_column" in item:
            errors.append("call_args.source_column removed; use sources[]")
            break
    return errors


def validate_harness_part(harness: Any) -> list[str]:
    """Same gate `inspect yaml` uses for parts/harness.yaml."""
    if not isinstance(harness, dict):
        return ["harness part is not a mapping"]
    errors: list[str] = []
    call = harness.get("call") if isinstance(harness.get("call"), dict) else {}
    kind = str(call.get("kind") or "").strip()
    if kind and kind not in _CALL_KINDS:
        errors.append(f"call.kind {kind!r} not in pta|aclnn|mixed")
    return errors


def check_tg_part(doc: Any) -> list[str]:
    """Dispatch bind/harness part checks. init.yaml stays parse-only here."""
    if not isinstance(doc, dict):
        return ["part is not a mapping"]
    schema = str(doc.get("schema") or "")
    if schema in {INIT_SCHEMA, "tg-init/v1"}:
        return []
    if schema == "tg-harness-part/v1":
        return validate_harness_part(doc)
    if schema == "tg-bind-part/v1" or "mapping" in doc:
        return validate_bind_part(doc)
    return []


def domains_as_dict(raw: Any) -> dict[str, Any]:
    """Normalize bind domains (list-of-rows or dict) keyed by column name."""
    out: dict[str, Any] = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            col = str(key or "").strip()
            if isinstance(value, dict):
                row = dict(value)
                col = str(row.get("column") or col).strip()
            else:
                row = {"legal": value}
            if not col:
                continue
            row.setdefault("column", col)
            out[col] = row
        return out
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            col = str(item.get("column") or "").strip()
            if not col:
                continue
            row = dict(item)
            row.setdefault("column", col)
            out[col] = row
    return out


def validate_init(doc: dict[str, Any], *, require_mapping: bool | None = None) -> list[str]:
    errors: list[str] = []
    schema = str(doc.get("schema") or "")
    if schema and schema != INIT_SCHEMA:
        errors.append(f"schema {schema!r} != {INIT_SCHEMA}")
    kind = str(doc.get("kind") or "default_input").strip()
    if kind not in {"script_repo", "default_input"}:
        errors.append(f"kind {kind!r} invalid")
    table_kind = str(doc.get("table_kind") or "").strip().lower()
    if table_kind not in {"csv", "xls", "xlsx"}:
        errors.append(f"table_kind {table_kind!r} invalid or missing")
    if not str(doc.get("uo_digest") or "").strip():
        errors.append("uo_digest required")
    cols = column_names(doc)
    if kind == "script_repo" and not cols:
        errors.append("script_repo init.yaml has no columns")
    mapping = mapping_as_dict(doc.get("mapping"))
    for name, row in mapping.items():
        if isinstance(row, dict):
            errors.extend(_validate_mapping_row(name, row))
    must_map = require_mapping if require_mapping is not None else kind == "script_repo"
    if must_map and not mapping:
        errors.append("script_repo mapping is empty; bind columns to script and UO identifiers")
    confirmed = any(is_bound_control(row) for row in mapping.values())
    if kind == "script_repo" and must_map and mapping and not confirmed:
        errors.append("script_repo has no confirmed+active control with uo.id; old role+uo_id is not a bind")
    if kind == "script_repo":
        if not str(doc.get("entry") or "").strip():
            errors.append("entry required")
        if not str(doc.get("case_arg") or "").strip():
            errors.append("case_arg (--case) required")
        modes = doc.get("modes") if isinstance(doc.get("modes"), dict) else {}
        precision = modes.get("precision") or doc.get("precision_cmd")
        perf = modes.get("perf") or doc.get("perf_cmd")
        if not precision:
            errors.append("precision run command missing")
        if not perf:
            errors.append("perf run command missing")
        golden_only = False
        for bucket in (modes.get("precision"), modes.get("perf"), [doc.get("precision_cmd"), doc.get("perf_cmd")]):
            joined = " ".join(str(x) for x in (bucket or []) if x)
            if "--golden-only" in joined and "only_grad" not in joined:
                golden_only = True
        if golden_only:
            errors.append("precision mode must not be recorded as --golden-only")
        domains = doc.get("domains") if isinstance(doc.get("domains"), dict) else doc.get("value_domains")
        if not isinstance(domains, dict) or not domains:
            errors.append("value domains missing")
        if "golden" not in doc:
            errors.append("golden required")
        if "compare" not in doc and "script_compare" not in doc:
            errors.append("script compare required")
        if "generate_inputs" not in doc:
            errors.append("generate_inputs required")
    _COMPARE = frozenset({"match", "tighter_profile", "tighter_operator", "mismatch"})
    domains = doc.get("domains") if isinstance(doc.get("domains"), dict) else {}
    for key, row in domains.items():
        if not isinstance(row, dict):
            continue
        cmp = str(row.get("compare") or "").strip()
        if cmp and cmp not in _COMPARE:
            errors.append(f"domains.{key}.compare {cmp!r} not in match|tighter_profile|tighter_operator|mismatch")
    call = doc.get("call") if isinstance(doc.get("call"), dict) else {}
    kind = str(call.get("kind") or "").strip()
    if kind and kind not in {"pta", "aclnn", "mixed"}:
        errors.append(f"call.kind {kind!r} not in pta|aclnn|mixed")
    return errors


def parse_plan_fence(text: str) -> dict[str, Any]:
    matches = list(_FENCE_RE.finditer(text or ""))
    if not matches:
        raise ProductError("plan.md has no yaml fence", ask="plan_invalid")
    body = matches[-1].group(1)
    try:
        import yaml

        doc = yaml.safe_load(body)
    except Exception as exc:  # noqa: BLE001
        raise ProductError(f"plan.md yaml fence parse failed: {exc}") from exc
    if not isinstance(doc, dict):
        raise ProductError("plan.md yaml fence is not a mapping")
    return doc


def load_plan(tg_root: Path) -> tuple[str, dict[str, Any]]:
    path = plan_path(tg_root)
    if not path.is_file():
        raise ProductError(
            "missing tg/plan.md; run /tg-plan",
            ask="plan_required",
            payload={"path": path.as_posix(), "next": "/tg-init then /tg-plan"},
        )
    text = path.read_text(encoding="utf-8")
    return text, parse_plan_fence(text)


def pending_test_harness_gap(text: str, fence: dict[str, Any]) -> bool:
    """Fence YAML is the only gate. Prose headings are explanation, not state."""
    del text
    block = fence.get("test_harness_gap")
    if not isinstance(block, dict) or not block:
        block = fence.get("harness_intent")
    if not isinstance(block, dict) or not block:
        return False
    return not bool(block.get("done"))


def pending_harness_intent(text: str, fence: dict[str, Any]) -> bool:
    """Deprecated alias of pending_test_harness_gap."""
    return pending_test_harness_gap(text, fence)


_EVIDENCE_KINDS = frozenset({"replay_field", "derived", "dispatch_map", "probe", "source_proof"})
_LADDER_LEVELS = ("L0", "L1", "L2", "L3")
_PLAN_PROSE_HEADINGS = ("测什么", "覆盖什么", "怎么判定")
_OBSERVE_PREFIXES = ("case.", "replay.", "probe.")


def validate_plan_prose(text: str) -> list[str]:
    errors: list[str] = []
    for heading in _PLAN_PROSE_HEADINGS:
        if not re.search(rf"^##\s*{re.escape(heading)}\s*$", text or "", re.MULTILINE):
            errors.append(f"plan.md missing heading {heading!r}")
    return errors


def _check_observe_field(field: str, *, owner: str) -> str | None:
    name = str(field or "").strip()
    if not name:
        return f"{owner}: observe field empty"
    bare = name.split(".")[-1].strip().lower()
    lowered = name.lower()
    if bare in _ORACLE_EVIDENCE_FIELDS or "precision" in lowered or lowered.endswith("md5"):
        return f"{owner}: evidence.field {name!r} is an oracle, not a Target observe field"
    if "." not in name:
        return None
    if not name.startswith(_OBSERVE_PREFIXES):
        return f"{owner}: observe field {name!r} must be case.*|replay.*|probe.* or a bare symbol"
    parts = name.split(".")
    if len(parts) != 2 or not parts[1]:
        return f"{owner}: observe field {name!r} must have exactly two segments (replay.field)"
    return None


def _check_controls(row: dict[str, Any], *, owner: str, allowed: set[str]) -> list[str]:
    errors: list[str] = []
    cols = [str(c).strip() for c in (row.get("controls") or []) if str(c).strip()]
    hint = row.get("construct_hint") if isinstance(row.get("construct_hint"), dict) else {}
    hint_cols = [str(c).strip() for c in (hint.get("columns") or []) if str(c).strip()]
    for col in cols + hint_cols:
        if col.lower() not in allowed:
            errors.append(f"{owner}: column {col!r} not in init.yaml (and not added_columns)")
    return errors


def _state_flip_columns(row: dict[str, Any]) -> list[str]:
    cols = [str(c).strip() for c in (row.get("controls") or []) if str(c).strip()]
    hint = row.get("construct_hint") if isinstance(row.get("construct_hint"), dict) else {}
    cols.extend(str(c).strip() for c in (hint.get("columns") or []) if str(c).strip())
    return cols


def _require_bound_controls(
    row: dict[str, Any],
    *,
    owner: str,
    allowed: set[str],
    mapping: dict[str, Any] | None,
) -> list[str]:
    """Any column that claims to flip implementation state must be a bound control."""
    errors = _check_controls(row, owner=owner, allowed=allowed)
    if mapping is None:
        return errors
    for col in _state_flip_columns(row):
        mrow = _mapping_row_for(mapping, col)
        if not is_bound_control(mrow):
            errors.append(
                f"{owner}: control {col!r} is not confirmed+active; "
                "mark untestable + needs_binding"
            )
    return errors


def _mapping_row_for(mapping: dict[str, Any], col: str) -> Any:
    if col in mapping:
        return mapping[col]
    wanted = col.lower()
    for key, row in mapping.items():
        if str(key).strip().lower() == wanted:
            return row
    return None


def validate_plan_fence(
    fence: dict[str, Any],
    *,
    init_columns: list[str],
    init_mapping: Any = None,
    allow_legal_keys: bool = False,
    observe_fields: set[str] | None = None,
) -> list[str]:
    from testcase_agent.coverage.predicate import validate_predicate

    errors: list[str] = []
    schema = str(fence.get("schema") or fence.get("version") or "")
    if schema != PLAN_SCHEMA:
        errors.append(f"plan schema {schema!r} unexpected; want {PLAN_SCHEMA}")
    if fence.get("variables") is not None:
        errors.append("variables removed; use targets / dimensions / guards")
    if fence.get("direction") is not None:
        errors.append("direction removed; use predicate + optional construct_hint")
    if fence.get("ladder") is not None:
        errors.append("ladder removed; use coverage.L0|L1|L2|L3")
    if fence.get("obligations"):
        errors.append("obligations are compiled by the engine; do not put them in plan.md")
    allowed = {c.lower() for c in init_columns}
    extra_cols = {
        str(c).strip()
        for c in (fence.get("added_columns") or [])
        if str(c).strip()
    }
    allowed |= {c.lower() for c in extra_cols}
    if str(fence.get("mode") or "").strip() in {"tilingkey_full_coverage", "T=D", "t_equals_d"}:
        errors.append("tilingkey_full_coverage / T=D is not a plan mode")

    targets = fence.get("targets") or []
    if not isinstance(targets, list) or not targets:
        errors.append("targets empty; at least one Target")
        return errors
    target_ids: set[str] = set()
    for idx, row in enumerate(targets):
        if not isinstance(row, dict):
            errors.append(f"targets[{idx}] is not a mapping")
            continue
        tid = str(row.get("id") or "").strip()
        if not tid:
            errors.append(f"targets[{idx}] missing id")
            continue
        if tid in target_ids:
            errors.append(f"duplicate target id {tid}")
        target_ids.add(tid)
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        kind = str(evidence.get("kind") or "").strip()
        if kind not in _EVIDENCE_KINDS:
            errors.append(f"{tid}: evidence.kind must be replay_field|derived|dispatch_map|probe|source_proof")
        field = str(evidence.get("field") or "").strip()
        if kind in {"replay_field", "probe"} and not field:
            errors.append(f"{tid}: evidence.field required")
        if field:
            err = _check_observe_field(field, owner=tid)
            if err:
                errors.append(err)
        if kind == "derived":
            pred = evidence.get("predicate") or evidence.get("expr")
            errors.extend(validate_predicate(pred, path=f"{tid}.evidence.predicate"))

    dim_ids: set[str] = set()
    for idx, row in enumerate(fence.get("dimensions") or []):
        if not isinstance(row, dict):
            errors.append(f"dimensions[{idx}] is not a mapping")
            continue
        did = str(row.get("id") or "").strip()
        if not did:
            errors.append(f"dimensions[{idx}] missing id")
            continue
        if did in dim_ids:
            errors.append(f"duplicate dimension id {did}")
        dim_ids.add(did)
        tgt = str(row.get("target") or "").strip()
        if not tgt:
            errors.append(f"{did}: target required")
        elif tgt not in target_ids:
            errors.append(f"{did}: target {tgt!r} is not a declared Target")
        controls = [str(c).strip() for c in (row.get("controls") or []) if str(c).strip()]
        if not controls:
            errors.append(f"{did}: controls required")
        bound_mapping = mapping_as_dict(init_mapping) if init_mapping is not None else None
        errors.extend(
            _require_bound_controls(
                row, owner=did, allowed=allowed, mapping=bound_mapping
            )
        )
        parts = row.get("partitions") or []
        if not isinstance(parts, list) or len(parts) < 2:
            errors.append(f"{did}: need >=2 partitions")
        seen_parts: set[str] = set()
        for pidx, part in enumerate(parts if isinstance(parts, list) else []):
            if not isinstance(part, dict):
                errors.append(f"{did}.partitions[{pidx}] is not a mapping")
                continue
            pid = str(part.get("id") or "").strip()
            if not pid:
                errors.append(f"{did}.partitions[{pidx}] missing id")
                continue
            if pid in seen_parts:
                errors.append(f"{did}: duplicate partition {pid}")
            seen_parts.add(pid)
            errors.extend(validate_predicate(part.get("predicate"), path=f"{did}.{pid}.predicate"))
        classifier = row.get("classifier") if isinstance(row.get("classifier"), dict) else {}
        for req in classifier.get("requires") or []:
            err = _check_observe_field(str(req), owner=f"{did}.classifier")
            if err:
                errors.append(err)

    guard_ids: set[str] = set()
    for idx, row in enumerate(fence.get("guards") or []):
        if not isinstance(row, dict):
            errors.append(f"guards[{idx}] is not a mapping")
            continue
        gid = str(row.get("id") or "").strip()
        if not gid:
            errors.append(f"guards[{idx}] missing id")
            continue
        if gid in guard_ids:
            errors.append(f"duplicate guard id {gid}")
        guard_ids.add(gid)
        tgt = str(row.get("target") or "").strip()
        if tgt not in target_ids:
            errors.append(f"{gid}: must bind to a declared Target")
        if not (row.get("controls") or []):
            errors.append(f"{gid}: controls required")
        bound_mapping = mapping_as_dict(init_mapping) if init_mapping is not None else None
        errors.extend(
            _require_bound_controls(
                row, owner=gid, allowed=allowed, mapping=bound_mapping
            )
        )
        errors.extend(validate_predicate(row.get("predicate"), path=f"{gid}.predicate"))
        if not isinstance(row.get("negate_hint"), dict) or not row.get("negate_hint"):
            errors.append(f"{gid}: negate_hint required")

    cov = fence.get("coverage") if isinstance(fence.get("coverage"), dict) else {}
    if not cov:
        errors.append("coverage missing; need L0|L1|L2|L3")
    else:
        for level in _LADDER_LEVELS:
            if level not in cov and str(cov.get("enumerate") or "") != "legal_keys":
                errors.append(f"coverage.{level} missing")

        def _dim_refs(raw: Any) -> list[str]:
            if isinstance(raw, dict):
                raw = raw.get("dimensions") or raw.get("dims") or raw.get("guards") or []
            if not isinstance(raw, list):
                return []
            out: list[str] = []
            for item in raw:
                if isinstance(item, dict):
                    out.extend(_dim_refs(item.get("dims") or item.get("dimensions") or item.get("id")))
                elif isinstance(item, list):
                    out.extend(str(x).strip() for x in item if str(x).strip())
                else:
                    vid = str(item or "").strip()
                    if vid:
                        out.append(vid)
            return out

        for did in _dim_refs(cov.get("L0")):
            if did not in dim_ids:
                errors.append(f"coverage.L0 unknown dimension {did}")
        l1 = cov.get("L1")
        combos = (l1.get("combinations") if isinstance(l1, dict) else l1) or []
        if isinstance(combos, list):
            for combo in combos:
                ids = _dim_refs(combo)
                for did in ids:
                    if did not in dim_ids:
                        errors.append(f"coverage.L1 unknown dimension {did}")
                if ids and (len(ids) != 2 or len(set(ids)) != 2):
                    errors.append(
                        f"coverage.L1 must name exactly two unique Dimensions, got {ids}"
                    )
                if isinstance(combo, dict) and ids and not str(combo.get("reason") or "").strip():
                    errors.append("coverage.L1 combination missing reason")
        l2_block = cov.get("L2")
        l2_items = (
            (l2_block.get("tuples") or l2_block.get("combinations") or [])
            if isinstance(l2_block, dict)
            else (l2_block or [])
        )
        for item in l2_items:
            ids = _dim_refs(item)
            for did in ids:
                if did not in dim_ids:
                    errors.append(f"coverage.L2 unknown dimension {did}")
            if ids and (len(ids) < 3 or len(set(ids)) != len(ids)):
                errors.append(
                    f"coverage.L2 must name unique Dimensions (len>=3), got {ids}"
                )
        for gid in _dim_refs(cov.get("L3")):
            if gid not in guard_ids:
                errors.append(f"coverage.L3 unknown guard {gid}")
        if str(cov.get("enumerate") or "").strip() not in {"", "legal_keys"}:
            errors.append("coverage.enumerate must be omitted or legal_keys")
        elif str(cov.get("enumerate") or "").strip() == "legal_keys" and not allow_legal_keys:
            errors.append("coverage.enumerate: legal_keys is not authorized; pin enumerate: legal_keys")

    untestable = fence.get("untestable") or []
    if untestable and not isinstance(untestable, list):
        errors.append("untestable must be a list")
    elif isinstance(untestable, list):
        for idx, row in enumerate(untestable):
            if not isinstance(row, dict):
                errors.append(f"untestable[{idx}] is not a mapping")
                continue
            if not str(row.get("reason") or "").strip():
                errors.append(f"untestable[{idx}] missing reason")
    from testcase_agent.coverage.contract import validate_executability

    bound_mapping = mapping_as_dict(init_mapping) if init_mapping is not None else None
    errors.extend(
        validate_executability(
            fence,
            init_columns=list(init_columns),
            mapping=bound_mapping,
            observe_fields=observe_fields,
        )
    )
    return errors


_APPROVAL_META = frozenset(
    {
        "approved",
        "approved_at",
        "decision",
        "plan_hash",
        "run_id",
        "workflow_id",
        "phase",
        "action_id",
        "actor_id",
        "role_id",
        "action_session_id",
        "lease_id",
        "prepare_nonce_hash",
    }
)


def plan_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def semantic_plan_hash(fence: dict[str, Any]) -> str:
    """Hash Plan semantics, excluding approval stamps so validate/approve can bind."""
    import yaml

    payload = {k: v for k, v in (fence or {}).items() if k not in _APPROVAL_META}
    blob = yaml.safe_dump(payload, allow_unicode=True, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def is_plan_approved(fence: dict[str, Any]) -> bool:
    if fence.get("approved") is True:
        return True
    decision = str(fence.get("decision") or "").strip().lower()
    return decision in {"approve", "approved"}


def worklog_open_ids(text: str) -> list[str]:
    match = _OPEN_RE.search(text or "")
    if not match:
        return []
    raw = match.group(1).strip()
    if not raw:
        return []
    parts = [p.strip().strip("'\"") for p in raw.split(",")]
    return [p for p in parts if p]


def cases_path(tg_root: Path, table_kind: str) -> Path:
    kind = str(table_kind or "csv").strip().lower()
    if kind == "xls":
        return Path(tg_root) / "cases.xls"
    if kind == "xlsx":
        return Path(tg_root) / "cases.xlsx"
    return Path(tg_root) / "cases.csv"


def write_cases_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> Path:
    import csv

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: "" if row.get(c) is None else str(row.get(c)) for c in columns})
    return path


def write_cases_table(
    path: Path,
    columns: list[str],
    rows: list[dict[str, Any]],
    *,
    table_kind: str,
) -> Path:
    kind = str(table_kind or "csv").strip().lower()
    if kind == "csv":
        return write_cases_csv(path, columns, rows)
    if kind == "xlsx":
        try:
            from openpyxl import Workbook
        except ImportError as exc:  # pragma: no cover
            raise ProductError("openpyxl required to write xlsx") from exc
        wb = Workbook()
        ws = wb.active
        ws.append(list(columns))
        for row in rows:
            ws.append(["" if row.get(c) is None else str(row.get(c)) for c in columns])
        path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(path)
        return path
    if kind == "xls":
        try:
            import xlwt
        except ImportError as exc:  # pragma: no cover
            raise ProductError("xlwt required to write xls") from exc
        book = xlwt.Workbook()
        sheet = book.add_sheet("cases")
        for i, col in enumerate(columns):
            sheet.write(0, i, col)
        for r, row in enumerate(rows, start=1):
            for c, col in enumerate(columns):
                val = row.get(col)
                sheet.write(r, c, "" if val is None else str(val))
        path.parent.mkdir(parents=True, exist_ok=True)
        book.save(str(path))
        return path
    raise ProductError(f"unsupported table_kind {table_kind!r}")


def dump_init(tg_root: Path, doc: dict[str, Any]) -> Path:
    path = init_path(tg_root)
    payload = dict(doc)
    payload.setdefault("schema", INIT_SCHEMA)
    write_yaml(path, payload)
    return path


def collect_intent_sources(project_root: Path, *, architecture: str = "") -> dict[str, Any]:
    """Read optional CE markdown / handoff. Never writes a TG product. No CE yaml."""
    sources: list[dict[str, Any]] = []
    root = Path(project_root).expanduser().resolve()
    arch = str(architecture or "").strip()
    agent = root / ".ascendc-pilot" / arch if arch else root / ".ascendc-pilot"
    plan_dir = agent / "ce" / "plan"
    if plan_dir.is_dir():
        for plan_md in sorted(plan_dir.glob("*_plan.md")):
            if plan_md.is_file():
                sources.append({"kind": "ce_plan", "path": plan_md.as_posix()})
    handoff = agent / "session_handoff.md"
    if handoff.is_file():
        sources.append({"kind": "session_handoff", "path": handoff.as_posix()})
    return {"schema": "tg-intent-sources/v1", "sources": sources}
