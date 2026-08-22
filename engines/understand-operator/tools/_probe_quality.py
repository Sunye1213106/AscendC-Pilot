# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from uo_init.store.reader import close_uo_connections
from uo_init.uo_query import open_query

OPS = {
    "FAG": Path(r"d:\TEST\ops-transformer\attention\flash_attention_score_grad"),
    "IFA": Path(r"d:\TEST\ops-transformer\attention\incre_flash_attention"),
    "GMM": Path(r"d:\TEST\ops-transformer\gmm\grouped_matmul"),
    "NSA": Path(r"d:\TEST\ops-transformer\attention\nsa_compress"),
}


def main() -> None:
    out: dict[str, object] = {}
    q = open_query(OPS["FAG"], architecture="arch35")
    idx = q.agent_query()
    phases = [row for row in (idx.get("phases") or []) if row.get("pipe") or row.get("file")]
    out["fag_launch"] = [
        {"pipe": r.get("pipe"), "file": r.get("file"), "line": r.get("line") or r.get("line_start")}
        for r in phases[:6]
    ]
    out["fag_hint"] = idx.get("hint")
    istnd = q.agent_query(pattern="Dim=IsTnd")
    out["fag_dim_istnd"] = {
        "completeness": istnd.get("completeness"),
        "values": (istnd.get("dim_coverage") or {}).get("IsTnd"),
    }
    combo = q.agent_query(pattern="IsTnd=1")
    out["fag_istnd1"] = {
        "matching": combo.get("matching_block_count"),
        "completeness": combo.get("completeness"),
        "nearby_in_coverage": "nearby" in (combo.get("coverage") or {}),
    }
    s1 = q.agent_query(pattern="s1Inner")
    card = next((c for c in (s1.get("cards") or []) if c.get("kind") == "TILING_FIELD"), None)
    out["fag_s1inner"] = {
        "kind": (card or {}).get("kind"),
        "readers": ((card or {}).get("extras") or {}).get("readers"),
        "writes": "WRITES" in ((card or {}).get("edges") or {}),
    }
    ssm = q.agent_query(pattern="SetScheduleMode")
    kinds = set()
    for c in ssm.get("cards") or []:
        kinds.update((c.get("edges") or {}).keys())
        if c.get("kind") in {"FUNCTION", "METHOD"}:
            out["fag_ssm_span"] = c.get("definition_span")
            out["fag_ssm_snip_lines"] = (c.get("snippet") or "").count("\n") + 1
    out["fag_ssm_edges"] = sorted(kinds)
    gf = q.agent_query(pattern="GRAPH_FAILED")
    out["fag_graph_failed"] = [
        {"kind": c.get("kind"), "catalog": (c.get("extras") or {}).get("catalog"), "role": (c.get("extras") or {}).get("role")}
        for c in (gf.get("cards") or [])
    ]
    empty = q.agent_query(pattern="Dim=__no_such_dim__")
    out["fag_empty_cover"] = {
        "completeness": empty.get("completeness"),
        "matching": empty.get("matching_block_count"),
        "nearby": empty.get("nearby"),
        "coverage_nearby": (empty.get("coverage") or {}).get("nearby"),
    }
    q.close()
    close_uo_connections()

    q = open_query(OPS["IFA"], architecture="arch35")
    ham = q.agent_query(pattern="HasAttenMask=true")
    out["ifa_ham"] = {
        "matching": ham.get("matching_block_count"),
        "completeness": ham.get("completeness"),
        "values": (q.agent_query(pattern="Dim=HasAttenMask").get("dim_coverage") or {}).get("HasAttenMask"),
    }
    q.close()
    close_uo_connections()

    q = open_query(OPS["GMM"], architecture="arch35")
    tb = q.agent_query(pattern="Dim=TRANS_B")
    gn = q.agent_query(pattern="groupNum")
    card = next((c for c in (gn.get("cards") or []) if c.get("kind") in {"TILING_FIELD", "FIELD"}), gn.get("cards", [{}])[0] if gn.get("cards") else {})
    out["gmm_trans_b"] = (tb.get("dim_coverage") or {}).get("TRANS_B")
    out["gmm_groupnum_readers"] = len(((card or {}).get("extras") or {}).get("readers") or [])
    out["gmm_localtensor_ok"] = q.agent_query(pattern="LocalTensor").get("ok")
    q.close()
    close_uo_connections()

    q = open_query(OPS["NSA"], architecture="arch35")
    nidx = q.agent_query()
    out["nsa_dim_names"] = nidx.get("dim_names")
    pipe = q.agent_query(pattern="pipe")
    pc = (pipe.get("cards") or [{}])[0]
    out["nsa_pipe"] = {"file": pc.get("file"), "line": pc.get("line"), "ok": pipe.get("ok")}
    q.close()
    close_uo_connections()
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
