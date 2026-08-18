"""Hard isolation + product fingerprint for the TG↔UO boundary."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class IsolationError(PermissionError):
    """Raised when TG attempts to write into either UO namespace."""


def _is_uo_tree(resolved: Path) -> bool:
    """Match both the formal product tree and the retired arch work tree."""
    parts = resolved.parts
    try:
        idx = parts.index(".ascendc-pilot")
    except ValueError:
        return False
    tail = parts[idx + 1 :]
    if not tail:
        return False
    # <op>/.ascendc-pilot/uo/**
    if tail[0] == "uo":
        return True
    # <op>/.ascendc-pilot/<arch>/uo/**
    return len(tail) >= 2 and tail[1] == "uo"


def assert_tg_write_path(path: Path | str, *, out_root: Path | None = None) -> Path:
    resolved = Path(path).expanduser().resolve()
    if _is_uo_tree(resolved):
        raise IsolationError(
            f"UO_ROOT: TG isolation refuses write under UO authority/work tree: {resolved}. "
            "TG artifacts must stay under .ascendc-pilot/<arch>/tg."
        )
    if out_root is not None:
        root = Path(out_root).expanduser().resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise IsolationError(f"TG isolation: write path {resolved} is outside OUT_ROOT {root}") from exc
    return resolved


def _project_from_uo_hint(uo_hint: Path) -> tuple[Path | None, str]:
    """Recover operator root and arch from old/new UO path shapes."""
    root = Path(uo_hint).expanduser().resolve()
    parts = root.parts
    try:
        idx = parts.index(".ascendc-pilot")
    except ValueError:
        return None, ""
    project = Path(*parts[:idx]) if idx > 0 else Path(root.anchor)
    tail = parts[idx + 1 :]
    arch = ""
    if len(tail) >= 2 and tail[1] == "uo":
        arch = str(tail[0])
    return project, arch


def _product_fingerprint(uo_hint: Path) -> dict[str, Any] | None:
    project, arch = _project_from_uo_hint(uo_hint)
    if project is None:
        return None
    try:
        from testcase_agent import product_uo

        ident = product_uo.identity(project, architecture=arch)
    except Exception:
        return None
    sha = str(ident.get("sha256") or "")
    if not sha:
        return None
    # The product byte digest is the lock. Metadata is explanatory, not a
    # second mutable authority that can drift independently.
    return {
        "version": 2,
        "authority": "uo_product",
        "uo_product": str(ident.get("path") or ""),
        "digest": sha,
        "uo_sha256": sha,
        "revision": str(ident.get("revision") or ""),
        "graph_fingerprint": str(ident.get("graph_fingerprint") or ""),
        "op_name": str(ident.get("op_name") or ""),
        "architecture": str(ident.get("architecture") or arch),
    }


def compute_kb_fingerprint(uo_root: Path) -> dict[str, Any]:
    """Fingerprint the formal ``.uo`` product. Missing product fail-closes."""
    product = _product_fingerprint(Path(uo_root))
    if product is not None:
        return product
    root = Path(uo_root).expanduser().resolve()
    return {
        "version": 2,
        "authority": "missing",
        "digest": "",
        "uo_root": root.as_posix(),
        "reason": "no_uo_product",
    }


def write_kb_fingerprint(out_root: Path, uo_root: Path) -> dict[str, Any]:
    fp = compute_kb_fingerprint(uo_root)
    from .products import dump_init, load_init

    try:
        doc = load_init(out_root)
    except Exception:
        doc = {"schema": "tg-init/v1"}
    doc["uo_digest"] = str(fp.get("digest") or "")
    if fp.get("uo_product"):
        doc["uo_product"] = str(fp.get("uo_product"))
    dump_init(out_root, doc)
    return fp


def read_kb_fingerprint(out_root: Path) -> dict[str, Any]:
    from .products import load_init

    try:
        doc = load_init(out_root)
    except Exception:
        return {}
    digest = str(doc.get("uo_digest") or "").strip()
    if not digest:
        return {}
    return {
        "digest": digest,
        "uo_product": str(doc.get("uo_product") or ""),
        "authority": "init.yaml",
    }


def kb_fingerprint_matches(out_root: Path, uo_root: Path) -> tuple[bool, dict[str, Any]]:
    stored = read_kb_fingerprint(out_root)
    current = compute_kb_fingerprint(uo_root)
    if not stored or not stored.get("digest"):
        return False, {"stored": stored, "current": current, "reason": "missing_fingerprint"}
    ok = str(stored.get("digest")) == str(current.get("digest"))
    return ok, {"stored": stored, "current": current, "reason": "" if ok else "digest_mismatch"}
