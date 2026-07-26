"""Shared extract_plan load / validate helpers (no operator-specific names)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from uo.scripts._ir_io import read_yaml
from uo.scripts.ir_summary import (
    DEFAULT_LARGE_IR_MUST,
    attach_large_ir_meta,
    scan_yaml_section_lines,
)
from uo.scripts.source_evidence import (
    MIN_EVIDENCE_SNIPPET_CHARS as _MIN_EVIDENCE_SNIPPET_CHARS,
    is_placeholder_sha256,
    parse_line_span as _parse_line_span,
    require_disk_window_proof,
    require_high_confidence_source_fields,
)

WRITER_ROLES = frozenset(
    {
        "tiling_writer",
        "key_writer",
        "workspace_writer",
        "provenance_helper",
        "ignore",
    }
)

# Roles that stay on the host call chain (attrs/branches), including TDF writers.
CHAIN_ROLES = frozenset(
    {
        "tiling_writer",
        "key_writer",
        "workspace_writer",
        "provenance_helper",
    }
)

EVIDENCE_SOURCES = frozenset({"source", "cbm", "candidate_only"})
PROMOTED_WRITER_ROLES = frozenset({"tiling_writer", "key_writer", "workspace_writer"})
WEAK_SCORE_THRESHOLD = 0.55


def _cand_identity(item: dict[str, Any]) -> str:
    if item.get("identity_key"):
        return str(item["identity_key"]).casefold()
    fp = str(item.get("file_path") or "").replace("\\", "/")
    qn = str(item.get("qualified_name") or item.get("name") or "")
    cls = str(item.get("class_or_namespace") or "")
    sig = str(item.get("normalized_signature") or item.get("signature") or "")
    tpl = str(item.get("template_arity_or_signature") or "")
    return f"{fp}|{qn}|{cls}|{sig}|{tpl}".casefold()


def load_extract_plan(uo_root: Path) -> dict[str, Any] | None:
    path = uo_root / "ir" / "extract_plan.yaml"
    if not path.is_file():
        return None
    # read_yaml applies literal-block sanitize for extract_plan.yaml
    data = read_yaml(path)
    return data if isinstance(data, dict) else None


_CANDIDATES_SECTION_KEYS = (
    "writer_candidates",
    "receiver_candidates",
    "alias_candidates",
    "non_sink_root_candidates",
    "extra_entry_candidates",
)


def scan_candidates_section_lines(candidates_path: Path) -> dict[str, dict[str, int]]:
    """Thin wrap: extract_plan candidates section keys → public YAML line scan."""
    return scan_yaml_section_lines(candidates_path, _CANDIDATES_SECTION_KEYS)


_NAME_ITEM_LINE_RE = re.compile(r"^(\s*)-\s+name:\s*")


def scan_candidate_name_item_lines(
    candidates_path: Path | None,
    *,
    section_lines: dict[str, dict[str, int]] | None = None,
) -> dict[str, list[int]]:
    """1-based YAML lines of ``- name:`` items per candidates section (order preserved)."""
    out: dict[str, list[int]] = {k: [] for k in _CANDIDATES_SECTION_KEYS}
    if candidates_path is None or not Path(candidates_path).is_file():
        return out
    try:
        text = Path(candidates_path).read_text(encoding="utf-8")
    except OSError:
        return out
    sections = section_lines or scan_candidates_section_lines(Path(candidates_path))
    lines = text.splitlines()
    for key in _CANDIDATES_SECTION_KEYS:
        span = sections.get(key) if isinstance(sections, dict) else None
        if not isinstance(span, dict):
            continue
        start = int(span.get("start_line") or 0)
        end = int(span.get("end_line") or 0)
        if start < 1 or end < start:
            continue
        for lineno in range(start, min(end, len(lines)) + 1):
            if _NAME_ITEM_LINE_RE.match(lines[lineno - 1] or ""):
                out[key].append(lineno)
    return out


def _source_window_nav(c: dict[str, Any]) -> tuple[int | None, int | None, str | None]:
    """Return (start_line, end_line, source_window_sha256) from candidate fields."""
    sw = c.get("source_window") if isinstance(c.get("source_window"), dict) else {}
    start = int(c.get("start_line") or sw.get("start_line") or 0) or None
    end = int(c.get("end_line") or sw.get("end_line") or 0) or None
    sha = str(sw.get("sha256") or "").strip() or None
    return start, end, sha


def build_extract_plan_candidates_summary(
    candidates: dict[str, Any],
    *,
    candidates_sha256: str = "",
    section_lines: dict[str, dict[str, int]] | None = None,
    candidates_line_count: int | None = None,
    candidates_path: Path | None = None,
) -> dict[str, Any]:
    """Action-shaped summary; public ``section_lines``/``must`` via ``ir_summary``."""
    writers = [c for c in (candidates.get("writer_candidates") or []) if isinstance(c, dict)]
    receivers = [
        c for c in (candidates.get("receiver_candidates") or []) if isinstance(c, dict)
    ]
    sinks = [c for c in receivers if c.get("is_tiling_sink_suggested") is True]
    aliases = [c for c in (candidates.get("alias_candidates") or []) if isinstance(c, dict)]
    non_sinks = [
        c for c in (candidates.get("non_sink_root_candidates") or []) if isinstance(c, dict)
    ]
    extras = [
        c for c in (candidates.get("extra_entry_candidates") or []) if isinstance(c, dict)
    ]
    name_lines = scan_candidate_name_item_lines(
        candidates_path, section_lines=section_lines
    )
    writer_lines = name_lines.get("writer_candidates") or []
    recv_lines = name_lines.get("receiver_candidates") or []

    def _short_writer(c: dict[str, Any], idx: int) -> dict[str, Any]:
        start, end, sha = _source_window_nav(c)
        card: dict[str, Any] = {
            "name": str(c.get("name") or "").strip(),
            "file_path": str(c.get("file_path") or "").replace("\\", "/"),
            "start_line": start,
            "end_line": end,
            "source_window_sha256": sha,
            "role_suggested": str(c.get("role_suggested") or "").strip() or None,
            "score": c.get("score"),
        }
        if idx < len(writer_lines):
            card["candidates_line"] = writer_lines[idx]
        return card

    def _short_recv(c: dict[str, Any], idx: int) -> dict[str, Any]:
        start, end, sha = _source_window_nav(c)
        card: dict[str, Any] = {
            "name": str(c.get("name") or "").strip(),
            "file_path": str(c.get("file_path") or "").replace("\\", "/"),
            "start_line": start,
            "end_line": end,
            "source_window_sha256": sha,
            "is_tiling_sink_suggested": bool(c.get("is_tiling_sink_suggested")),
            "score": c.get("score"),
        }
        if idx < len(recv_lines):
            card["candidates_line"] = recv_lines[idx]
        return card

    key_writers = [
        str(c.get("name") or "").strip()
        for c in writers
        if str(c.get("role_suggested") or "").strip() == "key_writer"
        and str(c.get("name") or "").strip()
    ]
    # Sink cards keep navigation; map each sink back to its receiver index for candidates_line.
    sink_cards: list[dict[str, Any]] = []
    for c in sinks[:80]:
        try:
            ridx = receivers.index(c)
        except ValueError:
            ridx = len(recv_lines)  # omit candidates_line when unmapped
        sink_cards.append(_short_recv(c, ridx))

    non_sink_root_names = [
        str(c.get("name") or "").strip()
        for c in non_sinks
        if str(c.get("name") or "").strip()
    ]
    domain = {
        "kind": "extract_plan_candidates_summary",
        "counts": {
            "writers": len(writers),
            "receivers": len(receivers),
            "sinks_suggested": len(sinks),
            "aliases": len(aliases),
            "non_sink_roots": len(non_sinks),
            "extra_entries": len(extras),
        },
        "writer_candidates": [_short_writer(c, i) for i, c in enumerate(writers[:80])],
        "sink_candidates": sink_cards,
        "receiver_candidates": [_short_recv(c, i) for i, c in enumerate(receivers[:80])],
        "key_writer_suggested": key_writers,
        "alias_candidates": [
            {
                "local": str(c.get("local") or "").strip(),
                "tdf_leaf": str(c.get("tdf_leaf") or "").strip(),
            }
            for c in aliases[:80]
            if str(c.get("local") or "").strip() and str(c.get("tdf_leaf") or "").strip()
        ],
        # Compact allowlist for plan.non_sink_roots (assign-LHS names, not functions).
        "non_sink_root_names": non_sink_root_names,
    }
    must = (
        f"{DEFAULT_LARGE_IR_MUST} "
        "extract_plan: also Read extract_plan.rework_hints.yaml if present; "
        "aliases require local+tdf_leaf. "
        "Copy summary source_window_sha256 into evidence_window_sha256 "
        "(or leave sha blank when evidence_files+lines+contiguous snippet are set — "
        "apply enrich fills sha from disk). "
        "FORBIDDEN: Grep/findstr whole candidates only to harvest sha256; "
        "FORBIDDEN: reuse a neighbor candidate's hash. "
        "non_sink_roots: prefer []; if accepting any, copy exact names from "
        "summary non_sink_root_names only (assign-LHS identifiers, not functions). "
        "FORBIDDEN: invent names from evidence_snippet / source identifiers; "
        "uncertain → omit."
    )
    return attach_large_ir_meta(
        domain,
        section_lines=section_lines,
        source_line_count=candidates_line_count,
        must=must,
        source_sha256=candidates_sha256,
    )


def _item_has_disk_window_proof(
    item: dict[str, Any],
    *,
    project_root: Path | None,
) -> tuple[bool, str]:
    """True when window sha AND contiguous snippet both match disk (policy: evidence)."""
    match = require_disk_window_proof(project_root, item, pad=0)
    if match.get("ok"):
        return True, "sha_and_snippet"
    return False, str(match.get("error") or "no disk window proof")


def plan_writer_names(plan: dict[str, Any], *, roles: set[str] | None = None) -> set[str]:
    allowed = roles or CHAIN_ROLES
    out: set[str] = set()
    for item in plan.get("writers") or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()
        if role not in allowed:
            continue
        name = str(item.get("name") or "").strip()
        if name:
            out.add(name)
            out.add(name.casefold())
    return out


def plan_tiling_writer_names(plan: dict[str, Any]) -> set[str]:
    return plan_writer_names(plan, roles={"tiling_writer", "workspace_writer"})


def plan_chain_names(plan: dict[str, Any]) -> set[str]:
    """Helpers kept on host chain (writers + provenance), excluding ignore."""
    return plan_writer_names(plan, roles=set(CHAIN_ROLES))


def plan_provenance_names(plan: dict[str, Any]) -> set[str]:
    return plan_writer_names(plan, roles={"provenance_helper"})

def plan_tiling_sink_receivers(plan: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for item in plan.get("receivers") or []:
        if not isinstance(item, dict):
            continue
        if not item.get("is_tiling_sink"):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            out.add(name)
            out.add(name.casefold())
    return out


def plan_non_sink_roots(plan: dict[str, Any]) -> set[str]:
    """Accepted non-sink roots are bare string names only (contract)."""
    out: set[str] = set()
    for r in plan.get("non_sink_roots") or []:
        if isinstance(r, str) and r.strip():
            out.add(r.strip().casefold())
    return out


def plan_aliases(plan: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in plan.get("aliases") or []:
        if not isinstance(item, dict):
            continue
        local = str(item.get("local") or "").strip()
        leaf = str(item.get("tdf_leaf") or "").strip()
        if local and leaf:
            out[local] = leaf
    return out


def plan_derived_roots(plan: dict[str, Any]) -> set[str]:
    """Accepted derived roots are bare string names only (contract)."""
    out: set[str] = set()
    for r in plan.get("derived_roots") or []:
        if isinstance(r, str) and r.strip():
            out.add(r.strip())
    return out


def _validate_string_name_list(
    values: Any,
    *,
    field: str,
    allowed_cf: set[str],
    errors: list[str],
) -> None:
    """``non_sink_roots`` / ``derived_roots``: string names only; no mapping/adjudication objects."""
    if values is None:
        return
    if not isinstance(values, list):
        errors.append(f"{field} must be a list of string names")
        return
    for item in values:
        if isinstance(item, dict):
            errors.append(
                f"{field} entry must be a string name, got mapping "
                "(do not write adjudication/unresolved objects; "
                "confirm with a bare string or omit the name)"
            )
            continue
        if not isinstance(item, str):
            errors.append(f"{field} entry must be a string name, got {type(item).__name__}")
            continue
        name = item.strip()
        if not name:
            continue
        if name.casefold() not in allowed_cf:
            errors.append(f"{field[:-1] if field.endswith('s') else field} not in candidates: {name}")


def drop_invented_non_sink_roots(
    plan: dict[str, Any],
    candidates: dict[str, Any],
) -> list[str]:
    """Drop invented ``non_sink_roots`` string names (not in candidates/receivers).

    Product resilience (same spirit as evidence sha enrich): keep allowlisted
    strings; leave mappings / non-strings for validate to reject. Returns action tags.
    """
    raw = plan.get("non_sink_roots")
    if not isinstance(raw, list) or not raw:
        return []
    non_sink_cands = {
        str(c.get("name") or "").strip().casefold()
        for c in (candidates.get("non_sink_root_candidates") or [])
        if isinstance(c, dict) and str(c.get("name") or "").strip()
    }
    recv_cf: set[str] = set()
    for c in candidates.get("receiver_candidates") or []:
        if not isinstance(c, dict):
            continue
        n = str(c.get("name") or "").strip()
        if n:
            recv_cf.add(n.casefold())
    for item in plan.get("receivers") or []:
        if not isinstance(item, dict):
            continue
        n = str(item.get("name") or "").strip()
        if n:
            recv_cf.add(n.casefold())
    allowed_cf = non_sink_cands | recv_cf
    kept: list[Any] = []
    dropped = 0
    for item in raw:
        if isinstance(item, str):
            name = item.strip()
            if not name:
                continue
            if name.casefold() in allowed_cf:
                kept.append(name)
            else:
                dropped += 1
            continue
        # Mappings / wrong types: keep for validate (do not silently widen contract).
        kept.append(item)
    if dropped:
        plan["non_sink_roots"] = kept
        return ["drop_invented_non_sink"] * dropped
    return []


# Top-level keys that belong in ledger / llm_tasks / free-form essays — never in extract_plan.yaml.
FORBIDDEN_EXTRACT_PLAN_KEYS = frozenset(
    {
        "call_edge_adjudications",
        "llm_tasks",
        "tasks",
        "edge_patches",
        "semantic_patches",
        "dispatches_to",
        "mark_missing",
        "accepted_edges",
        "entrypoint_dispatch_bind",
        "accepted_candidate_ids",
        "blocking_reasons",
        # Free-form / wrong-schema dumps seen from producers that skipped source tools.
        "semantic_groups",
        "ignored_candidates",
        "receiver_summary",
        "alias_summary",
        "adjudication",
    }
)

# Alignment / math helpers — never promote as tiling/key/workspace writers.
HELPER_WRITER_NAMES = frozenset(
    {
        "alignto",
        "ceildivide",
        "ceildivideby",
        "min",
        "max",
        "std::min",
        "std::max",
    }
)

def read_evidence_window(
    project_root: Path,
    file_path: str,
    lines_field: Any,
    *,
    pad: int = 0,
) -> str:
    """Read a bounded source window (shared helper; policy: evidence / code-access)."""
    from uo.scripts.source_evidence import read_source_window

    span = _parse_line_span(lines_field)
    if span is None:
        return ""
    lo, hi = span
    return read_source_window(project_root, file_path, lo, hi, pad=pad)


def _effective_evidence_source(item: dict[str, Any]) -> str:
    raw = str(item.get("evidence_source") or "").strip()
    if raw in EVIDENCE_SOURCES:
        return raw
    return "candidate_only"


def _evidence_list(cand: dict[str, Any] | None) -> set[str]:
    if not cand:
        return set()
    ev = cand.get("evidence")
    if not isinstance(ev, list):
        return set()
    return {str(x).strip() for x in ev if str(x).strip()}


STRONG_WRITER_EVIDENCE = frozenset(
    {"tilingdata_assign", "recv_set_call", "sink_set_writer", "one_hop_callee"}
)


def _writer_candidate_weak(
    item: dict[str, Any],
    cand: dict[str, Any] | None,
    all_writers: list[dict[str, Any]],
) -> bool:
    """True when heuristic score/evidence is too weak to promote without source read."""
    name = str(item.get("name") or "").strip()
    if not name:
        return False
    same_name = sum(
        1
        for c in all_writers
        if isinstance(c, dict) and str(c.get("name") or "").casefold() == name.casefold()
    )
    if same_name > 1:
        return True
    if not cand:
        # No matched candidate — treat promotion as weak (fail-closed).
        return True
    score = float(cand.get("score") or 0)
    if score > 0 and score < WEAK_SCORE_THRESHOLD:
        return True
    ev = _evidence_list(cand)
    if "assign_lhs_only" in ev:
        return True
    if "has_set_field" in ev and not (ev & STRONG_WRITER_EVIDENCE):
        return True
    # Suggested non-sink cannot be promoted to sink writer roles without source proof.
    if cand.get("is_tiling_sink_suggested") is False:
        return True
    if cand.get("non_sink_suggested") is True or cand.get("suggested_non_sink") is True:
        return True
    # Setter name alone cannot prove a real TilingData sink write.
    setter_only = bool(ev & {"has_set_field", "setter_name"}) and not (ev & STRONG_WRITER_EVIDENCE)
    if setter_only:
        return True
    qn = str(cand.get("qualified_name") or "").strip()
    cn = str(cand.get("name") or "").strip()
    if qn and cn and qn == cn and not str(cand.get("class_or_namespace") or "").strip():
        # Incomplete qualified name.
        return True
    start = int(item.get("start_line") or cand.get("start_line") or 0)
    if start > 0:
        fp = str(item.get("file_path") or cand.get("file_path") or "").replace("\\", "/")
        overlaps = [
            c
            for c in all_writers
            if isinstance(c, dict)
            and str(c.get("file_path") or "").replace("\\", "/") == fp
            and int(c.get("start_line") or 0) == start
            and str(c.get("name") or "").casefold() != name.casefold()
        ]
        if overlaps:
            return True
    return False


def _validate_decision_evidence(
    item: dict[str, Any],
    *,
    label: str,
    errors: list[str],
    cand: dict[str, Any] | None = None,
    all_pool: list[dict[str, Any]] | None = None,
    check_weak_writer_promotion: bool = False,
    project_root: Path | None = None,
) -> None:
    """Source-evidence contract — delegates shared rules to source_evidence (policy)."""
    evidence_source = _effective_evidence_source(item)
    errors.extend(require_high_confidence_source_fields(item, label=label))

    # Disk match once (avoid duplicate high-confidence + promote appends).
    disk_err = ""
    needs_disk = (
        item.get("source_verified") is True
        or str(item.get("confidence") or "").strip().lower() == "high"
    )
    if needs_disk and project_root is not None and evidence_source in ("source", "cbm"):
        ok_disk, why = _item_has_disk_window_proof(item, project_root=project_root)
        if not ok_disk:
            disk_err = f"{label} {why}"
            errors.append(disk_err)

    if check_weak_writer_promotion:
        role = str(item.get("role") or "").strip()
        promoting = role in PROMOTED_WRITER_ROLES or item.get("is_tiling_sink") is True
        # Product rule: any promoted writer/sink must prove via CBM or windowed source
        # read — candidate YAML short snippets / search_graph hits alone are never enough.
        if promoting:
            files = item.get("evidence_files")
            lines = item.get("evidence_lines")
            reason = str(item.get("decision_reason") or "").strip()
            snip = str(item.get("evidence_snippet") or "").strip()
            win_sha = str(item.get("evidence_window_sha256") or "").strip()
            has_files = isinstance(files, list) and any(str(f).strip() for f in files)
            has_lines = isinstance(lines, list) and bool(lines)
            has_proof = (
                len(snip) >= _MIN_EVIDENCE_SNIPPET_CHARS
                and not is_placeholder_sha256(win_sha)
            )
            if evidence_source == "candidate_only" or not (
                evidence_source in ("source", "cbm")
                and item.get("source_verified") is True
                and has_files
                and has_lines
                and reason
                and has_proof
            ):
                weak = _writer_candidate_weak(item, cand, all_pool or [])
                kind = "weak candidate" if weak else "promoted writer"
                errors.append(
                    f"{label} {kind} cannot promote to {role or 'tiling_sink'!r} "
                    "without CBM/source window evidence "
                    "(require evidence_source source|cbm, source_verified:true, "
                    "evidence_files/evidence_lines/decision_reason, and "
                    "evidence_window_sha256 AND evidence_snippet; "
                    "prefer candidate source_window.sha256; or set role:ignore / omit)"
                )
            elif project_root is not None and not disk_err:
                ok_disk, why = _item_has_disk_window_proof(item, project_root=project_root)
                if not ok_disk:
                    errors.append(f"{label} {why}")


def _match_candidate(
    item: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any] | None:
    name = str(item.get("name") or "").strip()
    if not name:
        return None
    fp = str(item.get("file_path") or "").replace("\\", "/").strip()
    qn = str(item.get("qualified_name") or "").strip()
    exact: list[dict[str, Any]] = []
    by_name: list[dict[str, Any]] = []
    for c in candidates:
        if not isinstance(c, dict):
            continue
        cn = str(c.get("name") or "").strip()
        if cn.casefold() != name.casefold():
            continue
        by_name.append(c)
        cfp = str(c.get("file_path") or "").replace("\\", "/").strip()
        cqn = str(c.get("qualified_name") or "").strip()
        if (fp and cfp and fp == cfp) or (qn and cqn and qn == cqn):
            exact.append(c)
    if exact:
        return exact[0]
    if len(by_name) == 1:
        return by_name[0]
    # Ambiguous short-name match — fail closed (do not pick arbitrarily).
    return None


def normalize_plan_from_candidates(
    plan: dict[str, Any],
    candidates: dict[str, Any],
) -> dict[str, Any]:
    """Fill missing role from candidate suggestions before validate.

    Does not invent writers/receivers; does NOT default missing is_tiling_sink to true.
    Missing sink evidence must fail closed in validate.
    """
    out = dict(plan)
    writers = []
    for item in out.get("writers") or []:
        if not isinstance(item, dict):
            writers.append(item)
            continue
        row = dict(item)
        role = str(row.get("role") or "").strip()
        if role not in WRITER_ROLES:
            cand = _match_candidate(row, list(candidates.get("writer_candidates") or []))
            suggested = str((cand or {}).get("role_suggested") or "").strip()
            if suggested in WRITER_ROLES:
                row["role"] = suggested
        writers.append(row)
    out["writers"] = writers

    receivers = []
    for item in out.get("receivers") or []:
        if not isinstance(item, dict):
            receivers.append(item)
            continue
        row = dict(item)
        if "is_tiling_sink" not in row:
            cand = _match_candidate(row, list(candidates.get("receiver_candidates") or []))
            if cand is not None and "is_tiling_sink_suggested" in cand:
                row["is_tiling_sink"] = bool(cand.get("is_tiling_sink_suggested"))
            # else: leave unset → validate fails closed
        receivers.append(row)
    out["receivers"] = receivers
    return out


def validate_extract_plan_against_candidates(
    plan: dict[str, Any],
    candidates: dict[str, Any],
    *,
    project_root: Path | None = None,
) -> list[str]:
    """Return rejection reasons; empty means OK."""
    errors: list[str] = []
    if int(plan.get("version") or 0) != 1:
        errors.append("version must be 1")

    sha = str(plan.get("candidates_sha256") or "").strip()
    if not sha:
        errors.append("candidates_sha256 missing (copy exact value from prepare stub)")
    elif is_placeholder_sha256(sha):
        errors.append(
            "candidates_sha256 is placeholder/invalid — copy the sha256 from prepare "
            "task_prompt_stub (do not invent; producer bash cannot compute hashes)"
        )

    for key in plan:
        if str(key) in FORBIDDEN_EXTRACT_PLAN_KEYS:
            errors.append(
                f"forbidden extract_plan field {key!r} "
                "(edge/llm_task adjudication belongs in semantic_resolution_ledger via apply_semantic_patch; "
                "writers/receivers/aliases/non_sink_roots are the only plan collections)"
            )

    if "writers" not in plan or not isinstance(plan.get("writers"), list):
        errors.append("extract_plan.writers must be a list (omit items instead of inventing semantic_groups)")

    writer_names = {
        str(c.get("name") or "").strip()
        for c in (candidates.get("writer_candidates") or [])
        if isinstance(c, dict) and str(c.get("name") or "").strip()
    }
    recv_names = {
        str(c.get("name") or "").strip()
        for c in (candidates.get("receiver_candidates") or [])
        if isinstance(c, dict) and str(c.get("name") or "").strip()
    }
    alias_pairs = {
        (str(c.get("local") or "").strip(), str(c.get("tdf_leaf") or "").strip())
        for c in (candidates.get("alias_candidates") or [])
        if isinstance(c, dict)
    }
    non_sink_cands = {
        str(c.get("name") or "").strip().casefold()
        for c in (candidates.get("non_sink_root_candidates") or [])
        if isinstance(c, dict) and str(c.get("name") or "").strip()
    }
    extra_cands = {
        str(c.get("name") or "").strip()
        for c in (candidates.get("extra_entry_candidates") or [])
        if isinstance(c, dict) and str(c.get("name") or "").strip()
    }
    writer_cf = {n.casefold() for n in writer_names}
    recv_cf = {n.casefold() for n in recv_names}

    for item in plan.get("writers") or []:
        if not isinstance(item, dict):
            errors.append("writer entry must be mapping")
            continue
        name = str(item.get("name") or "").strip()
        role = str(item.get("role") or "").strip()
        if not name:
            errors.append("writer missing name")
        elif name not in writer_names and name.casefold() not in writer_cf:
            errors.append(f"writer not in candidates: {name}")
        if name and name.casefold() in HELPER_WRITER_NAMES and role in PROMOTED_WRITER_ROLES:
            errors.append(
                f"writer {name} is an alignment/math helper — set role:ignore or omit "
                "(do not promote AlignTo/CeilDivide as tiling/key/workspace writers)"
            )
        # Require identity fields — ban short-name-only hits.
        if not (item.get("file_path") or item.get("qualified_name") or item.get("identity_key")):
            # Ban short-name-only when multiple candidates share the name.
            matches = [
                c
                for c in (candidates.get("writer_candidates") or [])
                if isinstance(c, dict) and str(c.get("name") or "").casefold() == name.casefold()
            ]
            if len(matches) > 1:
                errors.append(f"writer {name} ambiguous without identity fields (file_path|qualified_name|identity_key)")
        if role not in WRITER_ROLES:
            errors.append(
                f"writer {name or '?'} missing/invalid role {role!r} "
                f"(copy role_suggested from extract_plan_candidates.yaml; "
                f"allowed: {sorted(WRITER_ROLES)})"
            )
        writer_pool = list(candidates.get("writer_candidates") or [])
        matched = _match_candidate(item, writer_pool)
        _validate_decision_evidence(
            item,
            label=f"writer {name or '?'}",
            errors=errors,
            cand=matched,
            all_pool=writer_pool,
            check_weak_writer_promotion=True,
            project_root=project_root,
        )

    for item in plan.get("receivers") or []:
        if not isinstance(item, dict):
            errors.append("receiver entry must be mapping")
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            errors.append("receiver missing name")
        elif name not in recv_names and name.casefold() not in recv_cf:
            errors.append(f"receiver not in candidates: {name}")
        if not (item.get("file_path") or item.get("qualified_name") or item.get("identity_key")):
            matches = [
                c
                for c in (candidates.get("receiver_candidates") or [])
                if isinstance(c, dict) and str(c.get("name") or "").casefold() == name.casefold()
            ]
            if len(matches) > 1:
                errors.append(f"receiver {name} ambiguous without identity fields (file_path|qualified_name|identity_key)")
        if "is_tiling_sink" not in item:
            errors.append(
                f"receiver {name} missing is_tiling_sink "
                "(copy is_tiling_sink_suggested from extract_plan_candidates.yaml)"
            )
        recv_pool = list(candidates.get("receiver_candidates") or [])
        matched_recv = _match_candidate(item, recv_pool)
        _validate_decision_evidence(
            item,
            label=f"receiver {name or '?'}",
            errors=errors,
            cand=matched_recv,
            all_pool=recv_pool,
            check_weak_writer_promotion=bool(item.get("is_tiling_sink")),
            project_root=project_root,
        )

    for item in plan.get("aliases") or []:
        if not isinstance(item, dict):
            errors.append("alias entry must be mapping")
            continue
        local = str(item.get("local") or "").strip()
        leaf = str(item.get("tdf_leaf") or "").strip()
        if not local or not leaf:
            errors.append("alias missing local/tdf_leaf")
        elif (local, leaf) not in alias_pairs and not any(
            a[0].casefold() == local.casefold() and a[1].casefold() == leaf.casefold() for a in alias_pairs
        ):
            errors.append(f"alias not in candidates: {local}={leaf}")

    # non_sink_roots: bare string names only (no identity fields; no adjudication dicts).
    # Allow names from non_sink_root_candidates or receivers (intermediate receivers).
    non_sink_allowed = set(non_sink_cands) | recv_cf | {n.casefold() for n in recv_names}
    _validate_string_name_list(
        plan.get("non_sink_roots"),
        field="non_sink_roots",
        allowed_cf=non_sink_allowed,
        errors=errors,
    )

    # derived_roots: bare string names only when present (optional; empty OK).
    derived = plan.get("derived_roots")
    if derived is not None:
        if not isinstance(derived, list):
            errors.append("derived_roots must be a list of string names")
        else:
            for item in derived:
                if isinstance(item, dict):
                    errors.append(
                        "derived_roots entry must be a string name, got mapping "
                        "(do not write adjudication/unresolved objects)"
                    )
                elif not isinstance(item, str):
                    errors.append(
                        f"derived_roots entry must be a string name, got {type(item).__name__}"
                    )

    for entry in plan.get("extra_host_entries") or []:
        if isinstance(entry, dict):
            name = str(entry.get("name") or "").strip()
        else:
            name = str(entry).strip()
        if name and name not in extra_cands and name.casefold() not in {n.casefold() for n in extra_cands}:
            errors.append(f"extra_host_entry not in candidates: {name}")

    _validate_extract_plan_contracts(plan, candidates, errors)
    return errors


def _validate_extract_plan_contracts(
    plan: dict[str, Any],
    candidates: dict[str, Any],
    errors: list[str],
) -> None:
    """Action-local schema contracts (sinks / key_writer) — not global evidence policy."""
    sink_cands = [
        c
        for c in (candidates.get("receiver_candidates") or [])
        if isinstance(c, dict) and c.get("is_tiling_sink_suggested") is True
    ]
    sink_names = {
        str(c.get("name") or "").strip()
        for c in sink_cands
        if str(c.get("name") or "").strip()
    }

    promoted_writers = [
        w
        for w in (plan.get("writers") or [])
        if isinstance(w, dict)
        and str(w.get("role") or "").strip() in PROMOTED_WRITER_ROLES
    ]
    tiling_sink_receivers = [
        r
        for r in (plan.get("receivers") or [])
        if isinstance(r, dict) and r.get("is_tiling_sink") is True
    ]
    plan_recv_cf = {
        str(r.get("name") or "").strip().casefold()
        for r in (plan.get("receivers") or [])
        if isinstance(r, dict) and str(r.get("name") or "").strip()
    }

    if sink_cands and promoted_writers and not tiling_sink_receivers:
        errors.append(
            "tiling_sink receivers must not be empty when candidates suggest sinks "
            f"({len(sink_cands)} is_tiling_sink_suggested) and plan promotes "
            f"{len(promoted_writers)} writer(s) — copy sinks from "
            "extract_plan_candidates.yaml / candidates.summary.yaml"
        )

    # Writer evidence that names a suggested sink ⇒ that sink must be listed.
    for w in promoted_writers:
        blob = " ".join(
            [
                str(w.get("evidence_snippet") or ""),
                str(w.get("decision_reason") or ""),
            ]
        )
        if not blob.strip():
            continue
        wname = str(w.get("name") or "").strip() or "?"
        for sn in sorted(sink_names):
            if sn.casefold() in plan_recv_cf:
                continue
            # Word-ish match: sink token appears in evidence text.
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(sn)}(?![A-Za-z0-9_])", blob):
                errors.append(
                    f"writer {wname} evidence names sink {sn!r} but receivers omit it "
                    "(add receiver with is_tiling_sink:true or drop the sink mention)"
                )

    # Unique GetTilingKey (role_suggested=key_writer) ⇒ key_writer or explicit ignore.
    key_cands = [
        c
        for c in (candidates.get("writer_candidates") or [])
        if isinstance(c, dict)
        and str(c.get("role_suggested") or "").strip() == "key_writer"
        and str(c.get("name") or "").strip().casefold() == "gettilingkey"
    ]
    if len(key_cands) == 1:
        plan_writers = [w for w in (plan.get("writers") or []) if isinstance(w, dict)]
        gtk = [
            w
            for w in plan_writers
            if str(w.get("name") or "").strip().casefold() == "gettilingkey"
        ]
        if not gtk:
            errors.append(
                "GetTilingKey (role_suggested=key_writer) must appear in writers "
                "as key_writer or role:ignore — do not omit silently"
            )
        else:
            role = str(gtk[0].get("role") or "").strip()
            if role not in {"key_writer", "ignore"}:
                errors.append(
                    f"GetTilingKey must use role key_writer or ignore (got {role!r})"
                )
