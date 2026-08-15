# -*- coding: utf-8 -*-
"""Project REGISTER_TILING_TEMPLATE_WITH_ARCH into the CodeMap.

Reuses ``anchors.extract_registry`` and ``registry_capable.extract_iscapable``.
Does not re-parse macros and does not overlap ``REGISTER_TILING_FOR_TILINGKEY``.
"""

from __future__ import annotations

import re
from pathlib import Path

from uo_init.anchors import extract_registry
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.registry_capable import extract_iscapable
from uo_init.source_layout import selected_host_files, selected_kernel_files

_REGISTER_TILING_DEFAULT_RE = re.compile(
    r"REGISTER_TILING_DEFAULT\s*\(\s*([A-Za-z_:][A-Za-z0-9_:]*)\s*\)"
)


def enrich_tiling_template_registry(
    codemap: CodeMap,
    operator_root: str | Path,
    *,
    architecture: str = "",
) -> CodeMap:
    root = Path(operator_root).expanduser().resolve()
    op_name = str(codemap.op_name or "").strip()
    hits = extract_registry(root, op_name) if op_name else []
    count = 0
    for hit in hits:
        cls = str(hit.get("class") or "")
        if not cls:
            continue
        abs_file = Path(str(hit.get("file") or ""))
        try:
            rel = str(abs_file.resolve().relative_to(root)).replace("\\", "/")
        except ValueError:
            rel = str(hit.get("file") or "").replace("\\", "/")
        line = int(hit.get("line") or 0)
        cap_file = ""
        cap_line = 0
        try:
            found = extract_iscapable(abs_file, class_name=cls) if abs_file.is_file() else []
        except Exception:
            found = []
        if found:
            cap_file = str(found[0].file or rel)
            cap_line = int(found[0].line or 0)
            try:
                cap_path = Path(cap_file)
                cap_file = str(cap_path.resolve().relative_to(root)).replace("\\", "/")
            except (ValueError, OSError):
                cap_file = cap_file.replace("\\", "/")
        eid = f"TILINGTPLREG::{rel}::{line}::{cls}"
        codemap.upsert(
            EntityKind.PREDICATE,
            f"REGISTER_TILING_TEMPLATE_{cls}",
            eid=eid,
            attrs={
                "predicate_role": "tiling_template_registry",
                "class": cls,
                "priority": int(hit.get("priority") or 0),
                "arch_expr": str(hit.get("arch_expr") or ""),
                "op": str(hit.get("op") or op_name),
                "architecture": architecture,
                "is_capable_file": cap_file,
                "is_capable_line": cap_line,
                "provenance": "source_register_tiling_template",
            },
            file=rel,
            line=line,
            status="confirmed",
        )
        count += 1
    defaults = _emit_register_tiling_defaults(codemap, root, architecture)
    meta = dict(codemap.meta.get("tiling_template_registry") or {})
    meta["count"] = count
    meta["register_tiling_default"] = defaults
    codemap.meta["tiling_template_registry"] = meta
    return codemap


def _emit_register_tiling_defaults(
    codemap: CodeMap, root: Path, architecture: str
) -> int:
    count = 0
    seen: set[Path] = set()
    for path in list(selected_host_files(root, architecture)) + list(
        selected_kernel_files(root, architecture)
    ):
        key = path.resolve()
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        raw = path.read_text(encoding="utf-8", errors="replace")
        try:
            rel = path.resolve().relative_to(root).as_posix()
        except ValueError:
            rel = path.as_posix().replace("\\", "/")
        for match in _REGISTER_TILING_DEFAULT_RE.finditer(raw):
            cls = match.group(1)
            line = raw.count("\n", 0, match.start()) + 1
            eid = f"TILINGDEFAULT::{rel}::{line}::{cls}"
            codemap.upsert(
                EntityKind.PREDICATE,
                "REGISTER_TILING_DEFAULT",
                eid=eid,
                attrs={
                    "predicate_role": "tiling_default_registry",
                    "class": cls.split("::")[-1],
                    "architecture": architecture,
                    "provenance": "source_register_tiling_default",
                },
                file=rel,
                line=line,
                status="confirmed",
            )
            count += 1
    return count
