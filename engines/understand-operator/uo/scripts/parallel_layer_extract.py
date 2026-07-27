"""Deterministic parallel host/kernel extraction helpers."""

from __future__ import annotations

import os
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any


def parallel_enabled(*, explicit: bool | None = None) -> bool:
    if explicit is not None:
        return bool(explicit)
    return os.environ.get("UO_PARALLEL_EXTRACT", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _host_worker(args: tuple[str, str, str, bool]) -> dict[str, Any]:
    repo_root_s, op_name, architecture, allow_empty_plan = args
    import sys
    import time as _time

    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from uo.scripts.extract_host_subgraph import extract_host_subgraph

    t0 = _time.perf_counter()
    payload = extract_host_subgraph(
        Path(repo_root_s),
        op_name,
        architecture=architecture,
        allow_empty_plan=allow_empty_plan,
    )
    payload = dict(payload)
    payload["_worker_ms"] = int((_time.perf_counter() - t0) * 1000)
    return payload


def _kernel_worker(args: tuple[str, str, str]) -> dict[str, Any]:
    repo_root_s, op_name, architecture = args
    import sys
    import time as _time

    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from uo.scripts.extract_kernel_subgraph import extract_kernel_subgraph

    t0 = _time.perf_counter()
    # Avoid nested ProcessPool: outer host/kernel pool already uses a worker process.
    payload = extract_kernel_subgraph(
        Path(repo_root_s),
        op_name,
        architecture=architecture,
        file_parallel=False,
    )
    payload = dict(payload)
    payload["_worker_ms"] = int((_time.perf_counter() - t0) * 1000)
    return payload


def extract_host_kernel_parallel(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
    allow_empty_plan: bool = False,
    parallel: bool | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Run host and kernel extraction; parallel when enabled and both are needed.

    Returns (host, kernel, timing) where timing includes parallel metadata.
    """
    timing: dict[str, Any] = {
        "parallel": {"enabled": False, "used": False, "fallback": False, "fallback_reason": "", "wall_ms": 0},
        "host": {"worker_ms": 0},
        "kernel": {"worker_ms": 0},
    }
    if not parallel_enabled(explicit=parallel):
        t0 = time.perf_counter()
        from uo.scripts.extract_host_subgraph import extract_host_subgraph

        host = extract_host_subgraph(
            repo_root,
            op_name,
            architecture=architecture,
            allow_empty_plan=allow_empty_plan,
        )
        host_ms = int((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        from uo.scripts.extract_kernel_subgraph import extract_kernel_subgraph

        kernel = extract_kernel_subgraph(repo_root, op_name, architecture=architecture)
        kernel_ms = int((time.perf_counter() - t0) * 1000)
        timing["host"]["worker_ms"] = host_ms
        timing["kernel"]["worker_ms"] = kernel_ms
        timing["host_ms"] = host_ms
        timing["kernel_ms"] = kernel_ms
        timing["host"] = host_ms  # back-compat int for build_layered_kb.update
        # Keep both shapes: ints for timing_ms merge + nested detail
        return host, kernel, {
            "host": host_ms,
            "kernel": kernel_ms,
            "parallel_enabled": False,
            "parallel_used": False,
            "parallel_fallback": False,
            "parallel_fallback_reason": "",
            "host_kernel_wall_ms": host_ms + kernel_ms,
        }

    wall0 = time.perf_counter()
    repo_s = str(repo_root.resolve())
    host_args = (repo_s, op_name, architecture, allow_empty_plan)
    kernel_args = (repo_s, op_name, architecture)
    fallback = False
    reason = ""
    try:
        with ProcessPoolExecutor(max_workers=2) as pool:
            host_future = pool.submit(_host_worker, host_args)
            kernel_future = pool.submit(_kernel_worker, kernel_args)
            host = host_future.result()
            kernel = kernel_future.result()
        host_ms = int(host.pop("_worker_ms", 0) or 0)
        kernel_ms = int(kernel.pop("_worker_ms", 0) or 0)
    except Exception as exc:  # noqa: BLE001
        fallback = True
        reason = f"{type(exc).__name__}: {exc}"[:300]
        from uo.scripts.extract_host_subgraph import extract_host_subgraph
        from uo.scripts.extract_kernel_subgraph import extract_kernel_subgraph

        t0 = time.perf_counter()
        host = extract_host_subgraph(
            repo_root,
            op_name,
            architecture=architecture,
            allow_empty_plan=allow_empty_plan,
        )
        host_ms = int((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        kernel = extract_kernel_subgraph(repo_root, op_name, architecture=architecture)
        kernel_ms = int((time.perf_counter() - t0) * 1000)

    wall_ms = int((time.perf_counter() - wall0) * 1000)
    return host, kernel, {
        "host": host_ms,
        "kernel": kernel_ms,
        "host_kernel_parallel": wall_ms,
        "parallel_enabled": True,
        "parallel_used": not fallback,
        "parallel_fallback": fallback,
        "parallel_fallback_reason": reason,
        "host_kernel_wall_ms": wall_ms,
    }
