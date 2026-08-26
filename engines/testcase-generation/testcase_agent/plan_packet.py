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

from . import product_uo

PACKET_SCHEMA = "tg-plan-scope-packet/v2"

# Bumped whenever the meaning of a plan section changes. Plan Owner receives
# these verbatim; a stale methodology copy is detected by contract_digest.
METHOD_CONTRACT = {
    "schema": "tg-plan/v3",
    "guard_semantics": "activation/v1",
    "l2_contract": "full_cross_exclusions/v1",
    "target_policy": "changed_assignment/v1",
    "probe_policy": "branch_consumed_local/v1",
    "observation_policy": "packet_allowlist/v1",
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
        "skills/test-plan/references/coverage-planning.md",
        "skills/test-plan/references/target-planning.md",
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


def resolve_changed_file(project_root: Path, rel: str) -> Path | None:
    """Map a contract path (repo-relative) onto this operator tree."""
    text = str(rel or "").strip().replace("\\", "/").lstrip("./")
    if not text:
        return None
    root = Path(project_root)
    direct = root / text
    if direct.is_file():
        return direct
    parts = text.split("/")
    for cut in range(1, len(parts)):
        cand = root / "/".join(parts[cut:])
        if cand.is_file():
            return cand
    name = parts[-1]
    for path in root.rglob(name):
        if path.is_file():
            return path
    return None


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
        out.append({"file": file, "line": line_i, "name": str(row.get("name") or "")})
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
) -> dict[str, Any]:
    """Observable assignments living in the pinned changed files, with writers/readers."""
    if not changed_files:
        return {"candidates": [], "identifiers": [], "note": "pin 无 changed_files"}
    allow = {str(x) for x in (replay_allowed or [])}
    changed_tails = {
        str(rel).replace("\\", "/").lstrip("./").split("/")[-1] for rel in changed_files if rel
    }
    candidates: list[dict[str, Any]] = []
    identifiers: list[str] = []
    note = ""
    try:
        with _open_query(Path(project_root), op_name=op_name, architecture=architecture) as query:
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
                try:
                    impact = query.field_impact(name)
                except Exception:  # noqa: BLE001
                    impact = {}
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
                        if str(w.get("file") or "").split("/")[-1] in changed_tails
                    ]
                    row["written_in_changed_files"] = bool(changed_writers)
                candidates.append(row)
                identifiers.append(name)
                if len(candidates) >= _BEHAVIOR_CAP:
                    note = f"截断到前 {_BEHAVIOR_CAP} 个候选；其余用 uo_query 按符号名查"
                    break
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
) -> list[dict[str, Any]]:
    """Host locals assigned in the changed files, flagged when a branch consumes them.

    Probe eligibility needs a *unique* assignment inside the pinned change; the
    same identifier written twice is reported as ambiguous rather than silently
    picked, matching the injector's `PROBE_AMBIGUOUS`.
    """
    allow = {str(x) for x in (replay_allowed or [])}
    assign = re.compile(r"\b([A-Za-z_]\w*)\s*=(?!=)")
    per_name: dict[str, dict[str, Any]] = {}
    for rel in changed_files or []:
        path = resolve_changed_file(Path(project_root), rel)
        if path is None or path.suffix not in _SOURCE_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = text.splitlines()
        local: dict[str, dict[str, Any]] = {}
        written_at: dict[str, set[int]] = {}
        for idx, line in enumerate(lines, start=1):
            if "TG_PROBE" in line:
                continue
            for match in assign.finditer(line):
                name = match.group(1)
                if not _IDENT.match(name) or len(name) < 4 or name in allow:
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
                if len(row["assignments"]) < 4:
                    row["assignments"].append({"file": path.name, "line": idx})
                written_at.setdefault(name, set()).add(idx)
                local[name] = row
        # Consumption is judged inside the file that assigns the name (a host
        # local never escapes its translation unit) and excludes the assignment
        # itself, whose right-hand side says nothing about who reads the result.
        for name, row in local.items():
            needle = re.compile(rf"\b{re.escape(name)}\b")
            skip = written_at.get(name) or set()
            for idx, line in enumerate(lines, start=1):
                if idx in skip or not needle.search(line):
                    continue
                stripped = line.strip()
                if stripped.startswith(("if", "} else if", "else if", "while")) or " ? " in line:
                    row["consumed_by_branch"] = True
                if _ASSIGN_SKIP.search(line) or re.search(r"[<>]\s*[A-Za-z0-9_(]", line):
                    row["consumed_by_compare"] = True
                if re.search(r"\b(Min|Max|std::min|std::max)\s*\(", line):
                    row["consumed_by_compare"] = True
    out: list[dict[str, Any]] = []
    for row in per_name.values():
        if not (row["consumed_by_branch"] or row["consumed_by_compare"]):
            continue
        unique = len(row["assignments"]) == 1
        row["probeable"] = unique
        if not unique:
            row["probe_blocked"] = "PROBE_AMBIGUOUS: 改动范围内多处赋值"
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
            "unresolved_active 里落在本次 Target 路径闭包上的列必须出现在 untestable。"
        ),
    }


def build_semantic_packet(
    project_root: Path,
    *,
    op_name: str = "",
    architecture: str = "",
    changed_files: list[str] | None = None,
    init_doc: dict[str, Any] | None = None,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Assemble the UO-grounded half of the packet. Never raises on UO gaps."""
    files = [str(f) for f in (changed_files or []) if str(f).strip()]
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
    )
    locals_rows = branch_locals(Path(project_root), files, replay_allowed=allowed)
    catalog["probe_candidates"] = [
        row["name"] for row in locals_rows if row.get("probeable")
    ]
    return {
        "method_contract": method_contract(repo_root),
        "observation_catalog": catalog,
        "controls": controls_catalog(init_doc),
        "behavior_candidates": behavior.get("candidates") or [],
        "branch_locals": locals_rows,
        "identifiers": behavior.get("identifiers") or [],
        "packet_notes": [
            n
            for n in (behavior.get("note"), catalog.get("replay_forbidden_error"))
            if n
        ],
    }
