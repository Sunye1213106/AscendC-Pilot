"""Deterministic TG fast paths.

The cache is content-addressed and fail-closed: a plan may reuse the existing CSV
contract only when the snapshot, consumer files, domain hints, and binding lexicon
match the receipt written by a successful contract build.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

EngineFallback = Callable[..., dict[str, Any]]
_TEXT_EXTENSIONS = frozenset({".py", ".md", ".markdown", ".yaml", ".yml", ".json", ".txt"})
_MAX_SCAN_FILES = 64
_MAX_FILE_BYTES = 256 * 1024


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        import yaml

        loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
        value = yaml.load(path.read_text(encoding="utf-8"), Loader=loader) or {}
        return value if isinstance(value, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _write_yaml_if_changed(path: Path, payload: dict[str, Any]) -> bool:
    try:
        from testcase_agent.io import write_yaml

        import yaml

        dumper = getattr(yaml, "CSafeDumper", yaml.SafeDumper)
        rendered = yaml.dump(payload, Dumper=dumper, allow_unicode=True, sort_keys=False)
        if path.is_file() and path.read_text(encoding="utf-8") == rendered:
            return False
        write_yaml(path, payload)
        return True
    except Exception:  # noqa: BLE001
        import yaml

        dumper = getattr(yaml, "CSafeDumper", yaml.SafeDumper)
        rendered = yaml.dump(payload, Dumper=dumper, allow_unicode=True, sort_keys=False)
        if path.is_file():
            try:
                if path.read_text(encoding="utf-8") == rendered:
                    return False
            except OSError:
                pass
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
        return True


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _resolve_consumer_root(project_root: Path, ctx: dict[str, Any]) -> Path | None:
    candidates = [
        ctx.get("csv_consumer_root"),
        ctx.get("test_script_root"),
    ]
    for rel in (
        Path(".ascendc-pilot/context/pilot_params.yaml"),
        Path(".ascendc-pilot/tg/init/run_context.yaml"),
    ):
        doc = _read_yaml(project_root / rel)
        candidates.extend([doc.get("csv_consumer_root"), doc.get("test_script_root")])
    for raw in candidates:
        text = str(raw or "").strip()
        if not text:
            continue
        path = Path(text).expanduser().resolve()
        if path.is_dir():
            return path
    return None


def _consumer_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for path in sorted(root.rglob("*")):
        if len(out) >= _MAX_SCAN_FILES:
            break
        if not path.is_file() or path.suffix.lower() not in _TEXT_EXTENSIONS:
            continue
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        out.append(path)
    return out


def _contract_fingerprint(project_root: Path, consumer: Path) -> tuple[str, dict[str, Any]]:
    tg = project_root / ".ascendc-pilot" / "tg"
    snapshot = tg / "snapshot" / "understand_contract.json"
    watched = [
        tg / "realization" / "domain_hints.yaml",
        tg / "realization" / "binding_lexicon.yaml",
        tg / "realization" / "lexicon.yaml",
        tg / "plan" / "human_supplement.yaml",
    ]
    rows: list[dict[str, Any]] = []
    if snapshot.is_file():
        rows.append({"path": "snapshot/understand_contract.json", "sha256": _hash_file(snapshot)})
    else:
        rows.append({"path": "snapshot/understand_contract.json", "sha256": "missing"})
    for path in watched:
        rel = path.relative_to(tg).as_posix()
        rows.append({"path": rel, "sha256": _hash_file(path) if path.is_file() else "missing"})
    for path in _consumer_files(consumer):
        rows.append(
            {
                "path": f"consumer:{path.relative_to(consumer).as_posix()}",
                "sha256": _hash_file(path),
                "size": int(path.stat().st_size),
            }
        )
    payload = {
        "version": 1,
        "consumer_root": consumer.as_posix(),
        "inputs": rows,
        "contract_schema": "tg-contract-fastpath-v1",
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest(), payload


def _required_artifacts(project_root: Path) -> list[Path]:
    tg = project_root / ".ascendc-pilot" / "tg"
    return [
        tg / "snapshot" / "understand_contract.json",
        tg / "realization" / "consumer_evidence.yaml",
        tg / "realization" / "consumer_schema.yaml",
        tg / "realization" / "realization_map.yaml",
        tg / "realization" / "binding_inventory.yaml",
        tg / "realization" / "domain_review.yaml",
        tg / "contract" / "testcase.yaml",
    ]


def _receipt_path(project_root: Path) -> Path:
    return project_root / ".ascendc-pilot" / "tg" / "realization" / "contract_fastpath.yaml"


def _artifact_hashes(project_root: Path) -> dict[str, str]:
    tg = project_root / ".ascendc-pilot" / "tg"
    out: dict[str, str] = {}
    for path in _required_artifacts(project_root):
        try:
            rel = path.relative_to(tg).as_posix()
        except ValueError:
            rel = path.as_posix()
        out[rel] = _hash_file(path) if path.is_file() else "missing"
    return out


def _cache_valid(project_root: Path, consumer: Path) -> tuple[bool, str, dict[str, Any]]:
    if any(not path.is_file() or path.stat().st_size == 0 for path in _required_artifacts(project_root)):
        return False, "", {}
    fingerprint, inputs = _contract_fingerprint(project_root, consumer)
    receipt = _read_yaml(_receipt_path(project_root))
    valid = (
        receipt.get("status") == "complete"
        and receipt.get("fingerprint") == fingerprint
        and receipt.get("consumer_root") == consumer.as_posix()
        and receipt.get("artifact_hashes") == _artifact_hashes(project_root)
    )
    return bool(valid), fingerprint, inputs


def _write_receipt(project_root: Path, consumer: Path, *, status: str = "complete") -> dict[str, Any]:
    fingerprint, inputs = _contract_fingerprint(project_root, consumer)
    payload = {
        "version": 1,
        "status": status,
        "fingerprint": fingerprint,
        "consumer_root": consumer.as_posix(),
        "inputs": inputs,
        "required_artifacts": [p.as_posix() for p in _required_artifacts(project_root)],
        "artifact_hashes": _artifact_hashes(project_root),
    }
    _write_yaml_if_changed(_receipt_path(project_root), payload)
    return payload


def _cached_contract_payload(project_root: Path) -> dict[str, Any]:
    tg = project_root / ".ascendc-pilot" / "tg"
    report = _read_yaml(tg / "realization" / "realization_report.yaml")
    inventory = _read_yaml(tg / "realization" / "binding_inventory.yaml")
    domain = _read_yaml(tg / "realization" / "domain_review.yaml")
    return {
        "status": "ok",
        "cache_hit": True,
        "contract_rebuilt": False,
        "validation": report,
        "binding_gaps": inventory.get("binding_gaps") or [],
        "domain_review_status": domain.get("status"),
    }


def _fast_contract_build(
    project_root: Path,
    workflow_id: str,
    action_id: str,
    ctx: dict[str, Any],
    *,
    fallback: EngineFallback,
) -> dict[str, Any]:
    consumer = _resolve_consumer_root(project_root, ctx)
    if consumer is None:
        return fallback(project_root, workflow_id, action_id, ctx=ctx)
    t0 = time.perf_counter()
    valid, fingerprint, _inputs = _cache_valid(project_root, consumer)
    if valid:
        return {
            "ok": True,
            "engine": "contract_build",
            "fast_path": "contract_fingerprint_reuse",
            "cache_hit": True,
            "contract_rebuilt": False,
            "csv_consumer_root": consumer.as_posix(),
            "fingerprint": fingerprint,
            "payload": _cached_contract_payload(project_root),
            "timing_ms": {"total": int((time.perf_counter() - t0) * 1000)},
        }
    result = fallback(project_root, workflow_id, action_id, ctx=ctx)
    if isinstance(result, dict) and result.get("ok"):
        receipt = _write_receipt(project_root, consumer)
        result = dict(result)
        result["cache_hit"] = False
        result["contract_rebuilt"] = True
        result["contract_fingerprint"] = receipt.get("fingerprint")
    return result


@contextmanager
def _reuse_contract_during_plan(project_root: Path, consumer: Path) -> Iterator[bool]:
    valid, _fingerprint, _inputs = _cache_valid(project_root, consumer)
    if not valid:
        yield False
        return
    try:
        import testcase_agent.planner as planner
    except ImportError:
        yield False
        return
    original = planner.tg_contract

    def cached_contract(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return _cached_contract_payload(project_root)

    planner.tg_contract = cached_contract
    try:
        yield True
    finally:
        planner.tg_contract = original


def _fast_plan_build(
    project_root: Path,
    workflow_id: str,
    action_id: str,
    ctx: dict[str, Any],
    *,
    fallback: EngineFallback,
) -> dict[str, Any]:
    consumer = _resolve_consumer_root(project_root, ctx)
    if consumer is None:
        return fallback(project_root, workflow_id, action_id, ctx=ctx)
    with _reuse_contract_during_plan(project_root, consumer) as reused:
        result = fallback(project_root, workflow_id, action_id, ctx=ctx)
    if isinstance(result, dict) and reused:
        result = dict(result)
        result["contract_cache_hit"] = True
        result["contract_rebuilt"] = False
    return result


@contextmanager
def _parallel_z3_defaults() -> Iterator[int]:
    """Use bounded independent fallback workers with fixed Z3 seeds.

    The optimized batch solver remains unchanged. ``jobs`` only affects independent
    fallback obligations, whose final results are reassembled by obligation id.
    """

    try:
        import testcase_agent.solve as solve_mod
    except ImportError:
        yield 1
        return
    jobs = max(1, min(4, int(os.environ.get("ASCENDC_TG_SOLVER_JOBS", "0") or 0) or (os.cpu_count() or 1)))
    original = solve_mod.tg_solve

    def wrapped(*args: Any, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("jobs", jobs)
        try:
            import z3

            z3.set_param("smt.random_seed", 0)
            z3.set_param("sat.random_seed", 0)
        except Exception:  # noqa: BLE001
            pass
        out = original(*args, **kwargs)
        if isinstance(out, dict):
            out["solver_jobs"] = jobs
            out["solver_seed"] = 0
        return out

    solve_mod.tg_solve = wrapped
    try:
        yield jobs
    finally:
        solve_mod.tg_solve = original


def _fast_z3_solve(
    project_root: Path,
    workflow_id: str,
    action_id: str,
    ctx: dict[str, Any],
    *,
    fallback: EngineFallback,
) -> dict[str, Any]:
    with _parallel_z3_defaults() as jobs:
        result = fallback(project_root, workflow_id, action_id, ctx=ctx)
    if isinstance(result, dict):
        result = dict(result)
        result["solver_jobs"] = jobs
        result["solver_seed"] = 0
    return result


def invoke_fast_tg_engine(
    project_root: Path,
    workflow_id: str,
    action_id: str,
    *,
    ctx: dict[str, Any] | None,
    fallback: EngineFallback,
) -> dict[str, Any]:
    payload = dict(ctx or {})
    if workflow_id == "tg-init" and action_id == "contract_build":
        return _fast_contract_build(Path(project_root), workflow_id, action_id, payload, fallback=fallback)
    if workflow_id == "tg-plan" and action_id == "plan_build":
        return _fast_plan_build(Path(project_root), workflow_id, action_id, payload, fallback=fallback)
    if workflow_id == "tg-solve" and action_id == "z3_solve":
        return _fast_z3_solve(Path(project_root), workflow_id, action_id, payload, fallback=fallback)
    return fallback(project_root, workflow_id, action_id, ctx=payload)
