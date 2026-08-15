# -*- coding: utf-8 -*-
"""Agent-facing UO query facade.

The unified ``.uo`` CodeMap is the only query authority. Production callers
must use :func:`open_query`, which fail-closes when no ``.uo`` product exists.
"""
from __future__ import annotations

from pathlib import Path


def open_query(
    uo_root: str | Path,
    *,
    op_name: str = "",
    architecture: str = "",
):
    """Open the unified ``.uo`` SQL query backend.

    Fail-closed: no product means no query. sqlite / YAML are not fallbacks.
    """
    from uo_init.store.reader import find_uo_product
    from uo_init.query.sql import UoSqlQuery

    root = Path(uo_root).expanduser().resolve()
    product = find_uo_product(root, op_name=op_name, architecture=architecture)
    if product is None or product.suffix != ".uo":
        arch = architecture or "<arch>"
        raise FileNotFoundError(
            f"no .uo product under {root}; expected "
            f".ascendc-pilot/{arch}/uo/<op>.{arch}.uo. "
            "Run /uo-init or answer from source. Do not Glob or Grep for .uo."
        )
    return UoSqlQuery(product)
