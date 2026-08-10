"""Final UO product compaction.

UO is allowed to materialize a YAML/IR work tree while the compiler is running,
but that tree is not a durable API.  After the binary CodeMap passes review,
remove the arch-scoped work tree so the only durable UO authority is
``.ascendc-pilot/uo/<op>.<arch>.uo``.
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

    arch = str(meta.get("architecture") or "arch35").strip() or "arch35"
    root = Path(project_root).expanduser().resolve()
    formal = root / ".ascendc-pilot" / "uo"
    try:
        product.relative_to(formal.resolve())
    except ValueError:
        return {"ok": False, "skipped": "product_outside_formal_uo", "path": str(product)}

    try:
        from ascendc_pilot.paths import uo_root

        work = uo_root(root, arch=arch)
    except Exception:
        work = root / ".ascendc-pilot" / arch / "uo"
    work = Path(work).expanduser().resolve()

    # Never allow compaction to touch the formal product namespace even if a
    # future path helper changes shape.
    if work == formal.resolve() or formal.resolve() in work.parents:
        return {"ok": False, "skipped": "unsafe_worktree_path", "path": str(work)}

    removed_files = 0
    removed_bytes = 0
    if work.exists():
        for p in work.rglob("*"):
            if p.is_file():
                removed_files += 1
                try:
                    removed_bytes += p.stat().st_size
                except OSError:
                    pass
        shutil.rmtree(work)
    # Keep an empty compatibility mount point for old is_dir() probes.  It is
    # deliberately not an authority and contains no YAML/DB/cache products.
    work.mkdir(parents=True, exist_ok=True)

    remaining = [p for p in work.rglob("*") if p.is_file()]
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
