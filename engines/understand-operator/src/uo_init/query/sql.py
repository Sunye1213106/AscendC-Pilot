# -*- coding: utf-8 -*-
"""Indexed SQLite query over a committed ``.uo`` product.

Agent-facing ``acp uo-query`` must never hydrate the full CodeMap.  All
navigation uses ``entity`` / ``relation`` / ``source_span`` indexes.  Dump /
audit helpers that truly need the in-memory graph stay on
:class:`uo_init.query.engine.CodeMapQuery` and are lazy here.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import deque
from pathlib import Path
from typing import Any, Iterable

from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.query.evidence import (
    USEFUL_EDGE_KINDS,
    bucket_hits,
    field_edge_kinds,
    is_flag_sync_api_name,
    is_kernel_api_name,
    is_tque_api_name,
    project_entity,
    project_relation,
)
from uo_init.query.legal_key_cache import _pattern_filters
from uo_init.source_locator import locations_from_attr_sites

SNIPPET_LINES = 40
SNIPPET_BEFORE = 3
BRANCH_OUTER_BEFORE = 16
PRIMARY_CANDIDATES = 3
MAX_PAYLOAD_CHARS = 12_000
MAX_REL_HOPS = 4
PACKING_RHS_TRIM = 400
_GET_OFFSET_RE = re.compile(r"\bGet\w*Offset\b")
_DATA_MOVE_RE = re.compile(r"\bDataCopy(?:Pad)?\b|\bLoadData\b")
_TRIVIAL_RHS_RE = re.compile(r"^(?:true|false|0|1|nullptr)?$", re.IGNORECASE)
NEIGHBOR_REL_KINDS = (
    "SELECTS",
    "CONTROLS",
    "CALLS",
    "SIGNALS",
    "AWAITS",
    "DECLARES",
    "WRAPS",
    "BINDS",
    "READS",
    "WRITES",
)
_EXACT_KINDS = {EntityKind.TYPE.value}
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_LEGACY_KIND_MAP: dict[str, set[str]] = {
    "Variable": {"VARIABLE", "COMPILE_VAR", "MACRO"},
    "Input": {"INPUT"},
    "OptionalInput": {"INPUT"},
    "Output": {"OUTPUT"},
    "TilingDataField": {"TILING_FIELD"},
    "TilingKeyDim": {"TILING_KEY"},
    "HostBranch": {"BRANCH"},
    "KernelBranch": {"BRANCH"},
    "Predicate": {"PREDICATE"},
    "TemplateBinding": {"TEMPLATE", "TEMPLATE_ARG", "TEMPLATE_INSTANCE"},
}


def _kind_names(kinds: Iterable[str]) -> set[str]:
    out: set[str] = set()
    valid = {k.value for k in EntityKind}
    for raw in kinds:
        text = str(raw or "").strip()
        if not text:
            continue
        if text in _LEGACY_KIND_MAP:
            out.update(_LEGACY_KIND_MAP[text])
        upper = text.upper()
        if upper in valid:
            out.add(upper)
    return out


def _parse_data(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _row_get(row: sqlite3.Row, key: str, default: Any = None) -> Any:
    try:
        value = row[key]
    except (IndexError, KeyError):
        return default
    return default if value is None else value


def _norm_file(file: str) -> str:
    text = str(file or "").replace("\\", "/")
    if not text:
        return ""
    for marker in ("/op_kernel/", "/op_host/", "/include/"):
        idx = text.lower().find(marker)
        if idx >= 0:
            return text[idx + 1 :]
    if ":" in text[:3]:
        return Path(text).name
    return text.lstrip("./")


def _architecture_from_name(path: Path) -> str:
    name = path.name
    if not name.endswith(".uo"):
        return ""
    stem = name[: -len(".uo")]
    parts = stem.rsplit(".", 1)
    if len(parts) == 2 and parts[1].startswith("arch"):
        return parts[1]
    return ""


def _op_root_from_product(product: Path) -> Path | None:
    parts = product.resolve().parts
    try:
        idx = parts.index(".ascendc-pilot")
    except ValueError:
        return None
    if idx <= 0:
        return None
    return Path(*parts[:idx])


def _is_truncated_branch_text(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    if "..." in raw:
        return True
    if raw.count("<") != raw.count(">"):
        return True
    return len(raw) > 80 and "<" in raw


def _keep_branch(kind: str, name: str, data: dict[str, Any]) -> bool:
    if kind != EntityKind.BRANCH.value:
        return True
    cond = str(data.get("condition") or name or "")
    return not _is_truncated_branch_text(cond)


def _last_ident(name: str) -> str:
    text = str(name or "").replace(".", "::")
    return text.split("::")[-1].strip()


def _name_rank(
    name: str,
    eid: str,
    needle: str,
    *,
    exact_kind: bool,
    kind: str = "",
) -> int | None:
    if not needle:
        return 3
    low_name = str(name or "").lower()
    ident = _last_ident(low_name)
    id_ident = _last_ident(str(eid or "").replace("/", "::"))
    member = low_name.startswith(needle + "::")
    exact = low_name == needle or ident == needle or id_ident == needle
    if member:
        return 0
    if exact:
        return 1 if str(kind or "").upper() == EntityKind.METHOD.value else 0
    if exact_kind:
        return None
    if low_name.startswith(needle) or ident.startswith(needle):
        return 2
    if needle in low_name:
        return 3
    return None


def _prefer_src_id(eid: str) -> int:
    text = str(eid or "")
    if text.startswith(("SRCTYPE::", "SRCFIELD::", "SRCKDEF")):
        return 0
    if text.startswith("TYPE_"):
        return 2
    return 1


def _definition_rank(kind: str, name: str, eid: str, facts: dict[str, Any] | None) -> tuple[int, int]:
    src = _prefer_src_id(eid)
    kind_u = str(kind or "").upper()
    facts = facts if isinstance(facts, dict) else {}
    if kind_u == EntityKind.METHOD.value:
        use = 0 if "::" in str(name or "") else 2
    elif kind_u == EntityKind.TYPE.value:
        cpp = str(facts.get("cpp_kind") or "").lower()
        role = str(facts.get("role") or "")
        use = 0 if cpp in {"class", "struct"} or role == "storage_wrapper_type" else 1
    else:
        use = 0
    return (src, use)


def _agent_sort_key(hit: dict[str, Any], needle: str) -> tuple[Any, ...]:
    kind = str(hit.get("kind") or "")
    name = str(hit.get("name") or "")
    eid = str(hit.get("id") or "")
    facts = hit.get("facts") if isinstance(hit.get("facts"), dict) else {}
    match = _name_rank(name, eid, needle.lower().strip(), exact_kind=False, kind=kind)
    if match is None:
        match = 9
    src, use = _definition_rank(kind, name, eid, facts)
    return (match, src, use, int(hit.get("line_start") or 0), eid)


def _drop_redundant_type_hashes(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    src_names = {
        str(hit.get("name") or "").lower()
        for hit in hits
        if str(hit.get("id") or "").startswith("SRCTYPE::")
    }
    if not src_names:
        return hits
    return [
        hit
        for hit in hits
        if not (
            str(hit.get("id") or "").startswith("TYPE_")
            and str(hit.get("name") or "").lower() in src_names
        )
    ]


def _diversify_by_function(
    hits: list[dict[str, Any]], *, limit: int
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    counts: dict[str, int] = {}
    exemplars: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in hits:
        facts = hit.get("facts") if isinstance(hit.get("facts"), dict) else {}
        fn = str(facts.get("function") or "").strip() or "(unknown)"
        counts[fn] = counts.get(fn, 0) + 1
        if fn in seen:
            continue
        seen.add(fn)
        if len(exemplars) < max(0, int(limit)):
            exemplars.append(hit)
    return exemplars, counts


def _trivial_rhs(rhs: str) -> bool:
    return bool(_TRIVIAL_RHS_RE.match(str(rhs or "").strip().rstrip(";")))


def _hit_expr(hit: dict[str, Any]) -> str:
    facts = hit.get("facts") if isinstance(hit.get("facts"), dict) else {}
    for key in ("rhs", "expression", "packing_expr"):
        text = str(facts.get(key) or "").strip()
        if text:
            return text
    return str(hit.get("name") or "").strip()


def _packing_site_sort_key(site: Any) -> tuple[Any, ...]:
    if not isinstance(site, dict):
        return (9, 9, 0, 9, 0)
    rhs = str(site.get("rhs") or "")
    fn = str(site.get("function") or "").strip()
    return (
        1 if _trivial_rhs(rhs) else 0,
        0 if fn else 1,
        -len(rhs),
        0 if site.get("guards") else 1,
        int(site.get("line") or 0),
    )


def _field_value_rank(hit: dict[str, Any]) -> tuple[Any, ...]:
    rhs = _hit_expr(hit)
    return (
        1 if _trivial_rhs(rhs) else 0,
        -len(rhs),
        -int(hit.get("line_start") or 0),
    )


def _write_site_sort_key(hit: dict[str, Any]) -> tuple[Any, ...]:
    rhs = _hit_expr(hit)
    return (
        1 if _trivial_rhs(rhs) else 0,
        -len(rhs),
        -int(hit.get("line_start") or 0),
        str(hit.get("id") or ""),
    )


def _branch_sort_key(hit: dict[str, Any]) -> tuple[Any, ...]:
    snippet = str(hit.get("snippet") or "")
    facts = hit.get("facts") if isinstance(hit.get("facts"), dict) else {}
    fn = str(facts.get("function") or "")
    line = int(hit.get("line_start") or 0)
    constexpr_n = snippet.count("if constexpr")
    fn_offset = 1 if fn.endswith("Offset") else 0
    body_assigns = 0
    body_lines = 0
    data_move = 0
    offset_calls = 0
    started = False
    hit_indent: int | None = None
    for raw in snippet.splitlines():
        no = _snippet_line_no(raw)
        text = raw.split(":", 1)[1] if no is not None and ":" in raw else raw
        if no is not None and line > 0 and no < line:
            continue
        stripped = text.strip()
        indent = len(text) - len(text.lstrip(" \t"))
        if not started:
            if no is not None and line > 0 and no != line:
                continue
            started = True
            hit_indent = indent
            if _DATA_MOVE_RE.search(text):
                data_move = 1
            continue
        if stripped.startswith("}") and hit_indent is not None and indent <= hit_indent:
            break
        if not stripped or stripped.startswith("//"):
            continue
        body_lines += 1
        if _DATA_MOVE_RE.search(text):
            data_move = 1
        offset_calls += len(_GET_OFFSET_RE.findall(text))
        if "=" in stripped and not stripped.lstrip().startswith(("if", "for", "while")):
            body_assigns += 1
    return (
        fn_offset,
        0 if data_move else 1,
        0 if constexpr_n >= 2 else 1,
        -min(body_assigns, 12),
        offset_calls,
        -body_lines,
        line,
        str(hit.get("id") or ""),
    )


def _branch_window_start(lines: list[str], centre: int) -> int:
    default = max(1, centre - SNIPPET_BEFORE)
    if centre <= 1 or centre > len(lines):
        return default
    hit = lines[centre - 1]
    hit_indent = len(hit) - len(hit.lstrip(" \t"))
    lo = max(0, centre - 1 - BRANCH_OUTER_BEFORE)
    for i in range(centre - 2, lo - 1, -1):
        raw = lines[i]
        stripped = raw.lstrip(" \t")
        if "if constexpr" not in stripped:
            continue
        indent = len(raw) - len(stripped)
        if indent < hit_indent:
            return i + 1
    return default


def _candidate_limit(limit: int) -> int:
    return max(0, min(int(limit), PRIMARY_CANDIDATES))


def _snippet_line_no(raw: str) -> int | None:
    prefix = str(raw or "").split(":", 1)[0].strip()
    if prefix.isdigit():
        return int(prefix)
    return None


def _snippet_covers_line(snippet: str, line: int) -> bool:
    want = int(line or 0)
    if want <= 0:
        return bool(str(snippet or "").strip())
    return any(_snippet_line_no(row) == want for row in str(snippet or "").splitlines())


def _clip_snippet_around_line(snippet: str, line: int, *, max_lines: int) -> str:
    rows = str(snippet or "").splitlines()
    if len(rows) <= max_lines:
        return str(snippet or "")
    idx = 0
    want = int(line or 0)
    if want > 0:
        for i, raw in enumerate(rows):
            if _snippet_line_no(raw) == want:
                idx = i
                break
    before = min(SNIPPET_BEFORE, idx)
    start = max(0, idx - before)
    end = min(len(rows), start + max_lines)
    if end - start < max_lines:
        start = max(0, end - max_lines)
    return "\n".join(rows[start:end])


def _cap_snippet(text: str, line_start: int) -> str:
    raw = str(text or "")
    if not raw.strip():
        return ""
    lines = raw.splitlines() or [raw]
    lines = lines[:SNIPPET_LINES]
    start = int(line_start or 0)
    if start <= 0 or (lines and lines[0][:1].isdigit() and (":" in lines[0][:8] or "|" in lines[0][:8])):
        return "\n".join(lines)
    return "\n".join(f"{start + offset}:{line}" for offset, line in enumerate(lines))


def _resolve_source_path(op_root: Path | None, file: str) -> Path | None:
    if not file:
        return None
    candidates: list[Path] = []
    rel = Path(str(file).replace("\\", "/"))
    if rel.is_file():
        candidates.append(rel)
    if op_root is not None:
        candidates.append(op_root / str(file).replace("\\", "/"))
        candidates.append(op_root / rel.name)
    return next((p for p in candidates if p.is_file()), None)


def _disk_window(
    op_root: Path | None,
    file: str,
    line: int,
    *,
    kind: str = "",
) -> str:
    if not file or int(line or 0) <= 0:
        return ""
    path = _resolve_source_path(op_root, file)
    if path is None:
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    centre = int(line)
    kind_u = str(kind or "").upper()
    if kind_u in {EntityKind.METHOD.value, EntityKind.FUNCTION.value}:
        start = centre
    elif kind_u == EntityKind.BRANCH.value:
        start = _branch_window_start(lines, centre)
    else:
        start = max(1, centre - SNIPPET_BEFORE)
    end = min(len(lines), start + SNIPPET_LINES - 1)
    if end < centre:
        end = min(len(lines), centre + SNIPPET_LINES - 1)
        start = max(1, min(start, centre))
    return "\n".join(f"{i}:{lines[i - 1]}" for i in range(start, end + 1))


def _rhs_looks_truncated(rhs: str) -> bool:
    text = str(rhs or "")
    if len(text) >= PACKING_RHS_TRIM:
        return True
    stripped = text.rstrip()
    return stripped.endswith(("&&", "||", "(", ",", "+"))


def _read_statement(op_root: Path | None, file: str, line: int) -> str:
    path = _resolve_source_path(op_root, str(file or ""))
    if path is None or int(line or 0) <= 0:
        return ""
    try:
        rows = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    start = int(line) - 1
    if start < 0 or start >= len(rows):
        return ""
    buf: list[str] = []
    for raw in rows[start : start + 24]:
        buf.append(raw.rstrip())
        if ";" in raw:
            break
    blob = "\n".join(buf)
    if "=" in blob:
        blob = blob.split("=", 1)[1]
    return blob.replace(";", "").strip()


def _template_block_rows(blob: Any) -> list[dict[str, Any]]:
    if not isinstance(blob, dict):
        return []
    for key in ("groups", "blocks", "rows", "template_blocks"):
        rows = blob.get(key)
        if isinstance(rows, list):
            return [r for r in rows if isinstance(r, dict)]
    return []


def _value_matches_domain(value: str, domain: Any) -> bool:
    want = str(value)
    if isinstance(domain, (list, tuple, set)):
        return any(str(v) == want for v in domain)
    return str(domain) == want


def _template_block_matches(row: dict[str, Any], filters: dict[str, str]) -> bool:
    fixed = row.get("fixed_fields") or {}
    domains = row.get("field_domains") or {}
    if not isinstance(fixed, dict):
        fixed = {}
    if not isinstance(domains, dict):
        domains = {}
    for name, value in filters.items():
        if name in fixed:
            if str(fixed[name]) != str(value):
                return False
            continue
        if name in domains:
            if not _value_matches_domain(str(value), domains[name]):
                return False
            continue
        return False
    return True


def _file_index_entry(hit: dict[str, Any]) -> dict[str, Any]:
    facts = hit.get("facts") if isinstance(hit.get("facts"), dict) else {}
    return {
        "id": hit.get("id"),
        "name": hit.get("name"),
        "line": hit.get("line_start"),
        "function": facts.get("function") or "",
    }


def _group_by_file(hits: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for hit in hits:
        file = str(hit.get("file") or "")
        if not file:
            continue
        grouped.setdefault(file, []).append(_file_index_entry(hit))
    return grouped


def _clip_hit_snippets(rows: list[Any], *, max_lines: int) -> None:
    for row in rows:
        if not isinstance(row, dict):
            continue
        snip = row.get("snippet")
        if not isinstance(snip, str) or snip.count("\n") + 1 <= max_lines:
            continue
        row["snippet"] = _clip_snippet_around_line(
            snip, int(row.get("line_start") or 0), max_lines=max_lines
        )


def _clip_snippets(payload: dict[str, Any], *, max_lines: int) -> None:
    for key in (
        "rows",
        "branches",
        "calls",
        "buffers",
        "hits",
        "locations",
        "keys",
        "templates",
        "candidates",
        "writers",
        "readers",
        "fields",
    ):
        rows = payload.get(key)
        if isinstance(rows, list):
            _clip_hit_snippets(rows, max_lines=max_lines)
    field = payload.get("field")
    if isinstance(field, dict):
        _clip_hit_snippets([field], max_lines=max_lines)


def _clip_relationships(payload: dict[str, Any], *, max_rels: int = MAX_REL_HOPS) -> None:
    for key in (
        "rows",
        "branches",
        "calls",
        "buffers",
        "hits",
        "locations",
        "keys",
        "templates",
        "fields",
    ):
        rows = payload.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            rels = row.get("relationships")
            if isinstance(rels, list) and len(rels) > max_rels:
                row["relationships"] = rels[:max_rels]


def _payload_size(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str))


def _fit_payload(payload: dict[str, Any], *, max_chars: int = MAX_PAYLOAD_CHARS) -> dict[str, Any]:
    if _payload_size(payload) <= max_chars:
        return payload
    out = dict(payload)
    out["truncated"] = True
    _clip_relationships(out)
    if _payload_size(out) <= max_chars:
        return out
    out.pop("edges", None)
    if _payload_size(out) <= max_chars:
        return out
    out.pop("files", None)
    if _payload_size(out) <= max_chars:
        return out
    for key in ("readers", "writers", "neighbors"):
        rows = out.get(key)
        if not isinstance(rows, list) or len(rows) <= PRIMARY_CANDIDATES:
            continue
        out[key] = rows[:PRIMARY_CANDIDATES]
        if _payload_size(out) <= max_chars:
            return out
    if _payload_size(out) <= max_chars:
        return out
    _clip_snippets(out, max_lines=12)
    if _payload_size(out) <= max_chars:
        return out
    for key in (
        "rows",
        "branches",
        "calls",
        "buffers",
        "hits",
        "locations",
        "keys",
        "templates",
        "macros_compile_vars",
        "template_blocks",
        "gaps",
        "tiling_data",
        "fields",
        "neighbors",
        "writers",
        "readers",
    ):
        rows = out.get(key)
        if not isinstance(rows, list) or len(rows) <= 1:
            continue
        while len(rows) > 1:
            rows.pop()
            probe = dict(out)
            probe[key] = rows
            if _payload_size(probe) <= max_chars:
                out[key] = rows
                return out
    return out


class UoSqlQuery:
    """Read-only query facade over ``*.uo`` SQLite indexes."""

    backend = "codemap"

    def __init__(self, product: str | Path):
        self.product = Path(product).expanduser().resolve()
        if not self.product.is_file() or self.product.suffix != ".uo":
            raise FileNotFoundError(self.product)
        self.database = self.product
        self._architecture = _architecture_from_name(self.product)
        self._op_root = _op_root_from_product(self.product)
        self._engine = None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self.product.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    @property
    def architecture(self) -> str:
        if self._architecture:
            return self._architecture
        from uo_init.store.reader import read_meta

        self._architecture = str(read_meta(self.product).get("architecture") or "")
        return self._architecture

    def _foreign_file(self, file: str) -> bool:
        text = str(file or "").replace("\\", "/")
        arch = self.architecture
        if not text or not arch:
            return False
        from uo_init.source_layout import is_other_arch_path

        return is_other_arch_path(Path(text), arch)

    def _hit(
        self,
        row: sqlite3.Row,
        *,
        why: str = "",
        distance: int | None = None,
        require_span_for_branch: bool = False,
        with_snippet: bool = True,
        with_rels: bool = False,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, Any] | None:
        data = _parse_data(_row_get(row, "data", "{}"))
        kind = str(_row_get(row, "kind") or "")
        name = str(_row_get(row, "name") or "")
        if not _keep_branch(kind, name, data):
            return None
        file = _norm_file(str(_row_get(row, "file") or ""))
        if self._foreign_file(file):
            return None
        mapping = {
            "id": _row_get(row, "id") or "",
            "kind": kind,
            "name": name,
            "status": _row_get(row, "status") or "",
            "file": file,
            "line_start": int(_row_get(row, "line_start") or 0),
            "line_end": int(_row_get(row, "line_end") or 0),
            "attrs": data,
        }
        hit = project_entity(
            mapping,
            why=why,
            distance=distance,
            require_span_for_branch=require_span_for_branch,
        )
        if hit is None:
            return None
        if with_snippet:
            orig = str(_row_get(row, "file") or "")
            snippet = str(_row_get(row, "snippet") or "")
            line = int(hit.get("line_start") or 0)
            thin = (not snippet.strip()) or snippet.count("\n") < 2
            numbered = bool(snippet) and snippet[:1].isdigit() and (
                ":" in snippet[:8] or "|" in snippet[:8]
            )
            if line > 0 and (thin or not _snippet_covers_line(snippet, line)):
                window = _disk_window(self._op_root, orig, line, kind=kind) or _disk_window(
                    self._op_root, file, line, kind=kind
                )
                if window:
                    snippet = window
                    numbered = True
            hit["snippet"] = snippet if numbered else _cap_snippet(snippet, line)
        if with_rels and conn is not None:
            rels = self._relationships(
                conn, str(hit.get("id") or ""), entity_kind=kind
            )
            if rels:
                hit["relationships"] = rels
        return hit

    def _relationships(
        self,
        conn: sqlite3.Connection,
        entity_id: str,
        *,
        limit: int = MAX_REL_HOPS,
        entity_kind: str = "",
    ) -> list[dict[str, Any]]:
        if not entity_id:
            return []
        placeholders = ",".join("?" for _ in NEIGHBOR_REL_KINDS)
        fetch = max(int(limit) * 4, 16)
        rows = conn.execute(
            f"""
            SELECT r.kind AS rel_kind, r.src AS src, r.dst AS dst,
                   e.id AS other_id, e.kind AS other_kind, e.name AS other_name,
                   e.file AS other_file, e.line_start AS other_line
            FROM relation r
            JOIN entity e ON e.id = CASE WHEN r.src = ? THEN r.dst ELSE r.src END
            WHERE (r.src = ? OR r.dst = ?) AND r.kind IN ({placeholders})
            ORDER BY r.kind, e.kind, e.name
            LIMIT ?
            """,
            (entity_id, entity_id, entity_id, *NEIGHBOR_REL_KINDS, fetch),
        ).fetchall()
        skip_tpl = str(entity_kind or "").upper() == EntityKind.TILING_KEY.value
        out: list[dict[str, Any]] = []
        for row in rows:
            other_kind = str(row["other_kind"] or "")
            other_name = str(row["other_name"] or "")
            rel_kind = str(row["rel_kind"] or "")
            if skip_tpl and rel_kind == "BINDS" and (
                other_kind == EntityKind.TEMPLATE.value or other_name.startswith("ARGS_SEL")
            ):
                continue
            out.append(
                {
                    "kind": rel_kind,
                    "src": str(row["src"] or ""),
                    "dst": str(row["dst"] or ""),
                    "other_id": str(row["other_id"] or ""),
                    "other_kind": other_kind,
                    "other_name": other_name,
                    "file": _norm_file(str(row["other_file"] or "")),
                    "line_start": int(row["other_line"] or 0),
                }
            )
            if len(out) >= int(limit):
                break
        return out

    def _select_entities(
        self,
        conn: sqlite3.Connection,
        *,
        kinds: Iterable[str] = (),
        extra_where: str = "",
        params: Iterable[Any] = (),
        limit: int = 50,
        order: str = "e.kind, e.name, e.id",
    ) -> list[sqlite3.Row]:
        allowed = [k for k in kinds if k]
        where: list[str] = []
        sql_params: list[Any] = []
        if allowed:
            placeholders = ",".join("?" for _ in allowed)
            where.append(f"e.kind IN ({placeholders})")
            sql_params.extend(allowed)
        if extra_where:
            where.append(f"({extra_where})")
            sql_params.extend(list(params))
        clause = " AND ".join(where) if where else "1=1"
        sql_params.append(max(0, int(limit)))
        return conn.execute(
            f"""
            SELECT e.id, e.kind, e.name, e.status, e.file, e.line_start, e.line_end, e.data,
                   IFNULL(s.snippet, '') AS snippet
            FROM entity e
            LEFT JOIN source_span s ON s.entity_id = e.id
            WHERE {clause}
            ORDER BY {order}
            LIMIT ?
            """,
            tuple(sql_params),
        ).fetchall()

    def _hits_from_rows(
        self,
        conn: sqlite3.Connection,
        rows: Iterable[sqlite3.Row],
        *,
        why: str = "",
        with_snippet: bool = True,
        with_rels: bool = False,
        require_span_for_branch: bool = False,
    ) -> list[dict[str, Any]]:
        preferred: dict[tuple[str, str, str, int], dict[str, Any]] = {}
        order: list[tuple[str, str, str, int]] = []
        for row in rows:
            hit = self._hit(
                row,
                why=why,
                require_span_for_branch=require_span_for_branch,
                with_snippet=with_snippet,
                with_rels=with_rels,
                conn=conn,
            )
            if hit is None:
                continue
            file = _norm_file(str(hit.get("file") or ""))
            line = int(hit.get("line_start") or 0)
            key = (
                str(hit.get("kind") or ""),
                str(hit.get("name") or "").lower(),
                file,
                line,
            )
            existing = preferred.get(key)
            if existing is None:
                preferred[key] = hit
                order.append(key)
                continue
            if _prefer_src_id(str(hit.get("id") or "")) < _prefer_src_id(str(existing.get("id") or "")):
                preferred[key] = hit
        return _drop_redundant_type_hashes([preferred[key] for key in order])

    def _entity_row(self, conn: sqlite3.Connection, name_or_id: str) -> sqlite3.Row | None:
        key = str(name_or_id or "")
        if not key:
            return None
        row = conn.execute(
            """
            SELECT e.id, e.kind, e.name, e.status, e.file, e.line_start, e.line_end, e.data,
                   IFNULL(s.snippet, '') AS snippet
            FROM entity e
            LEFT JOIN source_span s ON s.entity_id = e.id
            WHERE e.id = ?
            LIMIT 1
            """,
            (key,),
        ).fetchone()
        if row is not None:
            return row
        return conn.execute(
            """
            SELECT e.id, e.kind, e.name, e.status, e.file, e.line_start, e.line_end, e.data,
                   IFNULL(s.snippet, '') AS snippet
            FROM entity e
            LEFT JOIN source_span s ON s.entity_id = e.id
            WHERE e.name = ?
            ORDER BY e.kind, e.id
            LIMIT 1
            """,
            (key,),
        ).fetchone()

    def search(
        self, pattern: str, *, kinds: Iterable[str] = (), limit: int = 50
    ) -> list[dict[str, Any]]:
        needle = str(pattern or "").lower().strip()
        allowed = _kind_names(kinds)
        fetch = max(int(limit) * 8, 32)
        with self._connect() as conn:
            kind_filter = ""
            kind_params: list[Any] = []
            if allowed:
                placeholders = ",".join("?" for _ in allowed)
                kind_filter = f" AND e.kind IN ({placeholders})"
                kind_params.extend(sorted(allowed))
            if needle:
                prefix = f"{needle}%"
                extra = """
                    lower(IFNULL(e.name, '')) = ?
                    OR lower(IFNULL(e.name, '')) LIKE ?
                    OR lower(IFNULL(e.name, '')) LIKE '%::' || ?
                    OR lower(IFNULL(e.name, '')) LIKE '%.' || ?
                    OR lower(IFNULL(e.id, '')) = ?
                    OR lower(IFNULL(e.id, '')) LIKE '%::' || ?
                    OR lower(IFNULL(e.id, '')) LIKE '%.' || ?
                    OR (
                      e.kind NOT IN ('TYPE')
                      AND lower(IFNULL(e.name, '')) LIKE ?
                    )
                """
                sql_params: list[Any] = [
                    needle,
                    prefix,
                    needle,
                    needle,
                    needle,
                    needle,
                    needle,
                    f"%{needle}%",
                    *kind_params,
                    fetch,
                ]
            else:
                extra = "1=1"
                sql_params = [*kind_params, fetch]
            rows = conn.execute(
                f"""
                SELECT e.id, e.kind, e.name, e.status, e.file, e.line_start, e.line_end, e.data,
                       IFNULL(s.snippet, '') AS snippet
                FROM entity e
                LEFT JOIN source_span s ON s.entity_id = e.id
                WHERE ({extra}) {kind_filter}
                LIMIT ?
                """,
                tuple(sql_params),
            ).fetchall()
            matched: list[sqlite3.Row] = []
            for row in rows:
                kind = str(row["kind"] or "")
                rank = _name_rank(
                    str(row["name"] or ""),
                    str(row["id"] or ""),
                    needle,
                    exact_kind=kind in _EXACT_KINDS,
                    kind=kind,
                )
                if rank is None:
                    continue
                matched.append(row)
            hits = self._hits_from_rows(
                conn,
                matched,
                why="search",
                with_snippet=True,
                with_rels=True,
            )
            hits.sort(key=lambda hit: _agent_sort_key(hit, needle))
            if allowed == {EntityKind.BRANCH.value} or (
                hits and all(str(hit.get("kind") or "") == EntityKind.BRANCH.value for hit in hits)
            ):
                hits, _ = _diversify_by_function(hits, limit=int(limit))
            return hits[: max(0, int(limit))]

    def neighbors(
        self, entity_id: str, *, depth: int = 1, limit: int = 100
    ) -> list[dict[str, Any]]:
        max_depth = max(1, min(int(depth), 4))
        with self._connect() as conn:
            start = self._entity_row(conn, entity_id)
            if start is None:
                return []
            start_id = str(start["id"])
            seen = {start_id}
            queue: deque[tuple[str, int]] = deque([(start_id, 0)])
            ordered: list[tuple[str, int]] = [(start_id, 0)]
            while queue and len(ordered) < int(limit):
                cur, dist = queue.popleft()
                if dist >= max_depth:
                    continue
                for row in conn.execute(
                    """
                    SELECT CASE WHEN src = ? THEN dst ELSE src END AS other
                    FROM relation
                    WHERE src = ? OR dst = ?
                    """,
                    (cur, cur, cur),
                ):
                    other = str(row["other"] or "")
                    if not other or other in seen:
                        continue
                    seen.add(other)
                    queue.append((other, dist + 1))
                    ordered.append((other, dist + 1))
                    if len(ordered) >= int(limit):
                        break
            out: list[dict[str, Any]] = []
            for eid, dist in ordered[: int(limit)]:
                row = self._entity_row(conn, eid)
                if row is None:
                    continue
                hit = self._hit(row, distance=dist, with_snippet=False, with_rels=False)
                if hit is not None:
                    out.append(hit)
        return out

    def edges_of(
        self, entity_id: str, *, kind: str = "", limit: int = 100
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            start = self._entity_row(conn, entity_id)
            if start is None:
                return []
            eid = str(start["id"])
            wanted = str(kind or "").upper()
            if wanted:
                rows = conn.execute(
                    """
                    SELECT id, kind, src, dst, status FROM relation
                    WHERE (src = ? OR dst = ?) AND kind = ?
                    ORDER BY kind, src, dst LIMIT ?
                    """,
                    (eid, eid, wanted, int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, kind, src, dst, status FROM relation
                    WHERE src = ? OR dst = ?
                    ORDER BY kind, src, dst LIMIT ?
                    """,
                    (eid, eid, int(limit)),
                ).fetchall()
        return [
            {
                "id": str(row["id"] or ""),
                "kind": str(row["kind"] or ""),
                "src": str(row["src"] or ""),
                "dst": str(row["dst"] or ""),
                "status": str(row["status"] or ""),
            }
            for row in rows
        ]

    def constraints_for(self, entity_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            start = self._entity_row(conn, entity_id)
            if start is None:
                return []
            eid = str(start["id"])
            ids = {eid}
            for row in conn.execute(
                """
                SELECT CASE WHEN src = ? THEN dst ELSE src END AS other, kind
                FROM relation
                WHERE src = ? OR dst = ?
                """,
                (eid, eid, eid),
            ):
                if str(row["kind"] or "") in {
                    RelationKind.GUARDED_BY.value,
                    RelationKind.CONTROLS.value,
                    RelationKind.DERIVES.value,
                    RelationKind.BINDS.value,
                }:
                    ids.add(str(row["other"] or ""))
            hits: list[dict[str, Any]] = []
            for other in ids:
                row = self._entity_row(conn, other)
                if row is None or str(row["kind"] or "") != EntityKind.PREDICATE.value:
                    continue
                hit = self._hit(row, with_snippet=False)
                if hit is not None:
                    hits.append(hit)
        return hits

    def _reachable_kinds(
        self, start_id: str, kinds: set[str], *, depth: int = 6, limit: int = 80
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            start = self._entity_row(conn, start_id)
            if start is None:
                return []
            sid = str(start["id"])
            seen = {sid}
            queue = deque([(sid, 0)])
            out: list[dict[str, Any]] = []
            while queue and len(out) < int(limit):
                cur, dist = queue.popleft()
                if dist >= int(depth):
                    continue
                for row in conn.execute(
                    """
                    SELECT CASE WHEN src = ? THEN dst ELSE src END AS other
                    FROM relation WHERE src = ? OR dst = ?
                    """,
                    (cur, cur, cur),
                ):
                    other = str(row["other"] or "")
                    if not other or other in seen:
                        continue
                    seen.add(other)
                    queue.append((other, dist + 1))
                    ent = self._entity_row(conn, other)
                    if ent is None:
                        continue
                    if str(ent["kind"] or "") in kinds:
                        hit = self._hit(ent, with_snippet=True, with_rels=False)
                        if hit is not None:
                            out.append(hit)
        return out[: int(limit)]

    def branches_for_key(self, key_id: str) -> list[dict[str, Any]]:
        return self._reachable_kinds(key_id, {EntityKind.BRANCH.value}, depth=4)

    def templates_for_key(self, key_id: str) -> list[dict[str, Any]]:
        return self._reachable_kinds(
            key_id,
            {
                EntityKind.TEMPLATE.value,
                EntityKind.TEMPLATE_ARG.value,
                EntityKind.TEMPLATE_INSTANCE.value,
            },
            depth=4,
        )

    def affected_shapes(self, entity_id: str) -> list[dict[str, Any]]:
        return self._reachable_kinds(
            entity_id,
            {EntityKind.INPUT.value, EntityKind.FIELD.value, EntityKind.TILING_FIELD.value},
            depth=4,
        )

    def controllability_of(self, branch_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            start = self._entity_row(conn, branch_id)
            if start is None:
                return []
            eid = str(start["id"])
            hits: list[dict[str, Any]] = []
            for row in conn.execute(
                """
                SELECT r.kind AS rel_kind,
                       e.id, e.kind, e.name, e.status, e.file, e.line_start, e.line_end, e.data,
                       IFNULL(s.snippet, '') AS snippet
                FROM relation r
                JOIN entity e ON e.id = CASE WHEN r.src = ? THEN r.dst ELSE r.src END
                LEFT JOIN source_span s ON s.entity_id = e.id
                WHERE r.src = ? OR r.dst = ?
                """,
                (eid, eid, eid),
            ):
                rel = str(row["rel_kind"] or "")
                kind = str(row["kind"] or "")
                if rel not in {
                    RelationKind.CONTROLS.value,
                    RelationKind.GUARDED_BY.value,
                    RelationKind.DERIVES.value,
                } and kind not in {
                    EntityKind.PREDICATE.value,
                    EntityKind.TILING_KEY.value,
                    EntityKind.INPUT.value,
                }:
                    continue
                hit = self._hit(row, with_snippet=False)
                if hit is not None:
                    hits.append(hit)
        return hits

    def entities_in_files(self, files: Iterable[str]) -> list[dict[str, Any]]:
        normalized = sorted({str(p).replace("\\", "/").lstrip("./") for p in files if str(p).strip()})
        if not normalized:
            return []
        with self._connect() as conn:
            hits: list[dict[str, Any]] = []
            for path in normalized:
                suffix = "/" + path if not path.startswith("/") else path
                rows = conn.execute(
                    """
                    SELECT e.id, e.kind, e.name, e.status, e.file, e.line_start, e.line_end, e.data,
                           IFNULL(s.snippet, '') AS snippet
                    FROM entity e
                    LEFT JOIN source_span s ON s.entity_id = e.id
                    WHERE replace(IFNULL(e.file, ''), '\\', '/') = ?
                       OR replace(IFNULL(e.file, ''), '\\', '/') LIKE '%' || ?
                    ORDER BY e.kind, e.id
                    LIMIT 200
                    """,
                    (path, suffix),
                ).fetchall()
                hits.extend(self._hits_from_rows(conn, rows, with_snippet=False))
        hits.sort(key=lambda r: (str(r.get("kind")), str(r.get("id"))))
        return hits

    def impact_of(self, file: str, line_range: tuple[int, int]) -> dict[str, Any]:
        start, end = sorted((int(line_range[0]), int(line_range[1])))
        needle = str(file or "").replace("\\", "/").lstrip("./")
        useful = set(USEFUL_EDGE_KINDS)
        with self._connect() as conn:
            seed_rows = conn.execute(
                """
                SELECT e.id, e.kind, e.name, e.status, e.file, e.line_start, e.line_end, e.data,
                       IFNULL(s.snippet, '') AS snippet
                FROM entity e
                LEFT JOIN source_span s ON s.entity_id = e.id
                WHERE replace(IFNULL(e.file, ''), '\\', '/') LIKE '%' || ?
                  AND IFNULL(e.line_end, e.line_start) >= ?
                  AND IFNULL(e.line_start, 0) <= ?
                  AND IFNULL(e.line_start, 0) > 0
                LIMIT 80
                """,
                (needle, start, end),
            ).fetchall()
            seeds = [row for row in seed_rows if self._file_matches(str(row["file"] or ""), needle)]
            seen: dict[str, int] = {str(row["id"]): 0 for row in seeds}
            queue: deque[tuple[str, int]] = deque((str(row["id"]), 0) for row in seeds)
            placeholders = ",".join("?" for _ in useful)
            useful_sorted = sorted(useful)
            while queue:
                cur, dist = queue.popleft()
                if dist >= 2:
                    continue
                for row in conn.execute(
                    f"""
                    SELECT dst FROM relation
                    WHERE src = ? AND kind IN ({placeholders})
                    """,
                    (cur, *useful_sorted),
                ):
                    other = str(row["dst"] or "")
                    if not other or other in seen:
                        continue
                    seen[other] = dist + 1
                    queue.append((other, dist + 1))
            hits: list[dict[str, Any]] = []
            for eid, dist in seen.items():
                row = self._entity_row(conn, eid)
                if row is None:
                    continue
                hit = self._hit(
                    row,
                    distance=dist,
                    why="seed" if dist == 0 else "slice_neighbor",
                    with_snippet=dist == 0,
                    with_rels=False,
                )
                if hit is not None:
                    hits.append(hit)
        hits.sort(key=lambda r: (int(r.get("distance") or 0), str(r.get("kind")), str(r.get("id"))))
        return {
            "ok": True,
            "seeds": [row for row in hits if int(row.get("distance") or 0) == 0],
            "hits": hits,
            "buckets": bucket_hits(hits),
            "count": len(hits),
        }

    @staticmethod
    def _file_matches(current: str, needle: str) -> bool:
        cur = str(current or "").replace("\\", "/").lstrip("./")
        want = str(needle or "").replace("\\", "/").lstrip("./")
        if not cur or not want:
            return False
        return cur == want or cur.endswith("/" + want) or want.endswith("/" + cur)

    def tiling_field(self, name_or_id: str) -> list[dict[str, Any]]:
        return self._named_fields(name_or_id, kinds=(EntityKind.TILING_FIELD.value,))

    def _named_fields(self, name_or_id: str, *, kinds: Iterable[str]) -> list[dict[str, Any]]:
        key = str(name_or_id or "").strip().lower()
        if not key:
            return []
        kind_list = [k for k in kinds if k]
        placeholders = ",".join("?" for _ in kind_list)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT e.id, e.kind, e.name, e.status, e.file, e.line_start, e.line_end, e.data,
                       IFNULL(s.snippet, '') AS snippet
                FROM entity e
                LEFT JOIN source_span s ON s.entity_id = e.id
                WHERE e.kind IN ({placeholders})
                  AND (
                    lower(IFNULL(e.name, '')) = ?
                    OR lower(IFNULL(e.name, '')) LIKE '%::' || ?
                    OR lower(IFNULL(e.name, '')) LIKE '%.' || ?
                    OR lower(e.id) = ?
                    OR lower(e.id) LIKE '%::' || ?
                  )
                ORDER BY CASE e.kind
                    WHEN 'TILING_FIELD' THEN 0
                    WHEN 'FIELD' THEN 1
                    ELSE 2
                END, e.id
                LIMIT 40
                """,
                (*kind_list, key, key, key, key, key),
            ).fetchall()
            hits = self._hits_from_rows(conn, rows, why="field", with_snippet=True, with_rels=True)
            hits.sort(
                key=lambda hit: (
                    0
                    if str(hit.get("name") or "").lower() == key
                    or _last_ident(str(hit.get("name") or "")).lower() == key
                    else 1,
                    {
                        EntityKind.TILING_FIELD.value: 0,
                        EntityKind.FIELD.value: 1,
                    }.get(str(hit.get("kind") or ""), 2),
                    *_field_value_rank(hit),
                )
            )
            return hits

    def field_impact(self, name_or_id: str) -> dict[str, Any]:
        fields = self._named_fields(
            name_or_id,
            kinds=(
                EntityKind.TILING_FIELD.value,
                EntityKind.FIELD.value,
                EntityKind.TILING_KEY.value,
            ),
        )
        if not fields:
            return {"ok": False, "error": "tiling_field_not_found", "query": name_or_id}
        primary = fields[0]
        fid = str(primary["id"])
        allowed = field_edge_kinds()
        edges = [
            project_relation(rel)
            for rel in self.edges_of(fid, limit=300)
            if str(rel.get("kind") or "") in allowed
        ]
        readers: list[dict[str, Any]] = []
        writers: list[dict[str, Any]] = []
        with self._connect() as conn:
            for rel in edges:
                src_id = str(rel.get("src") or "")
                dst_id = str(rel.get("dst") or "")
                if rel.get("kind") == RelationKind.READS.value and dst_id == fid:
                    row = self._entity_row(conn, src_id)
                    hit = self._hit(row, why="kernel_reader", with_snippet=False) if row else None
                    if hit:
                        readers.append(hit)
                if rel.get("kind") in {RelationKind.WRITES.value, RelationKind.DERIVES.value} and dst_id == fid:
                    row = self._entity_row(conn, src_id)
                    hit = self._hit(row, why="host_writer", with_snippet=False) if row else None
                    if hit:
                        writers.append(hit)
        for hit in writers[:12]:
            stmt = _read_statement(
                self._op_root, str(hit.get("file") or ""), int(hit.get("line_start") or 0)
            )
            if not stmt:
                continue
            facts = dict(hit.get("facts") or {}) if isinstance(hit.get("facts"), dict) else {}
            if len(stmt) > len(str(facts.get("rhs") or "")):
                facts["rhs"] = stmt
                hit["facts"] = facts
        writers.sort(key=_write_site_sort_key)
        cap = _candidate_limit(PRIMARY_CANDIDATES)
        for hit in writers[:cap]:
            if str(hit.get("snippet") or "").strip():
                continue
            window = _disk_window(
                self._op_root,
                str(hit.get("file") or ""),
                int(hit.get("line_start") or 0),
            )
            if window:
                hit["snippet"] = window
        primary = dict(primary)
        facts = dict(primary.get("facts") or {}) if isinstance(primary.get("facts"), dict) else {}
        if writers:
            best = writers[0]
            best_facts = best.get("facts") if isinstance(best.get("facts"), dict) else {}
            best_rhs = str(best_facts.get("rhs") or "")
            if _trivial_rhs(str(facts.get("rhs") or "")) and not _trivial_rhs(best_rhs):
                facts["rhs"] = best_rhs
            facts["primary_write"] = {
                "id": best.get("id"),
                "name": best.get("name"),
                "file": best.get("file"),
                "line": best.get("line_start"),
                "rhs": best_rhs,
            }
            keep_snip = _snippet_covers_line(
                str(primary.get("snippet") or ""), int(primary.get("line_start") or 0)
            )
            if not keep_snip and best.get("snippet"):
                primary["snippet"] = best["snippet"]
            primary["facts"] = facts
        candidates = writers[:cap] or fields[:cap]
        return _fit_payload(
            {
                "ok": True,
                "field": primary,
                "fields_matched": len(fields),
                "candidates": candidates,
                "writers": writers[:12],
                "readers": readers[:12],
                "edges": edges[:8],
            }
        )

    def constant(self, name: str) -> list[dict[str, Any]]:
        needle = str(name or "").lower()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT e.id, e.kind, e.name, e.status, e.file, e.line_start, e.line_end, e.data,
                       IFNULL(s.snippet, '') AS snippet
                FROM entity e
                LEFT JOIN source_span s ON s.entity_id = e.id
                WHERE e.kind IN ('COMPILE_VAR', 'MACRO')
                  AND lower(IFNULL(e.name, '')) LIKE ?
                LIMIT 20
                """,
                (f"%{needle}%",),
            ).fetchall()
            return self._hits_from_rows(conn, rows, with_snippet=True)

    def locate(
        self, query: str, *, kinds: Iterable[str] | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        rows = self.search(query, kinds=kinds or (), limit=limit)
        return [self._location(row) for row in rows if row.get("file")]

    def locate_dim(self, name: str, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT e.id, e.kind, e.name, e.status, e.file, e.line_start, e.line_end, e.data,
                       IFNULL(s.snippet, '') AS snippet
                FROM entity e
                LEFT JOIN source_span s ON s.entity_id = e.id
                WHERE e.kind = 'TILING_KEY' AND IFNULL(e.name, '') = ?
                LIMIT ?
                """,
                (str(name or ""), int(limit)),
            ).fetchall()
            hits = self._hits_from_rows(conn, rows, why="locate_dim", with_snippet=True)
        return self._locations_with_sites(hits, limit=limit)

    def locate_branch(self, branch_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            row = self._entity_row(conn, branch_id)
            if row is None or str(row["kind"] or "") != EntityKind.BRANCH.value:
                return []
            hit = self._hit(row, with_snippet=True)
        return ([self._location(hit)] if hit else [])[:limit]

    def locate_field(self, name: str, *, limit: int = 20) -> list[dict[str, Any]]:
        return self._locations_with_sites(self.tiling_field(name), limit=limit)

    def _locations_with_sites(
        self, rows: list[dict[str, Any]], *, limit: int
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[tuple[str, str, int]] = set()
        for row in rows:
            loc = self._location(row)
            file = str(loc.get("file") or "")
            line = int(loc.get("line_start") or 0)
            key = (str(loc.get("id") or ""), file, line)
            if file and line > 0 and key not in seen:
                seen.add(key)
                out.append(loc)
            attrs: dict[str, Any] = {}
            if isinstance(row.get("facts"), dict):
                attrs.update(row["facts"])
            if isinstance(row.get("data"), dict):
                attrs.update(row["data"])
            for extra in locations_from_attr_sites(
                str(row.get("id") or ""), str(row.get("kind") or ""), attrs or row
            ):
                extra_key = (extra.entity_id, extra.file, extra.line_start)
                if extra_key in seen:
                    continue
                seen.add(extra_key)
                payload = extra.to_dict()
                if not payload.get("snippet"):
                    payload["snippet"] = _disk_window(self._op_root, extra.file, extra.line_start)
                payload["snippet"] = _cap_snippet(
                    str(payload.get("snippet") or ""), int(payload.get("line_start") or 0)
                )
                out.append(payload)
            if len(out) >= int(limit):
                break
        return out[: int(limit)]

    @staticmethod
    def _location(row: dict[str, Any]) -> dict[str, Any]:
        facts = row.get("facts") if isinstance(row.get("facts"), dict) else {}
        return {
            "id": row.get("id"),
            "kind": row.get("kind"),
            "name": row.get("name"),
            "file": row.get("file"),
            "line_start": row.get("line_start"),
            "line_end": row.get("line_end"),
            "snippet": row.get("snippet") or facts.get("snippet") or "",
            "facts": facts,
            "relationships": row.get("relationships") or [],
        }

    def operator_api(self) -> dict[str, Any]:
        with self._connect() as conn:
            inputs = self._hits_from_rows(
                conn,
                self._select_entities(conn, kinds=("INPUT",), limit=200),
                with_snippet=False,
            )
            outputs = self._hits_from_rows(
                conn,
                self._select_entities(conn, kinds=("OUTPUT",), limit=200),
                with_snippet=False,
            )

        def _api_index(hit: dict[str, Any], key: str) -> int:
            facts = hit.get("facts") if isinstance(hit.get("facts"), dict) else {}
            return int(facts.get(key) or 0)

        tensor = [h for h in inputs if (h.get("facts") or {}).get("api_kind") == "tensor"]
        attrs = [h for h in inputs if (h.get("facts") or {}).get("api_kind") == "attribute"]
        tensor.sort(key=lambda h: _api_index(h, "api_index"))
        attrs.sort(key=lambda h: _api_index(h, "api_attr_index"))
        outputs.sort(key=lambda h: _api_index(h, "api_index"))
        return {"tensor_inputs": tensor, "attributes": attrs, "outputs": outputs}

    def input_roots(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return self._hits_from_rows(
                conn, self._select_entities(conn, kinds=("INPUT",), limit=400), with_snippet=False
            )

    def output_roots(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return self._hits_from_rows(
                conn, self._select_entities(conn, kinds=("OUTPUT",), limit=400), with_snippet=False
            )

    def _repair_packing_hit(self, hit: dict[str, Any]) -> dict[str, Any]:
        facts = hit.get("facts")
        if not isinstance(facts, dict):
            return hit
        sites = facts.get("packing_value_sites")
        if not isinstance(sites, list):
            return hit
        repaired: list[Any] = []
        for site in sites:
            if not isinstance(site, dict):
                repaired.append(site)
                continue
            item = dict(site)
            rhs = str(item.get("rhs") or "")
            stmt = _read_statement(
                self._op_root, str(item.get("file") or ""), int(item.get("line") or 0)
            )
            if stmt and (
                len(stmt) > len(rhs)
                or _rhs_looks_truncated(rhs)
                or (_trivial_rhs(rhs) and not _trivial_rhs(stmt))
            ):
                item["rhs"] = stmt
            repaired.append(item)
        repaired.sort(key=_packing_site_sort_key)
        facts = dict(facts)
        facts["packing_value_sites"] = repaired
        hit = dict(hit)
        hit["facts"] = facts
        best = next((site for site in repaired if isinstance(site, dict)), None)
        if best is not None:
            window = _disk_window(
                self._op_root, str(best.get("file") or ""), int(best.get("line") or 0)
            )
            if window:
                hit["snippet"] = window
        return hit

    def tiling_keys(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT e.id, e.kind, e.name, e.status, e.file, e.line_start, e.line_end, e.data,
                       IFNULL(s.snippet, '') AS snippet,
                       CAST(IFNULL(json_extract(e.data, '$.decl_order'), 0) AS INTEGER) AS decl_order
                FROM entity e
                LEFT JOIN source_span s ON s.entity_id = e.id
                WHERE e.kind = 'TILING_KEY'
                ORDER BY decl_order, e.name
                """
            ).fetchall()
            hits = self._hits_from_rows(conn, rows, with_snippet=True, with_rels=True)
        return [self._repair_packing_hit(hit) for hit in hits]

    def tiling_data(self, name: str = "") -> list[dict[str, Any]]:
        needle = str(name or "").strip()
        with self._connect() as conn:
            if needle:
                rows = conn.execute(
                    """
                    SELECT e.id, e.kind, e.name, e.status, e.file, e.line_start, e.line_end, e.data,
                           IFNULL(s.snippet, '') AS snippet
                    FROM entity e
                    LEFT JOIN source_span s ON s.entity_id = e.id
                    WHERE e.kind = 'TILING_DATA'
                      AND (e.name = ? OR e.id = ? OR e.name LIKE ?)
                    LIMIT 40
                    """,
                    (needle, needle, f"%{needle}%"),
                ).fetchall()
            else:
                rows = self._select_entities(conn, kinds=("TILING_DATA",), limit=80)
            return self._hits_from_rows(conn, rows, with_snippet=True)

    def tiling_fields(self, owner: str = "") -> list[dict[str, Any]]:
        with self._connect() as conn:
            if owner:
                rows = conn.execute(
                    """
                    SELECT e.id, e.kind, e.name, e.status, e.file, e.line_start, e.line_end, e.data,
                           IFNULL(s.snippet, '') AS snippet
                    FROM entity e
                    LEFT JOIN source_span s ON s.entity_id = e.id
                    WHERE e.kind = 'TILING_FIELD'
                      AND json_extract(e.data, '$.owner') = ?
                    LIMIT 200
                    """,
                    (owner,),
                ).fetchall()
            else:
                rows = self._select_entities(conn, kinds=("TILING_FIELD",), limit=200)
            return self._hits_from_rows(conn, rows, with_snippet=False)

    def tiling_registrations(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT r.id AS rel_id, r.kind AS rel_kind, r.src, r.dst, r.status AS rel_status,
                       s.id AS sid, s.kind AS skind, s.name AS sname, s.status AS sstatus,
                       s.file AS sfile, s.line_start AS sline, s.line_end AS slend,
                       d.id AS did, d.kind AS dkind, d.name AS dname, d.status AS dstatus,
                       d.file AS dfile, d.line_start AS dline, d.line_end AS dlend
                FROM relation r
                JOIN entity s ON s.id = r.src
                JOIN entity d ON d.id = r.dst
                WHERE r.kind = 'SELECTS'
                  AND s.kind = 'PREDICATE'
                  AND d.kind = 'TILING_DATA'
                  AND (
                    json_extract(s.data, '$.predicate_role') = 'packed_tiling_key_registration'
                    OR s.data LIKE '%packed_tiling_key_registration%'
                  )
                LIMIT 80
                """
            ).fetchall()
        return [
            {
                "predicate": {
                    "id": row["sid"],
                    "kind": row["skind"],
                    "name": row["sname"],
                    "status": row["sstatus"],
                    "file": row["sfile"],
                    "line_start": row["sline"],
                    "line_end": row["slend"],
                },
                "tiling_data": {
                    "id": row["did"],
                    "kind": row["dkind"],
                    "name": row["dname"],
                    "status": row["dstatus"],
                    "file": row["dfile"],
                    "line_start": row["dline"],
                    "line_end": row["dlend"],
                },
                "relation": {
                    "id": row["rel_id"],
                    "kind": row["rel_kind"],
                    "src": row["src"],
                    "dst": row["dst"],
                    "status": row["rel_status"],
                },
            }
            for row in rows
        ]

    def unresolved(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT e.id, e.kind, e.name, e.status, e.file, e.line_start, e.line_end, e.data,
                       IFNULL(s.snippet, '') AS snippet
                FROM entity e
                LEFT JOIN source_span s ON s.entity_id = e.id
                WHERE lower(e.status) IN ('unresolved', 'partial', 'unknown')
                LIMIT 400
                """
            ).fetchall()
            return self._hits_from_rows(conn, rows, with_snippet=False)

    def _lazy_engine(self):
        if self._engine is None:
            from uo_init.query.engine import CodeMapQuery
            from uo_init.store.reader import read_codemap

            self._engine = CodeMapQuery(read_codemap(self.product), path=str(self.product))
        return self._engine

    def audit(self) -> dict[str, Any]:
        return self._lazy_engine().audit()

    def summary(self) -> dict[str, Any]:
        return self._lazy_engine().summary()

    def _slice(
        self,
        seed_ids: Iterable[str],
        *,
        edge_kinds: Iterable[str] | None,
        depth: int,
        budget: int,
        direction: str,
    ) -> dict[str, Any]:
        wanted = {
            str(kind.value if hasattr(kind, "value") else kind).upper()
            for kind in (edge_kinds or ())
        }
        if not wanted:
            wanted = set(USEFUL_EDGE_KINDS)
        max_depth = max(0, int(depth))
        cap = max(1, int(budget))
        placeholders = ",".join("?" for _ in wanted)
        col_from, col_to = ("src", "dst") if direction == "forward" else ("dst", "src")
        with self._connect() as conn:
            present: list[str] = []
            for seed in seed_ids:
                row = self._entity_row(conn, str(seed))
                if row is not None:
                    present.append(str(row["id"]))
            seen: set[str] = set()
            queue: deque[tuple[str, int]] = deque()
            for seed in present:
                if seed not in seen and len(seen) < cap:
                    seen.add(seed)
                    queue.append((seed, 0))
            included: list[sqlite3.Row] = []
            truncated = len(set(present)) > cap
            wanted_sorted = sorted(wanted)
            while queue:
                current, distance = queue.popleft()
                if distance >= max_depth:
                    continue
                for rel in conn.execute(
                    f"""
                    SELECT id, kind, src, dst, status
                    FROM relation
                    WHERE {col_from} = ? AND kind IN ({placeholders})
                    ORDER BY kind, src, dst, id
                    """,
                    (current, *wanted_sorted),
                ):
                    other = str(rel[col_to] or "")
                    if not other:
                        continue
                    if other not in seen:
                        if len(seen) >= cap:
                            truncated = True
                            continue
                        if self._entity_row(conn, other) is None:
                            continue
                        seen.add(other)
                        queue.append((other, distance + 1))
                    included.append(rel)
            nodes: list[dict[str, Any]] = []
            for eid in sorted(seen):
                row = self._entity_row(conn, eid)
                if row is None:
                    continue
                hit = self._hit(row, with_snippet=False)
                if hit is not None:
                    hit["evidence_tier"] = "B"
                    nodes.append(hit)
            edges = [
                {
                    "id": str(rel["id"] or ""),
                    "kind": str(rel["kind"] or ""),
                    "src": str(rel["src"] or ""),
                    "dst": str(rel["dst"] or ""),
                    "status": str(rel["status"] or ""),
                    "evidence_tier": "B",
                }
                for rel in included
            ]
        return {
            "nodes": nodes,
            "edges": edges,
            "evidence_tier_hints": {"B": len(nodes) + len(edges)},
            "truncated": truncated,
        }

    def slice_forward(
        self,
        seed_ids: Iterable[str],
        *,
        edge_kinds: Iterable[str] | None = None,
        depth: int = 3,
        budget: int = 500,
    ) -> dict[str, Any]:
        return self._slice(
            seed_ids, edge_kinds=edge_kinds, depth=depth, budget=budget, direction="forward"
        )

    def slice_backward(
        self,
        seed_ids: Iterable[str],
        *,
        edge_kinds: Iterable[str] | None = None,
        depth: int = 3,
        budget: int = 500,
    ) -> dict[str, Any]:
        return self._slice(
            seed_ids, edge_kinds=edge_kinds, depth=depth, budget=budget, direction="backward"
        )

    def find_path(self, start: str, end: str | None = None, *, end_kind: str = "") -> list[dict[str, Any]]:
        with self._connect() as conn:
            starts = conn.execute(
                """
                SELECT id, kind, name FROM entity
                WHERE name = ? OR id = ?
                ORDER BY CASE kind
                  WHEN 'INPUT' THEN 0 WHEN 'OUTPUT' THEN 1 WHEN 'TILING_KEY' THEN 2
                  ELSE 9 END, id
                LIMIT 8
                """,
                (start, start),
            ).fetchall()
            if not starts:
                return []
            end_id = None
            end_kinds: set[str] = set()
            if end_kind:
                end_kinds.add(str(end_kind).upper())
            if end:
                ends = conn.execute(
                    "SELECT id, kind FROM entity WHERE name = ? OR id = ? LIMIT 4",
                    (end, end),
                ).fetchall()
                if ends:
                    end_id = str(ends[0]["id"])
                elif str(end).upper() in {k.value for k in EntityKind}:
                    end_kinds.add(str(end).upper())
            if not end_id and not end_kinds:
                end_kinds.add("KERNEL")
            for src in starts:
                path = self._bfs_path(conn, str(src["id"]), end_id=end_id, end_kinds=end_kinds)
                if path:
                    hits: list[dict[str, Any]] = []
                    for eid in path:
                        row = self._entity_row(conn, eid)
                        hit = self._hit(row, with_snippet=False) if row else None
                        if hit:
                            hits.append(hit)
                    return hits
        return []

    def _bfs_path(
        self,
        conn: sqlite3.Connection,
        start_id: str,
        *,
        end_id: str | None,
        end_kinds: set[str],
        max_depth: int = 16,
    ) -> list[str]:
        prev: dict[str, str | None] = {start_id: None}
        queue: deque[tuple[str, int]] = deque([(start_id, 0)])
        found: str | None = None
        while queue:
            cur, dist = queue.popleft()
            row = self._entity_row(conn, cur)
            kind = str(row["kind"] or "") if row is not None else ""
            if end_id and cur == end_id:
                found = cur
                break
            if end_kinds and kind in end_kinds and cur != start_id:
                found = cur
                break
            if dist >= max_depth:
                continue
            for rel in conn.execute("SELECT dst FROM relation WHERE src = ?", (cur,)):
                nxt = str(rel["dst"] or "")
                if not nxt or nxt in prev:
                    continue
                prev[nxt] = cur
                queue.append((nxt, dist + 1))
        if not found:
            return []
        path = [found]
        while prev.get(path[-1]) is not None:
            path.append(prev[path[-1]] or "")
        path.reverse()
        return [p for p in path if p]

    def selected_kernel(self, key_name: str = "") -> list[dict[str, Any]]:
        with self._connect() as conn:
            if not key_name:
                return self._hits_from_rows(
                    conn, self._select_entities(conn, kinds=("KERNEL",), limit=40), with_snippet=True
                )
            start = self._entity_row(conn, key_name)
            if start is None:
                return []
            eid = str(start["id"])
            rows = conn.execute(
                """
                SELECT e.id, e.kind, e.name, e.status, e.file, e.line_start, e.line_end, e.data,
                       IFNULL(s.snippet, '') AS snippet
                FROM relation r
                JOIN entity e ON e.id = r.dst
                LEFT JOIN source_span s ON s.entity_id = e.id
                WHERE r.src = ? AND r.kind IN ('SELECTS', 'CONTROLS')
                LIMIT 40
                """,
                (eid,),
            ).fetchall()
            return self._hits_from_rows(conn, rows, with_snippet=True)

    def available_arch(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return self._hits_from_rows(
                conn, self._select_entities(conn, kinds=("ARCH",), limit=20), with_snippet=False
            )

    def aggregate_tiling_key(self, pattern: str = "", *, limit: int = 50) -> dict[str, Any]:
        needle = str(pattern or "").strip()
        keys = self.tiling_keys()
        if needle:
            low = needle.lower()
            keys = [
                k
                for k in keys
                if low in str(k.get("name") or "").lower() or low in str(k.get("id") or "").lower()
            ]
        keys = keys[: max(0, int(limit))]
        return _fit_payload(
            {
                "ok": True,
                "mode": "tiling_key",
                "pattern": needle,
                "keys": keys,
                "count": len(keys),
                "files": _group_by_file(keys),
            }
        )

    def aggregate_tiling_data(self, pattern: str = "", *, limit: int = 50) -> dict[str, Any]:
        needle = str(pattern or "").strip()
        if needle:
            fields = self._named_fields(
                needle, kinds=(EntityKind.TILING_FIELD.value, EntityKind.FIELD.value)
            )[: int(limit)]
            impact = self.field_impact(needle) if fields else {"ok": False}
            data = self.tiling_data(needle)
        else:
            fields = self.tiling_fields()[: int(limit)]
            impact = {}
            data = self.tiling_data()
        return _fit_payload(
            {
                "ok": True,
                "mode": "tiling_data",
                "pattern": needle,
                "tiling_data": data[: int(limit)],
                "fields": fields,
                "impact": impact,
                "count": len(fields),
            }
        )

    def aggregate_kernel_branch(self, pattern: str = "", *, limit: int = 50) -> dict[str, Any]:
        needle = str(pattern or "").strip()
        tokens = _TOKEN_RE.findall(needle) or ([needle] if needle else [])
        name_tok = tokens[0] if tokens else ""
        func_tok = tokens[1] if len(tokens) > 1 else ""
        with self._connect() as conn:
            params: list[Any] = []
            where = ["e.kind = 'BRANCH'", "IFNULL(e.file, '') != ''", "IFNULL(e.line_start, 0) > 0"]
            if name_tok:
                where.append(
                    """(
                    e.name = ?
                    OR lower(e.name) = lower(?)
                    OR lower(e.name) LIKE '%::' || lower(?)
                    OR lower(e.name) LIKE '%.' || lower(?)
                    )"""
                )
                params.extend([name_tok, name_tok, name_tok, name_tok])
            if func_tok:
                where.append(
                    "(json_extract(e.data, '$.function') = ? OR lower(IFNULL(json_extract(e.data, '$.function'), '')) LIKE lower(?))"
                )
                params.extend([func_tok, f"%{func_tok}%"])
            order_name = name_tok or ""
            rows = conn.execute(
                f"""
                SELECT e.id, e.kind, e.name, e.status, e.file, e.line_start, e.line_end, e.data,
                       IFNULL(s.snippet, '') AS snippet
                FROM entity e
                LEFT JOIN source_span s ON s.entity_id = e.id
                WHERE {' AND '.join(where)}
                ORDER BY
                  CASE WHEN e.name = ? THEN 0 ELSE 1 END,
                  e.id
                LIMIT ?
                """,
                tuple(params + [order_name, max(int(limit) * 24, 80)]),
            ).fetchall()
            branches = self._hits_from_rows(
                conn, rows, why="kernel_branch", with_snippet=True, with_rels=True
            )
            if name_tok:
                low = name_tok.lower()
                kept: list[dict[str, Any]] = []
                for hit in branches:
                    facts = hit.get("facts") if isinstance(hit.get("facts"), dict) else {}
                    name_ok = (
                        str(hit.get("name") or "").lower() == low
                        or low in str(hit.get("name") or "").lower()
                        or low in str(facts.get("condition") or "").lower()
                    )
                    fn = str(facts.get("function") or "")
                    fn_ok = (not func_tok) or func_tok.lower() in fn.lower()
                    if name_ok and fn_ok:
                        kept.append(hit)
                branches = kept
        branches.sort(key=_branch_sort_key)
        total = len(branches)
        cap = _candidate_limit(limit)
        if func_tok:
            functions: dict[str, int] = {}
            for hit in branches:
                facts = hit.get("facts") if isinstance(hit.get("facts"), dict) else {}
                fn = str(facts.get("function") or "").strip() or "(unknown)"
                functions[fn] = functions.get(fn, 0) + 1
            exemplars = branches[:cap]
        else:
            exemplars, functions = _diversify_by_function(branches, limit=max(cap, int(limit)))
            exemplars = exemplars[:cap]
        return _fit_payload(
            {
                "ok": True,
                "mode": "kernel_branch",
                "pattern": needle,
                "branches": exemplars,
                "count": total,
                "functions": functions,
                "files": _group_by_file(exemplars),
            }
        )

    def aggregate_template_match(
        self,
        pattern: str = "",
        *,
        filters: dict[str, str] | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        needle = str(pattern or "").strip()
        structured = {
            str(k).strip(): str(v).strip()
            for k, v in dict(filters or {}).items()
            if str(k).strip() and str(v).strip()
        }
        if not structured:
            structured.update(_pattern_filters(needle))
        graph_pattern = "" if structured else needle
        if graph_pattern:
            templates = self.templates_for_key(graph_pattern)
            macros = self.constant(graph_pattern)
        else:
            with self._connect() as conn:
                templates = self._hits_from_rows(
                    conn,
                    self._select_entities(
                        conn,
                        kinds=("TEMPLATE", "TEMPLATE_ARG", "TEMPLATE_INSTANCE"),
                        limit=int(limit),
                    ),
                    with_snippet=False,
                )
                macros = self._hits_from_rows(
                    conn,
                    self._select_entities(conn, kinds=("MACRO", "COMPILE_VAR"), limit=int(limit)),
                    with_snippet=False,
                )
        block_matches: list[dict[str, Any]] = []
        block_status: dict[str, Any] = {"ok": True, "reason_code": "", "used": False}
        if structured:
            from uo_init.store.reader import load_view_blob_checked

            checked = load_view_blob_checked(
                self.product,
                "tiling/template_blocks.yaml",
                fallback_canonical=False,
            )
            block_status = {
                "ok": bool(checked.get("ok")),
                "reason_code": str(checked.get("reason_code") or ""),
                "used": bool(checked.get("ok")),
            }
            if checked.get("ok"):
                block_matches = [
                    row
                    for row in _template_block_rows(checked.get("view"))
                    if _template_block_matches(row, structured)
                ][: int(limit)]
        return _fit_payload(
            {
                "ok": bool(block_status.get("ok")) if structured else True,
                "mode": "template_match",
                "pattern": needle,
                "filters": structured,
                "templates": templates[: int(limit)],
                "macros_compile_vars": macros[: int(limit)],
                "template_blocks": block_matches,
                "template_projection": block_status,
                "count": len(block_matches) if structured else len(templates),
            }
        )

    def aggregate_buffer(self, pattern: str = "", *, limit: int = 50) -> dict[str, Any]:
        needle = str(pattern or "").strip()
        low = needle.lower()
        with self._connect() as conn:
            buf_rows = conn.execute(
                """
                SELECT e.id, e.kind, e.name, e.status, e.file, e.line_start, e.line_end, e.data,
                       IFNULL(s.snippet, '') AS snippet
                FROM entity e
                LEFT JOIN source_span s ON s.entity_id = e.id
                WHERE e.kind = 'BUFFER'
                  AND (? = '' OR lower(IFNULL(e.name, '')) LIKE ? OR lower(e.id) LIKE ?)
                LIMIT ?
                """,
                (needle, f"%{low}%", f"%{low}%", max(int(limit) * 4, 16)),
            ).fetchall()
            wrap_rows = conn.execute(
                """
                SELECT e.id, e.kind, e.name, e.status, e.file, e.line_start, e.line_end, e.data,
                       IFNULL(s.snippet, '') AS snippet
                FROM entity e
                LEFT JOIN source_span s ON s.entity_id = e.id
                WHERE e.kind = 'TYPE'
                  AND (
                    json_extract(e.data, '$.role') = 'storage_wrapper_type'
                    OR e.data LIKE '%"role":"storage_wrapper_type"%'
                  )
                  AND (
                    ? = ''
                    OR lower(IFNULL(e.name, '')) = ?
                    OR lower(IFNULL(e.name, '')) LIKE '%::' || ?
                  )
                LIMIT ?
                """,
                (needle, low, low, max(int(limit) * 4, 16)),
            ).fetchall()
            rows = self._hits_from_rows(
                conn,
                list(buf_rows) + list(wrap_rows),
                why="buffer",
                with_snippet=True,
                with_rels=True,
            )
        rows = rows[: max(0, int(limit))]
        return _fit_payload(
            {
                "ok": True,
                "mode": "buffer",
                "pattern": needle,
                "buffers": rows,
                "count": len(rows),
                "total": len(rows),
                "files": _group_by_file(rows),
            }
        )

    def aggregate_locate(self, pattern: str = "", *, limit: int = 20) -> dict[str, Any]:
        needle = str(pattern or "").strip()
        rows = self.locate_dim(needle, limit=limit) if needle else []
        if not rows and needle:
            rows = self.locate_field(needle, limit=limit)
        if not rows and needle:
            rows = self.locate(needle, limit=limit)
        rows = rows[: int(limit)]
        return _fit_payload(
            {
                "ok": True,
                "mode": "locate",
                "pattern": needle,
                "locations": rows,
                "count": len(rows),
                "files": _group_by_file(rows),
            }
        )

    def aggregate_kernel_api(self, pattern: str = "", *, limit: int = 50) -> dict[str, Any]:
        needle = str(pattern or "").strip().lower()
        with self._connect() as conn:
            if needle:
                rows = conn.execute(
                    """
                    SELECT e.id, e.kind, e.name, e.status, e.file, e.line_start, e.line_end, e.data,
                           IFNULL(s.snippet, '') AS snippet
                    FROM entity e
                    LEFT JOIN source_span s ON s.entity_id = e.id
                    WHERE e.kind = 'OPERATION'
                      AND (
                        lower(IFNULL(e.name, '')) LIKE ?
                        OR lower(IFNULL(json_extract(e.data, '$.callee'), '')) LIKE ?
                        OR lower(e.id) LIKE ?
                      )
                    ORDER BY e.file, e.line_start, e.id
                    LIMIT 400
                    """,
                    (f"%{needle}%", f"%{needle}%", f"%{needle}%"),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT e.id, e.kind, e.name, e.status, e.file, e.line_start, e.line_end, e.data,
                           IFNULL(s.snippet, '') AS snippet
                    FROM entity e
                    LEFT JOIN source_span s ON s.entity_id = e.id
                    WHERE e.kind = 'OPERATION'
                    ORDER BY e.file, e.line_start, e.id
                    LIMIT 400
                    """
                ).fetchall()
            hits: list[dict[str, Any]] = []
            for row in rows:
                data = _parse_data(row["data"])
                name = str(data.get("callee") or row["name"] or "")
                if needle:
                    if needle not in name.lower() and needle not in str(row["id"] or "").lower():
                        continue
                elif not is_kernel_api_name(name):
                    continue
                hit = self._hit(row, why="api_call", with_snippet=True, with_rels=False, conn=conn)
                if hit is None:
                    continue
                facts = dict(hit.get("facts") or {})
                sync: list[dict[str, Any]] = []
                queues: list[dict[str, Any]] = []
                for rel in conn.execute(
                    """
                    SELECT r.kind AS rel_kind, e.id, e.kind, e.name, e.file, e.line_start, e.data
                    FROM relation r
                    JOIN entity e ON e.id = r.dst
                    WHERE r.src = ?
                    """,
                    (str(hit["id"]),),
                ):
                    other_data = _parse_data(rel["data"])
                    if str(rel["rel_kind"] or "") in {
                        RelationKind.SIGNALS.value,
                        RelationKind.AWAITS.value,
                    }:
                        sync.append(
                            {
                                "kind": str(rel["rel_kind"] or ""),
                                "id": str(rel["id"] or ""),
                                "name": str(rel["name"] or ""),
                                "file": str(rel["file"] or ""),
                                "line_start": int(rel["line_start"] or 0),
                                "paired": bool(other_data.get("paired")),
                            }
                        )
                    if str(rel["kind"] or "") == EntityKind.QUEUE.value:
                        queues.append(
                            {
                                "id": str(rel["id"] or ""),
                                "name": str(rel["name"] or ""),
                                "tposition": other_data.get("tposition") or "",
                                "memory_space": other_data.get("memory_space") or "",
                            }
                        )
                if is_flag_sync_api_name(name) and sync:
                    facts["sync"] = sync
                if is_tque_api_name(name) and queues:
                    facts["queue"] = queues
                if facts:
                    hit["facts"] = facts
                hits.append(hit)
                if len(hits) >= int(limit):
                    break
        return _fit_payload(
            {
                "ok": True,
                "mode": "kernel_api",
                "pattern": needle,
                "calls": hits[: int(limit)],
                "count": min(len(hits), int(limit)),
                "total": len(hits),
                "files": _group_by_file(hits[: int(limit)]),
            }
        )

    def aggregate_gaps(self, pattern: str = "", *, limit: int = 50) -> dict[str, Any]:
        needle = str(pattern or "").strip().lower()
        rows = self.unresolved()
        total = len(rows)
        if needle:
            rows = [
                r
                for r in rows
                if needle in json.dumps(r, ensure_ascii=False, default=str).lower()
            ]
        rows = rows[: int(limit)]
        return _fit_payload(
            {
                "ok": True,
                "mode": "gaps",
                "pattern": needle,
                "gaps": rows,
                "count": len(rows),
                "total": total,
            }
        )

    def legal_key_query(
        self,
        *,
        pattern: str = "",
        dim: str = "",
        value: str = "",
        filters: dict[str, str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        from uo_init.query.legal_key_cache import query_legal_keys

        return query_legal_keys(
            self.product,
            pattern=pattern,
            dim=dim,
            value=value,
            filters=filters,
            limit=limit,
            offset=offset,
        )
