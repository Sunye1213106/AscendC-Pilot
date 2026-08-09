# -*- coding: utf-8 -*-
"""Import a historical ``.understand-operator.zip`` into the unified UO store.

The archive is treated as historical evidence, not current-source authority.
When ``operator_root`` is supplied, deterministic current-source passes enrich
it with API, TilingKey, TilingData and Kernel contract facts before the single
``.uo`` product is written.  Natural-language derivations/questions are never
promoted into semantic edges.
"""

from __future__ import annotations

import tempfile
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind
from uo_init.passes.source_contract import enrich_codemap_from_operator_source
from uo_init.store.writer import write_codemap

_HOST_KIND: dict[str, EntityKind] = {
    "runtime_variable": EntityKind.VARIABLE,
    "host_expression": EntityKind.PREDICATE,
    "predicate_expression": EntityKind.PREDICATE,
    "if_branch": EntityKind.BRANCH,
    "early_return": EntityKind.BRANCH,
    "tiling_key_field": EntityKind.TILING_KEY,
    "requires_constraint": EntityKind.PREDICATE,
    "implies_constraint": EntityKind.PREDICATE,
    "value_constraint": EntityKind.PREDICATE,
    # A field definition is a field. Write/workspace records are events and must
    # not inflate TilingData field cardinality.
    "tilingdata_field": EntityKind.TILING_FIELD,
    "tilingdata_write": EntityKind.OTHER,
    "workspace_write": EntityKind.OTHER,
}

_KERNEL_KIND: dict[str, EntityKind] = {
    "kernel_global_entry": EntityKind.KERNEL,
    "kernel_entry": EntityKind.KERNEL,
    "kernel_class_entry": EntityKind.KERNEL,
    "kernel_function": EntityKind.FUNCTION,
    "kernel_method": EntityKind.METHOD,
}


def _first_source(item: dict[str, Any]) -> tuple[str, int, int]:
    sources = item.get("sources") or []
    if not sources:
        file = str(item.get("file") or "")
        return file, 0, 0
    src = sources[0] if isinstance(sources[0], dict) else {}
    span = src.get("span") or {}
    return (
        str(src.get("file") or item.get("file") or ""),
        int(span.get("start_line") or 0),
        int(span.get("end_line") or span.get("start_line") or 0),
    )


def _is_arch_allowed(item: dict[str, Any], architecture: str) -> bool:
    declared = str(item.get("architecture_variant") or "").strip().lower()
    if declared and declared != architecture.lower():
        return False
    file, _, _ = _first_source(item)
    norm = file.replace("\\", "/").lower()
    for other in ("arch22", "arch32", "arch40"):
        if f"/{other}/" in norm:
            return False
    return True


def _attrs(item: dict[str, Any], *, section: str, archive_kind: str) -> dict[str, Any]:
    out = {
        k: v
        for k, v in item.items()
        if k not in {"id", "kind", "name", "status", "file"}
    }
    out["archive_section"] = section
    out["archive_kind"] = archive_kind
    out["provenance"] = "historical_understand_operator"
    return out


def _add_item(
    cm: CodeMap,
    item: dict[str, Any],
    *,
    section: str,
    kind: EntityKind,
) -> None:
    file, line_start, line_end = _first_source(item)
    name = str(item.get("name") or item.get("symbol") or item.get("id") or "")
    ent = cm.upsert(
        kind,
        name,
        eid=str(item.get("id") or "") or None,
        attrs=_attrs(item, section=section, archive_kind=str(item.get("kind") or "")),
        file=file,
        line=line_start,
        status=str(item.get("status") or "extracted"),
        confidence=1.0 if str(item.get("status") or "").lower() == "confirmed" else 0.9,
    )
    ent.line_end = line_end


def _add_unresolved(cm: CodeMap, item: dict[str, Any], *, section: str) -> None:
    sources = item.get("candidate_sources") or []
    src = sources[0] if sources and isinstance(sources[0], dict) else {}
    span = src.get("span") or {}
    ent = cm.upsert(
        EntityKind.OTHER,
        str(item.get("id") or item.get("reason") or "unresolved"),
        eid=str(item.get("id") or "") or None,
        attrs={
            **dict(item),
            "archive_section": section,
            "role": "unresolved",
            "provenance": "historical_understand_operator",
        },
        file=str(src.get("file") or ""),
        line=int(span.get("start_line") or 0),
        status="unresolved",
        confidence=0.0,
    )
    ent.line_end = int(span.get("end_line") or ent.line_start)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    return value if isinstance(value, dict) else {}


