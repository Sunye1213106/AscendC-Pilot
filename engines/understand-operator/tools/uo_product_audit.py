#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit a ``.uo`` product: what is in it, what is connected, what is dead weight.

Entity and relation counts say how much was extracted, not how much is worth
carrying. A fact only helps an Agent if it can be *found* (something names it),
*trusted* (it points at a source line) and *reached* (it hangs off the graph the
questions start from). This reports those three separately, plus where the bytes
went, so a product can be judged rather than just measured.

"Reached" is deliberately computed over undirected edges from a small anchor set
-- the operator API, the kernel, tiling keys and pipes -- because those are what
questions actually start from. An entity no walk from an anchor can arrive at is
paid for on every read and answers nothing.

    python tools/uo_product_audit.py
    python tools/uo_product_audit.py --samples 8 --json .perf/audit.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path
from typing import Any

ENGINE = Path(__file__).resolve().parents[1]

#: Where questions start. An entity is useful insofar as some walk from one of
#: these can arrive at it.
ANCHOR_KINDS = ("KERNEL", "INPUT", "OUTPUT", "TILING_KEY", "TILING_DATA", "PIPE", "ARCH")


def find_product(op: Path, arch: str) -> Path | None:
    root = op / ".ascendc-pilot" / arch / "uo"
    hits = sorted(root.glob(f"*.{arch}.uo")) if root.is_dir() else []
    return hits[0] if hits else None


def _table_bytes(con: sqlite3.Connection) -> dict[str, int]:
    """Per-object byte usage via the dbstat virtual table, or empty if absent."""
    try:
        return {
            str(name): int(size)
            for name, size in con.execute(
                "SELECT name, SUM(pgsize) FROM dbstat GROUP BY name"
            )
        }
    except sqlite3.Error:
        return {}


def audit(path: Path, samples: int) -> dict[str, Any]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        return _audit(con, path, samples)
    finally:
        con.close()


def _audit(con: sqlite3.Connection, path: Path, samples: int) -> dict[str, Any]:
    out: dict[str, Any] = {
        "product": str(path),
        "bytes": path.stat().st_size,
        "storage": {},
        "totals": {},
        "by_kind": {},
        "relations_by_kind": {},
        "reach": {},
        "isolated_samples": {},
    }

    sizes = _table_bytes(con)
    if sizes:
        out["storage"] = {
            name: round(n / 1048576, 3)
            for name, n in sorted(sizes.items(), key=lambda kv: -kv[1])
        }

    # --- entity inventory -------------------------------------------------
    rows = list(
        con.execute(
            """
            SELECT id, kind, name, file, line_start
            FROM entity
            """
        )
    )
    total = len(rows)
    out["totals"]["entities"] = total
    out["totals"]["relations"] = int(
        con.execute("SELECT COUNT(*) FROM relation").fetchone()[0]
    )
    for table in ("source_span", "legal_key", "legal_key_dim", "view_blob", "file"):
        try:
            out["totals"][table] = int(
                con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )
        except sqlite3.Error:
            out["totals"][table] = None

    spanned = {
        str(r[0])
        for r in con.execute("SELECT DISTINCT entity_id FROM source_span WHERE entity_id IS NOT NULL")
    }

    # --- degree over undirected edges -------------------------------------
    degree: dict[str, int] = defaultdict(int)
    adjacency: dict[str, list[str]] = defaultdict(list)
    rel_kinds: dict[str, int] = defaultdict(int)
    for src, dst, kind in con.execute("SELECT src, dst, kind FROM relation"):
        rel_kinds[str(kind)] += 1
        s, d = str(src), str(dst)
        degree[s] += 1
        degree[d] += 1
        adjacency[s].append(d)
        adjacency[d].append(s)
    out["relations_by_kind"] = dict(sorted(rel_kinds.items(), key=lambda kv: -kv[1]))

    # --- reachability from the anchors ------------------------------------
    anchors = [str(r["id"]) for r in rows if str(r["kind"]) in ANCHOR_KINDS]
    reached: set[str] = set(anchors)
    queue = deque(anchors)
    while queue:
        node = queue.popleft()
        for nxt in adjacency.get(node, ()):
            if nxt not in reached:
                reached.add(nxt)
                queue.append(nxt)

    per_kind: dict[str, dict[str, Any]] = {}
    isolated_by_kind: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        eid, kind = str(r["id"]), str(r["kind"])
        bucket = per_kind.setdefault(
            kind,
            {"count": 0, "named": 0, "located": 0, "spanned": 0, "isolated": 0, "reached": 0},
        )
        bucket["count"] += 1
        if str(r["name"] or "").strip():
            bucket["named"] += 1
        if str(r["file"] or "").strip() and int(r["line_start"] or 0) > 0:
            bucket["located"] += 1
        if eid in spanned:
            bucket["spanned"] += 1
        if degree.get(eid, 0) == 0:
            bucket["isolated"] += 1
            if len(isolated_by_kind[kind]) < samples:
                label = str(r["name"] or "").strip() or "<unnamed>"
                where = str(r["file"] or "")
                isolated_by_kind[kind].append(
                    f"{label} @ {where}:{r['line_start'] or 0}" if where else label
                )
        if eid in reached:
            bucket["reached"] += 1

    out["by_kind"] = dict(sorted(per_kind.items(), key=lambda kv: -kv[1]["count"]))
    out["isolated_samples"] = {k: v for k, v in isolated_by_kind.items() if v}

    isolated_total = sum(b["isolated"] for b in per_kind.values())
    out["reach"] = {
        "anchors": len(anchors),
        "reached": len(reached & {str(r["id"]) for r in rows}),
        "unreached": total - len(reached & {str(r["id"]) for r in rows}),
        "isolated": isolated_total,
        "named": sum(b["named"] for b in per_kind.values()),
        "located": sum(b["located"] for b in per_kind.values()),
        "spanned": sum(b["spanned"] for b in per_kind.values()),
    }
    return out


