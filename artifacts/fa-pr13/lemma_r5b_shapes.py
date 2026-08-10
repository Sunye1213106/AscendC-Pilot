#!/usr/bin/env python3
"""Mine R witnesses for Bn2/Nz and try to clone shapes for open targets."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PILOT = Path("/mnt/d/PR-review/AscendC-Pilot")
OP = Path("/work/ops-transformer/attention/flash_attention_score_grad")
OUT = PILOT / "artifacts" / "fa-pr13"


def setup():
    sys.path[:0] = [
        str(OUT),
        str(PILOT / "pilot"),
        str(PILOT / "engines/testcase-generation"),
        str(PILOT / "engines/understand-operator/src"),
        str(PILOT / "scripts"),
        str(PILOT / "operators"),
    ]
    os.environ.update(
        {
            "ASCENDC_PROJECT_ROOT": str(OP),
            "UO_OP_DIR": str(OP),
            "UO_OPERATOR": "flash_attention_score_grad",
            "UO_ARCH": "arch35",
            "UO_OPS_ROOT": "/work/ops-transformer",
            "OPS_TRANSFORMER_ROOT": "/work/ops-transformer",
            "UO_REPLAY_HOST": "native",
        }
    )


def main():
    setup()
    import pandas as pd
    from testcase_agent.closure import ledger, workspace as W, corpus as C
    from testcase_agent.closure.oracle import HostOracle
    from replay import inputs as I

    ws = W.default_workspace().ensure()
    R = ledger.load_R(ws)
    open_keys = sorted(ledger.declared() - R - ledger.load_E(ws))

    # Find corpus rows that hit Bn2 / Nz
    art = ws.artifacts
    csvs = list(Path(art).rglob("*.csv")) if art else []
    # Also look under closure state
    more = list((ws.state).rglob("*.csv"))
    print("csv_count", len(csvs) + len(more))

    # Decode R keys with Bn2=1
    bn2_r = []
    nz_r = []
    for k in sorted(R):
        inst = dict(W.decode(int(k)))
        if inst.get("IsBn2MultiBlk") == "1":
            bn2_r.append((int(k), inst))
        if inst.get("IsNzOut") == "1":
            nz_r.append((int(k), inst))
    print("R_bn2", len(bn2_r), "R_nz", len(nz_r))
    print("sample_bn2", bn2_r[:3])
    print("sample_nz", nz_r[:3])

    open_bn2 = [dict(W.decode(int(k))) | {"_key": int(k)} for k in open_keys if dict(W.decode(int(k))).get("IsBn2MultiBlk") == "1"]
    open_nz = [dict(W.decode(int(k))) | {"_key": int(k)} for k in open_keys if dict(W.decode(int(k))).get("IsNzOut") == "1"]
    print("open_bn2", len(open_bn2), "open_nz", len(open_nz))

    # Try alternate construct shapes for Bn2: vary b/n2/s around known-good envelope
    # Use construct_case then mutate b/s1/s2
    trials = []
    shapes = [
        (32, 8, 256, 256, 1),
        (16, 16, 256, 256, 1),
        (32, 8, 512, 512, 1),
        (64, 4, 256, 256, 1),
        (8, 32, 640, 640, 1),
        (32, 8, 192, 192, 1),
        (32, 8, 320, 320, 1),
        (128, 2, 256, 256, 1),
    ]
    for inst in open_bn2[:8]:
        base_cases = list(I.construct_case(inst) or [])
        if not base_cases:
            continue
        for b, n2, s1, s2, g in shapes:
            c = base_cases[0]
            # Case is likely a dataclass - copy fields
            try:
                from dataclasses import replace

                c2 = replace(c, b=b, n2=n2, s1=s1, s2=s2, g=g)
            except Exception:
                c2 = c
                for name, val in (("b", b), ("n2", n2), ("s1", s1), ("s2", s2), ("g", g)):
                    if hasattr(c2, name):
                        setattr(c2, name, val)
            trials.append((inst["_key"], c2, (b, n2, s1, s2, g)))

    print("bn2_trials", len(trials))
    if trials:
        oracle = HostOracle()
        verdicts = oracle.judge([t[1] for t in trials], tag="r5_bn2_shapes")
        hits = 0
        for (target, _c, shape), v in zip(trials, verdicts):
            if v.verdict and v.ok and int(v.key) == int(target):
                hits += 1
                print("HIT", target, shape)
        print("bn2_shape_hits", hits)
        # commit any ok rows
        rows = [
            {"ok": int(v.ok), "tiling_key": int(v.key), "reject": v.reject, "_arm": "r5_bn2"}
            for v in verdicts
            if v.verdict
        ]
        if rows:
            C.commit(rows, ws, name="r5_bn2_shapes.csv")
            ledger.rebuild(ws)

    # Nz shape variants
    nz_trials = []
    nz_shapes = [
        (2, 8, 4096, 4096, 72),
        (2, 8, 2048, 2048, 72),
        (4, 8, 4096, 4096, 80),
        (2, 16, 4096, 4096, 96),
        (1, 8, 8192, 8192, 72),
        (2, 8, 4096, 4096, 112),
    ]
    for inst in open_nz[:8]:
        base_cases = list(I.construct_case(inst) or [])
        if not base_cases:
            continue
        for b, n2, s1, s2, d in nz_shapes:
            c = base_cases[0]
            try:
                from dataclasses import replace

                c2 = replace(c, b=b, n2=n2, s1=s1, s2=s2, d=d, d1=d)
            except Exception:
                c2 = c
                for name, val in (("b", b), ("n2", n2), ("s1", s1), ("s2", s2), ("d", d), ("d1", d)):
                    if hasattr(c2, name):
                        setattr(c2, name, val)
            nz_trials.append((inst["_key"], c2, (b, n2, s1, s2, d)))
    print("nz_trials", len(nz_trials))
    if nz_trials:
        oracle = HostOracle()
        verdicts = oracle.judge([t[1] for t in nz_trials], tag="r5_nz_shapes")
        hits = 0
        for (target, _c, shape), v in zip(nz_trials, verdicts):
            if v.verdict and v.ok and int(v.key) == int(target):
                hits += 1
                print("HIT_NZ", target, shape)
        print("nz_shape_hits", hits)
        rows = [
            {"ok": int(v.ok), "tiling_key": int(v.key), "reject": v.reject, "_arm": "r5_nz"}
            for v in verdicts
            if v.verdict
        ]
        if rows:
            C.commit(rows, ws, name="r5_nz_shapes.csv")
            ledger.rebuild(ws)

    st = ledger.state(ws)
    print("STATE", st)
    (OUT / "lemma_r5b_shapes.json").write_text(json.dumps({"state": st}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