def read_understand_archive(
    archive: str | Path,
    *,
    op_name: str,
    architecture: str = "arch35",
    operator_root: str | Path | None = None,
) -> CodeMap:
    """Read historical facts and optionally enrich them from current source."""
    archive_path = Path(archive).expanduser().resolve()
    if not archive_path.is_file():
        raise FileNotFoundError(archive_path)

    with tempfile.TemporaryDirectory(prefix="understand-archive-") as td:
        tmp = Path(td)
        with zipfile.ZipFile(archive_path) as zf:
            zf.extractall(tmp)
        root = tmp / ".understand-operator" / op_name
        if not root.is_dir():
            raise FileNotFoundError(f"active archive root missing: {root}")
        manifest = _load_yaml(root / "manifest.yaml")
        host = _load_yaml(root / "facts" / "host.yaml")
        kernel = _load_yaml(root / "facts" / "kernel" / "overview.yaml")

        cm = CodeMap(op_name=op_name, architecture=architecture)
        arch = cm.upsert(EntityKind.ARCH, architecture)
        variant = cm.upsert(
            EntityKind.BUILD_VARIANT,
            architecture,
            attrs={
                "architecture": architecture,
                "archive_manifest": manifest,
                "provenance": "historical_understand_operator",
            },
        )
        cm.link(
            RelationKind.ACTIVE_UNDER,
            arch.id,
            variant.id,
            attrs={"provenance": "archive_requested_architecture"},
        )

        imported = Counter()
        skipped = Counter()
        host_sections = host.get("sections") or {}
        for section, payload in host_sections.items():
            if not isinstance(payload, dict):
                continue
            for item in payload.get("items") or []:
                if not isinstance(item, dict):
                    continue
                if not _is_arch_allowed(item, architecture):
                    skipped[f"host:{section}"] += 1
                    continue
                raw_kind = str(item.get("kind") or "")
                kind = _HOST_KIND.get(raw_kind, EntityKind.OTHER)
                _add_item(cm, item, section=f"host/{section}", kind=kind)
                imported[f"host:{section}"] += 1
            for item in payload.get("unresolved") or []:
                if isinstance(item, dict) and _is_arch_allowed(item, architecture):
                    _add_unresolved(cm, item, section=f"host/{section}")
                    imported[f"unresolved:host:{section}"] += 1

        kernel_sections = kernel.get("sections") or {}
        for section, payload in kernel_sections.items():
            if not isinstance(payload, dict):
                continue
            for item in payload.get("items") or []:
                if not isinstance(item, dict):
                    continue
                if not _is_arch_allowed(item, architecture):
                    skipped[f"kernel:{section}"] += 1
                    continue
                raw_kind = str(item.get("kind") or "")
                kind = _KERNEL_KIND.get(raw_kind, EntityKind.OTHER)
                _add_item(cm, item, section=f"kernel/{section}", kind=kind)
                imported[f"kernel:{section}"] += 1
            for item in payload.get("unresolved") or []:
                if isinstance(item, dict) and _is_arch_allowed(item, architecture):
                    _add_unresolved(cm, item, section=f"kernel/{section}")
                    imported[f"unresolved:kernel:{section}"] += 1

        # Exact archived bindings are safe to promote before source enrichment.
        variables: dict[str, Any] = {}
        for ent in cm.by_kind(EntityKind.VARIABLE):
            norm = ((ent.attrs.get("identity") or {}).get("normalized") or {})
            source_name = str(norm.get("source_name") or "").strip()
            if source_name:
                variables[source_name] = ent
        exact_bindings = 0
        for key in cm.by_kind(EntityKind.TILING_KEY):
            runtime_source = str(key.attrs.get("runtime_source_name") or "").strip()
            source = variables.get(runtime_source)
            if not runtime_source or source is None:
                continue
            cm.link(
                RelationKind.DERIVES,
                source.id,
                key.id,
                attrs={
                    "runtime_source_name": runtime_source,
                    "provenance": "archive_runtime_source_name",
                },
            )
            exact_bindings += 1

        for ent in cm.by_kind(EntityKind.KERNEL):
            cm.link(
                RelationKind.AVAILABLE_ON,
                ent.id,
                arch.id,
                attrs={"provenance": "archive_architecture_variant"},
            )

        cm.meta.update(
            {
                "archive_import": "understand-operator/v2+current-source",
                "archive_path": str(archive_path),
                "archive_manifest_stage_status": manifest.get("stages") or {},
                "archive_graph_status": manifest.get("graphs") or {},
                "archive_imported": dict(imported),
                "archive_skipped": dict(skipped),
                "archive_exact_runtime_bindings": exact_bindings,
                "archive_relation_policy": "structured-only/no-free-text-inference",
            }
        )

        if operator_root is not None:
            enrich_codemap_from_operator_source(
                cm,
                operator_root,
                architecture=architecture,
            )
        return cm


def understand_archive_to_uo(
    archive: str | Path,
    dest: str | Path,
    *,
    op_name: str,
    architecture: str = "arch35",
    operator_root: str | Path | None = None,
) -> dict[str, Any]:
    cm = read_understand_archive(
        archive,
        op_name=op_name,
        architecture=architecture,
        operator_root=operator_root,
    )
    written = write_codemap(
        cm,
        dest,
        meta={
            "import_kind": "historical_understand_operator+current_source",
            "imported_from": str(Path(archive)),
            "operator_root": str(Path(operator_root).resolve()) if operator_root is not None else "",
        },
    )
    written["summary"] = cm.summary()
    written["archive_imported"] = cm.meta.get("archive_imported")
    written["archive_exact_runtime_bindings"] = cm.meta.get("archive_exact_runtime_bindings")
    written["source_contract_stats"] = cm.meta.get("source_contract_stats")
    return written