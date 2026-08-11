# -*- coding: utf-8 -*-
"""Replay-backed L3 TilingData / runtime-kernel branch coverage.

TilingKey closure establishes reachable keys first. L3 then mutates inputs in
producer cones, replays them through the real Host tiling, and credits an
obligation only from an observation that returns the intended TilingKey.

Raw ``###TD`` bytes are decoded only through an optional operator package hook
(``tilingdata_decoder.py``). Missing/failed decode leaves debt open; static
candidate intent is never accepted as runtime coverage.
"""

from __future__ import annotations

import importlib.util
import json
import random
import sys
from pathlib import Path
from typing import Any, Iterable

import yaml

from testcase_agent.closure import branch_eval
from testcase_agent.closure import branch_outcome as BO
from testcase_agent.closure import corpus as C
from testcase_agent.closure import generate as G
from testcase_agent.closure import kernel_domain as KD
from testcase_agent.closure import ledger
from testcase_agent.closure import obligations as OBL
from testcase_agent.closure import workspace as W

_SCHEMA = "tg-branch-runtime/v1"
_TERMINAL = {OBL.COVERED, OBL.PROVEN_UNREACHABLE}


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return doc if isinstance(doc, dict) else {}


def active_mode(ws: W.Workspace | None = None) -> tuple[str, str]:
    """Return durable ``(mode, level)`` for search-round dispatch."""
    ws = (ws or W.default_workspace()).ensure()
    try:
        from ascendc_pilot.paths import context_root, tg_root

        tg = tg_root(ws.root)
        params = _load_yaml(context_root(ws.root) / "pilot_params.yaml")
    except Exception:
        tg = ws.state.parent
        params = {}
    plan = _load_yaml(tg / "plan" / "plan_intent.yaml")
    init = _load_yaml(tg / "init" / "init_intent.yaml")
    mode = str(
        plan.get("mode")
        or params.get("mode")
        or init.get("mode")
        or "tilingkey_full_coverage"
    ).strip()
    level = str(plan.get("level") or params.get("level") or "").strip().upper()
    return mode, level


def is_branch_mode(ws: W.Workspace | None = None) -> bool:
    mode, level = active_mode(ws)
    return mode == "branch_outcome_coverage" or level == "L3"


def _inventory_path(ws: W.Workspace) -> Path:
    return ws.state / "obligation_inventory.yaml"


def _runtime_path(ws: W.Workspace) -> Path:
    return ws.state / "branch_runtime.yaml"


def _rounds_dir(ws: W.Workspace) -> Path:
    path = ws.state / "branch_rounds"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_inventory(ws: W.Workspace | None = None) -> dict[str, Any]:
    """Build L3 inventory once; subsequent rounds preserve runtime statuses."""
    ws = (ws or W.default_workspace()).ensure()
    old = _load_yaml(_inventory_path(ws))
    if old.get("schema") == "tg-obligation-inventory/v1":
        return old
    return OBL.collect_obligations(ws=ws)


