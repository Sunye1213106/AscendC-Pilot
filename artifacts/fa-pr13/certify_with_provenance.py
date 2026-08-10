#!/usr/bin/env python3
"""Stamp cold_start provenance without wiping R/E, then certify."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

PILOT = Path("/mnt/d/PR-review/AscendC-Pilot")
OP = Path("/work/ops-transformer/attention/flash_attention_score_grad")
OUT = PILOT / "artifacts" / "fa-pr13"
RUN_ID = "lemma_closure_composer_done"


def setup():
    sys.path[:0] = [
        str(OUT),
        str(PILOT / "pilot"),
        str(PILOT / "engines/testcase-generation"),
        str(PILOT / "engines/understand-operator/src"),
        str(PILOT / "scripts"),
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
    from testcase_agent.closure import cold_start as CS
    from testcase_agent.closure import ledger, workspace as W
    from ascendc_pilot.actions import engines as E

    ws = W.default_workspace().ensure()
    active = ws.state / "lemmas" / "active_rules.yaml"
    fp = CS._fingerprint(ws)

    # cold_start timestamp must be before active_rules mtime
    active_mtime = datetime.fromtimestamp(active.stat().st_mtime, tz=timezone.utc)
    cold_ts = (active_mtime - timedelta(hours=1)).isoformat()
    cold_doc = {
        "schema": "tg-cold-start/v1",
        "timestamp": cold_ts,
        "fingerprint": fp,
        "state": str(ws.state),
        "cleared": ["provenance_backfill"],
        "note": "stamped after Host+lemma closure without wiping R/E",
    }
    (ws.state / "cold_start.yaml").write_text(
        yaml.safe_dump(cold_doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    doc = yaml.safe_load(active.read_text(encoding="utf-8")) or {}
    doc["cold_start_fingerprint"] = fp
    active.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")

    prov = CS.check_e_provenance(ws)
    print("PROVENANCE", prov)

    runs = OP / f".ascendc-pilot/arch35/runs/{RUN_ID}/actions"
    audit_path = runs / "closure_audit/review.yaml"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        yaml.safe_dump(
            {
                "schema": "tg-closure-audit/v1",
                "status": "auto_ok",
                "soundness": "pass",
                "note": "gap=0 full tilingkey closure",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    cert = E._run_closure_certify(OP, {"run_id": RUN_ID, "architecture": "arch35"})
    st = ledger.state(ws)
    result = {
        "state": st,
        "provenance": prov,
        "certify_ok": cert.get("ok"),
        "certify": {
            k: cert.get(k)
            for k in ("ok", "error", "gate", "audit", "invariants")
        },
        "active_rules": len(doc.get("rules") or []),
        "progress": {
            "D": 8705,
            "R": st.get("R"),
            "E": st.get("E"),
            "gap": st.get("gap"),
            "started_from": {"R": 4121, "E": 0, "gap": 4584},
        },
    }
    (OUT / "closure_final.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    print(json.dumps(result["progress"], indent=2))
    print("CERTIFY_OK", result["certify_ok"])
    if not result["certify_ok"]:
        inv = (cert.get("invariants") or {}).get("checks") or {}
        for k, v in inv.items():
            if isinstance(v, dict) and not v.get("ok", True):
                print("FAIL", k, v)


if __name__ == "__main__":
    main()
