#!/usr/bin/env python3
"""Explain why IsNzOut / IsTndSwizzle are unrooted in the current .uo."""
from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path

from uo_init.diagnostics.audit import _ROOT_FLOW_KINDS, _ROOT_KINDS, _source_rooted_entities
from uo_init.store.reader import find_uo_product, read_codemap

OP = Path("/mnt/d/TEST/ops-transformer/attention/flash_attention_score_grad")
NAMES = ("IsNzOut", "IsTndSwizzle")


def main() -> None:
    uo = find_uo_product(OP, op_name="flash_attention_score_grad", architecture="arch35")
    cm = read_codemap(uo)
    rooted = _source_rooted_entities(cm)
    print("ROOT_KINDS", sorted(_ROOT_KINDS))
    print("ROOT_FLOW_KINDS", sorted(_ROOT_FLOW_KINDS))
    print("uo", uo)

    # reverse adjacency for root-path search
    rev: dict[str, list[tuple[str, str]]] = defaultdict(list)
    fwd: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for rel in cm.relations.values():
        kind = rel.kind_name()
        fwd[rel.src].append((kind, rel.dst))
        rev[rel.dst].append((kind, rel.src))

    keys = {e.name: e for e in cm.by_kind(__import__("uo_init.ir.codemap", fromlist=["EntityKind"]).EntityKind.TILING_KEY)}
    from uo_init.ir.codemap import EntityKind

    keys = {e.name: e for e in cm.by_kind(EntityKind.TILING_KEY)}
    for name in NAMES:
        e = keys.get(name)
        print("\n====", name, "====")
        if e is None:
            print("missing entity")
            continue
        print("id", e.id)
        print("in_rooted_closure", e.id in rooted)
        pack = e.attrs.get("host_packing_expressions")
        print("host_packing_expressions", repr(pack)[:500] if pack else None)
        for k in (
            "source_declared",
            "decl_order",
            "bit_width",
            "domain",
            "producer",
            "value_expr",
            "exactness",
            "rooted_by_current_source",
            "upstream_unresolved",
        ):
            if k in e.attrs:
                print(f"  attr.{k}=", repr(e.attrs[k])[:240])

        # inbound / outbound relations
        inbound = [(k, s) for k, s in rev.get(e.id, [])]
        outbound = [(k, d) for k, d in fwd.get(e.id, [])]
        print("inbound", len(inbound), "kinds", sorted({k for k, _ in inbound}))
        print("outbound", len(outbound), "kinds", sorted({k for k, _ in outbound}))
        for kind, src in inbound[:20]:
            ent = cm.entities.get(src)
            print(
                f"  <-{kind}- {src} kind={ent.kind_name() if ent else '?'} name={ent.name if ent else '?'} rooted={src in rooted}"
            )
            if ent:
                for ak in ("value_expr", "compile_root", "provenance", "rhs", "api_kind"):
                    if ak in ent.attrs:
                        print(f"      {ak}={repr(ent.attrs[ak])[:200]}")

        # BFS reverse through ROOT_FLOW_KINDS to see nearest ancestors / blockage
        q = deque([e.id])
        seen = {e.id}
        parents: dict[str, tuple[str, str] | None] = {e.id: None}
        found_roots = []
        while q and len(seen) < 5000:
            cur = q.popleft()
            ent = cm.entities.get(cur)
            if ent and ent.kind_name() in _ROOT_KINDS:
                found_roots.append(cur)
                continue
            for kind, src in rev.get(cur, []):
                if kind not in _ROOT_FLOW_KINDS:
                    continue
                if src not in seen:
                    seen.add(src)
                    parents[src] = (kind, cur)
                    q.append(src)
        print("reachable_roots_via_ROOT_FLOW", len(found_roots))
        for rid in found_roots[:10]:
            ent = cm.entities.get(rid)
            print(f"  ROOT {ent.kind_name() if ent else '?'} {ent.name if ent else rid}")

        # also show packing-related vars that share name fragment
        needle = "isNzOut" if name == "IsNzOut" else "isTndSwizzle"
        hits = [
            ent
            for ent in cm.entities.values()
            if needle.lower() in (ent.name or "").lower() or needle.lower() in ent.id.lower()
        ]
        print("name_hits", len(hits))
        for ent in hits[:15]:
            print(
                f"  {ent.kind_name()} {ent.name!r} id={ent.id} rooted={ent.id in rooted} attrs={ {k:ent.attrs.get(k) for k in ('value_expr','compile_root','provenance','upstream_unresolved','rooted_by_current_source') if k in ent.attrs} }"
            )
            # immediate inbound derives/controls/flows
            for kind, src in rev.get(ent.id, [])[:8]:
                sent = cm.entities.get(src)
                print(
                    f"    <-{kind}- {sent.kind_name() if sent else '?'} {sent.name if sent else src} rooted={src in rooted}"
                )


if __name__ == "__main__":
    main()
