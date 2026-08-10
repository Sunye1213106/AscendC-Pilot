#!/usr/bin/env python3
"""d1 directed repair: flip the single differing dim from nearest R witness."""
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
    from testcase_agent.closure import ledger, workspace as W, residual, construct, corpus as C
    from testcase_agent.closure.oracle import HostOracle
    from replay import inputs as I

    ws = W.default_workspace().ensure()
    analysis = residual.analyse(ws)
    open_keys = sorted(ledger.declared() - ledger.load_R(ws) - ledger.load_E(ws))
    print("open", len(open_keys), "d1_rows", sum(1 for r in analysis["rows"] if r.get("distance") == 1))

    # Inspect a few construct vs host outcomes
    samples = []
    for k in open_keys[:8]:
        inst = dict(W.decode(int(k)))
        spelled = construct.build(inst)
        samples.append({"key": int(k), "inst": inst, "spelled": len(spelled), "path": construct.last_build_path()})
        if spelled:
            # show first case knobs if available
            c0 = spelled[0]
            samples[-1]["case0"] = {
                a: getattr(c0, a, None)
                for a in ("layout", "dtype", "b", "s1", "s2", "n2", "g", "d", "d1", "sparse", "deterministic")
                if hasattr(c0, a) or True
            }
    (OUT / "r4_sample_construct.json").write_text(json.dumps(samples, indent=2, default=str), encoding="utf-8")
    print(json.dumps(samples[:3], indent=2, default=str)[:2000])

    # Try construct_reasons guided - look at mismatch after host for one batch
    cases = []
    key_of = []
    for k in open_keys:
        inst = dict(W.decode(int(k)))
        try:
            spelled = list(I.construct_case(inst) or [])
        except Exception:
            spelled = construct.build(inst)
        if not spelled:
            continue
        cases.append(spelled[0])
        key_of.append(int(k))

    oracle = HostOracle()
    verdicts = oracle.judge(cases, tag="r4_diag")
    rewrite = 0
    hit = 0
    mismatch = {}
    for target_k, v in zip(key_of, verdicts):
        if not v.verdict:
            continue
        if int(v.key) == target_k and v.ok:
            hit += 1
        else:
            rewrite += 1
            try:
                want = dict(W.decode(target_k))
                got = dict(W.decode(int(v.key))) if v.ok else {}
                dims = [d for d in want if str(want.get(d)) != str(got.get(d))]
                mismatch[tuple(dims)] = mismatch.get(tuple(dims), 0) + 1
            except Exception:
                pass
    print("hit", hit, "rewrite", rewrite)
    print("mismatch_dims", sorted(mismatch.items(), key=lambda x: -x[1])[:15])

    st = ledger.state(ws)
    print("state", st)


if __name__ == "__main__":
    main()
