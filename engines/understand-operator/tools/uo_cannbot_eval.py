# -*- coding: utf-8 -*-
"""Snapshot / rebuild / compare the four cannbot operators."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
sys.path[:0] = [
    str(REPO / "engines" / "understand-operator" / "src"),
    str(REPO / "engines" / "common"),
    str(REPO / "pilot"),
]

OPS: dict[str, Path] = {
    "FAG": Path(r"d:\TEST\ops-transformer\attention\flash_attention_score_grad"),
    "IFA": Path(r"d:\TEST\ops-transformer\attention\incre_flash_attention"),
    "GMM": Path(r"d:\TEST\ops-transformer\gmm\grouped_matmul"),
    "NSA": Path(r"d:\TEST\ops-transformer\attention\nsa_compress"),
}
ARCH = "arch35"
OUT = REPO / "docs" / "test" / "results" / "uo-cannbot"


def _card_heads(payload: dict[str, Any], n: int = 4) -> list[dict[str, Any]]:
    rows = list(payload.get("cards") or payload.get("phases") or payload.get("seeds") or [])
    out: list[dict[str, Any]] = []
    for row in rows[:n]:
        if not isinstance(row, dict):
            continue
        extras = row.get("extras") if isinstance(row.get("extras"), dict) else {}
        edges = row.get("edges") if isinstance(row.get("edges"), dict) else {}
        out.append(
            {
                "kind": row.get("kind") or row.get("phase"),
                "name": row.get("name") or row.get("pipe"),
                "file": str(row.get("file") or "").replace("\\", "/"),
                "line": int(row.get("line") or row.get("line_start") or 0),
                "readers": len(extras.get("readers") or []),
                "reads_edges": int((edges.get("READS") or {}).get("count") or 0),
            }
        )
    return out


def snapshot_op(name: str, root: Path) -> dict[str, Any]:
    from uo_init.uo_query import open_query

    q = open_query(root, architecture=ARCH)
    queries: dict[str, Any] = {}
    if name == "FAG":
        cases = [
            ("index", {}),
            ("IsTnd=1", {"pattern": "IsTnd=1"}),
            ("Dim=IsTnd", {"pattern": "Dim=IsTnd"}),
            ("s1Inner", {"pattern": "s1Inner"}),
        ]
    elif name == "IFA":
        cases = [
            ("index", {}),
            ("HasAttenMask=true", {"pattern": "HasAttenMask=true"}),
            ("HasAttenMask=1", {"pattern": "HasAttenMask=1"}),
            ("Dim=HasAttenMask", {"pattern": "Dim=HasAttenMask"}),
        ]
    elif name == "GMM":
        cases = [
            ("index", {}),
            ("Dim=TRANS_B", {"pattern": "Dim=TRANS_B"}),
            ("TRANS_B=1", {"pattern": "TRANS_B=1"}),
            ("groupNum", {"pattern": "groupNum"}),
        ]
    else:
        cases = [("index", {})]
    for label, kwargs in cases:
        t0 = time.perf_counter()
        payload = q.agent_query(**kwargs)
        dt = round(time.perf_counter() - t0, 3)
        queries[label] = {
            "elapsed_s": dt,
            "shape": payload.get("shape"),
            "ok": payload.get("ok"),
            "count": payload.get("count"),
            "matching_block_count": payload.get("matching_block_count"),
            "dim_coverage": payload.get("dim_coverage"),
            "dim_names": payload.get("dim_names"),
            "hint": payload.get("hint"),
            "phases": [
                {
                    "pipe": row.get("pipe") or row.get("name"),
                    "file": str(row.get("file") or "").replace("\\", "/"),
                    "line": int(row.get("line") or 0),
                    "phase": row.get("phase"),
                }
                for row in list(payload.get("phases") or [])
            ],
            "cards": _card_heads(payload),
        }
    return queries


def judge(name: str, queries: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    index = queries.get("index") or {}
    hint = str(index.get("hint") or "")
    dims = [str(x) for x in (index.get("dim_names") or [])]
    if "IsTnd=1" in hint:
        out["index_hint"] = "regress"
    elif "Name=Value" in hint or "Dim=" in hint:
        out["index_hint"] = "improve" if "IsTnd=1" not in hint else "keep"
    else:
        out["index_hint"] = "keep"

    if name == "NSA":
        out["dim_names_no_zero"] = "improve" if "0" not in dims else "regress"
    if name == "FAG":
        cover = queries.get("IsTnd=1") or {}
        dim = queries.get("Dim=IsTnd") or {}
        cov = (dim.get("dim_coverage") or {}).get("IsTnd") or []
        out["IsTnd=1"] = (
            "improve"
            if int(cover.get("matching_block_count") or 0) > 0
            else "regress"
        )
        out["Dim=IsTnd"] = "keep" if set(str(v) for v in cov) >= {"0", "1"} or cov else "regress"
        phases = index.get("phases") or []
        bad = [
            row
            for row in phases
            if str(row.get("pipe") or "") in {"pipeBase", "pipePost"} and int(row.get("line") or 0) == 225
        ]
        out["pipe_not_225"] = "improve" if phases and not bad else ("regress" if bad else "keep")
        field = queries.get("s1Inner") or {}
        cards = field.get("cards") or []
        hit = next((c for c in cards if c.get("kind") == "TILING_FIELD"), cards[0] if cards else {})
        out["s1Inner_readers"] = (
            "improve" if int(hit.get("readers") or 0) or int(hit.get("reads_edges") or 0) else "keep"
        )
    if name == "IFA":
        true_hit = int((queries.get("HasAttenMask=true") or {}).get("matching_block_count") or 0)
        one_hit = int((queries.get("HasAttenMask=1") or {}).get("matching_block_count") or 0)
        cov = ((queries.get("Dim=HasAttenMask") or {}).get("dim_coverage") or {}).get("HasAttenMask") or []
        out["HasAttenMask=true"] = "improve" if true_hit > 0 else "regress"
        out["HasAttenMask=1"] = "improve" if one_hit > 0 else "keep"
        mixed = any(str(v).lower() in {"true", "false"} for v in cov)
        out["HasAttenMask_canonical"] = "improve" if cov and not mixed else ("keep" if cov else "regress")
    if name == "GMM":
        dim = queries.get("Dim=TRANS_B") or {}
        cov = (dim.get("dim_coverage") or {}).get("TRANS_B") or []
        out["Dim=TRANS_B"] = "improve" if cov or int(dim.get("matching_block_count") or 0) else "regress"
        out["index_has_TRANS_B"] = "improve" if "TRANS_B" in dims else "regress"
        field = queries.get("groupNum") or {}
        cards = field.get("cards") or []
        hit = next((c for c in cards if c.get("kind") == "TILING_FIELD"), cards[0] if cards else {})
        out["groupNum_readers"] = (
            "improve" if int(hit.get("readers") or 0) or int(hit.get("reads_edges") or 0) else "keep"
        )
    return out


def rebuild(name: str, root: Path) -> dict[str, Any]:
    from uo_init.codemap_engines import analyze, commit, verify

    os.environ["UO_ARCH"] = ARCH
    os.environ["UO_TIMING"] = "1"
    ctx = {
        "op_name": root.name,
        "architecture": ARCH,
        "arch_dir": ARCH,
        "auto_accept_clean": True,
        "force_confirm": True,
        "decision": "confirm",
    }
    stages: dict[str, Any] = {}
    for label, fn in (("analyze", analyze), ("commit", commit), ("verify", verify)):
        t0 = time.perf_counter()
        print(f"  {name} {label} …", flush=True)
        out = fn(root, ctx)
        dt = round(time.perf_counter() - t0, 3)
        stages[label] = {
            "elapsed_s": dt,
            "ok": bool(out.get("ok")),
            "error": out.get("error"),
            "path": out.get("path"),
        }
        print(f"  {name} {label} {dt:.1f}s ok={out.get('ok')} error={out.get('error')}", flush=True)
        if not out.get("ok"):
            break
    return stages


def main(argv: list[str]) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    mode = argv[1] if len(argv) > 1 else "all"
    names = argv[2:] or list(OPS)
    names = [n.upper() for n in names]
    if mode in {"snapshot", "all"}:
        before: dict[str, Any] = {}
        for name in names:
            print(f"snapshot {name}", flush=True)
            queries = snapshot_op(name, OPS[name])
            before[name] = {"queries": queries, "verdict": judge(name, queries)}
            print(json.dumps(before[name]["verdict"], ensure_ascii=False), flush=True)
        (OUT / "before.json").write_text(
            json.dumps(before, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    if mode in {"rebuild", "all"}:
        stages: dict[str, Any] = {}
        for name in names:
            print(f"rebuild {name}", flush=True)
            stages[name] = rebuild(name, OPS[name])
        (OUT / "rebuild.json").write_text(
            json.dumps(stages, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    if mode in {"after", "all"}:
        after: dict[str, Any] = {}
        for name in names:
            print(f"after {name}", flush=True)
            queries = snapshot_op(name, OPS[name])
            after[name] = {"queries": queries, "verdict": judge(name, queries)}
            print(json.dumps(after[name]["verdict"], ensure_ascii=False), flush=True)
        (OUT / "after.json").write_text(
            json.dumps(after, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
