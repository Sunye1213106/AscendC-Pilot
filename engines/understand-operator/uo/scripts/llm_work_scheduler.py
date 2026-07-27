"""Public LLM Work Scheduler — Map-Reduce sharding for all batch LLM Actions.

Hard limits (either may force a split):
  - max obligations per shard (default 30)
  - approximate token budget per shard

Errors:
  - LLM_WORK_NOT_SHARDED: obligation_count > max but planner produced < 2 shards
  - LLM_SHARD_TOO_LARGE: any shard exceeds max obligations or token budget
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable

from uo.scripts._ir_io import read_yaml, write_yaml

MAX_OBLIGATIONS_PER_SHARD = 30
# Rough char→token estimate (ASCII-heavy YAML/code); keep conservative.
DEFAULT_CHARS_PER_TOKEN = 4
DEFAULT_TOKEN_BUDGET = 12_000
ERR_NOT_SHARDED = "LLM_WORK_NOT_SHARDED"
ERR_SHARD_TOO_LARGE = "LLM_SHARD_TOO_LARGE"


def estimate_tokens(obj: Any, *, chars_per_token: int = DEFAULT_CHARS_PER_TOKEN) -> int:
    """Cheap token estimate from serialized size (no tokenizer dependency)."""
    try:
        import json

        raw = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        raw = str(obj)
    n = max(1, int(chars_per_token) or 4)
    return max(1, (len(raw) + n - 1) // n)


def obligation_id(item: dict[str, Any], *, id_keys: tuple[str, ...] = ("obligation_id", "candidate_id", "task_id", "id")) -> str:
    for k in id_keys:
        v = str(item.get(k) or "").strip()
        if v:
            return v
    return ""


def _stable_hash(parts: list[str]) -> str:
    raw = ",".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def plan_llm_work_shards(
    obligations: list[dict[str, Any]],
    *,
    action_session_id: str = "",
    source_snapshot_hash: str = "",
    max_per_shard: int = MAX_OBLIGATIONS_PER_SHARD,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    group_key_fn: Callable[[dict[str, Any]], str] | None = None,
    id_keys: tuple[str, ...] = ("obligation_id", "candidate_id", "task_id", "id"),
    batch_dir: str = "batches",
    part_dir: str = "parts",
    batch_name_fn: Callable[[str, int], str] | None = None,
    part_name_fn: Callable[[str, int], str] | None = None,
) -> dict[str, Any]:
    """Group by conflict key, then split by count OR token budget.

    Never splits a conflict group across shards when the group itself fits;
    oversize groups are split only as a last resort (still fails if a single
    item exceeds budget).
    """
    max_n = max(1, int(max_per_shard))
    budget = max(100, int(token_budget))
    gfn = group_key_fn or (lambda _x: "generic")
    rows = [o for o in (obligations or []) if isinstance(o, dict)]

    groups: dict[str, list[dict[str, Any]]] = {}
    for item in rows:
        groups.setdefault(str(gfn(item) or "generic"), []).append(item)

    shards: list[dict[str, Any]] = []
    shard_idx = 0
    errors: list[str] = []

    def _emit(chunk: list[dict[str, Any]], gkey: str, category: str) -> None:
        nonlocal shard_idx
        ids = [obligation_id(x, id_keys=id_keys) for x in chunk]
        ids = [i for i in ids if i]
        tok = estimate_tokens(chunk)
        if len(ids) > max_n or tok > budget:
            errors.append(
                f"{ERR_SHARD_TOO_LARGE}: shard would have count={len(ids)} "
                f"tokens≈{tok} (max_n={max_n}, budget={budget})"
            )
        sid = f"{category}_{shard_idx:03d}"
        if batch_name_fn:
            batch_file = batch_name_fn(sid, shard_idx)
        else:
            batch_file = f"{batch_dir}/batch_{shard_idx:03d}.yaml"
        if part_name_fn:
            part_file = part_name_fn(sid, shard_idx)
        else:
            part_file = f"{part_dir}/part_{shard_idx:03d}.yaml"
        shards.append(
            {
                "shard_id": sid,
                "shard_index": shard_idx,
                "category": category,
                "group_key": gkey,
                "obligation_ids": ids,
                "obligation_count": len(ids),
                "token_estimate": tok,
                "status": "pending",
                "batch_file": batch_file,
                "part_file": part_file,
            }
        )
        shard_idx += 1

    for gkey in sorted(groups.keys()):
        bucket = groups[gkey]
        category = gkey.split("::", 1)[0] if gkey else "generic"
        # Conflict groups must stay together. Oversize group → hard fail (do not split).
        if len(bucket) > max_n or estimate_tokens(bucket) > budget:
            errors.append(
                f"{ERR_SHARD_TOO_LARGE}: conflict group {gkey!r} has "
                f"count={len(bucket)} tokens≈{estimate_tokens(bucket)} "
                f"(max_n={max_n}, budget={budget}); groups must not cross shards"
            )
            # Still emit so callers can inspect; marked oversized.
            _emit(bucket, gkey, category)
            continue
        _emit(bucket, gkey, category)

    # Second pass: pack small groups into shards up to max_n / budget.
    # Rebuild by packing emitted small shards? Simpler: re-pack from groups that fit.
    # (Above emits one shard per group; pack adjacent small groups.)
    if not errors:
        packed: list[dict[str, Any]] = []
        cur_items: list[dict[str, Any]] = []
        cur_keys: list[str] = []
        cur_cat = "mixed"
        shard_idx = 0

        def _flush() -> None:
            nonlocal shard_idx, cur_items, cur_keys, cur_cat
            if not cur_items:
                return
            ids = [obligation_id(x, id_keys=id_keys) for x in cur_items]
            ids = [i for i in ids if i]
            tok = estimate_tokens(cur_items)
            gkey = "+".join(cur_keys[:3]) + (f"+{len(cur_keys)-3}" if len(cur_keys) > 3 else "")
            sid = f"{cur_cat}_{shard_idx:03d}"
            batch_file = (
                batch_name_fn(sid, shard_idx)
                if batch_name_fn
                else f"{batch_dir}/batch_{shard_idx:03d}.yaml"
            )
            part_file = (
                part_name_fn(sid, shard_idx)
                if part_name_fn
                else f"{part_dir}/part_{shard_idx:03d}.yaml"
            )
            packed.append(
                {
                    "shard_id": sid,
                    "shard_index": shard_idx,
                    "category": cur_cat,
                    "group_key": gkey,
                    "obligation_ids": ids,
                    "obligation_count": len(ids),
                    "token_estimate": tok,
                    "status": "pending",
                    "batch_file": batch_file,
                    "part_file": part_file,
                }
            )
            shard_idx += 1
            cur_items = []
            cur_keys = []

        for gkey in sorted(groups.keys()):
            bucket = groups[gkey]
            category = gkey.split("::", 1)[0] if gkey else "generic"
            trial = cur_items + bucket
            tok = estimate_tokens(trial)
            if cur_items and (len(trial) > max_n or tok > budget):
                _flush()
            if not cur_items:
                cur_cat = category
            cur_items.extend(bucket)
            cur_keys.append(gkey)
        _flush()
        shards = packed
    else:
        # Keep first-pass shards for diagnostics
        pass

    all_ids = []
    for sh in shards:
        all_ids.extend(sh.get("obligation_ids") or [])
    set_hash = _stable_hash(sorted(all_ids))

    total = len(all_ids)
    if total > max_n and len(shards) < 2:
        errors.append(
            f"{ERR_NOT_SHARDED}: obligation_count={total} > {max_n} but shard_count={len(shards)}"
        )
    for sh in shards:
        if int(sh.get("obligation_count") or 0) > max_n:
            errors.append(
                f"{ERR_SHARD_TOO_LARGE}: {sh.get('shard_id')} has "
                f"{sh.get('obligation_count')} > {max_n}"
            )
        if int(sh.get("token_estimate") or 0) > budget:
            errors.append(
                f"{ERR_SHARD_TOO_LARGE}: {sh.get('shard_id')} tokens≈"
                f"{sh.get('token_estimate')} > {budget}"
            )

    # Expected shard count lower bound for tests / gate
    expected_min = (total + max_n - 1) // max_n if total else 0

    return {
        "version": 1,
        "ok": not errors,
        "errors": errors,
        "action_session_id": action_session_id,
        "source_snapshot_hash": source_snapshot_hash,
        "obligation_set_hash": set_hash,
        "max_per_shard": max_n,
        "token_budget": budget,
        "obligation_count": total,
        "shard_count": len(shards),
        "expected_min_shards": expected_min,
        "shards": shards,
    }


def require_valid_manifest(manifest: dict[str, Any]) -> None:
    """Raise ValueError with LLM_* code when sharding contract fails."""
    errs = list(manifest.get("errors") or [])
    if not errs and manifest.get("ok") is False:
        errs = ["LLM_WORK_SCHEDULE_FAILED"]
    if errs:
        raise ValueError("; ".join(str(e) for e in errs))


def write_llm_batches(
    action_dir: Path,
    manifest: dict[str, Any],
    obligations_by_id: dict[str, dict[str, Any]],
    *,
    batches_subdir: str = "batches",
    parts_subdir: str = "parts",
    manifest_name: str = "decision_batches.yaml",
    extra_batch_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist manifest + per-shard batch YAML."""
    action_dir = Path(action_dir)
    batches_dir = action_dir / batches_subdir
    parts_dir = action_dir / parts_subdir
    batches_dir.mkdir(parents=True, exist_ok=True)
    parts_dir.mkdir(parents=True, exist_ok=True)
    (action_dir / "scratch").mkdir(parents=True, exist_ok=True)

    for shard in manifest.get("shards") or []:
        if not isinstance(shard, dict):
            continue
        sid = str(shard.get("shard_id") or "")
        idx = int(shard.get("shard_index") or 0)
        ids = list(shard.get("obligation_ids") or [])
        rows = [obligations_by_id[i] for i in ids if i in obligations_by_id]
        batch = {
            "version": 1,
            "shard_id": sid,
            "shard_index": idx,
            "category": shard.get("category"),
            "group_key": shard.get("group_key"),
            "action_session_id": manifest.get("action_session_id"),
            "source_snapshot_hash": manifest.get("source_snapshot_hash"),
            "obligation_set_hash": manifest.get("obligation_set_hash"),
            "obligation_ids": ids,
            "obligation_count": len(ids),
            "token_estimate": shard.get("token_estimate"),
            "obligations": rows,
        }
        if extra_batch_fields:
            batch.update(extra_batch_fields)
        # Prefer explicit batch_file basename under batches_dir
        bf = str(shard.get("batch_file") or f"batch_{idx:03d}.yaml")
        name = Path(bf).name
        write_yaml(batches_dir / name, batch)
        # Normalize stored relative path
        shard["batch_file"] = f"{batches_subdir}/{name}"
        # Keep part_file as provided (may be parts/part_{sid}.yaml)
        pf = str(shard.get("part_file") or f"{parts_subdir}/part_{idx:03d}.yaml")
        shard["part_file"] = pf.replace("\\", "/")
        if not shard["part_file"].startswith(parts_subdir):
            shard["part_file"] = f"{parts_subdir}/{Path(pf).name}"

    write_yaml(action_dir / manifest_name, manifest)
    return {
        "ok": bool(manifest.get("ok", True)),
        "shard_count": len(manifest.get("shards") or []),
        "dir": str(action_dir),
        "manifest": manifest_name,
    }