def components(path: Path, top: int, min_size: int) -> str:
    """Connected components, largest first, with each one's kind mix.

    A per-kind reach percentage says *that* something is unreachable; it cannot
    say why. REGISTER showed 2,275 entities with zero isolated rows and zero
    reach, which only makes sense if they hold edges among themselves in a
    component the anchors are not in -- a fact about graph shape that only shows
    up when the components are named. Also surfaces the long tail of small
    islands, where a two-node component usually means one edge is missing.
    """
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        kinds = {str(i): str(k) for i, k in con.execute("SELECT id, kind FROM entity")}
        names = {str(i): str(n or "") for i, n in con.execute("SELECT id, name FROM entity")}
        adjacency: dict[str, list[str]] = defaultdict(list)
        for src, dst in con.execute("SELECT src, dst FROM relation"):
            adjacency[str(src)].append(str(dst))
            adjacency[str(dst)].append(str(src))
    finally:
        con.close()

    seen: set[str] = set()
    groups: list[list[str]] = []
    for start in kinds:
        if start in seen:
            continue
        bucket: list[str] = []
        queue = deque([start])
        seen.add(start)
        while queue:
            node = queue.popleft()
            bucket.append(node)
            for nxt in adjacency.get(node, ()):
                if nxt not in seen and nxt in kinds:
                    seen.add(nxt)
                    queue.append(nxt)
        groups.append(bucket)
    groups.sort(key=len, reverse=True)

    lines = [
        f"{len(groups):,} connected components over {len(kinds):,} entities "
        f"(isolated singletons included)",
        "",
    ]
    shown = 0
    for group in groups:
        if len(group) < min_size or shown >= top:
            break
        shown += 1
        mix: dict[str, int] = defaultdict(int)
        for eid in group:
            mix[kinds[eid]] += 1
        has_anchor = any(kinds[e] in ANCHOR_KINDS for e in group)
        flag = "anchored" if has_anchor else "NO ANCHOR -- unreachable"
        top_kinds = ", ".join(
            f"{k}:{n:,}" for k, n in sorted(mix.items(), key=lambda kv: -kv[1])[:6]
        )
        lines.append(f"  {len(group):>7,} entities  [{flag}]")
        lines.append(f"          {top_kinds}")
        if not has_anchor:
            sample = [names[e] for e in group[:4] if names[e]]
            if sample:
                lines.append(f"          e.g. {' | '.join(s[:44] for s in sample)}")

    tail = [g for g in groups if len(g) < min_size]
    if tail:
        singles = sum(1 for g in tail if len(g) == 1)
        lines.append("")
        lines.append(
            f"  tail: {len(tail):,} components smaller than {min_size} "
            f"({singles:,} of them single isolated entities, "
            f"{sum(len(g) for g in tail):,} entities total)"
        )
    return "\n".join(lines)


