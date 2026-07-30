# -*- coding: utf-8 -*-
"""TilingData SchemaVariant bridge + macro provenance."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class SchemaVariant:
    name: str
    template_args: list[str]
    derived_from: dict[str, str]


@dataclass
class MacroSite:
    name: str
    file: str
    line: int
    snippet: str


# A TilingData struct instantiated with template arguments: the argument list
# is what carries the SchemaVariant. The class name is discovered from the
# source rather than hardcoded, since it differs per operator.
SCHEMA_RE = re.compile(r"\b(\w*TilingData\w*)\s*<([^<>;{}]+)>")


def parse_schema_variant(
    src: str, dim_names: set[str] | None = None
) -> SchemaVariant | None:
    """Find the templated TilingData instantiation and map its args to TPL dims.

    `dim_names` comes from the parsed TilingKey DSL; an argument matching a dim
    name by spelling is that dim. Positional arguments that are macros are
    recorded by position, since only the macro body can say what they encode.
    """
    m = SCHEMA_RE.search(src)
    if not m:
        return None
    name = m.group(1)
    args = [a.strip() for a in m.group(2).split(",") if a.strip()]
    known = dim_names or set()
    derived: dict[str, str] = {}
    for i, a in enumerate(args):
        if a in known:
            derived[a] = a
        elif a.isupper() or a.startswith("NEED_"):
            derived[f"arg{i}"] = a
    return SchemaVariant(name=name, template_args=args, derived_from=derived)


def collect_invoke_provenance(path: str | Path) -> list[MacroSite]:
    from uo_init.branch_inventory import INVOKE_MACRO_RE

    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    sites = []
    for m in INVOKE_MACRO_RE.finditer(text):
        line = text[: m.start()].count("\n") + 1
        sites.append(
            MacroSite(
                name=m.group(0),
                file=str(path).replace("\\", "/"),
                line=line,
                snippet=m.group(0),
            )
        )
    return sites


def field_subset_ok(host_fields: set[str], kernel_fields: set[str]) -> bool:
    return kernel_fields.issubset(host_fields)
