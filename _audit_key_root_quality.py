#!/usr/bin/env python3
"""Audit whether rooted TilingKeys are falsely closed / missing real assignments."""
from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from uo_init.diagnostics.audit import _ROOT_FLOW_KINDS, _ROOT_KINDS, _source_rooted_entities
from uo_init.ir.codemap import EntityKind
from uo_init.passes import host_defuse as hd
from uo_init.store.reader import find_uo_product, read_codemap

OP = Path("/mnt/d/TEST/ops-transformer/attention/flash_attention_score_grad")
ARCH = "arch35"


def _rev(cm):
    rev = defaultdict(list)
    for rel in cm.relations.values():
        rev[rel.dst].append(rel)
    return rev


def _collect_defuse(cm, start_id: str) -> list[dict[str, Any]]:
    rev = _rev(cm)
    out = []
    q = deque([start_id])
    seen = {start_id}
    while q:
        cur = q.popleft()
        for rel in rev.get(cur, []):
            if rel.kind_name() != "DERIVES":
                continue
            if rel.attrs.get("provenance") != "source_host_defuse" and not str(
                rel.src
            ).startswith("HOSTDEF::"):
                # still walk, but only record HOSTDEF nodes
                src = rel.src
                if src not in seen:
                    seen.add(src)
                    q.append(src)
                ent = cm.entities.get(src)
                if ent and (
                    ent.attrs.get("provenance") == "source_host_defuse"
                    or str(src).startswith("HOSTDEF::")
                ):
                    out.append(
                        {
                            "eid": src,
                            "name": ent.name,
                            "file": ent.file,
                            "line": ent.line_start,
                            "lhs": ent.attrs.get("lhs"),
                            "expression": (ent.attrs.get("expression") or ent.name)[:220],
                            "guards": ent.attrs.get("guards") or [],
                        }
                    )
                continue
            src = rel.src
            ent = cm.entities.get(src)
            if ent and (
                ent.attrs.get("provenance") == "source_host_defuse"
                or str(src).startswith("HOSTDEF::")
            ):
                out.append(
                    {
                        "eid": src,
                        "name": ent.name,
                        "file": ent.file,
                        "line": ent.line_start,
                        "lhs": ent.attrs.get("lhs"),
                        "expression": (ent.attrs.get("expression") or ent.name)[:220],
                        "guards": ent.attrs.get("guards") or [],
                    }
                )
            if src not in seen:
                seen.add(src)
                q.append(src)
    # unique by eid
    uniq = {}
    for row in out:
        uniq[row["eid"]] = row
    return list(uniq.values())


def _root_stats(cm, start_id: str, rooted: set[str]):
    rev = _rev(cm)
    q = deque([start_id])
    seen = {start_id}
    roots = []
    via_compile = 0
    via_input = 0
    via_macro = 0
    defuse_edges = 0
    while q:
        cur = q.popleft()
        for rel in rev.get(cur, []):
            if rel.kind_name() not in _ROOT_FLOW_KINDS:
                continue
            if rel.attrs.get("provenance") == "source_host_defuse":
                defuse_edges += 1
            src = rel.src
            ent = cm.entities.get(src)
            if ent and ent.kind_name() in _ROOT_KINDS:
                roots.append((ent.kind_name(), ent.name, rel.attrs.get("provenance")))
                if ent.kind_name() == "COMPILE_VAR":
                    via_compile += 1
                elif ent.kind_name() == "INPUT":
                    via_input += 1
                elif ent.kind_name() == "MACRO":
                    via_macro += 1
            if src not in seen:
                seen.add(src)
                q.append(src)
    return {
        "root_count": len(roots),
        "via_compile": via_compile,
        "via_input": via_input,
        "via_macro": via_macro,
        "defuse_edges_seen": defuse_edges,
        "roots_sample": roots[:12],
    }


def _assignment_lookup(by_exact, by_short, symbol: str):
    n = hd._norm(symbol)
    exact = list(by_exact.get(n) or [])
    short = list(by_short.get(hd._short(n)) or [])
    spellings = {r.lhs for r in short}
    chosen = list(exact)
    reason = "exact"
    if not chosen:
        if len(spellings) == 1:
            chosen = short
            reason = "short_unique"
        elif len(spellings) > 1:
            chosen = []
            reason = f"short_ambiguous:{sorted(spellings)}"
        else:
            reason = "none"
    # also compute preferred qualified if we were smarter
    preferred = [r for r in short if "." in r.lhs or "->" in r.lhs]
    defaults = [r for r in short if "." not in r.lhs and "->" not in r.lhs]
    return {
        "symbol": symbol,
        "exact": len(exact),
        "short": len(short),
        "spellings": sorted(spellings),
        "engine_reason": reason,
        "engine_chosen": [
            f"{r.file}:{r.line}:{r.lhs}=<{r.rhs[:60].replace(chr(10),' ')}>" for r in chosen[:5]
        ],
        "qualified_candidates": [
            f"{r.file}:{r.line}:{r.lhs}" for r in preferred[:8]
        ],
        "bare_default_candidates": [
            f"{r.file}:{r.line}:{r.lhs}={r.rhs[:40]}" for r in defaults[:8]
        ],
        "missed_if_ambiguous": [
            f"{r.file}:{r.line}:{r.lhs}" for r in preferred if reason.startswith("short_ambiguous")
        ],
    }


