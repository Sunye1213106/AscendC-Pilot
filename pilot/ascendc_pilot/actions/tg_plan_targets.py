"""Plan-scoped TilingKey closure for the default TG workflow.

The kernel declaration remains the global domain ``D``. ``tg-plan`` freezes an
approved target set ``T ⊆ D`` and ``tg-solve`` closes exactly ``T``. When the
user does not select targets, ``T = D``.

This module deliberately reuses the proven closure/replay implementation. It
only supplies the missing plan boundary; it does not introduce a second solver
or derive 19-dimensional closed-form key predicates.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

import yaml


def _hash_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return value if isinstance(value, dict) else {}


def _dump(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _parse_keys(raw: Any) -> list[int]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, (list, tuple, set)):
        values = list(raw)
    else:
        text = str(raw).replace(";", ",").replace("\n", ",")
        values = [part.strip() for part in text.split(",") if part.strip()]
    out: list[int] = []
    for value in values:
        try:
            key = int(str(value).strip(), 0)
        except (TypeError, ValueError):
            continue
        if key not in out:
            out.append(key)
    return out


def _parse_dimensions(raw: Any) -> dict[str, list[str]]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, list[str]] = {}
    for name, values in raw.items():
        if isinstance(values, (list, tuple, set)):
            vals = [str(v) for v in values]
        else:
            vals = [str(values)]
        vals = [v for v in vals if v != ""]
        if vals:
            out[str(name)] = vals
    return out


def _selection(ctx: dict[str, Any], intent: dict[str, Any]) -> dict[str, Any]:
    keys = _parse_keys(
        ctx.get("target_keys")
        or ctx.get("tiling_keys")
        or intent.get("target_keys")
        or intent.get("tiling_keys")
    )
    dimensions = _parse_dimensions(
        ctx.get("target_dimensions")
        or ctx.get("dimension_filter")
        or intent.get("target_dimensions")
        or intent.get("dimension_filter")
    )
    requested = str(ctx.get("target_mode") or intent.get("target_mode") or "").strip()
    intent_mode = str(intent.get("mode") or "").strip()
    if keys:
        mode = "explicit_keys"
    elif dimensions:
        mode = "dimension_filter"
    elif requested in {"explicit_keys", "dimension_filter", "all_declared", "scenario_set"}:
        mode = requested
    elif intent_mode == "scenario_targeted":
        mode = "scenario_set"
    else:
        mode = "all_declared"
    return {"target_mode": mode, "target_keys": keys, "target_dimensions": dimensions}


def _plan_dir(project_root: Path, level: str) -> Path:
    from ascendc_pilot.paths import tg_root

    return tg_root(project_root) / "plan" / "levels" / (level or "L0")


def _current_level(project_root: Path, ctx: dict[str, Any]) -> str:
    from ascendc_pilot.actions import engines as E

    return str(E._resolve_tg_ctx(project_root, ctx).get("level") or "L0")


def _global_declared(project_root: Path) -> set[int]:
    """Read the real declared key domain without leaking CLI-style SystemExit.

    Replay/workspace is also used by standalone scripts and historically raises
    ``SystemExit`` when its operator/schema cannot be located. Pilot engines must
    return a structured failure instead of terminating the caller process.
    """
    from testcase_agent.closure import workspace as W

    try:
        return set(W.declared())
    except SystemExit as exc:
        message = str(exc).strip() or "declared TilingKey source unavailable"
        raise RuntimeError(message) from None


def _uo_identity(project_root: Path, *, op_name: str, architecture: str) -> dict[str, Any]:
    from uo_init.store.reader import find_uo_product, read_meta

    product = find_uo_product(project_root, op_name=op_name, architecture=architecture)
    if product is None or product.suffix != ".uo":
        raise FileNotFoundError("missing .uo CodeMap; run uo-init first")
    digest = hashlib.sha256(product.read_bytes()).hexdigest()
    meta = read_meta(product)
    return {
        "path": product.as_posix(),
        "sha256": digest,
        "schema": str(meta.get("schema") or ""),
        "op_name": str(meta.get("op_name") or op_name),
        "architecture": str(meta.get("architecture") or architecture),
    }


def _select_targets(declared: set[int], selection: dict[str, Any]) -> tuple[set[int], list[str]]:
    from testcase_agent.closure import workspace as W

    errors: list[str] = []
    mode = str(selection.get("target_mode") or "all_declared")
    if mode == "explicit_keys":
        selected = set(_parse_keys(selection.get("target_keys")))
        outside = sorted(selected - declared)
        if outside:
            errors.append(f"TARGET_NOT_DECLARED:{outside[:20]}")
        return selected & declared, errors
    if mode == "dimension_filter":
        filt = _parse_dimensions(selection.get("target_dimensions"))
        known = set(W.dim_names())
        unknown = sorted(set(filt) - known)
        if unknown:
            errors.append(f"UNKNOWN_TILINGKEY_DIM:{unknown}")
            return set(), errors
        selected: set[int] = set()
        for key in declared:
            try:
                inst = W.decode(key)
            except Exception:
                continue
            if all(str(inst.get(name)) in allowed for name, allowed in filt.items()):
                selected.add(key)
        return selected, errors
    if mode == "scenario_set":
        errors.append("SCENARIO_SET_IS_NOT_DECLARED_KEYS")
        return set(), errors
    return set(declared), errors


def plan_intent(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Persist target intent. Absence of an explicit selector means all D."""
    from ascendc_pilot.actions import engines as E

    result = E._run_tg_plan_intent(project_root, ctx)
    if not result.get("ok"):
        return result
    tg_ctx = E._resolve_tg_ctx(project_root, ctx)
    tg = E._tg(project_root)
    path = tg / "plan" / "plan_intent.yaml"
    doc = _load(path)
    doc.update(_selection(ctx, doc))
    doc["mode"] = str(doc.get("mode") or tg_ctx.get("mode") or "tilingkey_full_coverage")
    if doc["mode"] == "scenario_targeted":
        doc["target_mode"] = "scenario_set"
        doc["forbid_cartesian_over_declared"] = True
        doc["do_not_widen_to_declared_set"] = True
        if not (doc.get("scenarios") or []):
            return {
                "ok": False,
                "engine": "plan_intent",
                "error": "SCENARIO_SET_EMPTY",
                "reason_code": "SCENARIO_SET_EMPTY",
                "message_zh": "scenario_targeted 禁止在缺 ScenarioSet 时把 T 扩成 D。",
            }
    doc["scope_policy"] = "freeze_targets_in_plan_build"
    _dump(path, doc)
    return {**result, **doc, "artifact": path.as_posix()}


