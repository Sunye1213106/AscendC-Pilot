#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agent-style UO-first query for IsNzOut / IsTndSwizzle, then minimal source verify."""
from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from pathlib import Path

from uo_init.query.engine import CodeMapQuery
from uo_init.store.reader import read_codemap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind

UO = Path(r"D:\PR-review\AscendC-Pilot\artifacts\fa-pr13\flash_attention_score_grad.arch35.uo")
OP = Path(r"D:\PR-review\TEST\ops-transformer\attention\flash_attention_score_grad")
VALUE_KINDS = {RelationKind.DERIVES.value, RelationKind.FLOWS_TO.value}


def src_line(file: str, line: int) -> str:
    rel = file.replace("\\", "/")
    if rel.startswith("flash_attention_score_grad/"):
        rel = rel[len("flash_attention_score_grad/") :]
    path = OP / rel
    if not path.is_file():
        return f"<missing {path}>"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if line < 1 or line > len(lines):
        return f"<oob {line}>"
    return lines[line - 1].rstrip()


def src_window(file: str, line: int, before: int = 2, after: int = 8) -> list[str]:
    rel = file.replace("\\", "/")
    if rel.startswith("flash_attention_score_grad/"):
        rel = rel[len("flash_attention_score_grad/") :]
    path = OP / rel
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    lo = max(1, line - before)
    hi = min(len(lines), line + after)
    return [f"{i}|{lines[i-1].rstrip()}" for i in range(lo, hi + 1)]


