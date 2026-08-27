# -*- coding: utf-8 -*-
"""UO-grounded scope packet for tg-plan.

Plan Owner consumes semantics; it must not rediscover them. Everything the
Coverage IR is allowed to name -- observable replay leaves, probeable host
locals, confirmed controls, changed behaviour candidates -- is resolved here
from the pinned change contract plus the finalized CodeMap, so the model never
has to reverse engineer the PR from raw diff or guess an observation vocabulary.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from acp_common.paths import canonical_path, resolve_under_operator, strip_dot_slash

from . import product_uo
from .pr_ownership import (
    annotate_candidate,
    changed_use_lines,
    consumed_names,
    is_control_or_compare,
    reaching_assignments,
)

PACKET_SCHEMA = "tg-plan-scope-packet/v3"

# Bumped whenever the meaning of a plan section changes. Plan Owner receives
# these verbatim; a stale methodology copy is detected by contract_digest.
METHOD_CONTRACT = {
    "schema": "tg-plan/v3",
    "guard_semantics": "activation/v1",
    "l2_contract": "per_target_cross/v1",
    "target_policy": "pr-owned-observable/v1",
    "probe_policy": "changed_use_reaching_def/v1",
    "observation_policy": "packet_allowlist/v1",
}

PACKET_USAGE = {
    "observation_catalog.replay_allowed": "`replay.<field>` 只能引用这些名字",
    "observation_catalog.replay_forbidden": "不得写成 `replay.*`；用 dispatch_map 或 probe",
    "observation_catalog.probe_candidates": "`probe.*` 的唯一来源",
    "controls.case_allowed": "`case.*` / controls / construct_hint.columns 只能用这些列",
    "behavior_candidates": (
        "发现用的词表。pr_regression Target 只能引用 "
        "change.ownership.pr_eligible 且 change.evidence 含 ownership 关系的符号"
    ),
    "deleted_symbols": "本次 hunk 删除、HEAD UO 里可能已经没有的符号；不要靠现图恢复",
    "modified_writes": "本次 hunk 新增赋值左侧；Owner 点名写点用这份，不要通读 diff",
    "plan_route_card": "给 Primary 拆路的改动摘要；Owner 不要用它代替 observation_catalog",
}

# Kinds that can legitimately back a Target's observable assignment.
_OBSERVABLE_KINDS = ("TILING_FIELD", "FIELD")
# Kinds that route dispatch but are not TilingData leaves; naming them under
# `replay.` is the `replay.DeterType` failure mode.
_DISPATCH_KINDS = ("TILING_KEY",)

_BEHAVIOR_CAP = 24
_LOCAL_CAP = 40
_IDENT = re.compile(r"^[A-Za-z_]\w*$")
_ASSIGN_SKIP = re.compile(r"==|!=|<=|>=")
_SOURCE_SUFFIXES = (".cpp", ".h", ".cc", ".hpp")


def contract_digest(repo_root: Path | str) -> str:
    """Digest of the authoritative methodology files Plan Owner must follow."""
    root = Path(repo_root)
    parts: list[bytes] = []
    for rel in (
        "prompts/tasks/tg/plan-owner.md",
        "skills/test-plan/SKILL.md",
        "skills/test-plan/references/coverage-ir.md",
        "skills/test-plan/references/target-planning.md",
        "skills/test-plan/references/evidence.md",
    ):
        path = root / rel
        try:
            parts.append(path.read_bytes())
        except OSError:
            parts.append(b"")
    digest = hashlib.sha256()
    for blob in parts:
        digest.update(hashlib.sha256(blob).digest())
    return digest.hexdigest()


def method_contract(repo_root: Path | str | None = None) -> dict[str, Any]:
    out = dict(METHOD_CONTRACT)
    if repo_root is not None:
        out["contract_digest"] = contract_digest(repo_root)
    return out


def _open_query(project_root: Path, *, op_name: str, architecture: str):
    from uo_init.uo_query import open_query

    return open_query(Path(project_root), op_name=op_name, architecture=architecture)


def resolve_changed_file(
    project_root: Path,
    rel: str,
    *,
    repo_root: Path | str | None = None,
) -> Path | None:
    """Map a contract path onto this operator tree. Fail closed on ambiguity."""
    repo = Path(repo_root) if repo_root else None
    return resolve_under_operator(Path(project_root), rel, repo_root=repo)


def observation_catalog(
    project_root: Path,
    *,
    op_name: str = "",
    architecture: str = "",
) -> dict[str, Any]:
    """Replay allowlist plus the dispatch names that must not be spelled `replay.*`."""
    allowed = product_uo.replay_observe_fields(
        project_root, op_name=op_name, architecture=architecture
    )
    out: dict[str, Any] = {
        "replay_allowed": sorted(allowed) if allowed else [],
        "replay_forbidden": [],
        "note": (
            "`replay.<field>` 只能引用 replay_allowed。replay_forbidden 里的名字是 dispatch "
            "维度实体，不是 TilingData 叶子：要观测它们请用 kind: dispatch_map 或 probe。"
        ),
    }
    if allowed is None:
        out["replay_allowed_unavailable"] = True
        out["note"] = "UO views/tilingdata.yaml 不可用；replay 字段词表未知，validate 时才会兜底检查。"
        return out
    forbidden: list[dict[str, Any]] = []
    try:
        with _open_query(Path(project_root), op_name=op_name, architecture=architecture) as query:
            for row in query.tiling_keys():
                name = str(row.get("name") or "").strip()
                if not name or name in allowed:
                    continue
                forbidden.append(
                    {
                        "name": name,
                        "kind": "TILING_KEY",
                        "file": str(row.get("file") or ""),
                        "line": int(row.get("line_start") or 0),
                        "reason": "dispatch 维度实体，不是 TilingData 叶子；不得写成 replay.<name>",
                    }
                )
    except Exception as exc:  # noqa: BLE001
        out["replay_forbidden_error"] = str(exc)[:200]
        return out
    forbidden.sort(key=lambda r: str(r.get("name")))
    out["replay_forbidden"] = forbidden
    return out


def _file_key(
    project_root: Path,
    rel: str,
    *,
    repo_root: Path | str | None = None,
) -> str:
    """Canonical operator-relative spelling, or a prefix-safe fallback."""
    repo = Path(repo_root) if repo_root else None
    canon = canonical_path(Path(project_root), rel, repo_root=repo)
    if canon is not None:
        return canon.canonical_operator_rel
    return strip_dot_slash(rel)


def _sites(rows: Any, *, limit: int = 4) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        file = str(row.get("file") or "").strip()
        line = row.get("line") if row.get("line") is not None else row.get("line_start")
        try:
            line_i = int(line or 0)
        except (TypeError, ValueError):
            line_i = 0
        if not file:
            continue
        item = {"file": file, "line": line_i, "name": str(row.get("name") or "")}
        if row.get("id"):
            item["id"] = str(row.get("id"))
        out.append(item)
        if len(out) >= limit:
            break
    return out


def behavior_candidates(
    project_root: Path,
    changed_files: list[str],
    *,
    op_name: str = "",
    architecture: str = "",
    replay_allowed: list[str] | None = None,
    repo_root: Path | str | None = None,
    changed_hunks: list[dict[str, Any]] | None = None,
    directed_proofs: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Observable assignments in the pinned files; ownership is hunk evidence."""
    if not changed_files:
        return {"candidates": [], "identifiers": [], "note": "pin 无 changed_files"}
    allow = {str(x) for x in (replay_allowed or [])}
    root = Path(project_root)
    changed_keys = {
        _file_key(root, str(rel), repo_root=repo_root) for rel in changed_files if rel
    }
    hunks = list(changed_hunks or [])
    proofs = directed_proofs or {}
    candidates: list[dict[str, Any]] = []
    identifiers: list[str] = []
    note = ""
    try:
        with _open_query(root, op_name=op_name, architecture=architecture) as query:
            hits = query.entities_in_files(changed_files)
            seen: set[str] = set()
            for hit in hits:
                kind = str(hit.get("kind") or "").strip()
                name = str(hit.get("name") or "").strip()
                if not name or name in seen:
                    continue
                if kind not in _OBSERVABLE_KINDS and kind not in _DISPATCH_KINDS:
                    continue
                seen.add(name)
                row: dict[str, Any] = {
                    "id": f"B{len(candidates) + 1}",
                    "symbol": name,
                    "kind": kind,
                    "declared_at": {
                        "file": str(hit.get("file") or ""),
                        "line": int(hit.get("line_start") or 0),
                    },
                }
                if kind in _DISPATCH_KINDS:
                    row["observable"] = {"dispatch": name}
                    row["not_a_replay_leaf"] = True
                elif name in allow or not allow:
                    row["observable"] = {"replay_field": name}
                else:
                    row["observable"] = {"probe": name}
                    row["replay_unavailable"] = True
                candidates.append(row)
                identifiers.append(name)
                if len(candidates) >= _BEHAVIOR_CAP:
                    note = f"截断到前 {_BEHAVIOR_CAP} 个候选"
                    break
            impacts: dict[str, Any] = {}
            try:
                impacts = query.field_impact_many(identifiers)
            except Exception:  # noqa: BLE001
                impacts = {}
            for row in candidates:
                name = str(row.get("symbol") or "")
                impact = impacts.get(name) if isinstance(impacts, dict) else {}
                if isinstance(impact, dict) and impact.get("ok") is not False:
                    writers = _sites(impact.get("writers"))
                    readers = _sites(impact.get("readers"))
                    if writers:
                        row["writers"] = writers
                    if readers:
                        row["readers"] = readers
                    changed_writers = [
                        w
                        for w in writers
                        if _file_key(root, str(w.get("file") or ""), repo_root=repo_root)
                        in changed_keys
                    ]
                    row["written_in_changed_files"] = bool(changed_writers)
                annotate_candidate(
                    row,
                    hunks=hunks,
                    file_key=lambda rel, _root=root: _file_key(
                        _root, rel, repo_root=repo_root
                    ),
                    query=query,
                    directed_proofs=proofs.get(name),
                )
    except Exception as exc:  # noqa: BLE001
        return {
            "candidates": [],
            "identifiers": [],
            "note": f"UO 不可用，behavior_candidates 未构建：{str(exc)[:160]}",
        }
    return {"candidates": candidates, "identifiers": identifiers, "note": note}