def isolated(path: Path, top: int) -> str:
    """Break the degree-0 entities down by the things that could explain them.

    A count of 1,920 isolated entities is not actionable; "which pass minted
    them, from which file, under which name shape" is. Grouping by `provenance`
    names the code responsible, grouping by directory catches whole trees that
    should not have been indexed at all, and the name prefixes show when a
    family of macros or registrations was extracted as a block and dropped as a
    block.
    """
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        degree: dict[str, int] = defaultdict(int)
        for src, dst in con.execute("SELECT src, dst FROM relation"):
            degree[str(src)] += 1
            degree[str(dst)] += 1
        rows = list(
            con.execute(
                "SELECT id, kind, IFNULL(name,''), IFNULL(file,''), data FROM entity"
            )
        )
    finally:
        con.close()

    orphans = [r for r in rows if degree.get(str(r[0]), 0) == 0]
    total = len(orphans)
    out = [f"{total:,} isolated entities (degree 0) out of {len(rows):,}", ""]

    by_kind: Counter[str] = Counter()
    by_prov: Counter[str] = Counter()
    by_dir: Counter[str] = Counter()
    prov_by_kind: dict[str, Counter[str]] = defaultdict(Counter)
    dir_by_kind: dict[str, Counter[str]] = defaultdict(Counter)
    prefix_by_kind: dict[str, Counter[str]] = defaultdict(Counter)

    for _eid, kind, name, file, data in orphans:
        k = str(kind)
        by_kind[k] += 1
        try:
            blob = json.loads(data or "{}")
        except json.JSONDecodeError:
            blob = {}
        attrs = blob.get("attrs") if isinstance(blob.get("attrs"), dict) else blob
        prov = str((attrs or {}).get("provenance") or "<none>")
        by_prov[prov] += 1
        prov_by_kind[k][prov] += 1
        norm = str(file).replace("\\", "/")
        folder = norm.rsplit("/", 1)[0] if "/" in norm else (norm or "<no file>")
        by_dir[folder] += 1
        dir_by_kind[k][folder] += 1
        # Family prefix: leading run of caps/underscores, else the first token.
        text = str(name)
        match = re.match(r"^[A-Z][A-Z0-9_]{3,}", text)
        prefix_by_kind[k][(match.group(0) if match else text[:14]) or "<unnamed>"] += 1

    out.append("by minting pass (provenance)")
    for prov, n in by_prov.most_common(top):
        out.append(f"  {n:>6}  {_pct(n, total)}  {prov}")

    out.append("")
    out.append("by directory")
    for folder, n in by_dir.most_common(top):
        out.append(f"  {n:>6}  {_pct(n, total)}  {folder}")

    out.append("")
    out.append("per kind, with the pass and place responsible")
    for kind, n in by_kind.most_common(top):
        out.append(f"\n  {kind}  {n:,} isolated  {_pct(n, total)}")
        provs = ", ".join(f"{p}:{c}" for p, c in prov_by_kind[kind].most_common(3))
        out.append(f"      pass:  {provs}")
        dirs = ", ".join(f"{d}:{c}" for d, c in dir_by_kind[kind].most_common(2))
        out.append(f"      where: {dirs}")
        fams = ", ".join(f"{p}*:{c}" for p, c in prefix_by_kind[kind].most_common(4))
        out.append(f"      names: {fams}")
    return "\n".join(out)


