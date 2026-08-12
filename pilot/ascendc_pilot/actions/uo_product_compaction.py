"""Final UO product compaction.

UO may materialize YAML/IR under ``.ascendc-pilot/<arch>/uo/`` while compiling.
After the binary CodeMap passes review, scrub transient work files but keep the
durable ``*.uo`` product in the same arch-scoped tree (multi-arch friendly).
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def compact_reviewed_uo(project_root: Path, result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("ok") or str(result.get("verdict") or "") not in {"", "pass"}:
        return {"ok": False, "skipped": "review_not_passed"}

    product = Path(str(result.get("path") or "")).expanduser()
    if not product.is_file() or product.suffix != ".uo":
        return {"ok": False, "skipped": "product_missing", "path": str(product)}
    product = product.resolve()

    try:
        from uo_init.store.reader import read_meta

        meta = read_meta(product)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "skipped": "product_meta_unreadable", "error": str(exc)[:200]}

    arch = str(meta.get("architecture") or "").strip()
    if not arch:
        return {
            "ok": False,
            "skipped": "architecture_missing",
            "error": "ARCHITECTURE_MISSING_IN_RUN_STATE",
            "reason_code": "ARCHITECTURE_MISSING_IN_RUN_STATE",
        }
    root = Path(project_root).expanduser().resolve()
    try:
        from ascendc_pilot.paths import uo_root

        work = uo_root(root, arch=arch)
    except Exception:
        work = root / ".ascendc-pilot" / arch / "uo"
    work = Path(work).expanduser().resolve()

    # Product must live inside the arch-scoped uo tree.
    try:
        product.relative_to(work)
    except ValueError:
        return {"ok": False, "skipped": "product_outside_arch_uo", "path": str(product)}

    removed_files = 0
    removed_bytes = 0
    if work.exists():
        for p in sorted(work.rglob("*"), reverse=True):
            if p == product or not p.exists():
                continue
            if p.is_file():
                # Preserve every durable CodeMap product under this arch tree.
                if p.suffix == ".uo":
                    continue
                removed_files += 1
                try:
                    removed_bytes += p.stat().st_size
                except OSError:
                    pass
                try:
                    p.unlink()
                except OSError:
                    pass
            elif p.is_dir():
                try:
                    # Drop empty dirs; leave dirs that still hold *.uo.
                    next(p.iterdir())
                except StopIteration:
                    try:
                        p.rmdir()
                    except OSError:
                        pass
                except OSError:
                    pass

    work.mkdir(parents=True, exist_ok=True)
    remaining = [
        p
        for p in work.rglob("*")
        if p.is_file() and p.suffix != ".uo"
    ]
    return {
        "ok": not remaining,
        "compacted": True,
        "worktree": str(work),
        "removed_files": removed_files,
        "removed_bytes": removed_bytes,
        "remaining_files": [str(p) for p in remaining],
        "uo_product": str(product),
        "authority": "uo_product",
    }


def install(registry: dict[tuple[str, str], Any]) -> None:
    """Wrap the public uo-init review engine with fail-safe compaction."""
    if getattr(install, "_installed", False):
        return
    key = ("uo-init", "review")
    original = registry.get(key)
    if original is None:
        return

    def reviewed(project_root: Path, ctx: dict[str, Any]) -> dict[str, Any]:
        result = original(project_root, ctx)
        if not result.get("ok"):
            return result
        compact = compact_reviewed_uo(Path(project_root), result)
        result = dict(result)
        result["compaction"] = compact
        if not compact.get("ok"):
            result["ok"] = False
            result["verdict"] = "fail"
            result["error"] = "UO_PRODUCT_COMPACTION_FAILED"
        return result

    registry[key] = reviewed
    install._installed = True
