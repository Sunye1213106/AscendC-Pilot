# -*- coding: utf-8 -*-
"""Why did the kernel / tilingdata domains come out empty?

The certificate reported both domains as ok with zero rows. Either the operator
genuinely has nothing there (it does not — UO counted TILING_FIELD entities) or
the domain never found the UO views it reads.
"""

from __future__ import annotations

from pathlib import Path


def main() -> int:
    from testcase_agent.closure import kernel_domain as KD
    from testcase_agent.closure import tilingdata_domain as TD
    from testcase_agent.closure import workspace as W

    ws = W.default_workspace().ensure()
    print("ws.root     :", ws.root)
    print("ws.state    :", ws.state)
    print("ws.artifacts:", ws.artifacts)

    uo = TD._uo_root(ws)
    print("\nuo_root     :", uo, "exists=", bool(uo and Path(uo).is_dir()))
    if uo:
        p = Path(uo)
        print("  views dir     :", (p / "views").is_dir())
        if (p / "views").is_dir():
            print("  views/*.yaml  :", sorted(x.name for x in (p / "views").glob("*.yaml")))
        print("  kb_graph.sqlite:", (p / "indexes" / "kb_graph.sqlite").is_file())

    doc = TD._load_tilingdata_doc(Path(uo)) if uo else {}
    print("\ntilingdata doc keys:", sorted(doc)[:12])
    print("  structs:", len(doc.get("structs") or []))
    fields = TD.load_tilingdata_fields(Path(uo) if uo else None)
    print("  loaded fields:", len(fields))

    print("\n--- kernel domain ---")
    try:
        branches = KD.load_kernel_branches(Path(uo)) if uo else []
        print("  loaded branches:", len(branches))
    except Exception as exc:  # noqa: BLE001
        print("  load_kernel_branches RAISED:", type(exc).__name__, exc)
    try:
        kc = KD.compute_r_kernel(ws, write=False)
        print("  compute_r_kernel:", {k: kc.get(k) for k in ("branches", "covered", "ok")})
    except Exception as exc:  # noqa: BLE001
        print("  compute_r_kernel RAISED:", type(exc).__name__, exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