def validate_llm_part(
    part: dict[str, Any],
    *,
    shard: dict[str, Any],
    manifest: dict[str, Any],
    decision_key: str = "decisions",
    id_field: str = "candidate_id",
) -> list[str]:
    """Validate one Map worker part against its shard assignment."""
    errors: list[str] = []
    if not isinstance(part, dict):
        return ["PART_NOT_MAPPING"]
    if str(part.get("shard_id") or "") != str(shard.get("shard_id") or ""):
        errors.append("PART_SHARD_MISMATCH")
    if str(part.get("action_session_id") or "") != str(manifest.get("action_session_id") or ""):
        errors.append("PART_ACTION_SESSION_MISMATCH")
    if str(part.get("source_snapshot_hash") or "") != str(
        manifest.get("source_snapshot_hash") or ""
    ):
        errors.append("PART_SOURCE_SNAPSHOT_MISMATCH")
    if str(part.get("obligation_set_hash") or "") and str(
        part.get("obligation_set_hash") or ""
    ) != str(manifest.get("obligation_set_hash") or ""):
        errors.append("PART_OBLIGATION_SET_HASH_MISMATCH")

    allowed = set(str(x) for x in (shard.get("obligation_ids") or []))
    seen: set[str] = set()
    rows = list(part.get(decision_key) or [])
    # Also accept accepted/rejected/deferred style
    if not rows:
        for k in ("accepted", "rejected", "deferred"):
            for r in part.get(k) or []:
                if isinstance(r, dict):
                    rows.append({**r, "_bucket": k})
    for row in rows:
        if not isinstance(row, dict):
            errors.append("PART_DECISION_NOT_MAPPING")
            continue
        oid = str(row.get(id_field) or row.get("obligation_id") or row.get("task_id") or "").strip()
        if not oid:
            errors.append("PART_DECISION_MISSING_ID")
            continue
        if oid not in allowed:
            errors.append(f"PART_DECISION_OUT_OF_SHARD:{oid}")
        if oid in seen:
            errors.append(f"PART_DECISION_DUPLICATE:{oid}")
        seen.add(oid)
    missing = sorted(allowed - seen)
    for oid in missing:
        errors.append(f"PART_DECISION_MISSING:{oid}")
    if int(shard.get("obligation_count") or len(allowed)) > MAX_OBLIGATIONS_PER_SHARD:
        errors.append(f"{ERR_SHARD_TOO_LARGE}:{shard.get('shard_id')}")
    return errors


