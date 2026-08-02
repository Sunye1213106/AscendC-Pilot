# -*- coding: utf-8 -*-
"""Build the batches a resolve_gaps worker would be handed, from the cache.

The point is to see what a model is actually asked, without paying the three
minutes the derivation costs. `_probe_derive.py --refresh` writes the cache;
this reads it, clusters the gaps and materializes the shards.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))
sys.path.insert(0, str(ROOT / "engines" / "common"))

CACHE = ROOT / ".probe_cache" / "fag_derive.json"


def main(argv: list[str] | None = None) -> int:
    from uo_init.blocker_shards import (
        function_sites,
        materialize_blocker_batches,
        plan_blocker_shards,
    )
    from uo_init.gaps import build_derivation_gap_report
    from uo_init.host_derivation import HostDerivation, _to_field

    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(CACHE))
    ap.add_argument("--out", default=str(ROOT / ".probe_cache" / "resolve_gaps"))
    ap.add_argument(
        "--show",
        type=int,
        default=0,
        help="print the first N blockers as a worker would read them",
    )
    args = ap.parse_args(argv)

    cached = json.loads(Path(args.cache).read_text(encoding="utf-8"))
    saved = cached["host_derivation"]
    doc = HostDerivation(
        op_name=str(saved.get("op_name") or ""),
        architecture=str(saved.get("architecture") or ""),
    )
    doc.fields = [_to_field(row, None) for row in saved.get("fields") or []]
    report = build_derivation_gap_report(doc)
    blockers = [b.to_dict() for b in report.blockers]

    by_reason = Counter(str(b.get("reason_code") or "") for b in blockers)
    print(f"blockers {len(blockers)}  open_fields {report.open_node_count}")
    for reason, n in by_reason.most_common():
        print(f"  {n:3d}  {reason}")

    manifest = plan_blocker_shards(blockers)
    if not manifest.get("ok"):
        print("SHARDING FAILED:", manifest.get("error"))
        return 1
    sites = None
    bundle_path = ROOT / ".probe_cache" / "fag_bundle.pkl"
    if bundle_path.is_file():
        import pickle

        with open(bundle_path, "rb") as fh:
            host_ir = pickle.load(fh).get("host_ir")
        if host_ir is not None:
            sites = function_sites(host_ir)
            print(f"know where {len(sites)} functions live")

    out = Path(args.out)
    materialize_blocker_batches(out, manifest, sites=sites)

    print(f"\n{manifest['shard_count']} shard(s) under {out}")
    import yaml

    for shard in manifest["shards"]:
        path = out / "inputs" / "batches" / f"batch_{shard['shard_id']}.yaml"
        batch = yaml.safe_load(path.read_text(encoding="utf-8"))
        rows = batch.get("blockers") or []
        with_src = [r for r in rows if r.get("source")]
        lines = sum(
            w["line_end"] - w["line_start"] + 1
            for r in with_src
            for w in r["source"]
        )
        print(
            f"  batch_{shard['shard_id']}: {len(rows)} blockers, "
            f"{len(with_src)} carry source ({lines} lines), "
            f"{path.stat().st_size // 1024} KiB"
        )
        for row in rows[: args.show]:
            _show(row)
    return 0


def _show(row: dict) -> None:
    print("\n" + "=" * 78)
    print(f"{row['id']}  {row.get('reason_code')}")
    print(f"  text  : {str(row.get('text') or '')[:200]}")
    print(f"  blocks: {len(row.get('affected_nodes') or [])} nodes")
    names = row.get("readable_vars") or []
    print(f"  may use ({len(names)}): {', '.join(names[:10])}{' …' if len(names) > 10 else ''}")
    for src in (row.get("source") or [])[:1]:
        name = str(src["file"]).rsplit("/", 1)[-1]
        print(f"  source: {name} {src['line_start']}-{src['line_end']} ({src['kind']})")
        for text in src["text"].splitlines()[:16]:
            print("        | " + text)


if __name__ == "__main__":
    raise SystemExit(main())