def main() -> None:
    uo = find_uo_product(OP, op_name="flash_attention_score_grad", architecture=ARCH)
    cm = read_codemap(uo)
    rooted_ids = _source_rooted_entities(cm)
    keys = sorted(
        (e for e in cm.by_kind(EntityKind.TILING_KEY) if e.attrs.get("source_declared")),
        key=lambda e: int(e.attrs.get("decl_order") or 0),
    )

    # parse assignments
    host_dir = OP / "op_host" / ARCH
    records = []
    for path in sorted(host_dir.rglob("*")):
        if path.suffix.lower() not in {".cpp", ".h", ".hpp", ".cc", ".cxx"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        records.extend(hd._assignments(OP, path, text))
    by_exact: dict[str, list] = defaultdict(list)
    by_short: dict[str, list] = defaultdict(list)
    for r in records:
        by_exact[hd._norm(r.lhs)].append(r)
        by_short[hd._short(r.lhs)].append(r)

    print("uo", uo)
    print("declared_keys", len(keys))
    print("host_key_root_trace", cm.meta.get("host_key_root_trace"))
    print()

    reports = []
    for key in keys:
        packing = list(key.attrs.get("host_packing_expressions") or [])
        is_rooted = key.id in rooted_ids
        # packing argument variables
        pack_vars = []
        for rel in cm.relations.values():
            if rel.dst == key.id and rel.kind_name() == "DERIVES":
                pred = cm.entities.get(rel.src)
                if not pred:
                    continue
                for rel2 in cm.relations.values():
                    if rel2.dst == pred.id and rel2.kind_name() == "DERIVES":
                        ent = cm.entities.get(rel2.src)
                        if ent and ent.kind_name() in {"VARIABLE", "FIELD"}:
                            pack_vars.append(ent)

        # unique pack vars
        seen_v = {}
        for v in pack_vars:
            seen_v[v.id] = v
        pack_vars = list(seen_v.values())

        defuse_nodes = []
        for v in pack_vars:
            defuse_nodes.extend(_collect_defuse(cm, v.id))
        # also from packing predicate
        for rel in cm.relations.values():
            if rel.dst == key.id and rel.kind_name() == "DERIVES":
                defuse_nodes.extend(_collect_defuse(cm, rel.src))
        uniq_def = {d["eid"]: d for d in defuse_nodes}
        defuse_nodes = list(uniq_def.values())

        lookups = []
        for v in pack_vars:
            lookups.append(_assignment_lookup(by_exact, by_short, v.name))
            # also without this.
            if v.name.startswith("this."):
                lookups.append(_assignment_lookup(by_exact, by_short, v.name[len("this.") :]))

        stats = _root_stats(cm, key.id, rooted_ids)

        # heuristics for false/weak closure
        flags = []
        if not is_rooted:
            flags.append("UNROOTED")
        if is_rooted and not defuse_nodes:
            flags.append("ROOTED_WITHOUT_HOSTDEF")
        if any(l["engine_reason"].startswith("short_ambiguous") for l in lookups):
            flags.append("ASSIGN_LOOKUP_AMBIGUOUS_DROPPED")
        # rooted only via compile constants and no INPUT
        if is_rooted and stats["via_input"] == 0 and stats["via_compile"] > 0:
            flags.append("COMPILE_ONLY_ROOTS")
        if is_rooted and stats["via_input"] == 0 and stats["via_compile"] == 0:
            flags.append("ROOTED_WITHOUT_INPUT_OR_COMPILE")  # macro/arch/buildvariant
        # defuse only captured default false/true/0 inits
        trivial = []
        for d in defuse_nodes:
            expr = str(d.get("expression") or "").strip()
            if expr in {"false", "true", "0", "1", "nullptr"} or expr.endswith("= false") or expr == "false":
                trivial.append(d)
        non_trivial = [d for d in defuse_nodes if d not in trivial]
        if is_rooted and defuse_nodes and not non_trivial:
            flags.append("ONLY_TRIVIAL_DEFAULT_DEFUSE")
        # missed qualified assignment while only trivial/default linked
        missed_qualified = []
        for l in lookups:
            if l["engine_reason"].startswith("short_ambiguous"):
                missed_qualified.extend(l["missed_if_ambiguous"])
            # even if short_unique, check if chosen is only bare default while qualified exists
            if l["engine_reason"] == "short_unique" and l["bare_default_candidates"] and l["qualified_candidates"]:
                # if engine chose bare
                if any(":" + hd._short(l["symbol"]) + "=<" in c or c.endswith(hd._short(l["symbol"])) for c in []):
                    pass
                chosen_text = " | ".join(l["engine_chosen"])
                if ("." not in chosen_text and "->" not in chosen_text) and l["qualified_candidates"]:
                    flags.append("CHOSE_BARE_DEFAULT_OVER_QUALIFIED")
                    missed_qualified.extend(l["qualified_candidates"])
        # packing member expr but no HOSTDEF at all while source has qualified assign
        if is_rooted:
            for l in lookups:
                if l["exact"] == 0 and l["qualified_candidates"] and not defuse_nodes:
                    flags.append("ROOTED_BUT_MISSED_QUALIFIED_ASSIGN")
                    missed_qualified.extend(l["qualified_candidates"])

        # Compare with IsDrop-style: packing local var usually has HOSTDEF
        report = {
            "key": key.name,
            "rooted": is_rooted,
            "packing": packing,
            "pack_vars": [v.name for v in pack_vars],
            "defuse_count": len(defuse_nodes),
            "nontrivial_defuse": len(non_trivial),
            "trivial_defuse": len(trivial),
            "defuse_sample": [
                f"{d.get('file')}:{d.get('line')} lhs={d.get('lhs')} expr={d.get('expression')}"
                for d in sorted(defuse_nodes, key=lambda x: (str(x.get("file")), int(x.get("line") or 0)))[:6]
            ],
            "lookups": lookups,
            "stats": stats,
            "flags": sorted(set(flags)),
            "missed_qualified_assigns": sorted(set(missed_qualified))[:10],
        }
        reports.append(report)

    # print summary table
    print("=== SUMMARY ===")
    for r in reports:
        flag = ",".join(r["flags"]) if r["flags"] else "ok"
        print(
            f"{r['key']:16} rooted={str(r['rooted']):5} "
            f"defuse={r['defuse_count']:2} nontrivial={r['nontrivial_defuse']:2} "
            f"in={r['stats']['via_input']} cv={r['stats']['via_compile']} "
            f"flags={flag}"
        )

    print("\n=== DETAIL FOR FLAGGED / UNROOTED ===")
    for r in reports:
        if not r["flags"]:
            continue
        print("\n" + "=" * 72)
        print(r["key"], r["flags"])
        print(" packing:", r["packing"])
        print(" pack_vars:", r["pack_vars"])
        print(" defuse_sample:")
        for s in r["defuse_sample"] or ["<none>"]:
            print("  ", s)
        print(" missed_qualified:", r["missed_qualified_assigns"])
        print(" roots_sample:", r["stats"]["roots_sample"])
        for l in r["lookups"]:
            print(
                f"  lookup {l['symbol']}: reason={l['engine_reason']} "
                f"exact={l['exact']} short={l['short']} spellings={l['spellings']}"
            )
            if l["engine_chosen"]:
                print("    chosen:", l["engine_chosen"][:3])
            if l["qualified_candidates"]:
                print("    qualified:", l["qualified_candidates"][:5])
            if l["bare_default_candidates"]:
                print("    bare:", l["bare_default_candidates"][:3])

    print("\n=== POTENTIAL FALSE CLOSURE (rooted but suspicious) ===")
    suspicious = [
        r
        for r in reports
        if r["rooted"]
        and any(
            f in r["flags"]
            for f in (
                "ROOTED_WITHOUT_HOSTDEF",
                "COMPILE_ONLY_ROOTS",
                "ONLY_TRIVIAL_DEFAULT_DEFUSE",
                "CHOSE_BARE_DEFAULT_OVER_QUALIFIED",
                "ROOTED_BUT_MISSED_QUALIFIED_ASSIGN",
                "ASSIGN_LOOKUP_AMBIGUOUS_DROPPED",
            )
        )
    ]
    if not suspicious:
        print("(none by heuristics)")
    for r in suspicious:
        print(
            f"- {r['key']}: {r['flags']} | nontrivial_defuse={r['nontrivial_defuse']} "
            f"input_roots={r['stats']['via_input']} compile_roots={r['stats']['via_compile']}"
        )
        if r["missed_qualified_assigns"]:
            print("  missed assigns:", r["missed_qualified_assigns"])

    # Also list all packing vars with ambiguous lookup regardless of key root
    print("\n=== ALL PACKING VARS WITH AMBIGUOUS SHORT LOOKUP ===")
    seen_sym = set()
    for r in reports:
        for l in r["lookups"]:
            if l["engine_reason"].startswith("short_ambiguous") and l["symbol"] not in seen_sym:
                seen_sym.add(l["symbol"])
                print(
                    f"- {l['symbol']}: spellings={l['spellings']} "
                    f"qualified={l['qualified_candidates'][:4]} bare={l['bare_default_candidates'][:2]}"
                )


if __name__ == "__main__":
    main()
