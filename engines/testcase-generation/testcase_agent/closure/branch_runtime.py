# -*- coding: utf-8 -*-
"""Replay-backed L3 TilingData / runtime-kernel branch coverage.

The canonical runtime debt ledger remains ``obligation_inventory.yaml`` with
its existing ``keys[].tilingdata_obligations/kernel_obligations`` schema. L3
mutates candidate inputs, replays the real Host tiling, and updates those rows
only when the observation returns the intended TilingKey.

Raw ``###TD`` bytes are decoded via UO layout + generic TilingData decoder;
``LayoutIncomplete`` falls back to a Local Extension ``tilingdata_decoder``.
Missing/failed decode leaves debt open; candidate intent and static set-cover
claims are never accepted as runtime evidence.
"""

from __future__ import annotations

import importlib.util
import json
import os
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

COVERED = "COVERED"
PROVEN_UNREACHABLE = "PROVEN_UNREACHABLE"
UNRESOLVED = "UNRESOLVED"
_TERMINAL = {COVERED, PROVEN_UNREACHABLE}
_SCHEMA = "tg-branch-runtime/v1"


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
    plan: dict[str, Any] = {}
    plan_md = tg / "plan.md"
    if plan_md.is_file():
        try:
            from testcase_agent.products import parse_plan_fence

            plan = parse_plan_fence(plan_md.read_text(encoding="utf-8"))
        except Exception:
            plan = {}
    init = _load_yaml(tg / "init.yaml")
    mode = str(
        plan.get("mode")
        or params.get("mode")
        or init.get("mode")
        or ""
    ).strip()
    level = str(plan.get("level") or params.get("level") or "").strip().upper()
    return mode, level


def is_branch_mode(ws: W.Workspace | None = None) -> bool:
    mode, level = active_mode(ws)
    return mode == "branch_outcome_coverage" or level == "L3"


def _inventory_path(ws: W.Workspace) -> Path:
    return ws.report("obligation_inventory.yaml")


def _runtime_path(ws: W.Workspace) -> Path:
    return ws.report("branch_runtime.yaml")


def _rounds_dir(ws: W.Workspace) -> Path:
    path = ws.state / "branch_rounds"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_inventory(ws: W.Workspace | None = None) -> dict[str, Any]:
    """Build inventory once, then read back the canonical persisted document."""
    ws = (ws or W.default_workspace()).ensure()
    old = _load_yaml(_inventory_path(ws))
    if old.get("schema") == "tg-obligation-inventory/v1":
        return old
    OBL.collect_obligations(ws=ws, write=True)
    return _load_yaml(_inventory_path(ws))


def _iter_obligations(inv: dict[str, Any]):
    for key_doc in inv.get("keys") or []:
        if not isinstance(key_doc, dict):
            continue
        try:
            key = int(key_doc.get("tiling_key"))
        except (TypeError, ValueError):
            continue
        for kind, bucket in (
            ("TILINGDATA_VALUE_CLASS", "tilingdata_obligations"),
            ("KERNEL_BRANCH_OUTCOME", "kernel_obligations"),
        ):
            for row in key_doc.get(bucket) or []:
                if isinstance(row, dict):
                    yield key, kind, row


def _open_for_key(inv: dict[str, Any], key: int) -> list[tuple[str, dict[str, Any]]]:
    return [
        (kind, row)
        for row_key, kind, row in _iter_obligations(inv)
        if row_key == int(key) and str(row.get("status") or UNRESOLVED) not in _TERMINAL
    ]


