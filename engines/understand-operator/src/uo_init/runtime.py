# -*- coding: utf-8 -*-
"""Process-local uo-init session teardown.

Caches are still module globals for in-run speed. Workflow end (and extract
failure) must drop them so a long-lived Python runner cannot leak TUs or
reuse the wrong operator bundle.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def live_ast_count() -> int:
    from uo_init import tu_cache

    return tu_cache.live_ast_count()


def end_session(
    op_root: str | Path | None = None,
    architecture: str | None = None,
) -> None:
    """Release process-global extract/analyze caches for this workflow."""
    from uo_init import include_heal, tu_cache
    from uo_init.build import drop_compile_mem
    from uo_init.passes.source_text_cache import clear as clear_source_text
    from uo_init.source_index import reset_index_cache

    tu_cache.clear_live_ast()
    try:
        from uo_init import pilot_engines as pe

        pe._STORE.clear()
    except Exception:  # noqa: BLE001
        pass
    drop_compile_mem(Path(op_root) if op_root else None, architecture=architecture)
    clear_source_text()
    reset_index_cache()
    include_heal.reset_index_cache()


def bundle_identity(
    project_root: str | Path,
    ctx: dict[str, Any] | None = None,
    *,
    op_name: str = "",
    architecture: str = "",
    extract_fingerprint: str = "",
) -> tuple[str, str, str, str]:
    ctx = ctx or {}
    root = str(Path(project_root).expanduser().resolve())
    name = str(op_name or ctx.get("op_name") or "")
    arch = str(
        architecture
        or ctx.get("arch_dir")
        or ctx.get("architecture")
        or ctx.get("arch")
        or ""
    )
    fp = str(extract_fingerprint or ctx.get("extract_fingerprint") or "")
    return (root, name, arch, fp)
