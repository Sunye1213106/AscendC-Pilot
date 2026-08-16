# -*- coding: utf-8 -*-
"""Shard unresolved blockers for Host map-reduce workers.

Used when an Action is declared map-reduce. ``/uo-init`` no longer runs
``resolve_gaps``; leftover comments below refer to the shard file layout only.

Host prepare owns the split; prompts must not implement sharding.
Hard limit mirrors ``bounded-semantic-batch``: ≤30 obligations per shard.
"""
from __future__ import annotations

import re
from typing import Any

MAX_BLOCKERS_PER_SHARD = 30
ERR_NOT_SHARDED = "LLM_WORK_NOT_SHARDED"
ERR_SHARD_TOO_LARGE = "LLM_SHARD_TOO_LARGE"


def _blocker_sort_key(row: dict[str, Any]) -> tuple[int, str, str]:
    """Prefer derivation blockers, then stable id."""
    reason = str(row.get("reason_code") or row.get("reason") or "")
    der = 0 if reason.startswith("DERIVATION_") else 1
    topic = str(row.get("topic") or row.get("atom") or "")
    bid = str(row.get("id") or row.get("blocker_id") or "")
    return (der, topic, bid)


def plan_blocker_shards(
    blockers: list[dict[str, Any]] | None,
    *,
    max_per_shard: int = MAX_BLOCKERS_PER_SHARD,
) -> dict[str, Any]:
    """Partition blockers into shards of at most ``max_per_shard``.

    Returns a manifest dict::

        {
          "ok": True,
          "obligation_count": N,
          "shard_count": K,
          "max_per_shard": 30,
          "shards": [
            {
              "shard_id": "000",
              "shard_index": 0,
              "blocker_ids": [...],
              "task_count": n,
              "batch_file": "inputs/batches/batch_000.yaml",
              "part_file": "parts/part_000.yaml",
            },
            ...
          ],
        }

    When ``N > max_per_shard`` but only one shard would be produced, sets
    ``ok=False`` with ``error=LLM_WORK_NOT_SHARDED``.
    """
    rows = [b for b in (blockers or []) if isinstance(b, dict)]
    ordered = sorted(rows, key=_blocker_sort_key)
    ids: list[str] = []
    by_id: dict[str, dict[str, Any]] = {}
    for row in ordered:
        bid = str(row.get("id") or row.get("blocker_id") or "").strip()
        if not bid or bid in by_id:
            continue
        by_id[bid] = row
        ids.append(bid)

    n = len(ids)
    limit = max(1, int(max_per_shard))
    shards: list[dict[str, Any]] = []
    if n == 0:
        return {
            "ok": True,
            "obligation_count": 0,
            "shard_count": 0,
            "max_per_shard": limit,
            "shards": [],
        }

    for start in range(0, n, limit):
        chunk = ids[start : start + limit]
        idx = len(shards)
        sid = f"{idx:03d}"
        shards.append(
            {
                "shard_id": sid,
                "shard_index": idx,
                "blocker_ids": list(chunk),
                "task_count": len(chunk),
                "batch_file": f"inputs/batches/batch_{sid}.yaml",
                "part_file": f"parts/part_{sid}.yaml",
            }
        )

    # Defensive: a single shard must never exceed the hard limit.
    for sh in shards:
        if int(sh.get("task_count") or 0) > limit:
            return {
                "ok": False,
                "error": ERR_SHARD_TOO_LARGE,
                "obligation_count": n,
                "shard_count": len(shards),
                "max_per_shard": limit,
                "shards": shards,
                "message_zh": f"单 shard 超过 {limit} 个 blocker",
            }

    if n > limit and len(shards) < 2:
        return {
            "ok": False,
            "error": ERR_NOT_SHARDED,
            "obligation_count": n,
            "shard_count": len(shards),
            "max_per_shard": limit,
            "shards": shards,
            "message_zh": f"任务数 {n} > {limit} 却未分片",
        }

    return {
        "ok": True,
        "obligation_count": n,
        "shard_count": len(shards),
        "max_per_shard": limit,
        "shards": shards,
        "blockers_by_id": by_id,
    }