def reduce_llm_parts(
    action_dir: Path,
    *,
    manifest: dict[str, Any] | None = None,
    manifest_name: str = "decision_batches.yaml",
    parts_subdir: str = "parts",
    decision_key: str = "decisions",
    id_field: str = "candidate_id",
    only_failed: bool = False,
) -> dict[str, Any]:
    """Merge parts; optionally skip already-ok shards when only_failed=True."""
    action_dir = Path(action_dir)
    if manifest is None:
        man_path = action_dir / manifest_name
        if not man_path.is_file():
            return {"ok": False, "errors": [f"{manifest_name} missing"]}
        manifest = read_yaml(man_path) or {}
    if not isinstance(manifest, dict):
        return {"ok": False, "errors": ["manifest not mapping"]}

    errors: list[str] = []
    merged_rows: list[dict[str, Any]] = []
    failed_shards: list[str] = []
    ok_shards: list[str] = []
    seen_ids: set[str] = set()
    expected = {
        str(s.get("shard_id") or "")
        for s in (manifest.get("shards") or [])
        if isinstance(s, dict) and s.get("shard_id")
    }

    for shard in manifest.get("shards") or []:
        if not isinstance(shard, dict):
            continue
        sid = str(shard.get("shard_id") or "")
        if only_failed and str(shard.get("status") or "") == "ok":
            ok_shards.append(sid)
            # Still count prior decisions as covered
            for oid in shard.get("obligation_ids") or []:
                seen_ids.add(str(oid))
            continue
        part_rel = str(shard.get("part_file") or f"{parts_subdir}/part_{shard.get('shard_index', 0):03d}.yaml")
        part_path = action_dir / part_rel
        if not part_path.is_file():
            # Also try basename under parts_subdir
            alt = action_dir / parts_subdir / Path(part_rel).name
            part_path = alt if alt.is_file() else part_path
        if not part_path.is_file():
            errors.append(f"PART_MISSING:{sid}")
            failed_shards.append(sid)
            continue
        part = read_yaml(part_path) or {}
        perr = validate_llm_part(
            part if isinstance(part, dict) else {},
            shard=shard,
            manifest=manifest,
            decision_key=decision_key,
            id_field=id_field,
        )
        if perr:
            errors.extend(perr)
            failed_shards.append(sid)
            continue
        # Collect decisions
        rows = list((part or {}).get(decision_key) or [])
        if not rows:
            for bucket in ("accepted", "rejected", "deferred"):
                for r in (part or {}).get(bucket) or []:
                    if isinstance(r, dict):
                        rows.append({**r, "_bucket": bucket})
        for r in rows:
            if not isinstance(r, dict):
                continue
            oid = str(r.get(id_field) or r.get("obligation_id") or "").strip()
            if oid in seen_ids and oid not in {
                str(x) for x in (shard.get("obligation_ids") or [])
            }:
                errors.append(f"REDUCE_DUPLICATE_OBLIGATION:{oid}")
                continue
            if oid in seen_ids:
                # already counted from ok shard skip path
                continue
            seen_ids.add(oid)
            merged_rows.append(r)
        shard["status"] = "ok"
        ok_shards.append(sid)

    # Coverage of all expected obligation ids
    all_expected: set[str] = set()
    for sh in manifest.get("shards") or []:
        if isinstance(sh, dict):
            all_expected.update(str(x) for x in (sh.get("obligation_ids") or []))
    missing = sorted(all_expected - seen_ids)
    for oid in missing:
        # If belonging to a failed shard, already reported
        errors.append(f"REDUCE_MISSING_OBLIGATION:{oid}")

    present_shards = set(ok_shards) | set(failed_shards)
    for sid in sorted(expected - present_shards):
        errors.append(f"SHARD_NOT_PRESENT:{sid}")

    report = {
        "ok": not errors,
        "errors": errors,
        "ok_shards": ok_shards,
        "failed_shards": failed_shards,
        "merged_count": len(merged_rows),
        "expected_count": len(all_expected),
        "retry_shards": list(failed_shards),
    }
    write_yaml(action_dir / "reduce_report.yaml", report)
    # Persist updated shard statuses
    write_yaml(action_dir / manifest_name, manifest)
    return {
        "ok": not errors,
        "errors": errors,
        "report": report,
        "decisions": merged_rows,
        "manifest": manifest,
        "retry_shards": list(failed_shards),
    }