def main() -> None:
    t0 = time.perf_counter()
    q = CodeMapQuery(read_codemap(UO), path=str(UO))
    cm = q.codemap
    t_load = time.perf_counter() - t0

    report: dict = {"load_s": round(t_load, 4), "keys": {}, "input_hits": {}, "gaps": []}

    # 1) tiling key contract via query API
    t1 = time.perf_counter()
    keys = {row["name"]: row for row in q.tiling_keys()}
    for name in ("IsNzOut", "IsTndSwizzle"):
        row = keys[name]
        path_to_kernel = q.find_path(name, end_kind="KERNEL")
        report["keys"][name] = {
            "decl_order": row.get("decl_order"),
            "bit_offset": row.get("bit_offset"),
            "packing": row.get("host_packing_expressions"),
            "path_to_kernel": [f"{e['kind']}:{e['name']}" for e in path_to_kernel],
        }

    # 2) packing symbols + producer predicates from graph
    inc = defaultdict(list)
    for r in cm.relations.values():
        inc[r.dst].append(r)

    for sym in ("fBaseParams.isNzOut", "tndBaseInfo.isTndSwizzle"):
        ents = [e for e in cm.entities.values() if e.name == sym]
        assert ents, sym
        e = next(x for x in ents if x.attrs.get("host_key_argument"))
        preds = []
        for r in inc[e.id]:
            if r.kind_name() != RelationKind.DERIVES.value:
                continue
            s = cm.entities[r.src]
            if s.kind_name() == EntityKind.PREDICATE.value:
                preds.append(
                    {
                        "expression": s.name,
                        "file": r.attrs.get("file") or s.file,
                        "line": r.attrs.get("line") or s.line_start,
                        "function": r.attrs.get("function") or s.attrs.get("function"),
                        "guards": s.attrs.get("guards") or [],
                        "lhs": s.attrs.get("lhs"),
                    }
                )
        report["keys"][sym] = {
            "canonical": e.attrs.get("canonical_symbol"),
            "producer_sites": e.attrs.get("producer_sites"),
            "rooted": e.attrs.get("rooted_by_current_source"),
            "upstream_unresolved": e.attrs.get("upstream_unresolved"),
            "assignment_predicates": preds,
        }

    # 3) one-hop / multi-hop dependency skeleton for both symbols
    for sym in ("fBaseParams.isNzOut", "tndBaseInfo.isTndSwizzle"):
        start = next(e.id for e in cm.entities.values() if e.name == sym and e.attrs.get("host_key_argument"))
        q_bfs = deque([(start, 0)])
        seen = {start}
        deps = []
        inputs_reached = []
        unresolved = []
        while q_bfs:
            cur, depth = q_bfs.popleft()
            if depth >= 5:
                continue
            for r in inc[cur]:
                if r.kind_name() not in VALUE_KINDS:
                    continue
                s = cm.entities.get(r.src)
                if not s or s.id in seen:
                    # still record input if already seen? skip
                    if s and s.kind_name() == EntityKind.INPUT.value and s.id not in {x["id"] for x in inputs_reached}:
                        inputs_reached.append({"id": s.id, "name": s.name, "depth": depth + 1, "via": r.attrs.get("provenance")})
                    continue
                if not s:
                    continue
                seen.add(s.id)
                item = {
                    "depth": depth + 1,
                    "kind": s.kind_name(),
                    "name": s.name,
                    "file": s.file,
                    "line": s.line_start,
                    "prov": r.attrs.get("provenance"),
                    "producer_sites": (s.attrs.get("producer_sites") or [])[:4],
                    "expression": s.attrs.get("expression") or (s.name if s.kind_name() == "PREDICATE" else None),
                    "guards": s.attrs.get("guards") or [],
                }
                deps.append(item)
                if s.kind_name() == EntityKind.INPUT.value:
                    inputs_reached.append({"id": s.id, "name": s.name, "depth": depth + 1, "via": r.attrs.get("provenance")})
                if "unresolved" in str(r.attrs.get("provenance") or "") or s.status == "partial":
                    unresolved.append({"name": s.name, "kind": s.kind_name(), "prov": r.attrs.get("provenance"), "status": s.status})
                q_bfs.append((s.id, depth + 1))
        report["keys"][sym]["dep_nodes"] = len(seen)
        report["keys"][sym]["deps_sample"] = [d for d in deps if d["depth"] <= 2][:40]
        report["keys"][sym]["inputs_reached"] = inputs_reached
        report["keys"][sym]["unresolved_sample"] = unresolved[:30]

    # 4) specifically chase enableSwizzle / templateSupportCond via find_symbol + upstream
    for name in ("fBaseParams.enableSwizzle", "templateSupportCond", "fBaseParams.layoutType", "fBaseParams.splitAxis"):
        hits = q.find_symbol(name)
        # Prefer host_key / defuse symbols with producer_sites.
        hits_sorted = sorted(
            hits,
            key=lambda h: (
                0 if h.get("producer_sites") else 1,
                0 if h.get("host_key_argument") else 1,
                int(h.get("line_start") or 10**9),
            ),
        )
        first = hits_sorted[0] if hits_sorted else None
        up = q.upstream(name, limit=24)
        report["keys"][f"chase::{name}"] = {
            "hit_count": len(hits),
            "first": None
            if not first
            else {
                "kind": first["kind"],
                "file": first.get("file"),
                "line": first.get("line_start"),
                "producer_sites": first.get("producer_sites"),
                "expression_attrs": {
                    k: first.get(k)
                    for k in ("expression", "lhs", "guards", "provenance", "canonical_symbol")
                },
            },
            "upstream": [
                {
                    "kind": u.get("kind"),
                    "name": u.get("name"),
                    "file": u.get("file"),
                    "line": u.get("line_start"),
                }
                for u in up[:20]
            ],
        }

    # 5) API surface for comparison completeness
    api = q.operator_api()
    report["api"] = {
        "tensor_inputs": [e["name"] for e in api["tensor_inputs"]],
        "attributes": [e["name"] for e in api["attributes"]],
    }

    # 6) path INPUT -> each key if any
    for key in ("IsNzOut", "IsTndSwizzle"):
        # try from a few likely inputs
        paths = {}
        for inp in ("query", "key", "value", "input_layout", "sparse_mode", "keep_prob", "deterministic"):
            p = q.find_path(inp, end=key)
            if p:
                paths[inp] = [f"{e['kind']}:{e['name']}" for e in p]
        report["input_hits"][key] = paths

    report["query_s"] = round(time.perf_counter() - t1, 4)

    # 7) Minimal source verify: ONLY windows at UO-pointed sites
    t2 = time.perf_counter()
    verify = []
    sites = []
    for sym in ("fBaseParams.isNzOut", "tndBaseInfo.isTndSwizzle"):
        for pred in report["keys"][sym]["assignment_predicates"]:
            sites.append(("assign", pred["file"], int(pred["line"]), pred["expression"][:80]))
        for ps in report["keys"][sym]["producer_sites"] or []:
            sites.append(("producer", ps["file"], int(ps["line"]), ps.get("lhs")))
    # also chase enableSwizzle / templateSupportCond producers from UO
    for name in ("fBaseParams.enableSwizzle", "templateSupportCond"):
        first = report["keys"][f"chase::{name}"]["first"]
        if first and first.get("producer_sites"):
            for ps in first["producer_sites"][:2]:
                sites.append((name, ps["file"], int(ps["line"]), ps.get("lhs")))
        elif first and first.get("file") and first.get("line"):
            sites.append((name, first["file"], int(first["line"]), name))

    for tag, f, ln, note in sites:
        window = src_window(str(f), int(ln), before=1, after=6)
        text = "\n".join(window)
        ok = True
        if note and isinstance(note, str) and len(note) < 40:
            ok = note.split(".")[-1] in text or note in text
        verify.append({"tag": tag, "file": f, "line": ln, "note": note, "ok": ok, "window": window})
    report["source_verify"] = verify
    report["verify_s"] = round(time.perf_counter() - t2, 4)
    report["total_s"] = round(time.perf_counter() - t0, 4)

    # gap heuristics from UO itself
    for sym in ("fBaseParams.isNzOut", "tndBaseInfo.isTndSwizzle"):
        if not report["keys"][sym]["inputs_reached"]:
            report["gaps"].append(f"{sym}: no INPUT entity reached within depth 5 via DERIVES/FLOWS_TO")
        if report["keys"][sym]["unresolved_sample"]:
            report["gaps"].append(
                f"{sym}: unresolved leaves e.g. {[u['name'] for u in report['keys'][sym]['unresolved_sample'][:8]]}"
            )
    for key, paths in report["input_hits"].items():
        if not paths:
            report["gaps"].append(f"find_path(INPUT-ish -> {key}) empty for sampled API names")

    out = Path(__file__).with_name("agent_uo_query_report.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # human summary
    print(f"load={report['load_s']}s query={report['query_s']}s verify={report['verify_s']}s total={report['total_s']}s")
    for name in ("IsNzOut", "IsTndSwizzle"):
        print("\n###", name)
        print("packing:", report["keys"][name]["packing"])
        print("path:", " -> ".join(report["keys"][name]["path_to_kernel"]))
    for sym in ("fBaseParams.isNzOut", "tndBaseInfo.isTndSwizzle"):
        print("\n###", sym)
        for p in report["keys"][sym]["assignment_predicates"]:
            print("ASSIGN@", f"{p['file']}:{p['line']}")
            print(p["expression"])
            print("guards:", p["guards"])
        print("inputs_reached:", report["keys"][sym]["inputs_reached"])
        print("unresolved:", [u["name"] for u in report["keys"][sym]["unresolved_sample"][:12]])
    print("\n### chase producers")
    for name in ("fBaseParams.enableSwizzle", "templateSupportCond", "fBaseParams.layoutType", "fBaseParams.splitAxis"):
        first = report["keys"][f"chase::{name}"]["first"]
        print(name, "->", None if not first else (first.get("file"), first.get("line"), first.get("producer_sites")))
    print("\n### input_hits")
    print(json.dumps(report["input_hits"], ensure_ascii=False, indent=2))
    print("\n### gaps")
    for g in report["gaps"]:
        print("-", g)
    print("\n### source windows (UO-pointed only)")
    for v in verify:
        print(f"\n[{v['tag']}] {v['file']}:{v['line']} ok={v['ok']}")
        print("\n".join(v["window"]))


if __name__ == "__main__":
    main()
