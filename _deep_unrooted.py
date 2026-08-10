#!/usr/bin/env python3
"""Deep-dive: why IsNzOut/IsTndSwizzle are unrooted vs a rooted key."""
from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path

from uo_init.diagnostics.audit import _ROOT_FLOW_KINDS, _ROOT_KINDS, _source_rooted_entities
from uo_init.ir.codemap import EntityKind
from uo_init.store.reader import find_uo_product, read_codemap

OP = Path("/mnt/d/TEST/ops-transformer/attention/flash_attention_score_grad")
COMPARE = ("IsNzOut", "IsTndSwizzle", "IsDrop", "IsTnd", "SplitAxis", "DeterType")


def ancestors(cm, start_id: str, kinds: set[str], limit: int = 80):
    rev = defaultdict(list)
    for rel in cm.relations.values():
        rev[rel.dst].append(rel)
    q = deque([start_id])
    seen = {start_id}
    rows = []
    while q and len(rows) < limit:
        cur = q.popleft()
        for rel in rev.get(cur, []):
            if rel.kind_name() not in kinds:
                continue
            src = rel.src
            if src in seen:
                continue
            seen.add(src)
            ent = cm.entities.get(src)
            rows.append(
                {
                    "kind": rel.kind_name(),
                    "src_id": src,
                    "src_kind": ent.kind_name() if ent else "?",
                    "src_name": ent.name if ent else "?",
                    "status": getattr(rel, "status", None),
                    "attrs": {
                        k: rel.attrs.get(k)
                        for k in ("provenance", "guard", "file", "line")
                        if k in rel.attrs
                    },
                }
            )
            q.append(src)
    return rows


def all_inbound(cm, eid: str):
    rows = []
    for rel in cm.relations.values():
        if rel.dst != eid:
            continue
        ent = cm.entities.get(rel.src)
        rows.append(
            (
                rel.kind_name(),
                ent.kind_name() if ent else "?",
                ent.name if ent else rel.src,
                rel.src,
                {k: rel.attrs.get(k) for k in ("provenance", "file", "line", "rhs") if k in rel.attrs},
            )
        )
    return rows


def main() -> None:
    uo = find_uo_product(OP, op_name="flash_attention_score_grad", architecture="arch35")
    cm = read_codemap(uo)
    rooted = _source_rooted_entities(cm)
    keys = {e.name: e for e in cm.by_kind(EntityKind.TILING_KEY)}

    print("meta.host_key_root_trace =", cm.meta.get("host_key_root_trace"))
    print("meta.host_tiling_key_packing =", cm.meta.get("host_tiling_key_packing"))

    for name in COMPARE:
        e = keys.get(name)
        print("\n" + "=" * 72)
        print(name, "rooted=" + str(bool(e and e.id in rooted)))
        if not e:
            print("MISSING")
            continue
        print("id", e.id)
        print("packing", e.attrs.get("host_packing_expressions"))
        print("ALL inbound to TILING_KEY:")
        for row in all_inbound(cm, e.id):
            print(" ", row)

        # follow packing predicate if any
        preds = [
            r.src
            for r in cm.relations.values()
            if r.dst == e.id and r.kind_name() == "DERIVES"
        ]
        for pid in preds:
            pent = cm.entities.get(pid)
            print(f"\n packing node {pent.kind_name() if pent else '?'} {pent.name if pent else pid}")
            print("  ALL inbound to packing node:")
            for row in all_inbound(cm, pid):
                print("   ", row)
            # one hop further for FIELD/VARIABLE
            for row in all_inbound(cm, pid):
                _, sk, sn, sid, _ = row
                if sk in {"FIELD", "VARIABLE", "PREDICATE"}:
                    print(f"\n  drill {sk} {sn}:")
                    for r2 in all_inbound(cm, sid):
                        print("    ", r2)

        print("\n ROOT_FLOW ancestors (DERIVES/FLOWS_TO/CONTROLS):")
        for row in ancestors(cm, e.id, _ROOT_FLOW_KINDS, limit=40):
            mark = "ROOT" if row["src_kind"] in _ROOT_KINDS else ("R" if row["src_id"] in rooted else ".")
            print(f"  [{mark}] <-{row['kind']}- {row['src_kind']} {row['src_name']}")

        print("\n ANY-edge ancestors (first 40, excluding CALLS explosion filter):")
        interesting = {
            "DERIVES",
            "FLOWS_TO",
            "CONTROLS",
            "WRITES",
            "READS",
            "BINDS",
            "SELECTS",
            "GUARDED_BY",
            "DECLARES",
            "REFERENCES",
        }
        for row in ancestors(cm, e.id, interesting, limit=50):
            mark = "ROOT" if row["src_kind"] in _ROOT_KINDS else ("R" if row["src_id"] in rooted else ".")
            print(f"  [{mark}] <-{row['kind']}- {row['src_kind']} {row['src_name']} {row['attrs']}")


if __name__ == "__main__":
    main()