def _pct(n: int, d: int) -> str:
    return f"{(100.0 * n / d):5.1f}%" if d else "    - "


def report(a: dict[str, Any]) -> str:
    total = a["totals"]["entities"]
    lines: list[str] = []
    lines.append(f"product      {a['product']}")
    lines.append(f"size         {a['bytes'] / 1048576:.2f} MB")
    lines.append(
        f"entities     {total:,}    relations {a['totals']['relations']:,}"
        f"    spans {a['totals'].get('source_span') or 0:,}"
        f"    legal_keys {a['totals'].get('legal_key') or 0:,}"
    )

    if a["storage"]:
        lines.append("\nwhere the bytes are (MB)")
        for name, mb in list(a["storage"].items())[:14]:
            if mb >= 0.05:
                lines.append(f"  {mb:8.2f}  {name}")

    r = a["reach"]
    lines.append("\nis a fact usable")
    lines.append(f"  named (findable by a query)     {r['named']:>7,}  {_pct(r['named'], total)}")
    lines.append(f"  located (has file:line)         {r['located']:>7,}  {_pct(r['located'], total)}")
    lines.append(f"  spanned (has a source span)     {r['spanned']:>7,}  {_pct(r['spanned'], total)}")
    lines.append(
        f"  reached from {r['anchors']} anchors"
        f"{'':>{max(0, 14 - len(str(r['anchors'])))}}{r['reached']:>7,}  {_pct(r['reached'], total)}"
    )
    lines.append(f"  isolated (degree 0)             {r['isolated']:>7,}  {_pct(r['isolated'], total)}")

    lines.append("\nby kind" + " " * 17 + "count   named  located  reached  isolated")
    for kind, b in a["by_kind"].items():
        c = b["count"]
        lines.append(
            f"  {kind:<22}{c:>7,}  {_pct(b['named'], c)}  {_pct(b['located'], c)}"
            f"  {_pct(b['reached'], c)}  {b['isolated']:>7,}"
        )

    lines.append("\nrelations by kind")
    for kind, n in list(a["relations_by_kind"].items())[:24]:
        lines.append(f"  {kind:<22}{n:>8,}")

    if a["isolated_samples"]:
        lines.append("\nisolated samples (paid for on every read, reachable by nothing)")
        for kind, rows in sorted(
            a["isolated_samples"].items(),
            key=lambda kv: -a["by_kind"][kv[0]]["isolated"],
        ):
            lines.append(f"  {kind}  ({a['by_kind'][kind]['isolated']:,} isolated)")
            for row in rows:
                lines.append(f"      {row}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="audit a .uo product")
    ap.add_argument("--op", type=Path, default=None)
    ap.add_argument("--arch", default=None)
    ap.add_argument("--product", type=Path, default=None)
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument(
        "--components",
        action="store_true",
        help="report connected components and their kind mix instead of the inventory",
    )
    ap.add_argument(
        "--isolated",
        action="store_true",
        help="attribute the degree-0 entities to a pass, a directory and a name family",
    )
    ap.add_argument("--top", type=int, default=12, help="components to show")
    ap.add_argument("--min-size", type=int, default=2, help="smallest component to show")
    args = ap.parse_args(argv)

    product = args.product
    if product is None:
        op = args.op or Path(os.environ.get("UO_OP_DIR") or "")
        arch = args.arch or os.environ.get("UO_ARCH") or ""
        if not op.is_dir() or not arch:
            print("pass --product, or --op/--arch (or set UO_OP_DIR/UO_ARCH)")
            return 2
        product = find_product(op, arch)
    if product is None or not product.is_file():
        print(f"no product found: {product}")
        return 2

    if args.components:
        print(components(product, args.top, args.min_size))
        return 0

    if args.isolated:
        print(isolated(product, args.top))
        return 0

    a = audit(product, args.samples)
    print(report(a))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(a, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