def _save_inventory(ws: W.Workspace, inv: dict[str, Any]) -> None:
    counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    open_n = 0
    for _key, kind, row in _iter_obligations(inv):
        counts[kind] = counts.get(kind, 0) + 1
        status = str(row.get("status") or UNRESOLVED)
        status_counts[status] = status_counts.get(status, 0) + 1
        if status not in _TERMINAL:
            open_n += 1
    inv["runtime_summary"] = {
        "counts": counts,
        "status_counts": status_counts,
        "unresolved_count": open_n,
        "coverage_complete": open_n == 0,
    }
    _inventory_path(ws).write_text(
        yaml.safe_dump(inv, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    summary_path = ws.report("obligation_summary.yaml")
    summary = _load_yaml(summary_path)
    summary["runtime"] = dict(inv["runtime_summary"])
    summary_path.write_text(
        yaml.safe_dump(summary, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def _key_gap(ws: W.Workspace) -> set[int]:
    return set(ledger.declared()) - set(ledger.load_R(ws)) - set(ledger.load_E(ws))


def precheck(ws: W.Workspace | None = None) -> dict[str, Any]:
    """L3 is valid only after the normal TilingKey partition is closed."""
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
    total = sum(1 for _ in _iter_obligations(inv))
    return {
        "ok": True,
        "reason": "READY",
        "reachable_keys": int(inv.get("reachable_keys") or len(inv.get("keys") or [])),
        "obligations": total,
    }


def _load_extension_decoder(ws: Any | None = None) -> tuple[Any | None, str]:
    """Local Extension tilingdata_decoder — only after generic layout fails."""
    root = None
    try:
        root = Path(getattr(ws, "root", None) or os.environ.get("ASCENDC_PROJECT_ROOT") or "")
        arch = str(os.environ.get("UO_ARCH") or os.environ.get("ASCENDC_ARCH") or "")
        if root.is_dir():
            from ascendc_pilot.local_extension import (
                LocalCapabilityRequired,
                LocalExtensionRegistry,
            )

            reg = LocalExtensionRegistry.from_operator_root(root, arch=arch or None)
            ext = reg.discover("tilingdata_decoder")
            if ext is not None:
                try:
                    return reg.load_module("tilingdata_decoder"), "local_extension"
                except LocalCapabilityRequired as exc:
                    return None, str(exc)
                except Exception as exc:
                    return None, f"LOCAL_CAPABILITY_REQUIRED:interface=tilingdata_decoder:load:{exc}"
    except Exception:
        pass

    # Fixture / package-file fallback for synthetic tests only.
    try:
        from replay.package_data import package_file

        path = package_file("tilingdata_decoder.py")
    except Exception as exc:
        return None, f"LOCAL_CAPABILITY_REQUIRED:interface=tilingdata_decoder:lookup:{exc}"
    if not path.is_file():
        return None, "LOCAL_CAPABILITY_REQUIRED:interface=tilingdata_decoder:missing"
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
        if not callable(getattr(mod, "decode", None)):
            return None, "LOCAL_CAPABILITY_REQUIRED:interface=tilingdata_decoder:no_decode"
        return mod, "package_file"
    except Exception as exc:
        return None, f"decoder_load_failed:{exc}"


def _decode_fields(
    raw: bytes | None,
    dims: dict[str, Any],
    *,
    ws: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """UO layout → generic decoder; LayoutIncomplete → Local Extension."""
    if not raw:
        return {}, {"ok": False, "reason": "td_missing"}

    root = None
    try:
        root = Path(getattr(ws, "root", None) or os.environ.get("ASCENDC_PROJECT_ROOT") or "")
    except Exception:
        root = None

    layout_err = ""
    try:
        from testcase_agent.tilingdata.decoder import LayoutIncomplete, decode as generic_decode
        from testcase_agent.tilingdata.layout import load_tilingdata_layout

        layout = load_tilingdata_layout(root if root and root.is_dir() else None)
        if layout:
            try:
                fields = generic_decode(raw, layout)
                if isinstance(fields, dict) and fields:
                    return dict(fields), {
                        "ok": True,
                        "layout": "generic_uo",
                        "absent_members": [],
                        "present_leaves": list(fields),
                        "owner": {},
                    }
            except LayoutIncomplete as exc:
                layout_err = str(exc)
            except Exception as exc:
                layout_err = f"generic_decode_failed:{exc}"
        else:
            layout_err = "UO_LAYOUT_INCOMPLETE:no_layout"
    except Exception as exc:
        layout_err = f"generic_import_failed:{exc}"

    decoder, decoder_status = _load_extension_decoder(ws)
    if decoder is None:
        return {}, {
            "ok": False,
            "reason": decoder_status or layout_err or "LOCAL_CAPABILITY_REQUIRED:interface=tilingdata_decoder",
            "generic_error": layout_err,
        }
    try:
        doc = decoder.decode(raw, dims)
    except TypeError:
        try:
            doc = decoder.decode(raw)
        except Exception as exc:
            return {}, {
                "ok": False,
                "reason": f"extension_decode_failed:{exc}",
                "decoder": decoder_status,
                "generic_error": layout_err,
            }
    except Exception as exc:
        return {}, {
            "ok": False,
            "reason": f"extension_decode_failed:{exc}",
            "decoder": decoder_status,
            "generic_error": layout_err,
        }
    if not isinstance(doc, dict):
        return {}, {"ok": False, "reason": "decode_not_mapping", "decoder": decoder_status}
    fields = doc.get("fields") if isinstance(doc.get("fields"), dict) else doc
    return dict(fields), {
        "ok": bool(fields),
        "layout": doc.get("layout") or decoder_status,
        "absent_members": list(doc.get("absent_members") or []),
        "present_leaves": list(doc.get("present_leaves") or []),
        "owner": dict(doc.get("owner") or {}),
        "generic_error": layout_err,
    }


def _decoder_context(ws: Any | None, dims: dict[str, Any]) -> dict[str, Any]:
    decoder, _status = _load_extension_decoder(ws)
    if decoder is None or not hasattr(decoder, "eval_context"):
        return {}
    try:
        doc = decoder.eval_context(dims)
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


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


def _fields_for(obligations: Iterable[tuple[str, dict[str, Any]]]) -> list[str]:
    fields: list[str] = []
    for _kind, row in obligations:
        if row.get("field"):
            fields.append(str(row["field"]))
        fields.extend(str(x) for x in (row.get("tilingdata_fields") or []) if x)
    return list(dict.fromkeys(fields))


def build_candidates(
    key: int,
    dims: dict[str, Any],
    obligations: list[tuple[str, dict[str, Any]]],
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
    while len(candidates) < budget and attempts < max(budget * 12, 24):
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


def _eval_td(row: dict[str, Any], env: BO.Env) -> bool | None:
    predicate = str(row.get("predicate") or "").strip()
    field = str(row.get("field") or "").strip()
    if not predicate:
        return field in env.fields
    try:
        return branch_eval.evaluate(predicate, env).value
    except Exception:
        return None


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


def _credit_kernel(
    row: dict[str, Any],
    branch: dict[str, Any] | None,
    env: BO.Env,
    meta: dict[str, Any],
    case_id: str,
) -> None:
    """Credit only an actually observed branch outcome.

    Key-determined exclusions are kept out of the runtime inventory for now:
    the existing certifier intentionally requires every runtime obligation to
    have a witnessed COVERED case. That is stricter than inference and matches
    the user's branch-case generation goal.
    """
    if not branch:
        return
    state, observed, _excluded = BO.state_of(
        branch,
        env,
        absent_members=set(meta.get("absent_members") or []),
        present_leaves=set(meta.get("present_leaves") or env.fields.keys()),
        owner=dict(meta.get("owner") or {}),
    )
    want = bool(row.get("outcome"))
    if want in observed:
        row["status"] = COVERED
        row["evidence"] = {
            "case_id": case_id,
            "kind": "runtime_kernel_branch",
            "state": state,
        }


def run_round(
    ws: W.Workspace | None = None,
    *,
    budget: int = 64,
    seed: int = 0,
    oracle: Any | None = None,
) -> dict[str, Any]:
    """Run one bounded L3 search → replay → evaluate round."""
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
        return {"ok": False, "round_dir": str(rd), "progress": progress, "route_hint": "PROOF_BLOCKED"}

    inv = ensure_inventory(ws)
    open_rows = [item for item in _iter_obligations(inv) if str(item[2].get("status") or UNRESOLVED) not in _TERMINAL]
    open_keys = list(dict.fromkeys(key for key, _kind, _row in open_rows))
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
        (rd / "progress.yaml").write_text(yaml.safe_dump(progress, sort_keys=False), encoding="utf-8")
        return {"ok": True, "round_dir": str(rd), "progress": progress, "route_hint": "GAP_ZERO"}

    per_key = max(2, min(12, int(max(1, budget) ** 0.5) + 1))
    target_keys = open_keys[: max(1, budget // per_key)]
    case_map: dict[str, Any] = {}
    target_of: dict[str, int] = {}
    for pos, key in enumerate(target_keys):
        made = build_candidates(
            key,
            W.decode(key),
            _open_for_key(inv, key),
            ws=ws,
            budget=per_key,
            seed=seed + pos * 997 + idx * 31,
        )
        for i, case in enumerate(made):
            cid = f"b{idx}_k{key}_{i:03d}"
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
        (rd / "progress.yaml").write_text(yaml.safe_dump(progress, sort_keys=False), encoding="utf-8")
        return {"ok": False, "round_dir": str(rd), "progress": progress, "route_hint": "SEARCH_STALLED"}

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
        (rd / "progress.yaml").write_text(yaml.safe_dump(progress, sort_keys=False), encoding="utf-8")
        return {"ok": False, "round_dir": str(rd), "progress": progress, "route_hint": "ORACLE_SUSPECT"}

    log_path = Path(runner.cache) / f"{tag}_log.txt"
    transcript = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
    raw_by_id = _raw_index(transcript)
    branches = KD.load_kernel_branches(ws=ws)
    branch_by_id = {BO.site_id(b): b for b in branches if isinstance(b, dict)}

    before = sum(1 for _k, _kind, row in _iter_obligations(inv) if str(row.get("status")) in _TERMINAL)
    on_key = 0
    decoded_n = 0
    decoder_status = "td_missing"
    evidence_rows: list[dict[str, Any]] = []
    for cid, result in results.items():
        target = target_of.get(cid)
        if target is None:
            continue
        actual = int(result.key or 0)
        if not result.ok or actual != target:
            evidence_rows.append({
                "case_id": cid,
                "target_key": target,
                "actual_key": actual,
                "ok": bool(result.ok),
                "on_key": False,
                "reject": result.reject,
            })
            continue

        on_key += 1
        dims = W.decode(target)
        raw_info = raw_by_id.get(cid) or {}
        decoded, meta = _decode_fields(raw_info.get("td"), dims, ws=ws)
        decoder_status = str(
            meta.get("decoder") or meta.get("layout") or meta.get("reason") or decoder_status
        )
        if meta.get("ok"):
            decoded_n += 1
        fields = dict(decoded)
        for name, value in dict(result.diag or {}).items():
            fields.setdefault(str(name), value)
        ctx = _decoder_context(ws, dims)
        env = BO.build_env(
            fields=fields,
            dims=dims,
            param_to_dim=dict(ctx.get("param_to_dim") or {}),
            enums=dict(ctx.get("enums") or {}),
            block_num=int(raw_info.get("block_num") or 0),
            derived=dict(ctx.get("derived") or {}),
            pins=dict(ctx.get("pins") or {}),
        )
        for kind, row in _open_for_key(inv, target):
            if kind == "TILINGDATA_VALUE_CLASS" and _eval_td(row, env) is True:
                row["status"] = COVERED
                row["evidence"] = {"case_id": cid, "kind": "runtime_tilingdata"}
                field = str(row.get("field") or "")
                if field in env.fields:
                    row["observed_value"] = env.fields[field]
            elif kind == "KERNEL_BRANCH_OUTCOME":
                _credit_kernel(
                    row,
                    branch_by_id.get(str(row.get("branch_id") or "")),
                    env,
                    meta,
                    cid,
                )
        evidence_rows.append({
            "case_id": cid,
            "target_key": target,
            "actual_key": actual,
            "ok": True,
            "on_key": True,
            "decoder_ok": bool(meta.get("ok")),
            "layout": meta.get("layout"),
            "field_count": len(env.fields),
        })

    _save_inventory(ws, inv)
    after = sum(1 for _k, _kind, row in _iter_obligations(inv) if str(row.get("status")) in _TERMINAL)
    runtime_summary = dict(inv.get("runtime_summary") or {})
    new_obligations = max(0, after - before)
    open_after = int(runtime_summary.get("unresolved_count") or 0)
    complete = open_after == 0

    try:
        actual_cases = {
            cid: case_map[cid]
            for cid, result in results.items()
            if cid in target_of and result.ok and int(result.key or 0) == target_of[cid]
        }
        actual_results = {cid: results[cid] for cid in actual_cases}
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
        "reason": "BRANCH_GAP_ZERO" if complete else ("BRANCH_PROGRESS" if new_obligations else "BRANCH_STALLED"),
        "new_R": 0,
        "new_obligations": new_obligations,
        "open_obligations": open_after,
        "target_keys": target_keys,
        "sent": len(case_map),
        "replayed": len(results),
        "on_key": on_key,
        "decoder": decoder_status,
        "decoded": decoded_n,
        "coverage_complete": complete,
        "status_counts": runtime_summary.get("status_counts") or {},
    }
    (rd / "progress.yaml").write_text(
        yaml.safe_dump(progress, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (rd / "evidence.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False, default=str) + "\n" for item in evidence_rows),
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
        "route_hint": "GAP_ZERO" if complete else ("SEARCH_PROGRESS" if new_obligations else "SEARCH_STALLED"),
        "branch_runtime": runtime,
    }


def route(ws: W.Workspace | None = None) -> dict[str, Any]:
    ws = (ws or W.default_workspace()).ensure()
    if not is_branch_mode(ws):
        return {}
    inv = ensure_inventory(ws)
    open_n = sum(
        1
        for _key, _kind, row in _iter_obligations(inv)
        if str(row.get("status") or UNRESOLVED) not in _TERMINAL
    )
    base = ledger.state(ws)
    if open_n == 0:
        return {"reason": "GAP_ZERO", "branch_open": 0, **base}
    recent = [
        _load_yaml(rd / "progress.yaml")
        for rd in sorted(_rounds_dir(ws).glob("round_*"))[-2:]
    ]
    recent = [x for x in recent if x]
    if recent and int(recent[-1].get("new_obligations") or 0) > 0:
        return {"reason": "SEARCH_PROGRESS", "branch_open": open_n, **base}
    if len(recent) >= 2 and all(int(x.get("new_obligations") or 0) == 0 for x in recent[-2:]):
        return {"reason": "SEARCH_STALLED", "branch_open": open_n, **base}
    return {"reason": "SEARCH_PROGRESS", "branch_open": open_n, **base}


def certification_summary(ws: W.Workspace | None = None) -> dict[str, Any]:
    ws = (ws or W.default_workspace()).ensure()
    inv = ensure_inventory(ws)
    open_n = sum(
        1
        for _key, _kind, row in _iter_obligations(inv)
        if str(row.get("status") or UNRESOLVED) not in _TERMINAL
    )
    return {
        "schema": _SCHEMA,
        "ok": open_n == 0,
        "open_obligations": open_n,
        "coverage_complete": open_n == 0,
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
