# -*- coding: utf-8 -*-
"""PR ownership: observable behavior changed, not merely nearby in a hunk.

Discovery (entities_in_files, impact_of) is not proof. A Target is PR-owned
only when machine evidence shows a writer/assignment change or a directed
control/data edge from a changed seed to that observable's writer.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from acp_common.paths import strip_dot_slash

OWNERSHIP_RELATIONS = frozenset(
    {"WRITES", "CONTROLS", "GUARDED_BY", "DERIVES", "FLOWS_TO"}
)
PRIMARY_KINDS = frozenset(
    {
        "writer_changed",
        "observable_assignment_changed",
        "observable_control_dependency_changed",
        "observable_data_dependency_changed",
    }
)

_CONTROL_NAMES = frozenset({"if", "while", "for", "switch", "catch", "return", "else"})
_ASSIGN = re.compile(r"(?<![<>!=])\b([A-Za-z_]\w*)\s*=(?!=)")
_DECL_ASSIGN = re.compile(
    r"^\s*(?:constexpr\s+|const\s+|static\s+|volatile\s+)*"
    r"(?:(?:unsigned|signed|long|short)\s+)*"
    r"(?:void|bool|int|float|double|auto|int\d+_t|uint\d+_t|size_t|char)\b"
    r"[\s\*&]*[A-Za-z_]\w*\s*="
)
_FIELD_WRITE = re.compile(r"(?:->|\.)\s*([A-Za-z_]\w*)\s*=")
_IDENT = re.compile(r"\b([A-Za-z_]\w*)\b")
_CONTROL = re.compile(r"^\s*(?:if\b|}?\s*else\s+if\b|while\b|return\b)")
_ASSIGN_SKIP = re.compile(r"==|!=|<=|>=")
_FUNC_OPEN = re.compile(
    r"^(?:[\w:<>,\*&\[\]\s]+)\s+([A-Za-z_]\w*)\s*\([^;]*\)\s*\{?\s*$"
)


def names_assigned_in(text: str) -> set[str]:
    """Assignments that write a value, not `int foo = 0` declarations."""
    names: set[str] = set()
    for raw in str(text or "").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("//"):
            continue
        if _DECL_ASSIGN.match(stripped):
            continue
        names.update(_ASSIGN.findall(raw))
        names.update(_FIELD_WRITE.findall(raw))
    return names


def is_control_or_compare(line: str) -> bool:
    stripped = str(line or "").strip()
    if not stripped or stripped.startswith("//"):
        return False
    if _CONTROL.search(stripped) or " ? " in line:
        return True
    if _ASSIGN_SKIP.search(line) or re.search(r"[<>]\s*[A-Za-z0-9_(]", line):
        return True
    if re.search(r"\b(Min|Max|std::min|std::max)\s*\(", line):
        return True
    return False


def path_matches(hunk_path: str | None, operator_rel: str) -> bool:
    hp = strip_dot_slash(hunk_path)
    op = strip_dot_slash(operator_rel)
    if not hp or not op or hp == "/dev/null":
        return False
    return hp == op or hp.endswith("/" + op) or op.endswith("/" + hp)


def hunks_covering(
    hunks: list[dict[str, Any]],
    operator_rel: str,
    line: int,
    *,
    side: str = "new",
) -> list[dict[str, Any]]:
    if int(line or 0) <= 0:
        return []
    out: list[dict[str, Any]] = []
    for hunk in hunks or []:
        path = hunk.get("new_file") if side == "new" else hunk.get("old_file")
        start = int(hunk.get("new_start") if side == "new" else hunk.get("old_start") or 0)
        end = int(hunk.get("new_end") if side == "new" else hunk.get("old_end") or 0)
        if not path_matches(str(path or ""), operator_rel):
            continue
        if start <= int(line) <= end:
            out.append(hunk)
    return out


def derive_change(kinds: list[str], evidence: list[dict[str, Any]]) -> dict[str, Any]:
    seen_kinds: list[str] = []
    for kind in kinds:
        if kind and kind not in seen_kinds:
            seen_kinds.append(kind)
    owned_evidence = [
        row
        for row in evidence
        if isinstance(row, dict) and str(row.get("relation") or "") in OWNERSHIP_RELATIONS
    ]
    primary = [k for k in seen_kinds if k in PRIMARY_KINDS]
    return {
        "kinds": seen_kinds,
        "ownership": {"pr_eligible": bool(primary) and bool(owned_evidence)},
        "evidence": evidence,
    }


def is_pr_owned(row: dict[str, Any] | None) -> bool:
    change = row.get("change") if isinstance(row, dict) else None
    if not isinstance(change, dict):
        return False
    ownership = change.get("ownership") if isinstance(change.get("ownership"), dict) else {}
    if not ownership.get("pr_eligible"):
        return False
    evidence = change.get("evidence") if isinstance(change.get("evidence"), list) else []
    return any(
        isinstance(item, dict) and str(item.get("relation") or "") in OWNERSHIP_RELATIONS
        for item in evidence
    )


def _directed_from_query(
    query: Any,
    *,
    symbol: str,
    writers: list[dict[str, Any]],
    hunks: list[dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]]]:
    kinds: list[str] = []
    evidence: list[dict[str, Any]] = []
    writer_ids = {str(w.get("id") or "") for w in writers if w.get("id")}
    if query is None:
        return kinds, evidence
    for hunk in hunks or []:
        new_file = str(hunk.get("new_file") or "")
        if not new_file or new_file == "/dev/null":
            continue
        start = int(hunk.get("new_start") or 0)
        end = int(hunk.get("new_end") or 0)
        try:
            impact = query.impact_of(new_file, (start, end))
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(impact, dict):
            continue
        seeds = [s for s in (impact.get("seeds") or []) if isinstance(s, dict)]
        seed_ids = [str(s.get("id") or "") for s in seeds if s.get("id")]
        try:
            edges_by_id = query.edges_of_many(seed_ids) if seed_ids else {}
        except Exception:  # noqa: BLE001
            edges_by_id = {}
        for seed in seeds:
            sid = str(seed.get("id") or "")
            if not sid:
                continue
            edges = edges_by_id.get(sid) or []
            for edge in edges or []:
                if not isinstance(edge, dict):
                    continue
                rel = str(edge.get("kind") or "")
                src = str(edge.get("src") or "")
                dst = str(edge.get("dst") or "")
                if rel not in OWNERSHIP_RELATIONS:
                    continue
                directed = False
                kind = ""
                if rel in {"WRITES", "DERIVES", "FLOWS_TO"} and src == sid:
                    if dst in writer_ids or str(seed.get("name") or "") == symbol:
                        directed = True
                        kind = "observable_data_dependency_changed"
                        if rel == "WRITES" and str(seed.get("name") or "") == symbol:
                            kind = "writer_changed"
                elif rel == "CONTROLS" and src == sid and dst in writer_ids:
                    directed = True
                    kind = "observable_control_dependency_changed"
                elif rel == "GUARDED_BY" and dst == sid and src in writer_ids:
                    directed = True
                    kind = "observable_control_dependency_changed"
                if not directed:
                    continue
                kinds.append(kind)
                evidence.append(
                    {
                        "hunk_id": hunk.get("hunk_id"),
                        "relation": rel,
                        "direction": "seed_to_writer",
                        "line": int(seed.get("line_start") or seed.get("line") or start),
                    }
                )
    return kinds, evidence


def annotate_candidate(
    row: dict[str, Any],
    *,
    hunks: list[dict[str, Any]] | None,
    file_key,
    query: Any = None,
    directed_proofs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Attach change.kinds / ownership / evidence. Never trust a bare bool."""
    symbol = str(row.get("symbol") or "").strip()
    kinds: list[str] = []
    evidence: list[dict[str, Any]] = []
    hunks = list(hunks or [])
    declared = row.get("declared_at") if isinstance(row.get("declared_at"), dict) else {}
    decl_file = file_key(str(declared.get("file") or ""))
    decl_line = int(declared.get("line") or 0)
    if hunks_covering(hunks, decl_file, decl_line, side="new"):
        kinds.append("declaration_in_changed_hunk")

    for writer in row.get("writers") or []:
        if not isinstance(writer, dict):
            continue
        wfile = file_key(str(writer.get("file") or ""))
        wline = int(writer.get("line") or writer.get("line_start") or 0)
        covered = hunks_covering(hunks, wfile, wline, side="new")
        for hunk in covered:
            kinds.append("writer_changed")
            evidence.append(
                {
                    "hunk_id": hunk.get("hunk_id"),
                    "relation": "WRITES",
                    "direction": "seed_to_writer",
                    "line": wline,
                }
            )

    for hunk in hunks:
        deleted = "\n".join(str(x) for x in (hunk.get("deleted_lines") or []))
        added = "\n".join(str(x) for x in (hunk.get("added_lines") or []))
        if symbol and symbol in names_assigned_in(deleted):
            kinds.append("observable_assignment_changed")
            evidence.append(
                {
                    "hunk_id": hunk.get("hunk_id"),
                    "relation": "WRITES",
                    "direction": "seed_to_writer",
                    "line": int(hunk.get("old_start") or 0),
                    "side": "old",
                }
            )
        if symbol and symbol in names_assigned_in(added):
            kinds.append("observable_assignment_changed")
            evidence.append(
                {
                    "hunk_id": hunk.get("hunk_id"),
                    "relation": "WRITES",
                    "direction": "seed_to_writer",
                    "line": int(hunk.get("new_start") or 0),
                    "side": "new",
                }
            )

    extra_kinds, extra_ev = _directed_from_query(
        query, symbol=symbol, writers=list(row.get("writers") or []), hunks=hunks
    )
    kinds.extend(extra_kinds)
    evidence.extend(extra_ev)
    for proof in directed_proofs or []:
        if not isinstance(proof, dict):
            continue
        kinds.append(str(proof.get("kind") or "observable_control_dependency_changed"))
        evidence.append(
            {
                "hunk_id": proof.get("hunk_id"),
                "relation": str(proof.get("relation") or "CONTROLS"),
                "direction": "seed_to_writer",
                "line": int(proof.get("line") or 0),
            }
        )

    if not kinds:
        kinds.append("entity_in_changed_file")
    row["change"] = derive_change(kinds, evidence)
    return row