def plan_build(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Freeze the exact target set T and write the only solve obligations."""
    from ascendc_pilot.actions import engines as E

    tg_ctx = E._resolve_tg_ctx(project_root, ctx)
    if not E._is_tilingkey_full(tg_ctx):
        return E._run_tg_plan_build(project_root, ctx)
    op_name = str(tg_ctx.get("op_name") or "")
    arch = str(tg_ctx.get("architecture") or "").strip()
    if not arch:
        return {
            "ok": False,
            "engine": "plan_build",
            "error": "ARCHITECTURE_MISSING_IN_RUN_STATE",
            "reason_code": "ARCHITECTURE_MISSING_IN_RUN_STATE",
        }
    if not op_name:
        return {"ok": False, "engine": "plan_build", "error": "op_name required"}

    try:
        declared = _global_declared(project_root)
        if not declared:
            return {"ok": False, "engine": "plan_build", "error": "DECLARED_SET_EMPTY"}
        uo = _uo_identity(project_root, op_name=op_name, architecture=arch)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "plan_build", "error": str(exc)[:400]}

    tg = E._tg(project_root)
    level = str(tg_ctx.get("level") or "L0")
    intent = _load(tg / "plan" / "plan_intent.yaml")
    selection = _selection(ctx, intent)
    targets, errors = _select_targets(declared, selection)
    if not targets:
        errors.append("TARGET_SET_EMPTY")
    if errors:
        return {"ok": False, "engine": "plan_build", "errors": errors, "target_mode": selection["target_mode"]}

    declared_hash = _hash_json(sorted(declared))
    target_hash = _hash_json(sorted(targets))
    snapshot_hash = _hash_json({"uo_sha256": uo["sha256"], "declared_hash": declared_hash, "architecture": arch})
    target_doc = {
        "schema": "tg-target-set/v1",
        "mode": "tilingkey_full_coverage",
        "target_mode": selection["target_mode"],
        "selector": {"keys": selection.get("target_keys") or [], "dimensions": selection.get("target_dimensions") or {}},
        "keys": sorted(targets),
        "count": len(targets),
        "target_hash": target_hash,
        "declared_count": len(declared),
        "declared_hash": declared_hash,
        "uo": uo,
        "snapshot_hash": snapshot_hash,
        "scope_rule": "tg-solve must not widen beyond these keys",
    }
    plan_hash = _hash_json({"snapshot_hash": snapshot_hash, "target_hash": target_hash, "mode": target_doc["target_mode"]})
    target_doc["plan_hash"] = plan_hash

    plan_dir = _plan_dir(project_root, level)
    target_path = plan_dir / "target_set.yaml"
    _dump(target_path, target_doc)
    obligations = {
        "schema": "coverage-obligations/v3",
        "version": 3,
        "mode": "tilingkey_full_coverage",
        "snapshot_hash": snapshot_hash,
        "plan_hash": plan_hash,
        "target_set": {
            "path": "target_set.yaml",
            "count": len(targets),
            "declared_count": len(declared),
            "target_hash": target_hash,
            "defaulted_to_all_declared": selection["target_mode"] == "all_declared",
        },
        "obligations": [
            {"id": "CLOSE_TARGET_SET", "kind": "set_closure", "invariant": "T = (R ∩ T) ∪ E"},
            {"id": "EXCLUSION_SOUNDNESS", "kind": "proof_policy", "invariant": "R ∩ E = ∅"},
            {"id": "WITNESS_PROVENANCE", "kind": "provenance", "invariant": "R grows only from real Host replay"},
            {"id": "EXCLUSION_PROVENANCE", "kind": "provenance", "invariant": "E grows only from reviewed source-backed lemmas"},
        ],
        "solver_policy": "construct/replay first; no global 19-dimension SAT derivation",
    }
    obligation_path = plan_dir / "coverage_obligations.yaml"
    _dump(obligation_path, obligations)
    # plan-build-v1 contract also requires tg/plan/coverage_obligations.yaml
    from ascendc_pilot.paths import tg_root

    root_obligation_path = tg_root(project_root) / "plan" / "coverage_obligations.yaml"
    _dump(root_obligation_path, obligations)
    unresolved = {
        "schema": "tg-unresolved/v1",
        "status": "ready_for_manual_review",
        "allow_solve": True,
        "allow_solve_reason": "tilingkey_full_coverage T=D approved for closure",
        "blocking_hard_obligations": [],
        "contract_gaps": [],
        "snapshot_hash": snapshot_hash,
        "plan_hash": plan_hash,
    }
    _dump(plan_dir / "unresolved.yaml", unresolved)
    return {
        "ok": True,
        "engine": "plan_build",
        "mode": "tilingkey_full_coverage",
        "artifact": obligation_path.as_posix(),
        "target_set": target_path.as_posix(),
        "target_mode": selection["target_mode"],
        "target_count": len(targets),
        "declared_count": len(declared),
        "plan_hash": plan_hash,
        "snapshot_hash": snapshot_hash,
    }


def _target_doc(project_root: Path, ctx: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    level = _current_level(project_root, ctx)
    path = _plan_dir(project_root, level) / "target_set.yaml"
    return path, _load(path)


def solve_precheck(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
    """Fail closed if the approved target set or UO/kernel snapshot changed."""
    from ascendc_pilot.actions import engines as E

    tg_ctx = E._resolve_tg_ctx(project_root, ctx)
    if not E._is_tilingkey_full(tg_ctx):
        return E._run_tg_solve_precheck(project_root, ctx)
    target_path, target = _target_doc(project_root, ctx)
    if not target:
        return {"ok": False, "engine": "solve_precheck", "error": "TARGET_SET_MISSING"}
    level = _current_level(project_root, ctx)
    supplement = _load(_plan_dir(project_root, level) / "human_supplement.yaml")
    if not supplement.get("approved") or not supplement.get("allow_solve"):
        return {"ok": False, "engine": "solve_precheck", "error": "PLAN_NOT_APPROVED"}

    try:
        declared = _global_declared(project_root)
        keys = set(_parse_keys(target.get("keys")))
        if not keys or not keys <= declared:
            return {
                "ok": False,
                "engine": "solve_precheck",
                "error": "TARGET_SET_STALE_OR_OUTSIDE_DECLARED",
                "outside": sorted(keys - declared)[:20],
            }
        arch = str(tg_ctx.get("architecture") or "").strip()
        if not arch:
            return {
                "ok": False,
                "engine": "solve_precheck",
                "error": "ARCHITECTURE_MISSING_IN_RUN_STATE",
                "reason_code": "ARCHITECTURE_MISSING_IN_RUN_STATE",
            }
        uo = _uo_identity(project_root, op_name=str(tg_ctx.get("op_name") or ""), architecture=arch)
        snapshot_hash = _hash_json(
            {
                "uo_sha256": uo["sha256"],
                "declared_hash": _hash_json(sorted(declared)),
                "architecture": arch,
            }
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "engine": "solve_precheck", "error": str(exc)[:400]}

    problems: list[str] = []
    if _hash_json(sorted(keys)) != str(target.get("target_hash") or ""):
        problems.append("TARGET_HASH_MISMATCH")
    if snapshot_hash != str(target.get("snapshot_hash") or ""):
        problems.append("UO_OR_DECLARED_SNAPSHOT_CHANGED")
    if str(supplement.get("approved_plan_hash") or "") != str(target.get("plan_hash") or ""):
        problems.append("APPROVED_PLAN_HASH_MISMATCH")
    return {
        "ok": not problems,
        "engine": "solve_precheck",
        "mode": "tilingkey_full_coverage",
        "target_set": target_path.as_posix(),
        "target_count": len(keys),
        "declared_count": len(declared),
        "problems": problems,
        **({"error": problems[0]} if problems else {}),
    }


@contextmanager
def _activate_target_scope(project_root: Path, ctx: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Temporarily present the approved T as closure's D without changing R."""
    from testcase_agent.closure import ledger
    from testcase_agent.closure import workspace as W

    path, target = _target_doc(project_root, ctx)
    global_declared = _global_declared(project_root)
    keys = set(_parse_keys(target.get("keys"))) if target else set(global_declared)
    if not keys:
        keys = set(global_declared)
    if not keys <= global_declared:
        raise ValueError("target set is not a subset of current declared domain")
    original_w_declared = W.declared
    original_l_declared = ledger.declared
    W.declared = lambda: frozenset(keys)  # type: ignore[assignment]
    ledger.declared = lambda: set(keys)  # type: ignore[assignment]
    try:
        yield {
            "target_path": path.as_posix(),
            "target_count": len(keys),
            "declared_count": len(global_declared),
            "targets": keys,
            "global_declared": global_declared,
        }
    finally:
        W.declared = original_w_declared  # type: ignore[assignment]
        ledger.declared = original_l_declared  # type: ignore[assignment]


def _scoped(base: Callable[[Path, dict[str, Any]], dict[str, Any]], *, certify: bool = False) -> Callable[[Path, dict[str, Any]], dict[str, Any]]:
    def run(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
        try:
            with _activate_target_scope(project_root, ctx) as scope:
                result = base(project_root, ctx)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "engine": getattr(base, "__name__", "tg_solve"), "error": str(exc)[:400]}
        result = dict(result or {})
        result.setdefault("target_count", scope["target_count"])
        result.setdefault("declared_count", scope["declared_count"])
        result["target_set"] = scope["target_path"]
        if certify:
            try:
                from testcase_agent.closure import ledger, report, workspace as W

                ws = W.default_workspace(project_root).ensure()
                R = ledger.load_R(ws)
                true_undeclared = R - set(scope["global_declared"])
                out_of_scope = (R & set(scope["global_declared"])) - set(scope["targets"])
                report.write_undeclared(ws, true_undeclared)
                result["undeclared"] = len(true_undeclared)
                result["out_of_scope_declared_witnesses"] = len(out_of_scope)
                nested = result.get("report")
                if isinstance(nested, dict):
                    nested["undeclared"] = len(true_undeclared)
                    nested["out_of_scope_declared_witnesses"] = len(out_of_scope)
                cert_path = ws.state / "certificate.yaml"
                cert = _load(cert_path)
                if cert:
                    cert.setdefault("report", {})["undeclared"] = len(true_undeclared)
                    cert["report"]["out_of_scope_declared_witnesses"] = len(out_of_scope)
                    cert["target_scope"] = {
                        "target_count": scope["target_count"],
                        "declared_count": scope["declared_count"],
                        "out_of_scope_declared_witnesses": len(out_of_scope),
                    }
                    _dump(cert_path, cert)
            except Exception:
                pass
        return result

    return run


def install(registry: dict[tuple[str, str], Callable[..., dict[str, Any]]]) -> None:
    """Install plan-target semantics into the existing TG action registry."""
    if getattr(install, "_installed", False):
        return
    registry[("tg-plan", "plan_intent")] = plan_intent
    registry[("tg-plan", "plan_build")] = plan_build
    registry[("tg-solve", "solve_precheck")] = solve_precheck
    for action_id in (
        "closure_ledger",
        "closure_search",
        "closure_residual",
        "closure_construct",
        "closure_explain",
        "lemma_leads",
        "lemma_evidence",
        "lemma_mine",
        "lemma_verify",
        "lemma_review",
        "lemma_apply",
        "lemma_loop",
        "closure_audit",
        "closure_certify",
    ):
        key = ("tg-solve", action_id)
        base = registry.get(key)
        if base is not None:
            registry[key] = _scoped(base, certify=action_id == "closure_certify")
    setattr(install, "_installed", True)