def branch_locals(
    project_root: Path,
    changed_files: list[str],
    *,
    replay_allowed: list[str] | None = None,
    repo_root: Path | str | None = None,
    changed_hunks: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Locals consumed by a changed branch/compare, with unique reaching defs.

    ``PROBE_AMBIGUOUS`` means more than one assignment in the containing
    function can reach that changed use — not "hunk contains two `=`".
    """
    allow = {str(x) for x in (replay_allowed or [])}
    hunks = list(changed_hunks or [])
    per_name: dict[str, dict[str, Any]] = {}
    root = Path(project_root)
    for rel in changed_files or []:
        path = resolve_changed_file(root, rel, repo_root=repo_root)
        if path is None or path.suffix not in _SOURCE_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        op_rel = _file_key(root, rel, repo_root=repo_root)
        uses = changed_use_lines(lines, op_rel, hunks) if hunks else [
            idx
            for idx, line in enumerate(lines, start=1)
            if is_control_or_compare(line)
        ]
        for use_line in uses:
            line = lines[use_line - 1] if 1 <= use_line <= len(lines) else ""
            consumed_by_branch = bool(
                line.strip().startswith(("if", "} else if", "else if", "while"))
                or " ? " in line
            )
            consumed_by_compare = (not consumed_by_branch) and is_control_or_compare(line)
            for name in consumed_names(line):
                if not _IDENT.match(name) or name in allow:
                    continue
                defs = reaching_assignments(lines, name, use_line)
                if not defs:
                    continue
                row = per_name.setdefault(
                    name,
                    {
                        "name": name,
                        "assignments": [],
                        "consumed_by_branch": False,
                        "consumed_by_compare": False,
                    },
                )
                row["consumed_by_branch"] = row["consumed_by_branch"] or consumed_by_branch
                row["consumed_by_compare"] = row["consumed_by_compare"] or consumed_by_compare
                for item in defs:
                    site = {"file": path.name, "line": int(item["line"])}
                    if site not in row["assignments"] and len(row["assignments"]) < 8:
                        row["assignments"].append(site)
    out: list[dict[str, Any]] = []
    for row in per_name.values():
        if not (row["consumed_by_branch"] or row["consumed_by_compare"]):
            continue
        unique = len(row["assignments"]) == 1
        row["probeable"] = unique
        if not unique:
            row["probe_blocked"] = "PROBE_AMBIGUOUS: 到达 changed use 的 reaching definition 不唯一"
        out.append(row)
    out.sort(
        key=lambda r: (not r.get("probeable"), not r.get("consumed_by_branch"), str(r.get("name")))
    )
    return out[:_LOCAL_CAP]


def controls_catalog(init_doc: dict[str, Any] | None) -> dict[str, Any]:
    """Split init columns into what may appear in `case.*` and what must go to untestable."""
    from .products import CONFIDENCES, mapping_as_dict

    doc = init_doc if isinstance(init_doc, dict) else {}
    mapping = mapping_as_dict(doc.get("mapping"))
    confirmed: list[str] = []
    unresolved: list[str] = []
    inactive: list[str] = []
    for col, row in sorted(mapping.items()):
        if not isinstance(row, dict):
            continue
        control = row.get("control") if isinstance(row.get("control"), dict) else {}
        status = str(control.get("status") or "").strip()
        confidence = str(row.get("confidence") or "").strip()
        if confidence not in CONFIDENCES:
            confidence = ""
        if status != "active":
            inactive.append(col)
        elif confidence == "confirmed":
            confirmed.append(col)
        else:
            unresolved.append(col)
    return {
        "case_allowed": confirmed,
        "unresolved_active": unresolved,
        "inactive": inactive,
        "note": (
            "case.* / controls / construct_hint.columns 只能用 case_allowed。"
            "路径闭包上 construct 未闭合的列写入 untestable.kind=control_gap，并填 needs_binding。"
            "本质不可控/不可观测用 harness_gap 或 opaque；ownership 未闭合用 unverified。"
            "身份缺口（空 uo.id + candidate）只要 confidence=confirmed 就不进 untestable。"
        ),
    }


_IDENT_TOKEN = re.compile(r"\b([A-Za-z_]\w{2,})\b")
_IDENT_SKIP = frozenset(
    {
        "int", "void", "bool", "char", "long", "short", "float", "double", "auto",
        "const", "static", "inline", "return", "class", "struct", "enum", "namespace",
        "template", "typename", "using", "public", "private", "protected", "virtual",
        "override", "nullptr", "true", "false", "this", "if", "else", "for", "while",
        "switch", "case", "break", "continue", "sizeof", "include", "define",
        "std", "vector", "string", "size_t",
    }
)
_ASSIGN_LHS = re.compile(r"([A-Za-z_]\w*)\s*=(?!=)")
_DIR_ROLES = (
    ("op_kernel/", "kernel"),
    ("op_host/", "host"),
    ("common/", "common"),
)


def _hunk_path(hunk: dict[str, Any] | None) -> str:
    if not isinstance(hunk, dict):
        return ""
    return str(hunk.get("new_file") or hunk.get("old_file") or "").replace("\\", "/").lstrip("./")


def _idents_in_lines(lines: Any) -> list[str]:
    seen: list[str] = []
    for line in lines or []:
        for match in _IDENT_TOKEN.finditer(str(line)):
            name = match.group(1)
            if name in _IDENT_SKIP or name.startswith("_"):
                continue
            if name not in seen:
                seen.append(name)
    return seen


def hunk_change_digest(
    hunks: list[dict[str, Any]] | None,
    *,
    cap: int = 24,
) -> dict[str, list[str]]:
    """Deleted symbols and assignment writes from operator hunks — not HEAD UO."""
    deleted: list[str] = []
    writes: list[str] = []
    for row in hunks or []:
        if not isinstance(row, dict):
            continue
        gone = _idents_in_lines(row.get("deleted_lines"))
        added = set(_idents_in_lines(row.get("added_lines")))
        for name in gone:
            if name not in added and name not in deleted:
                deleted.append(name)
            if len(deleted) >= cap:
                break
        for line in row.get("added_lines") or []:
            match = _ASSIGN_LHS.search(str(line))
            if not match:
                continue
            name = match.group(1)
            if name in _IDENT_SKIP or name in writes:
                continue
            writes.append(name)
            if len(writes) >= cap:
                break
        if len(deleted) >= cap and len(writes) >= cap:
            break
    return {"deleted_symbols": deleted[:cap], "modified_writes": writes[:cap]}


def _dir_role(path: str) -> str:
    n = str(path or "").replace("\\", "/")
    for marker, role in _DIR_ROLES:
        if n.startswith(marker) or f"/{marker}" in f"/{n}":
            return role
    return ""


def build_plan_route_card(
    changed_files: list[str] | None,
    changed_hunks: list[dict[str, Any]] | None,
    *,
    relevant_hunks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Short git digest for Primary routing. Not a constructability table."""
    rows = [h for h in (changed_hunks or []) if isinstance(h, dict)]
    rows.extend(h for h in (relevant_hunks or []) if isinstance(h, dict))
    by_file: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        path = _hunk_path(row)
        if path:
            by_file.setdefault(path, []).append(row)
    for rel in changed_files or []:
        path = str(rel or "").replace("\\", "/").lstrip("./")
        if path and path not in by_file:
            by_file[path] = []
    clusters_map: dict[str, dict[str, Any]] = {}
    file_rows: list[dict[str, Any]] = []
    for path, hunk_rows in sorted(by_file.items()):
        role = _dir_role(path)
        if not role:
            continue
        digest = hunk_change_digest(hunk_rows)
        file_rows.append(
            {
                "path": path,
                "status": (hunk_rows[0].get("status") if hunk_rows else "modified"),
                "hunks": len(hunk_rows),
                "kind": role,
            }
        )
        cluster = clusters_map.setdefault(
            role,
            {
                "id": f"C-{role}",
                "kind": role,
                "files": [],
                "deleted": [],
                "writes": [],
            },
        )
        cluster["files"].append(path)
        for name in digest.get("deleted_symbols") or []:
            if name not in cluster["deleted"]:
                cluster["deleted"].append(name)
        for name in digest.get("modified_writes") or []:
            if name not in cluster["writes"]:
                cluster["writes"].append(name)
    clusters = list(clusters_map.values())
    if not clusters:
        listed = [str(x) for x in (changed_files or []) if str(x).strip()][:16]
        clusters = [
            {
                "id": "C-main",
                "kind": "host",
                "files": listed,
                "deleted": [],
                "writes": [],
            }
        ]
        file_rows = [{"path": p, "status": "modified", "hunks": 0, "kind": "host"} for p in listed]
    n = len(clusters)
    if n <= 1:
        hint = "one_owner"
        hint_zh = "一路且短：立刻 1 个 Plan Owner"
    else:
        n_frag = min(n, 5)
        hint = "fragments"
        hint_zh = f"{n_frag} 路 FOCUS fragment + 1 个 Owner（最多 5 路）"
    overall = hunk_change_digest(rows)
    return {
        "files": file_rows[:24],
        "clusters": clusters[:5],
        "deleted_symbols": overall.get("deleted_symbols") or [],
        "modified_writes": overall.get("modified_writes") or [],
        "route_hint": hint,
        "route_hint_zh": hint_zh,
    }


def format_plan_route_card(card: dict[str, Any] | None) -> str:
    """One compact block Primary can split on without opening the packet."""
    doc = card if isinstance(card, dict) else {}
    clusters = [c for c in (doc.get("clusters") or []) if isinstance(c, dict)]
    if not clusters:
        return "改动摘要为空；按单簇处理，立刻 1 个 Plan Owner。"
    bits: list[str] = []
    for cluster in clusters:
        files = ", ".join(str(p) for p in (cluster.get("files") or [])[:6])
        extra: list[str] = []
        deleted = [str(x) for x in (cluster.get("deleted") or [])[:6] if x]
        writes = [str(x) for x in (cluster.get("writes") or [])[:6] if x]
        if deleted:
            extra.append("删 " + ",".join(deleted))
        if writes:
            extra.append("写 " + ",".join(writes))
        suffix = f"（{'；'.join(extra)}）" if extra else ""
        bits.append(f"{cluster.get('kind') or 'cluster'}[{files}]{suffix}")
    hint = str(doc.get("route_hint_zh") or "").strip()
    return "改动摘要：" + "；".join(bits) + ("。" + hint if hint else "。")


def semantic_delta(
    project_root: Path,
    *,
    op_name: str = "",
    architecture: str = "",
    changed_files: list[str] | None = None,
    changed_hunks: list[dict[str, Any]] | None = None,
    relevant_hunks: list[dict[str, Any]] | None = None,
    init_doc: dict[str, Any] | None = None,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Engine-facing batch UO context. Not an agent tool."""
    return build_semantic_packet(
        project_root,
        op_name=op_name,
        architecture=architecture,
        changed_files=changed_files,
        changed_hunks=changed_hunks,
        relevant_hunks=relevant_hunks,
        init_doc=init_doc,
        repo_root=repo_root,
    )


def build_semantic_packet(
    project_root: Path,
    *,
    op_name: str = "",
    architecture: str = "",
    changed_files: list[str] | None = None,
    changed_hunks: list[dict[str, Any]] | None = None,
    relevant_hunks: list[dict[str, Any]] | None = None,
    init_doc: dict[str, Any] | None = None,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Assemble the UO-grounded half of the packet. Never raises on UO gaps."""
    files = [str(f) for f in (changed_files or []) if str(f).strip()]
    hunks = [row for row in (changed_hunks or []) if isinstance(row, dict)]
    extra = [row for row in (relevant_hunks or []) if isinstance(row, dict)]
    catalog = observation_catalog(
        Path(project_root), op_name=op_name, architecture=architecture
    )
    allowed = list(catalog.get("replay_allowed") or [])
    behavior = behavior_candidates(
        Path(project_root),
        files,
        op_name=op_name,
        architecture=architecture,
        replay_allowed=allowed,
        repo_root=repo_root,
        changed_hunks=hunks,
    )
    locals_rows = branch_locals(
        Path(project_root),
        files,
        replay_allowed=allowed,
        repo_root=repo_root,
        changed_hunks=hunks,
    )
    catalog["probe_candidates"] = [
        row["name"] for row in locals_rows if row.get("probeable")
    ]
    digest = hunk_change_digest(hunks + extra)
    return {
        "method_contract": method_contract(repo_root),
        "observation_catalog": catalog,
        "controls": controls_catalog(init_doc),
        "behavior_candidates": behavior.get("candidates") or [],
        "branch_locals": locals_rows,
        "identifiers": behavior.get("identifiers") or [],
        "deleted_symbols": digest.get("deleted_symbols") or [],
        "modified_writes": digest.get("modified_writes") or [],
        "plan_route_card": build_plan_route_card(files, hunks, relevant_hunks=extra),
        "usage": dict(PACKET_USAGE),
        "packet_notes": [
            n
            for n in (behavior.get("note"), catalog.get("replay_forbidden_error"))
            if n
        ],
    }
