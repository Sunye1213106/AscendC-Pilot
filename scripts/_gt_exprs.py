# -*- coding: utf-8 -*-
"""Print the derived expression for the dimensions that read few variables.

These are the ones a unit test's inputs can be mapped onto by hand, so they are
where a ground-truth check can start. The five that read fifty variables each
are the overapproximated ones and are not the point here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / ".probe_cache"
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.concrete_eval import ValueTree  # noqa: E402

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 12


def main() -> int:
    doc = json.loads((CACHE / "fag_derive.json").read_text(encoding="utf-8"))
    for f in doc["fields"]:
        expr = f.get("value_expr")
        if expr is None:
            continue
        t = ValueTree(expr)
        _c, v = t.cuts()
        if len(v) > LIMIT:
            continue
        text = json.dumps(expr, ensure_ascii=False)
        print(f"\n{'=' * 100}")
        print(f"{f['name']}   ({len(v)} vars: {sorted(v)})")
        print(f"exactness={f.get('exactness')}")
        print(f"len={len(text)}")
        print(text[:2600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
