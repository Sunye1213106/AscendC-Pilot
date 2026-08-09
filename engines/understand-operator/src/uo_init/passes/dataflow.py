# -*- coding: utf-8 -*-
"""DataflowPass — def-use / lifecycle edges on CodeMap."""

from __future__ import annotations

from typing import Any

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind


def run(codemap: CodeMap, *, context: dict[str, Any] | None = None) -> CodeMap:
    ctx = context or {}
    host_ir = ctx.get("host_ir")
    if host_ir is None:
        codemap.meta["dataflow_pass"] = "v1-skip"
        return codemap

    # Field write → FLOWS_TO consumers that read the same path tail.
    writes_by_path: dict[str, list[str]] = {}
    for ev in getattr(host_ir, "writes", None) or []:
        path = str(getattr(ev, "path", "") or "")
        fn = str(getattr(ev, "function", "") or "")
        if not path:
            continue
        field = codemap.upsert(EntityKind.FIELD, path, attrs={"layer": "host"})
        if fn:
            writer = codemap.upsert(EntityKind.FUNCTION, fn, attrs={"layer": "host"})
            codemap.link(RelationKind.WRITES, writer.id, field.id)
            writes_by_path.setdefault(path, []).append(writer.id)

    for name, summary in (getattr(host_ir, "summaries", None) or {}).items():
        reader = codemap.upsert(EntityKind.FUNCTION, str(name), attrs={"layer": "host"})
        for r in getattr(summary, "reads", None) or []:
            path = str(r)
            var = codemap.upsert(EntityKind.VARIABLE, path, attrs={"layer": "host"})
            codemap.link(RelationKind.READS, reader.id, var.id)
            for writer_id in writes_by_path.get(path, ()):
                codemap.link(RelationKind.FLOWS_TO, writer_id, reader.id)
                field = codemap.by_name(path, kind=EntityKind.FIELD)
                if field:
                    codemap.link(RelationKind.FLOWS_TO, field[0].id, var.id)

    codemap.meta["dataflow_pass"] = "v1"
    return codemap
