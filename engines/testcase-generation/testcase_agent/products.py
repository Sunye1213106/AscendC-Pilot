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
PLAN_SCHEMA = "tg-plan/v1"
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
    mapping = doc.get("mapping") if isinstance(doc.get("mapping"), dict) else {}
    must_map = require_mapping if require_mapping is not None else kind == "script_repo"
    if must_map and not mapping:
        errors.append("script_repo mapping is empty; bind columns to script and UO identifiers")
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


def pending_harness_intent(text: str, fence: dict[str, Any]) -> bool:
    if fence.get("harness_intent_pending") is True:
        return True
    heading = re.search(r"^#\s*harness_intent\b", text, re.MULTILINE | re.IGNORECASE)
    if not heading:
        return False
    if fence.get("harness_intent_done") is True:
        return False
    block = fence.get("harness_intent")
    if isinstance(block, dict) and block:
        return not bool(block.get("done"))
    return True


def validate_plan_fence(fence: dict[str, Any], *, init_columns: list[str]) -> list[str]:
    errors: list[str] = []
    schema = str(fence.get("schema") or fence.get("version") or "")
    if schema not in {PLAN_SCHEMA, "1", "1.0", ""}:
        # version: 1 is accepted; schema tg-plan/v1 preferred
        if schema not in {PLAN_SCHEMA, "1"}:
            errors.append(f"plan schema {schema!r} unexpected")
    allowed = {c.lower() for c in init_columns}
    extra_cols = {
        str(c).strip()
        for c in (fence.get("added_columns") or [])
        if str(c).strip()
    }
    allowed |= {c.lower() for c in extra_cols}
    cover = fence.get("cover") if isinstance(fence.get("cover"), dict) else {}
    budget = cover.get("budget")
    if budget is not None:
        try:
            if int(budget) <= 0:
                errors.append("cover.budget must be positive")
        except (TypeError, ValueError):
            errors.append("cover.budget is not an int")
    obligations = fence.get("obligations") or []
    if not isinstance(obligations, list):
        errors.append("obligations must be a list")
        return errors
    seen: set[str] = set()
    for idx, row in enumerate(obligations):
        if not isinstance(row, dict):
            errors.append(f"obligations[{idx}] is not a mapping")
            continue
        oid = str(row.get("id") or "").strip()
        if not oid:
            errors.append(f"obligations[{idx}] missing id")
            continue
        if oid in seen:
            errors.append(f"duplicate obligation id {oid}")
        seen.add(oid)
        if not str(row.get("why") or "").strip():
            errors.append(f"{oid}: why required")
        klass = str(row.get("class") or "").strip().lower()
        if klass == "untestable":
            errors.append(f"{oid}: put untestable rows in untestable:, not obligations")
        elif klass not in {"replay", "derived"}:
            errors.append(f"{oid}: class must be replay|derived")
        control = row.get("control") if isinstance(row.get("control"), dict) else {}
        cols = [str(c).strip() for c in (control.get("columns") or []) if str(c).strip()]
        if not cols:
            errors.append(f"{oid}: control.columns empty")
        if not str(control.get("recipe") or "").strip():
            errors.append(f"{oid}: control.recipe required")
        for col in cols:
            if col.lower() not in allowed:
                errors.append(f"{oid}: column {col!r} not in init.yaml (and not added_columns)")
        hit = row.get("hit")
        if not isinstance(hit, dict) or not hit:
            errors.append(f"{oid}: hit missing")
        uo = row.get("uo") if isinstance(row.get("uo"), dict) else {}
        if not str(uo.get("span") or uo.get("query") or "").strip():
            errors.append(f"{oid}: uo.query/span required")
        cover = row.get("cover")
        level = ""
        if isinstance(cover, str):
            level = cover
        elif isinstance(cover, dict):
            level = str(cover.get("level") or cover.get("ladder") or "")
        if level and str(level).upper() not in {"L0", "L1", "L2", "L3"}:
            errors.append(f"{oid}: cover must be L0|L1|L2|L3")
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
