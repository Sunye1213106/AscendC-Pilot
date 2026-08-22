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
PLAN_SCHEMA = "tg-plan/v2"
WORKLOG_SCHEMA = "tg-worklog/v1"

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


_ROLES_OPTIONAL_UO = frozenset({"script_meta", "result_sink", "feature"})
_CALL_KINDS = frozenset({"pta", "aclnn", "mixed"})
_MAPPING_WRAPPER_KEYS = frozenset({"columns", "rows", "items", "mapping"})


def _ingest_mapping_row(out: dict[str, Any], item: dict[str, Any], *, fallback: str = "") -> None:
    col = str(item.get("column") or fallback).strip()
    if not col:
        return
    row = dict(item)
    row.setdefault("column", col)
    out[col] = row


def _drop_unfilled_mapping(out: dict[str, Any]) -> dict[str, Any]:
    """Form cells with explicit empty role are not yet bound."""
    kept: dict[str, Any] = {}
    for key, row in out.items():
        if isinstance(row, dict) and "role" in row and not str(row.get("role") or "").strip():
            continue
        kept[key] = row
    return kept


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
            if not label:
                continue
            row = {"uo_id": value, "column": label}
            out[label] = row
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


def validate_bind_part(bind: Any) -> list[str]:
    """Structural gate for `inspect yaml` / Primary PASS: kind enum + mapping shape.

    Identifier values (empty or wrong uo_id) are Primary content, not this gate.
    """
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
    must_map = require_mapping if require_mapping is not None else kind == "script_repo"
    if must_map and not mapping:
        errors.append("script_repo mapping is empty; bind columns to script and UO identifiers")
    api_mapped = False
    for col, row in mapping.items():
        if not isinstance(row, dict):
            continue
        role = str(row.get("role") or "api_arg").strip() or "api_arg"
        if role in _ROLES_OPTIONAL_UO:
            continue
        api_mapped = True
    if kind == "script_repo" and must_map and mapping and not api_mapped:
        errors.append("script_repo API argument columns are unbound; script_meta-only mapping is not enough")
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
    if fence.get("test_harness_gap_pending") is True or fence.get("harness_intent_pending") is True:
        return True
    heading = re.search(
        r"^#\s*(test_harness_gap|harness_intent)\b", text, re.MULTILINE | re.IGNORECASE
    )
    if not heading:
        return False
    if fence.get("test_harness_gap_done") is True or fence.get("harness_intent_done") is True:
        return False
    block = fence.get("test_harness_gap")
    if not isinstance(block, dict) or not block:
        block = fence.get("harness_intent")
    if isinstance(block, dict) and block:
        return not bool(block.get("done"))
    return True


def pending_harness_intent(text: str, fence: dict[str, Any]) -> bool:
    """Deprecated alias of pending_test_harness_gap."""
    return pending_test_harness_gap(text, fence)


_EVIDENCE_KINDS = frozenset({"replay_field", "derived", "dispatch_map", "probe", "source_proof"})
_LADDER_LEVELS = ("L0", "L1", "L2", "L3")
_PLAN_PROSE_HEADINGS = ("测什么", "第一轮怎么造", "怎么知道打到了")


def validate_plan_prose(text: str) -> list[str]:
    errors: list[str] = []
    for heading in _PLAN_PROSE_HEADINGS:
        if not re.search(rf"^##\s*{re.escape(heading)}\s*$", text or "", re.MULTILINE):
            errors.append(f"plan.md missing heading {heading!r}")
    return errors


def validate_plan_fence(fence: dict[str, Any], *, init_columns: list[str]) -> list[str]:
    errors: list[str] = []
    schema = str(fence.get("schema") or fence.get("version") or "")
    if schema != PLAN_SCHEMA:
        errors.append(f"plan schema {schema!r} unexpected; want {PLAN_SCHEMA}")
    if fence.get("obligations"):
        errors.append("obligations removed; use variables")
    allowed = {c.lower() for c in init_columns}
    extra_cols = {
        str(c).strip()
        for c in (fence.get("added_columns") or [])
        if str(c).strip()
    }
    allowed |= {c.lower() for c in extra_cols}
    if str(fence.get("mode") or "").strip() in {"tilingkey_full_coverage", "T=D", "t_equals_d"}:
        errors.append("tilingkey_full_coverage / T=D is not a plan mode")
    variables = fence.get("variables") or []
    if not isinstance(variables, list):
        errors.append("variables must be a list")
        return errors
    if not variables:
        errors.append("variables empty; at least one independent test variable")
        return errors
    seen: set[str] = set()
    for idx, row in enumerate(variables):
        if not isinstance(row, dict):
            errors.append(f"variables[{idx}] is not a mapping")
            continue
        vid = str(row.get("id") or "").strip()
        if not vid:
            errors.append(f"variables[{idx}] missing id")
            continue
        if vid in seen:
            errors.append(f"duplicate variable id {vid}")
        seen.add(vid)
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        kind = str(evidence.get("kind") or "").strip()
        if kind not in _EVIDENCE_KINDS:
            errors.append(f"{vid}: evidence.kind must be replay_field|derived|dispatch_map|probe|source_proof")
        direction = row.get("direction") if isinstance(row.get("direction"), dict) else {}
        cols = [str(c).strip() for c in (direction.get("columns") or []) if str(c).strip()]
        for col in cols:
            if col.lower() not in allowed:
                errors.append(f"{vid}: column {col!r} not in init.yaml (and not added_columns)")
    ladder = fence.get("ladder") if isinstance(fence.get("ladder"), dict) else {}
    if not ladder:
        errors.append("ladder missing; need L0|L1|L2|L3")
    else:
        for level in _LADDER_LEVELS:
            if level not in ladder:
                errors.append(f"ladder.{level} missing")
        l0 = ladder.get("L0") or []
        l1 = ladder.get("L1") or []
        if not l0:
            errors.append("ladder.L0 empty")
        if len(variables) >= 2 and not l1:
            errors.append("ladder.L1 empty when two or more variables; default solve generates L0+L1")
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
    return errors


def plan_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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
