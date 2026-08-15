# -*- coding: utf-8 -*-
"""Check a committed .uo against the cannbot locate-surface bar (any op+arch)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [
    str(REPO / "engines" / "understand-operator" / "src"),
    str(REPO / "engines" / "common"),
    str(REPO / "pilot"),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("op_dir", type=Path, help="Operator source root (contains op_kernel/)")
    parser.add_argument("--arch", required=True, help="Architecture id (required; no silent default)")
    parser.add_argument("--product", type=Path, default=None)
    args = parser.parse_args(argv)

    from uo_init.diagnostics.product_check import check_cannbot_product
    from uo_init.store.reader import find_uo_product, read_codemap

    op = args.op_dir.expanduser().resolve()
    product = args.product
    if product is None:
        product = find_uo_product(op, architecture=args.arch)
    if product is None or not Path(product).is_file():
        print(json.dumps({"ok": False, "error": "missing_uo_product"}, ensure_ascii=False))
        return 1
    cm = read_codemap(product)
    facts = check_cannbot_product(cm, source_root=op, architecture=args.arch)
    facts["product"] = str(product)
    print(json.dumps(facts, ensure_ascii=False, indent=2, default=str))
    return 0 if facts.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
