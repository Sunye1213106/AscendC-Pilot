# -*- coding: utf-8 -*-
"""Do the new provenance gates reject the workspace the bypass scripts produced?

The previous run reached gap=0 after a cold_start.yaml was stamped with a
backdated timestamp. If the gates are real, they refuse it.
"""

from __future__ import annotations


def show(label, fn):
    print(f"--- {label} ---")
    try:
        print(fn())
    except BaseException as exc:  # noqa: BLE001
        print(f"RAISED {type(exc).__name__}: {exc}")


def main() -> int:
    from testcase_agent.closure import cold_start as CS
    from testcase_agent.closure import ledger
    from testcase_agent.closure import workspace as W

    ws = W.default_workspace().ensure()
    print("state:", ws.state)
    R, E, D = ledger.load_R(ws), ledger.load_E(ws), ledger.declared()
    print(f"R={len(R)} E={len(E)} D={len(D)} open={len(D - R - E)}")

    show("check_e_provenance", lambda: CS.check_e_provenance(ws))
    show("verify_chain", lambda: CS.verify_chain(ws))
    show("require_cold_start", lambda: CS.require_cold_start(ws))
    show("load_chain", lambda: CS.load_chain(ws))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