#: Blockers whose answer needs the surrounding code read, not merely located.
#: Everything on this list asks "what does this compute", which three lines
#: around the guard cannot show.
_WANTS_SOURCE = (
    "LOOP_SUMMARY_NEEDED",
    "UNWRITTEN_INITIAL_VALUE",
    "DERIVATION_UNDECIDED",
    "OPAQUE_EXPRESSION",
    "CYCLIC_FIELD_DEPENDENCY",
)


#: How much source one blocker may carry. Thirty of these go in a batch, and
#: a batch nobody can read through is not evidence — it is a file dump with a
#: question buried in it.
SOURCE_LINE_BUDGET = 260

#: And how much of that one window may take, so that following a call still
#: has room. A tiling function of several hundred lines is not a better answer
#: than the branch chain plus the helper it hands off to.
MAIN_WINDOW_LINES = 150

#: An identifier immediately followed by `(` — a call, near enough.
_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\(")

#: Names that are calls but never the answer to anything.
_NOT_WORTH_FOLLOWING = frozenset(
    {
        "if",
        "for",
        "while",
        "switch",
        "return",
        "sizeof",
        "static_cast",
        "reinterpret_cast",
        "const_cast",
        "dynamic_cast",
    }
)


def function_sites(host_ir: Any) -> dict[str, tuple[str, int]]:
    """Where each function's body is, taken from any event inside it.

    The IR records no span for a function, but everything that happens inside
    one carries the file and line it happened on, and the earliest of those is
    inside the body. That is all `evidence_window` needs — it widens to the
    braces.

    Every kind of event has to be looked at, not just member writes. A helper
    that computes and returns a value writes no member at all, and those are
    exactly the ones worth following: `bandIdx = FindBandIdx(params)` is a
    question about a function that would be invisible here.
    """
    out: dict[str, tuple[str, int]] = {}
    for attr in ("writes", "local_writes", "controls"):
        for event in getattr(host_ir, attr, None) or []:
            name = str(getattr(event, "function", "") or "")
            path = str(getattr(event, "file", "") or "")
            try:
                line = int(getattr(event, "line", 0) or 0)
            except (TypeError, ValueError):
                continue
            if not name or not path or line <= 0:
                continue
            seen = out.get(name)
            if seen is None or line < seen[1]:
                out[name] = (path, line)
    return out


def symbol_sites(host_ir: Any) -> dict[str, tuple[str, int]]:
    """Where each written name is first written, by its last path segment.

    A fallback for blockers whose guard carries no evidence of its own —
    `parseInfo[s2Outer - 1][LENGTH_IDX]` is a real question with no file and
    no line attached, and without one it reaches the worker as a bare
    expression. The first write to `parseInfo` is not necessarily the place
    the question is about, but it is inside the code that fills it.
    """
    out: dict[str, tuple[str, int]] = {}
    for attr in ("writes", "local_writes"):
        for event in getattr(host_ir, attr, None) or []:
            path = str(getattr(event, "path", "") or "")
            name = path.rsplit(".", 1)[-1]
            file = str(getattr(event, "file", "") or "")
            try:
                line = int(getattr(event, "line", 0) or 0)
            except (TypeError, ValueError):
                continue
            if not name or not file or line <= 0:
                continue
            seen = out.get(name)
            if seen is None or line < seen[1]:
                out[name] = (file, line)
    return out


def _attach_source(
    row: dict[str, Any],
    ops_root: Any,
    sites: dict[str, tuple[str, int]] | None = None,
    symbols: dict[str, tuple[str, int]] | None = None,
) -> dict[str, Any]:
    """Put the enclosing function or loop next to the blocker's evidence.

    A quote proves a line was read; it does not let anyone work out what the
    code does. For the questions on `_WANTS_SOURCE` the code is the question,
    so it travels with it — a weak model has no other way to answer, and a
    strong one should not have to go looking.
    """
    from pathlib import Path

    from uo_init.source_window import evidence_window

    reason = str(row.get("reason_code") or row.get("reason") or "")
    if not reason.startswith(_WANTS_SOURCE):
        return row
    out = dict(row)
    windows: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    quoted: list[str] = []
    for ev in row.get("evidence") or []:
        if not isinstance(ev, dict):
            continue
        quoted.append(str(ev.get("snippet") or ""))
        rel = str(ev.get("file") or "")
        line = int(ev.get("line_start") or ev.get("line") or 0)
        if not rel or line <= 0:
            continue
        candidates = [Path(rel)]
        if ops_root is not None:
            candidates.append(Path(ops_root) / rel)
        hit = next((p for p in candidates if p.is_file()), None)
        if hit is None:
            continue
        window = evidence_window(hit, line, max_lines=MAIN_WINDOW_LINES)
        if window is None:
            continue
        window["file"] = rel.replace("\\", "/")
        span = (window["file"], window["line_start"], window["line_end"])
        if span in seen:
            continue
        seen.add(span)
        windows.append(window)
        # The snippet is the IR's rendering of the guard and often names no
        # call at all -- an unwritten-value question reads "<member> has no
        # write outside <guard>". The source line the evidence points at is
        # where `= FindBandIdx(params)` actually appears.
        body = window["text"].splitlines()
        at = line - window["line_start"]
        if 0 <= at < len(body):
            quoted.append(body[at])
    windows = windows[:3]
    if not windows and symbols:
        windows = _named_windows(str(row.get("text") or ""), symbols, ops_root, seen)
    spent = sum(w["line_end"] - w["line_start"] + 1 for w in windows)
    windows += _callee_windows(
        quoted, sites, ops_root, seen, budget=SOURCE_LINE_BUDGET - spent
    )
    if windows:
        out["source"] = windows
    return out


def _named_windows(
    text: str,
    symbols: dict[str, tuple[str, int]],
    ops_root: Any,
    seen: set[tuple[str, int, int]],
    limit: int = 1,
) -> list[dict[str, Any]]:
    """Last resort: show where a name in the question is written."""
    from pathlib import Path

    from uo_init.source_window import evidence_window

    out: list[dict[str, Any]] = []
    for name in re.findall(r"\b([A-Za-z_]\w*)\b", text):
        if name not in symbols or len(out) >= limit:
            continue
        rel, line = symbols[name]
        candidates = [Path(rel)]
        if ops_root is not None:
            candidates.append(Path(ops_root) / rel)
        hit = next((p for p in candidates if p.is_file()), None)
        if hit is None:
            continue
        window = evidence_window(hit, line, max_lines=MAIN_WINDOW_LINES)
        if window is None:
            continue
        window["file"] = rel.replace("\\", "/")
        window["writes"] = name
        span = (window["file"], window["line_start"], window["line_end"])
        if span in seen:
            continue
        seen.add(span)
        out.append(window)
    return out


def _callee_windows(
    quoted: list[str],
    sites: dict[str, tuple[str, int]] | None,
    ops_root: Any,
    seen: set[tuple[str, int, int]],
    *,
    budget: int,
    limit: int = 2,
) -> list[dict[str, Any]]:
    """Follow the calls made in the quoted lines to the code behind them.

    `bandIdx = FindBandIdx(params)` explains nothing on its own: the question
    is what `FindBandIdx` computes, and the call site is the one place that
    cannot say.

    Read off the evidence lines rather than the whole window, which is both
    more accurate and very much smaller — a window is a function, a function
    calls dozens of things, and almost none of them are what this blocker is
    about. Two calls at most, only ones the walk recorded, and only while
    there is budget: an answer nobody can read through is not evidence.
    """
    from pathlib import Path

    from uo_init.source_window import evidence_window

    if not sites or budget <= 0:
        return []
    called: list[str] = []
    for text in quoted:
        for name in _CALL.findall(text or ""):
            if name in _NOT_WORTH_FOLLOWING or name in called:
                continue
            if name in sites:
                called.append(name)
    out: list[dict[str, Any]] = []
    for name in called[:limit]:
        rel, line = sites[name]
        candidates = [Path(rel)]
        if ops_root is not None:
            candidates.append(Path(ops_root) / rel)
        hit = next((p for p in candidates if p.is_file()), None)
        if hit is None:
            continue
        window = evidence_window(hit, line, max_lines=budget)
        if window is None:
            continue
        size = window["line_end"] - window["line_start"] + 1
        if size > budget:
            continue
        window["file"] = rel.replace("\\", "/")
        window["defines"] = name
        span = (window["file"], window["line_start"], window["line_end"])
        if span in seen:
            continue
        seen.add(span)
        out.append(window)
        budget -= size
    return out


def materialize_blocker_batches(
    action_dir: Any,
    manifest: dict[str, Any],
    *,
    unresolved: dict[str, Any] | None = None,
    closed_vocabulary: dict[str, Any] | None = None,
    ops_root: Any = None,
    sites: dict[str, tuple[str, int]] | None = None,
) -> dict[str, Any]:
    """Write batch YAML files under ``action_dir/inputs/batches/``.

    ``action_dir`` is ``runs/{run_id}/actions/resolve_gaps``.
    """
    from pathlib import Path

    import yaml

    root = Path(action_dir)
    batches_dir = root / "inputs" / "batches"
    batches_dir.mkdir(parents=True, exist_ok=True)
    (root / "parts").mkdir(parents=True, exist_ok=True)
    (root / "scratch").mkdir(parents=True, exist_ok=True)

    if ops_root is None:
        from uo_init import paths

        ops_root = paths.ops_root()

    by_id = manifest.get("blockers_by_id") or {}
    if not by_id and unresolved:
        for row in unresolved.get("blockers") or []:
            if isinstance(row, dict) and row.get("id"):
                by_id[str(row["id"])] = row

    vocab = closed_vocabulary
    if vocab is None and unresolved:
        vocab = unresolved.get("closed_vocabulary")

    written: list[str] = []
    for sh in manifest.get("shards") or []:
        if not isinstance(sh, dict):
            continue
        sid = str(sh.get("shard_id") or "")
        bids = [str(x) for x in (sh.get("blocker_ids") or [])]
        blockers = [
            _attach_source(by_id[b], ops_root, sites) for b in bids if b in by_id
        ]
        batch = {
            "version": 1,
            "shard_id": sid,
            "shard_index": int(sh.get("shard_index") or 0),
            "blocker_ids": bids,
            "blockers": blockers,
            "closed_vocabulary": vocab or {},
            "part_file": str(sh.get("part_file") or f"parts/part_{sid}.yaml"),
            "instruction_zh": (
                "仅处理本 batch 的 blocker_ids；"
                "classification 必须落在封闭词汇表；"
                "input_derived 的 var_id 必须来自白名单；"
                f"写 parts/part_{sid}.yaml（patches 列表）；禁止写 uo/ir/**。"
            ),
        }
        path = batches_dir / f"batch_{sid}.yaml"
        path.write_text(
            yaml.safe_dump(batch, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        written.append(path.as_posix())

    man_path = root / "inputs" / "blocker_batches.yaml"
    man_out = {
        "version": 1,
        "obligation_count": manifest.get("obligation_count"),
        "shard_count": manifest.get("shard_count"),
        "max_per_shard": manifest.get("max_per_shard"),
        "shards": [
            {k: v for k, v in sh.items() if k != "blockers_by_id"}
            for sh in (manifest.get("shards") or [])
            if isinstance(sh, dict)
        ],
    }
    man_path.write_text(
        yaml.safe_dump(man_out, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return {"ok": True, "batches": written, "manifest": man_path.as_posix()}
