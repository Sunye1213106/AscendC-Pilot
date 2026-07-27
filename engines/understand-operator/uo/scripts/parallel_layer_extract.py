"""Deterministic parallel host/kernel extraction helpers."""

from __future__ import annotations

import os
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

    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from uo.scripts.extract_host_subgraph import extract_host_subgraph

    return extract_host_subgraph(
        Path(repo_root_s),
        op_name,
        architecture=architecture,
        allow_empty_plan=allow_empty_plan,
    )


def _kernel_worker(args: tuple[str, str, str]) -> dict[str, Any]:
    repo_root_s, op_name, architecture = args
    import sys

    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from uo.scripts.extract_kernel_subgraph import extract_kernel_subgraph

    return extract_kernel_subgraph(Path(repo_root_s), op_name, architecture=architecture)


def extract_host_kernel_parallel(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
    allow_empty_plan: bool = False,
    parallel: bool | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, int]]:
    """Run host and kernel extraction; parallel when enabled and both are needed."""
    timing_ms: dict[str, int] = {}
    if not parallel_enabled(explicit=parallel):
        import time

        t0 = time.perf_counter()
        from uo.scripts.extract_host_subgraph import extract_host_subgraph

        host = extract_host_subgraph(
            repo_root,
            op_name,
            architecture=architecture,
            allow_empty_plan=allow_empty_plan,
        )
        timing_ms["host"] = int((time.perf_counter() - t0) * 1000)
        t0 = time.perf_counter()
        from uo.scripts.extract_kernel_subgraph import extract_kernel_subgraph

        kernel = extract_kernel_subgraph(repo_root, op_name, architecture=architecture)
        timing_ms["kernel"] = int((time.perf_counter() - t0) * 1000)
        return host, kernel, timing_ms

    import time

    t0 = time.perf_counter()
    repo_s = str(repo_root.resolve())
    host_args = (repo_s, op_name, architecture, allow_empty_plan)
    kernel_args = (repo_s, op_name, architecture)
    try:
        with ProcessPoolExecutor(max_workers=2) as pool:
            host_future = pool.submit(_host_worker, host_args)
            kernel_future = pool.submit(_kernel_worker, kernel_args)
            host = host_future.result()
            kernel = kernel_future.result()
    except Exception:  # noqa: BLE001
        from uo.scripts.extract_host_subgraph import extract_host_subgraph
        from uo.scripts.extract_kernel_subgraph import extract_kernel_subgraph

        host = extract_host_subgraph(
            repo_root,
            op_name,
            architecture=architecture,
            allow_empty_plan=allow_empty_plan,
        )
        kernel = extract_kernel_subgraph(repo_root, op_name, architecture=architecture)
    elapsed = int((time.perf_counter() - t0) * 1000)
    timing_ms["host_kernel_parallel"] = elapsed
    timing_ms["host"] = elapsed
    timing_ms["kernel"] = elapsed
    return host, kernel, timing_ms