def _save_inventory(ws: W.Workspace, inv: dict[str, Any]) -> None:
    rows = [r for r in (inv.get("obligations") or []) if isinstance(r, dict)]
    counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for row in rows:
        typ = str(row.get("type") or "")
        st = str(row.get("status") or OBL.UNRESOLVED)
        counts[typ] = counts.get(typ, 0) + 1
        status_counts[st] = status_counts.get(st, 0) + 1
    open_rows = [r for r in rows if str(r.get("status") or OBL.UNRESOLVED) not in _TERMINAL]
    inv["summary"] = {
        **dict(inv.get("summary") or {}),
        "counts": counts,
        "status_counts": status_counts,
        "unresolved_count": len(open_rows),
        "coverage_complete": not open_rows,
    }
    _inventory_path(ws).write_text(
        yaml.safe_dump(inv, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (ws.state / "obligation_summary.yaml").write_text(
        yaml.safe_dump(inv["summary"], allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _key_gap(ws: W.Workspace) -> set[int]:
    return set(ledger.declared()) - set(ledger.load_R(ws)) - set(ledger.load_E(ws))


def precheck(ws: W.Workspace | None = None) -> dict[str, Any]:
    """Runtime branch work is valid only after D = R ∪ E for TilingKeys."""
    ws = (ws or W.default_workspace()).ensure()
    gap = _key_gap(ws)
    if gap:
        return {
            "ok": False,
            "reason": "TILINGKEY_CLOSURE_REQUIRED",
            "open_key_count": len(gap),
            "sample": sorted(gap)[:20],
        }
    inv = ensure_inventory(ws)
    return {
        "ok": True,
        "reason": "READY",
        "reachable_keys": int((inv.get("summary") or {}).get("reachable_keys") or 0),
        "obligations": int(
            (inv.get("summary") or {}).get("total_obligations")
            or len(inv.get("obligations") or [])
        ),
    }


def _load_decoder() -> tuple[Any | None, str]:
    """Load optional operator ``tilingdata_decoder.py`` without engine priors."""
    try:
        from replay.package_data import package_file

        path = package_file("tilingdata_decoder.py")
    except Exception as exc:
        return None, f"package_lookup_failed:{exc}"
    if not path.is_file():
        return None, "decoder_missing"
    name = "uo_operator_tilingdata_decoder"
    try:
        if name in sys.modules:
            del sys.modules[name]
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            return None, "decoder_spec_failed"
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        if not hasattr(mod, "decode"):
            return None, "decoder_no_decode"
        return mod, "ok"
    except Exception as exc:
        return None, f"decoder_load_failed:{exc}"


def _case_signature(case: Any) -> tuple:
    I = W.replay_inputs()
    try:
        desc = I.SEMANTICS.describe(case)
    except Exception:
        desc = repr(case)
    if isinstance(desc, dict):
        return tuple(
            (str(k), json.dumps(v, sort_keys=True, default=str))
            for k, v in desc.items()
        )
    return (str(desc),)


def _base_cases_for_key(key: int, dims: dict[str, Any], ws: W.Workspace) -> list[Any]:
    out: list[Any] = []
    try:
        from testcase_agent.closure import construct

        out.extend(list(construct.build(dims) or []))
    except Exception:
        pass
    try:
        df = C.dedup(C.coerce(C.load(ws)))
        if df is not None and not df.empty and {"tiling_key", "ok"}.issubset(df.columns):
            good = df[
                (df["tiling_key"].astype(str) == str(key))
                & (df["ok"].astype(str).isin({"1", "True", "true"}))
            ]
            for _, row in good.tail(4).iterrows():
                try:
                    out.append(G.case_from_row(row))
                except Exception:
                    pass
    except Exception:
        pass
    seen: set[tuple] = set()
    dedup: list[Any] = []
    for case in out:
        sig = _case_signature(case)
        if sig in seen:
            continue
        seen.add(sig)
        dedup.append(case)
    return dedup


def _open_for_key(inv: dict[str, Any], key: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in inv.get("obligations") or []:
        if not isinstance(row, dict):
            continue
        try:
            row_key = int(row.get("tiling_key"))
        except (TypeError, ValueError):
            continue
        if row_key != int(key):
            continue
        if str(row.get("status") or OBL.UNRESOLVED) in _TERMINAL:
            continue
        out.append(row)
    return out


def _fields_for(obligations: Iterable[dict[str, Any]]) -> list[str]:
    fields: list[str] = []
    for row in obligations:
        if row.get("field"):
            fields.append(str(row["field"]))
        fields.extend(str(x) for x in (row.get("tilingdata_fields") or []) if x)
    return list(dict.fromkeys(fields))


def build_candidates(
    key: int,
    dims: dict[str, Any],
    obligations: list[dict[str, Any]],
    *,
    ws: W.Workspace,
    budget: int,
    seed: int,
) -> list[Any]:
    """Mutate producer-cone knobs while retaining a known same-key base."""
    bases = _base_cases_for_key(key, dims, ws)
    if not bases:
        return []
    rng = random.Random(seed)
    fields = _fields_for(obligations)
    candidates: list[Any] = []
    seen: set[tuple] = set()

    def add(case: Any) -> None:
        if len(candidates) >= budget:
            return
        try:
            norm = case.normalised() if hasattr(case, "normalised") else case
        except Exception:
            return
        sig = _case_signature(norm)
        if sig in seen:
            return
        seen.add(sig)
        candidates.append(norm)

    for base in bases[:3]:
        add(base)
    try:
        from ascendc_pilot.paths import uo_root

        uo = str(uo_root(ws.root))
    except Exception:
        uo = str(ws.root)
    attempts = 0
    max_attempts = max(budget * 12, 24)
    while len(candidates) < budget and attempts < max_attempts:
        attempts += 1
        base = rng.choice(bases)
        try:
            if fields and rng.random() < 0.85:
                case = G.mutate_in_cone(
                    base,
                    rng.choice(fields),
                    rng,
                    k=1 if attempts % 3 else 2,
                    uo_root=uo,
                )
            else:
                case = G.mutate(base, rng, k=1 if attempts % 3 else 2)
        except Exception:
            try:
                case = G.mutate(base, rng, k=1)
            except Exception:
                continue
        add(case)
    return candidates


def _decoder_context(decoder: Any | None, dims: dict[str, Any]) -> dict[str, Any]:
    if decoder is None or not hasattr(decoder, "eval_context"):
        return {}
    try:
        doc = decoder.eval_context(dims)
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def _decode_fields(
    decoder: Any | None,
    raw: bytes | None,
    dims: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if decoder is None or not raw:
        return {}, {"ok": False, "reason": "decoder_or_td_missing"}
    try:
        doc = decoder.decode(raw, dims)
    except Exception as exc:
        return {}, {"ok": False, "reason": f"decode_failed:{exc}"}
    if not isinstance(doc, dict):
        return {}, {"ok": False, "reason": "decode_not_mapping"}
    fields = doc.get("fields") if isinstance(doc.get("fields"), dict) else doc
    return dict(fields), {
        "ok": bool(fields),
        "layout": doc.get("layout"),
        "absent_members": list(doc.get("absent_members") or []),
        "present_leaves": list(doc.get("present_leaves") or []),
        "owner": dict(doc.get("owner") or {}),
    }


def _eval_td_obligation(row: dict[str, Any], env: BO.Env) -> bool | None:
    predicate = str(row.get("predicate") or "").strip()
    field = str(row.get("field") or "").strip()
    if not predicate:
        return field in env.fields
    try:
        return branch_eval.evaluate(predicate, env).value
    except Exception:
        return None


def _case_ids(prefix: str, cases: list[Any]) -> dict[str, Any]:
    return {f"{prefix}_{i:03d}": c for i, c in enumerate(cases)}


def _raw_index(transcript: str) -> dict[str, dict[str, Any]]:
    try:
        from testcase_agent.closure.key_data_coupling import harvest_td_observations

        return {
            str(row.get("case_id")): row
            for row in harvest_td_observations(transcript)
            if isinstance(row, dict) and row.get("case_id")
        }
    except Exception:
        return {}


def _credit_kernel_row(
    row: dict[str, Any],
    branch: dict[str, Any] | None,
    env: BO.Env,
    meta: dict[str, Any],
    case_id: str,
) -> None:
    if not branch:
        return
    state, observed, excluded = BO.state_of(
        branch,
        env,
        absent_members=set(meta.get("absent_members") or []),
        present_leaves=set(meta.get("present_leaves") or env.fields.keys()),
        owner=dict(meta.get("owner") or {}),
    )
    want = bool(row.get("outcome"))
    if want in observed:
        row["status"] = OBL.COVERED
        row["evidence"] = {
            "case_id": case_id,
            "kind": "runtime_kernel_branch",
            "state": state,
        }
    elif want in excluded:
        row["status"] = OBL.PROVEN_UNREACHABLE
        row["exclusion_basis"] = {
            "kind": "key_determined_or_reviewed_pin",
            "case_id": case_id,
            "state": state,
        }


def run_round(
    ws: W.Workspace | None = None,
    *,
    budget: int = 64,
    seed: int = 0,
    oracle: Any | None = None,
) -> dict[str, Any]:
    """Run one bounded L3 search/replay/evaluate round."""
    del oracle
    ws = (ws or W.default_workspace()).ensure()
    ready = precheck(ws)
    rounds = _rounds_dir(ws)
    idx = len(list(rounds.glob("round_*"))) + 1
    rd = rounds / f"round_{idx:04d}"
    rd.mkdir(parents=True, exist_ok=True)
    if not ready.get("ok"):
        progress = {
            "schema": _SCHEMA,
            "round": idx,
            "ok": False,
            "reason": ready.get("reason"),
            "new_R": 0,
            "new_obligations": 0,
            **ready,
        }
        (rd / "progress.yaml").write_text(
            yaml.safe_dump(progress, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        return {
            "ok": False,
            "round_dir": str(rd),
            "progress": progress,
            "route_hint": "PROOF_BLOCKED",
        }

    inv = ensure_inventory(ws)
    open_rows = [
        row for row in (inv.get("obligations") or [])
        if isinstance(row, dict)
        and str(row.get("status") or OBL.UNRESOLVED) not in _TERMINAL
    ]
    open_keys = list(
        dict.fromkeys(
            int(row["tiling_key"])
            for row in open_rows
            if row.get("tiling_key") is not None
        )
    )
    if not open_keys:
        progress = {
            "schema": _SCHEMA,
            "round": idx,
            "ok": True,
            "reason": "BRANCH_GAP_ZERO",
            "new_R": 0,
            "new_obligations": 0,
            "open_obligations": 0,
            "coverage_complete": True,
        }
        (rd / "progress.yaml").write_text(
            yaml.safe_dump(progress, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        return {
            "ok": True,
            "round_dir": str(rd),
            "progress": progress,
            "route_hint": "GAP_ZERO",
        }

    per_key = max(2, min(12, int(max(1, budget) ** 0.5) + 1))
    target_keys = open_keys[: max(1, budget // per_key)]
    case_map: dict[str, Any] = {}
    target_of: dict[str, int] = {}
    for pos, key in enumerate(target_keys):
        dims = W.decode(key)
        made = build_candidates(
            key,
            dims,
            _open_for_key(inv, key),
            ws=ws,
            budget=per_key,
            seed=seed + pos * 997 + idx * 31,
        )
        for cid, case in _case_ids(f"b{idx}_k{key}", made).items():
            case_map[cid] = case
            target_of[cid] = key

    if not case_map:
        progress = {
            "schema": _SCHEMA,
            "round": idx,
            "ok": False,
            "reason": "BRANCH_CONSTRUCT_EMPTY",
            "new_R": 0,
            "new_obligations": 0,
            "target_keys": target_keys,
            "open_obligations": len(open_rows),
        }
        (rd / "progress.yaml").write_text(
            yaml.safe_dump(progress, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        return {
            "ok": False,
            "round_dir": str(rd),
            "progress": progress,
            "route_hint": "SEARCH_STALLED",
        }

    runner = W.replay_runner()
    tag = f"branch_r{idx:04d}"
    try:
        results = runner.run(case_map, tag=tag, with_log=True, check=False)
    except Exception as exc:
        progress = {
            "schema": _SCHEMA,
            "round": idx,
            "ok": False,
            "reason": "BRANCH_REPLAY_FAILED",
            "error": str(exc)[:500],
            "new_R": 0,
            "new_obligations": 0,
            "sent": len(case_map),
        }
        (rd / "progress.yaml").write_text(
            yaml.safe_dump(progress, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        return {
            "ok": False,
            "round_dir": str(rd),
            "progress": progress,
            "route_hint": "ORACLE_SUSPECT",
        }

    log_path = Path(runner.cache) / f"{tag}_log.txt"
    transcript = (
        log_path.read_text(encoding="utf-8", errors="replace")
        if log_path.is_file()
        else ""
    )
    raw_by_id = _raw_index(transcript)
    decoder, decoder_status = _load_decoder()
    branches = KD.load_kernel_branches(ws=ws)
    branch_by_id = {
        BO.site_id(branch): branch
        for branch in branches
        if isinstance(branch, dict)
    }

    before_terminal = sum(
        1
        for row in inv.get("obligations") or []
        if isinstance(row, dict) and str(row.get("status")) in _TERMINAL
    )
    on_key = 0
    decode_ok = 0
    evidence_rows: list[dict[str, Any]] = []
    for cid, result in results.items():
        target = target_of.get(cid)
        if target is None:
            continue
        actual = int(result.key or 0)
        if not result.ok or actual != target:
            evidence_rows.append(
                {
                    "case_id": cid,
                    "target_key": target,
                    "actual_key": actual,
                    "ok": bool(result.ok),
                    "on_key": False,
                    "reject": result.reject,
                }
            )
            continue

        on_key += 1
        dims = W.decode(target)
        raw_info = raw_by_id.get(cid) or {}
        decoded, dec_meta = _decode_fields(decoder, raw_info.get("td"), dims)
        if dec_meta.get("ok"):
            decode_ok += 1
        fields = dict(decoded)
        for name, value in dict(result.diag or {}).items():
            fields.setdefault(str(name), value)
        ctx = _decoder_context(decoder, dims)
        env = BO.build_env(
            fields=fields,
            dims=dims,
            param_to_dim=dict(ctx.get("param_to_dim") or {}),
            enums=dict(ctx.get("enums") or {}),
            block_num=int(raw_info.get("block_num") or 0),
            derived=dict(ctx.get("derived") or {}),
            pins=dict(ctx.get("pins") or {}),
        )

        for row in _open_for_key(inv, target):
            if row.get("type") == "TILINGDATA_VALUE_CLASS":
                verdict = _eval_td_obligation(row, env)
                if verdict is True:
                    row["status"] = OBL.COVERED
                    row["evidence"] = {
                        "case_id": cid,
                        "kind": "runtime_tilingdata",
                    }
                    fld = str(row.get("field") or "")
                    if fld in env.fields:
                        row["observed_value"] = env.fields[fld]
            elif row.get("type") == "KERNEL_BRANCH_OUTCOME":
                _credit_kernel_row(
                    row,
                    branch_by_id.get(str(row.get("branch_id") or "")),
                    env,
                    dec_meta,
                    cid,
                )

        evidence_rows.append(
            {
                "case_id": cid,
                "target_key": target,
                "actual_key": actual,
                "ok": True,
                "on_key": True,
                "decoder_ok": bool(dec_meta.get("ok")),
                "layout": dec_meta.get("layout"),
                "field_count": len(env.fields),
                "diag_fields": sorted((result.diag or {}).keys()),
            }
        )

    _save_inventory(ws, inv)
    after_terminal = sum(
        1
        for row in inv.get("obligations") or []
        if isinstance(row, dict) and str(row.get("status")) in _TERMINAL
    )
    new_obligations = max(0, after_terminal - before_terminal)
    summary = dict(inv.get("summary") or {})
    open_after = int(summary.get("unresolved_count") or 0)
    complete = open_after == 0

    try:
        actual_cases: dict[str, Any] = {}
        actual_results: dict[str, Any] = {}
        for cid, result in results.items():
            target = target_of.get(cid)
            if target is not None and result.ok and int(result.key or 0) == target:
                actual_cases[cid] = case_map[cid]
                actual_results[cid] = result
        if actual_cases:
            runner.write_wide(
                ws.artifacts / f"branch_round_{idx:04d}_key_cases.csv",
                actual_cases,
                actual_results,
            )
    except Exception:
        pass

    progress = {
        "schema": _SCHEMA,
        "round": idx,
        "ok": True,
        "reason": (
            "BRANCH_GAP_ZERO"
            if complete
            else ("BRANCH_PROGRESS" if new_obligations else "BRANCH_STALLED")
        ),
        "new_R": 0,
        "new_obligations": new_obligations,
        "open_obligations": open_after,
        "target_keys": target_keys,
        "sent": len(case_map),
        "replayed": len(results),
        "on_key": on_key,
        "decoder": decoder_status,
        "decoded": decode_ok,
        "coverage_complete": complete,
        "status_counts": summary.get("status_counts") or {},
    }
    (rd / "progress.yaml").write_text(
        yaml.safe_dump(progress, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (rd / "evidence.jsonl").write_text(
        "".join(
            json.dumps(item, ensure_ascii=False, default=str) + "\n"
            for item in evidence_rows
        ),
        encoding="utf-8",
    )
    runtime = {
        "schema": _SCHEMA,
        "latest_round": idx,
        "coverage_complete": complete,
        "open_obligations": open_after,
        "decoder": decoder_status,
        "round_dir": rd.as_posix(),
        "progress": progress,
    }
    _runtime_path(ws).write_text(
        yaml.safe_dump(runtime, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return {
        "ok": True,
        "round_dir": str(rd),
        "progress": progress,
        "route_hint": (
            "GAP_ZERO"
            if complete
            else ("SEARCH_PROGRESS" if new_obligations else "SEARCH_STALLED")
        ),
        "branch_runtime": runtime,
    }


def route(ws: W.Workspace | None = None) -> dict[str, Any]:
    """Map branch debt to the existing tg-solve reason codes."""
    ws = (ws or W.default_workspace()).ensure()
    if not is_branch_mode(ws):
        return {}
    inv = ensure_inventory(ws)
    open_n = int((inv.get("summary") or {}).get("unresolved_count") or 0)
    base = ledger.state(ws)
    if open_n == 0:
        return {"reason": "GAP_ZERO", "branch_open": 0, **base}
    recent: list[dict[str, Any]] = []
    for rd in sorted(_rounds_dir(ws).glob("round_*"))[-2:]:
        doc = _load_yaml(rd / "progress.yaml")
        if doc:
            recent.append(doc)
    if recent and int(recent[-1].get("new_obligations") or 0) > 0:
        return {"reason": "SEARCH_PROGRESS", "branch_open": open_n, **base}
    if len(recent) >= 2 and all(
        int(item.get("new_obligations") or 0) == 0 for item in recent[-2:]
    ):
        return {"reason": "SEARCH_STALLED", "branch_open": open_n, **base}
    return {"reason": "SEARCH_PROGRESS", "branch_open": open_n, **base}


def certification_summary(ws: W.Workspace | None = None) -> dict[str, Any]:
    ws = (ws or W.default_workspace()).ensure()
    inv = ensure_inventory(ws)
    summary = dict(inv.get("summary") or {})
    open_n = int(summary.get("unresolved_count") or 0)
    return {
        "schema": _SCHEMA,
        "ok": open_n == 0,
        "open_obligations": open_n,
        "coverage_complete": open_n == 0,
        "status_counts": summary.get("status_counts") or {},
        "runtime": _load_yaml(_runtime_path(ws)),
    }


__all__ = [
    "active_mode",
    "is_branch_mode",
    "ensure_inventory",
    "precheck",
    "build_candidates",
    "run_round",
    "route",
    "certification_summary",
]
