# -*- coding: utf-8 -*-
"""Does the certificate still pass when the kernel / tilingdata views are absent?

Before: both domains reported zero rows and every per-domain invariant held
vacuously, so gap=0 certified on the host domain alone.
"""

from __future__ import annotations

import json


def main() -> int:
    from testcase_agent.closure import report as REP
    from testcase_agent.closure import workspace as W

    ws = W.default_workspace().ensure()
    inv = REP.certify_invariants(ws)
    print("overall ok:", inv["ok"])
    for name, chk in sorted(inv["checks"].items()):
        flag = "PASS" if chk.get("ok") else "FAIL"
        print(f"  [{flag}] {name}: {str(chk.get('detail'))[:150]}")
    print("\ndomains:")
    print(json.dumps(
        {
            k: {kk: vv for kk, vv in (v or {}).items()
                if kk in ("branches", "covered", "fields", "established", "source")}
            for k, v in (inv.get("domains") or {}).items()
        },
        indent=1, default=str,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
