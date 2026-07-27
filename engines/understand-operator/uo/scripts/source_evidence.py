"""Shared source-window evidence helpers.

Authority: skills/policies/evidence + code-access (+ source-authority).
Any gate that accepts confidence=high / source_verified=true MUST verify
evidence_snippet against on-disk source via these helpers — do not fork
per-action rules.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

MIN_EVIDENCE_SNIPPET_CHARS = 48
_PLACEHOLDER_SHA_RE = re.compile(
    r"PLACEHOLDER|TODO|REPLACE|FILL_?ME|\bXXX\b",
    re.IGNORECASE,
)
_LINE_SPAN_RE = re.compile(r"^\s*(\d+)\s*[-–:]\s*(\d+)\s*$")


def is_placeholder_sha256(value: object) -> bool:
    s = str(value or "").strip()
    if not s:
        return True
    if _PLACEHOLDER_SHA_RE.search(s):
        return True
    if len(s) != 64:
        return True
    return any(c not in "0123456789abcdef" for c in s.lower())


def normalize_code_text(text: str) -> str:
    return "\n".join(
        ln.rstrip() for ln in str(text or "").replace("\r\n", "\n").split("\n")
    ).strip()


def normalize_code_dedent(text: str) -> str:
    """Compare code ignoring leading indentation (keep relative structure via strip)."""
    return "\n".join(
        ln.strip() for ln in str(text or "").replace("\r\n", "\n").split("\n") if ln.strip()
    )


def parse_line_span(lines_field: Any) -> tuple[int, int] | None:
    """Accept [start,end], [start], ['10-40'], or '10-40'."""
    if isinstance(lines_field, str):
        m = _LINE_SPAN_RE.match(lines_field)
        if m:
            lo, hi = int(m.group(1)), int(m.group(2))
            return (lo, hi) if lo >= 1 and hi >= lo else None
        try:
            n = int(lines_field.strip())
            return (n, n) if n >= 1 else None
        except ValueError:
            return None
    if not isinstance(lines_field, list) or not lines_field:
        return None
    if len(lines_field) == 1:
        return parse_line_span(lines_field[0])
    try:
        lo = int(lines_field[0])
        hi = int(lines_field[1])
    except (TypeError, ValueError):
        first = lines_field[0]
        if isinstance(first, str):
            return parse_line_span(first)
        return None
    return (lo, hi) if lo >= 1 and hi >= lo else None


def read_source_window(
    project_root: Path,
    file_path: str,
    start_line: int,
    end_line: int,
    *,
    pad: int = 0,
) -> str:
    """1-based inclusive window; empty string if unreadable."""
    from uo.scripts.cbm_client import read_source_snippet

    return read_source_snippet(
        project_root, file_path, start_line, end_line, pad=pad
    )


def evidence_snippet_matches_source(
    project_root: Path | None,
    item: dict[str, Any],
    *,
    min_chars: int = MIN_EVIDENCE_SNIPPET_CHARS,
    pad: int = 2,
    require_full_contiguous: bool = False,
) -> dict[str, Any]:
    """Fail-closed: claimed snippet must appear in the real source window.

    When ``require_full_contiguous`` (high-confidence / disk proof), the full
    snippet (or indent-tolerant form) must be a contiguous window substring —
    prefix/head-only matches are rejected (blocks collage snippets).
    """
    if project_root is None:
        return {"ok": False, "error": "project_root required for source evidence check"}
    snippet = str(item.get("evidence_snippet") or "").strip()
    if len(snippet) < min_chars:
        return {
            "ok": False,
            "error": f"evidence_snippet missing or shorter than {min_chars} chars",
        }
    files = item.get("evidence_files")
    lines = item.get("evidence_lines")
    if not isinstance(files, list) or not any(str(f).strip() for f in files):
        return {"ok": False, "error": "evidence_files required"}
    span = parse_line_span(lines)
    if span is None:
        return {"ok": False, "error": "evidence_lines required (e.g. ['1837-1944'] or [10, 40])"}
    fp = str(files[0] or "").replace("\\", "/").strip()
    lo, hi = span
    window = read_source_window(Path(project_root), fp, lo, hi, pad=pad)
    if not window.strip():
        return {"ok": False, "error": f"cannot read source window for {fp!r} at {lines!r}"}
    norm_snip = normalize_code_text(snippet)
    norm_win = normalize_code_text(window)
    # Exact window match first; then indent-tolerant (agents often re-indent YAML blocks).
    dedent_snip = normalize_code_dedent(snippet)
    dedent_win = normalize_code_dedent(window)
    full_hit = norm_snip in norm_win or (bool(dedent_snip) and dedent_snip in dedent_win)
    if require_full_contiguous:
        if not full_hit:
            return {
                "ok": False,
                "error": (
                    "evidence_snippet is not a contiguous substring of the source window "
                    "(collage / skipped lines rejected)"
                ),
            }
    else:
        head = norm_snip[: max(min_chars, min(160, len(norm_snip)))]
        if not full_hit and head not in norm_win:
            return {
                "ok": False,
                "error": "evidence_snippet does not match source at evidence_files/evidence_lines",
            }
    window_sha = hashlib.sha256(window.encode("utf-8", errors="ignore")).hexdigest()
    claimed = str(item.get("evidence_window_sha256") or "").strip()
    if claimed and claimed != window_sha:
        return {"ok": False, "error": "evidence_window_sha256 mismatch with on-disk source window"}
    return {"ok": True, "window_sha256": window_sha}


def window_sha_matches_source(
    project_root: Path | None,
    item: dict[str, Any],
    *,
    pad: int = 0,
) -> dict[str, Any]:
    """Verify evidence_window_sha256 against on-disk window (no snippet required)."""
    if project_root is None:
        return {"ok": False, "error": "project_root required for window sha check"}
    claimed = str(item.get("evidence_window_sha256") or "").strip().lower()
    if is_placeholder_sha256(claimed):
        return {"ok": False, "error": "evidence_window_sha256 missing/placeholder"}
    files = item.get("evidence_files")
    span = parse_line_span(item.get("evidence_lines"))
    if not isinstance(files, list) or not any(str(f).strip() for f in files):
        return {"ok": False, "error": "evidence_files required for window sha"}
    if span is None:
        return {"ok": False, "error": "evidence_lines required for window sha"}
    fp = str(files[0] or "").replace("\\", "/").strip()
    lo, hi = span
    window = read_source_window(Path(project_root), fp, lo, hi, pad=pad)
    if not window.strip():
        return {"ok": False, "error": f"cannot read source window for {fp!r}"}
    actual = hashlib.sha256(window.encode("utf-8", errors="ignore")).hexdigest()
    if claimed != actual:
        return {"ok": False, "error": "evidence_window_sha256 mismatch with on-disk source window"}
    return {"ok": True, "window_sha256": actual}


def require_disk_window_proof(
    project_root: Path | None,
    item: dict[str, Any],
    *,
    min_chars: int = MIN_EVIDENCE_SNIPPET_CHARS,
    pad: int = 0,
) -> dict[str, Any]:
    """High-confidence disk proof: window sha AND contiguous snippet (policy: evidence).

    Fail-closed. Search hits / sha-only / collage (non-contiguous) snippets must not pass.
    """
    if project_root is None:
        return {"ok": False, "error": "project_root required for disk window proof"}
    sha_match = window_sha_matches_source(project_root, item, pad=pad)
    if not sha_match.get("ok"):
        return {
            "ok": False,
            "error": str(sha_match.get("error") or "evidence_window_sha256 disk mismatch"),
        }
    snip_match = evidence_snippet_matches_source(
        project_root,
        item,
        min_chars=min_chars,
        pad=pad,
        require_full_contiguous=True,
    )
    if not snip_match.get("ok"):
        return {
            "ok": False,
            "error": str(
                snip_match.get("error")
                or "evidence_snippet missing or not contiguous in source window"
            ),
        }
    return {
        "ok": True,
        "window_sha256": sha_match.get("window_sha256") or snip_match.get("window_sha256"),
    }


def snippet_needs_contiguous_backfill(snippet: object) -> bool:
    """True when snippet is missing, too short, or looks like a collage (ellipsis)."""
    s = str(snippet or "")
    if len(s.strip()) < MIN_EVIDENCE_SNIPPET_CHARS:
        return True
    if "..." in s or "…" in s:
        return True
    return False


def enrich_item_evidence_from_disk(
    project_root: Path,
    item: dict[str, Any],
    *,
    candidate: dict[str, Any] | None = None,
    pad: int = 0,
    min_chars: int = MIN_EVIDENCE_SNIPPET_CHARS,
) -> list[str]:
    """Backfill contiguous snippet + window sha from disk (or candidate source_window).

    Only runs when evidence_files/evidence_lines resolve to a window of at least
    ``min_chars`` (avoids "fixing" single-line wrong spans into a pass).
    Returns list of enrichment action tags (empty = no change).
    """
    actions: list[str] = []
    if item.get("source_verified") is not True and not item.get("is_tiling_sink"):
        return actions

    files = item.get("evidence_files")
    span = parse_line_span(item.get("evidence_lines"))
    window = ""
    fp = ""
    lo = hi = 0
    if isinstance(files, list) and any(str(f).strip() for f in files) and span is not None:
        fp = str(files[0] or "").replace("\\", "/").strip()
        lo, hi = span
        window = read_source_window(Path(project_root), fp, lo, hi, pad=pad)

    # Prefer candidate source_window when plan window is unusable / too small.
    sw = (candidate or {}).get("source_window") if isinstance(candidate, dict) else None
    if (not window.strip() or len(window.strip()) < min_chars) and isinstance(sw, dict):
        sw_text = str(sw.get("text") or "")
        if len(sw_text.strip()) >= min_chars and not sw.get("text_truncated"):
            window = sw_text
            sw_fp = str(sw.get("file_path") or fp).replace("\\", "/")
            sw_lo = int(sw.get("start_line") or lo or 0)
            sw_hi = int(sw.get("end_line") or hi or sw_lo)
            if sw_fp and sw_lo >= 1 and sw_hi >= sw_lo:
                item["evidence_files"] = [sw_fp]
                item["evidence_lines"] = [sw_lo, sw_hi]
                fp, lo, hi = sw_fp, sw_lo, sw_hi
                # Re-read from disk for authoritative sha (not truncated candidate text).
                disk = read_source_window(Path(project_root), fp, lo, hi, pad=pad)
                if disk.strip():
                    window = disk
                actions.append("from_candidate_source_window")

    if len(window.strip()) < min_chars:
        return actions

    actual_sha = hashlib.sha256(window.encode("utf-8", errors="ignore")).hexdigest()
    claimed_sha = str(item.get("evidence_window_sha256") or "").strip().lower()
    if is_placeholder_sha256(claimed_sha) or claimed_sha != actual_sha:
        item["evidence_window_sha256"] = actual_sha
        actions.append("sha")

    snip = str(item.get("evidence_snippet") or "")
    need_snip = snippet_needs_contiguous_backfill(snip)
    if not need_snip:
        # Still replace if not a contiguous substring of this window.
        probe = {
            **item,
            "evidence_snippet": snip,
            "evidence_window_sha256": actual_sha,
            "evidence_files": [fp] if fp else item.get("evidence_files"),
            "evidence_lines": [lo, hi] if lo and hi else item.get("evidence_lines"),
        }
        match = evidence_snippet_matches_source(
            project_root,
            probe,
            min_chars=min_chars,
            pad=pad,
            require_full_contiguous=True,
        )
        need_snip = not match.get("ok")

    if need_snip:
        # Keep YAML manageable: prefer first contiguous chunk that is long enough.
        item["evidence_snippet"] = window if len(window) <= 12000 else window[:12000]
        actions.append("snippet")

    return actions


def bucket_extract_plan_errors(errors: list[str]) -> dict[str, Any]:
    """Compress duplicate validate reasons into buckets for Host / failure_card."""
    buckets: dict[str, list[str]] = {
        "collage_snippet": [],
        "sha_mismatch": [],
        "alias_schema": [],
        "non_sink_invented": [],
        "empty_sinks": [],
        "key_writer": [],
        "other": [],
    }
    seen: set[str] = set()
    unique: list[str] = []
    for raw in errors:
        e = str(raw or "").strip()
        if not e or e in seen:
            continue
        seen.add(e)
        unique.append(e)
        if "contiguous" in e or "collage" in e:
            buckets["collage_snippet"].append(e)
        elif "sha256 mismatch" in e or "window_sha" in e:
            buckets["sha_mismatch"].append(e)
        elif "alias missing" in e or "alias not in" in e:
            buckets["alias_schema"].append(e)
        elif "non_sink_root not in" in e:
            buckets["non_sink_invented"].append(e)
        elif "tiling_sink receivers must not be empty" in e:
            buckets["empty_sinks"].append(e)
        elif "GetTilingKey" in e:
            buckets["key_writer"].append(e)
        else:
            buckets["other"].append(e)
    counts = {k: len(v) for k, v in buckets.items() if v}
    summary_parts = [f"{k}={n}" for k, n in counts.items()]
    return {
        "counts": counts,
        "summary": ", ".join(summary_parts) if summary_parts else "none",
        "unique_errors": unique[:40],
        "unique_count": len(unique),
        "raw_count": len(errors),
    }


def require_high_confidence_source_fields(
    item: dict[str, Any],
    *,
    label: str,
) -> list[str]:
    """Structural checks shared by all Actions (policy: evidence)."""
    errors: list[str] = []
    src = str(item.get("evidence_source") or "").strip().lower()
    source_verified = item.get("source_verified") is True
    conf = str(item.get("confidence") or "").strip().lower()

    if conf == "high" and not source_verified:
        errors.append(
            f"{label} confidence:high requires source_verified:true "
            "and on-disk window proof (policy: evidence)"
        )

    if source_verified or conf == "high":
        if src not in ("source", "cbm"):
            errors.append(
                f"{label} source_verified/high requires evidence_source source|cbm "
                f"(got {src or 'empty'})"
            )
        files = item.get("evidence_files") or []
        if not isinstance(files, list) or not any(str(f).strip() for f in files):
            errors.append(
                f"{label} source_verified/high requires non-empty evidence_files"
            )
        if parse_line_span(item.get("evidence_lines")) is None:
            errors.append(
                f"{label} source_verified/high requires evidence_lines window"
            )
        snip = str(item.get("evidence_snippet") or "").strip()
        win_sha = str(item.get("evidence_window_sha256") or "").strip()
        # Hard rule: sha AND contiguous snippet (not OR).
        if is_placeholder_sha256(win_sha):
            errors.append(
                f"{label} source_verified/high requires evidence_window_sha256 "
                "(disk window sha; copy from candidate source_window.sha256)"
            )
        if len(snip) < MIN_EVIDENCE_SNIPPET_CHARS:
            errors.append(
                f"{label} source_verified/high requires evidence_snippet "
                f"(≥{MIN_EVIDENCE_SNIPPET_CHARS} chars, contiguous window text)"
            )

    if src == "candidate_only":
        if source_verified:
            errors.append(f"{label} candidate_only cannot set source_verified:true")
        if conf and conf not in ("candidate", "low", "medium") and conf != "high":
            # allow empty; reject fake "source_verified" confidence strings
            if conf in ("source_verified", "verified"):
                errors.append(
                    f"{label} evidence_source candidate_only requires confidence:candidate "
                    f"(got {conf!r})"
                )
        if conf == "high":
            errors.append(
                f"{label} candidate_only cannot use confidence:high (policy: evidence)"
            )

    return errors


def verify_scope_symbol_evidence(
    project_root: Path,
    candidate_rel: str,
    candidate_path: Path,
    windows: list[Any],
    *,
    missing_symbol: str = "",
) -> dict[str, Any]:
    """Machine-verify scope-expansion symbol/evidence windows (shared, fail-closed).

    Requires canonical path equality (not basename), line range in file, contiguous
    snippet in window, and window_sha256 match when provided.
    """
    cand = str(candidate_rel or "").replace("\\", "/").strip()
    if not cand or not candidate_path.is_file():
        return {"ok": False, "error": "EVIDENCE_CANDIDATE_MISSING", "reason_code": "EVIDENCE_CANDIDATE_MISSING"}
    try:
        cand_resolved = candidate_path.resolve()
        total_lines = len(cand_resolved.read_text(encoding="utf-8", errors="ignore").splitlines())
    except OSError as exc:
        return {"ok": False, "error": str(exc)[:200], "reason_code": "EVIDENCE_READ_FAILED"}

    matched = False
    last_error = "EVIDENCE_WINDOW_MISSING"
    for win in windows or []:
        if not isinstance(win, dict):
            continue
        wpath = str(win.get("file") or win.get("path") or "").replace("\\", "/").strip()
        if not wpath:
            continue
        # Canonical path must match exactly (no basename / endswith shortcuts).
        if wpath != cand and Path(wpath).as_posix() != cand:
            # Allow absolute/resolved equality only.
            try:
                if Path(wpath).resolve() != cand_resolved:
                    last_error = "EVIDENCE_PATH_MISMATCH"
                    continue
            except OSError:
                last_error = "EVIDENCE_PATH_MISMATCH"
                continue

        span = parse_line_span(win.get("lines") or win.get("evidence_lines"))
        if span is None:
            last_error = "EVIDENCE_LINES_INVALID"
            continue
        lo, hi = span
        if lo < 1 or hi < lo or hi > max(total_lines, 1):
            last_error = "EVIDENCE_LINES_OUT_OF_RANGE"
            continue

        snippet = str(win.get("snippet") or win.get("evidence_snippet") or "").strip()
        symbol = str(win.get("symbol") or missing_symbol or "").strip()
        if not snippet and not symbol:
            last_error = "EVIDENCE_EMPTY"
            continue

        item = {
            "evidence_files": [cand],
            "evidence_lines": [lo, hi],
            "evidence_snippet": snippet,
            "evidence_window_sha256": win.get("window_sha256") or win.get("evidence_window_sha256") or "",
        }
        if snippet:
            proof = evidence_snippet_matches_source(
                project_root,
                item,
                min_chars=min(MIN_EVIDENCE_SNIPPET_CHARS, max(1, len(snippet))),
                pad=0,
                require_full_contiguous=True,
            )
            if not proof.get("ok"):
                last_error = "EVIDENCE_SNIPPET_MISMATCH"
                continue
            claimed_sha = str(item.get("evidence_window_sha256") or "").strip()
            if claimed_sha and claimed_sha != proof.get("window_sha256"):
                last_error = "EVIDENCE_WINDOW_SHA_MISMATCH"
                continue
        elif str(item.get("evidence_window_sha256") or "").strip():
            sha_ok = window_sha_matches_source(project_root, item, pad=0)
            if not sha_ok.get("ok"):
                last_error = "EVIDENCE_WINDOW_SHA_MISMATCH"
                continue

        if symbol:
            window = read_source_window(Path(project_root), cand, lo, hi, pad=0)
            if symbol not in window and missing_symbol and missing_symbol not in window:
                # For missing_symbol claims, absence in *other* files is OK; presence of
                # the target symbol name in the evidence window is required when provided
                # as positive location proof. If only missing_symbol is set without snippet,
                # require the window text to be non-empty (inspected).
                if snippet or win.get("symbol"):
                    if symbol not in window:
                        last_error = "EVIDENCE_SYMBOL_ABSENT"
                        continue

        file_sha = str(win.get("source_file_sha256") or "").strip()
        if file_sha:
            import hashlib as _hashlib

            actual = _hashlib.sha256(cand_resolved.read_bytes()).hexdigest()
            if file_sha.lower() != actual.lower():
                last_error = "EVIDENCE_FILE_SHA_MISMATCH"
                continue

        matched = True
        break

    if matched:
        return {"ok": True, "reason_code": "symbol_evidence_verified"}
    return {"ok": False, "error": last_error, "reason_code": last_error}