def build_dispatch_tasks(
    manifest: dict[str, Any],
    *,
    action_id: str,
    run_id: str,
    actor_id: str = "uo-semantic-resolve",
    action_session_id: str = "",
    batch_root: str = "",
    part_root: str = "",
    forbid_extra: str = "",
) -> list[dict[str, Any]]:
    """Build Primary-facing dispatch_tasks[] stubs (no sharding algorithm in prompt)."""
    out: list[dict[str, Any]] = []
    session = str(action_session_id or manifest.get("action_session_id") or "")
    base = f"runs/{run_id}/actions/{action_id}"
    for shard in manifest.get("shards") or []:
        if not isinstance(shard, dict):
            continue
        sid = str(shard.get("shard_id") or "")
        idx = int(shard.get("shard_index") or 0)
        batch_rel = str(shard.get("batch_file") or f"batches/batch_{idx:03d}.yaml")
        part_rel = str(shard.get("part_file") or f"parts/part_{idx:03d}.yaml")
        if batch_root:
            batch_path = f"{base}/{batch_root}/{Path(batch_rel).name}"
        else:
            batch_path = f"{base}/{batch_rel}".replace("//", "/")
        if part_root:
            part_path = f"{base}/{part_root}/{Path(part_rel).name}"
        else:
            part_path = f"{base}/{part_rel}".replace("//", "/")
        stub = (
            f"action_id={action_id} shard_id={sid}\n"
            f"run_id={run_id}\n"
            f"action_session_id={session}\n"
            f"read ONLY: {batch_path}\n"
            f"write ONLY: {part_path}\n"
            f"scratch: {base}/scratch/{sid}/**\n"
            "FORBIDDEN: read other batches / full worklist / full candidates / other parts\n"
            "FORBIDDEN: write decision_report.yaml / uo/ir/** / finalize / next / advance\n"
            f"obligation_count={shard.get('obligation_count')} (hard max {MAX_OBLIGATIONS_PER_SHARD})\n"
            "Decide each obligation in this batch only; run shard self-check; stop.\n"
        )
        if forbid_extra:
            stub += forbid_extra + "\n"
        out.append(
            {
                "shard_id": sid,
                "shard_index": idx,
                "actor_id": actor_id,
                "category": shard.get("category"),
                "obligation_ids": list(shard.get("obligation_ids") or []),
                "obligation_count": shard.get("obligation_count"),
                "task_prompt_stub": stub,
                "batch_file": batch_rel,
                "part_file": part_rel,
                "batch_path": batch_path,
                "part_path": part_path,
            }
        )
    return out


__all__ = [
    "DEFAULT_TOKEN_BUDGET",
    "ERR_NOT_SHARDED",
    "ERR_SHARD_TOO_LARGE",
    "MAX_OBLIGATIONS_PER_SHARD",
    "build_dispatch_tasks",
    "estimate_tokens",
    "obligation_id",
    "plan_llm_work_shards",
    "reduce_llm_parts",
    "require_valid_manifest",
    "validate_llm_part",
    "write_llm_batches",
]