def enclosing_function_range(lines: list[str], use_line: int) -> tuple[int, int]:
    """1-based inclusive range of the function containing ``use_line``."""
    if not lines:
        return (1, 1)
    idx = min(max(int(use_line), 1), len(lines))
    start = 1
    for i in range(idx, 0, -1):
        text = lines[i - 1].strip()
        match = _FUNC_OPEN.match(text)
        if match and match.group(1) not in _CONTROL_NAMES:
            start = i
            if "{" not in lines[i - 1] and i < len(lines) and "{" in lines[i]:
                start = i
            break
        if _FUNC_OPEN.match(lines[i - 1]) and not any(
            lines[i - 1].strip().startswith(k) for k in _CONTROL_NAMES
        ):
            start = i
            break
    depth = 0
    begun = False
    end = len(lines)
    for i in range(start, len(lines) + 1):
        depth += lines[i - 1].count("{") - lines[i - 1].count("}")
        if lines[i - 1].count("{"):
            begun = True
        if begun and depth <= 0:
            end = i
            break
    if not begun:
        return (1, len(lines))
    return (start, end)


def changed_use_lines(
    lines: list[str],
    operator_rel: str,
    hunks: list[dict[str, Any]],
) -> list[int]:
    uses: set[int] = set()
    for hunk in hunks or []:
        if path_matches(str(hunk.get("new_file") or ""), operator_rel):
            start = int(hunk.get("new_start") or 0)
            end = int(hunk.get("new_end") or 0)
            for line_no in range(start, end + 1):
                if 1 <= line_no <= len(lines) and is_control_or_compare(lines[line_no - 1]):
                    uses.add(line_no)
        if path_matches(str(hunk.get("old_file") or ""), operator_rel):
            for raw in hunk.get("deleted_lines") or []:
                if is_control_or_compare(str(raw)):
                    uses.add(int(hunk.get("old_start") or 0) or int(hunk.get("new_start") or 0))
    return sorted(uses)


def consumed_names(line: str) -> list[str]:
    names: list[str] = []
    for match in _IDENT.finditer(line or ""):
        name = match.group(1)
        if len(name) < 4:
            continue
        names.append(name)
    return names


def reaching_assignments(
    lines: list[str],
    name: str,
    use_line: int,
) -> list[dict[str, int]]:
    start, end = enclosing_function_range(lines, use_line)
    found: list[dict[str, int]] = []
    needle = re.compile(rf"\b{re.escape(name)}\s*=(?!=)")
    for idx in range(start, min(end, use_line) + 1):
        if needle.search(lines[idx - 1]):
            found.append({"line": idx})
    return found
