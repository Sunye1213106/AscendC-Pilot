# -*- coding: utf-8 -*-
"""Run K6 over the cached derivation and report what it can decide.

`_probe_derive.py` answers "how faithfully is each dimension derived"; this
answers the question after it: given those expressions, how many of the legal
TilingKeys can the solver actually rule in or out. The full export
(`uo_tg_rebuild_and_probe.py`) reaches the same numbers but folds the kernel on
the way, which costs minutes -- too slow to iterate against.

Reads the artifacts `_probe_derive.py` leaves in `.probe_cache/`, so run that
first.

    python scripts/_probe_reach.py            # summary
    python scripts/_probe_reach.py --omitted  # why each dropped dimension dropped
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "engines" / "understand-operator" / "src"
sys.path.insert(0, str(SRC))

CACHE = ROOT / ".probe_cache"
BUNDLE = CACHE / "fag_bundle.pkl"
RESULT = CACHE / "fag_derive.json"
REACH = CACHE / "fag_reach.json"
HISTORY = ROOT / "docs" / "debug" / "reach-history.jsonl"


def load():
    if not (BUNDLE.is_file() and RESULT.is_file()):
        raise SystemExit("no cached derivation; run scripts/_probe_derive.py first")
    with BUNDLE.open("rb") as fh:
        bundle = pickle.load(fh)
    doc_raw = json.loads(RESULT.read_text(encoding="utf-8"))["host_derivation"]

    from uo_init.host_derivation import HostDerivation, _reregister_soft_vars, _to_field
    from uo_init.tpl_bind import merge_literal_encode_alts

    doc = HostDerivation(
        op_name=str(doc_raw.get("op_name") or ""),
        architecture=str(doc_raw.get("architecture") or ""),
        fields=[_to_field(row, None) for row in doc_raw.get("fields") or []],
    )
    var_model = bundle["var_model"]
    _reregister_soft_vars(var_model, doc)
    binding = bundle.get("binding")
    if binding is not None and bundle.get("host_ir") is not None:
        binding = merge_literal_encode_alts(binding, bundle["host_ir"])
    return doc, var_model, bundle["tpl_schema"], binding


def _first_symbol(why: str) -> str:
    """The symbol out of an `omitted` reason like `unmodelled_variable(x)`."""
    if why.endswith(")") and "(" in why:
        return why[why.index("(") + 1 : -1]
    return why


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--omitted", action="store_true", help="list dropped dimensions")
    ap.add_argument("--limit", type=int, default=0, help="only the first N keys")
    ap.add_argument("--timeout", type=int, default=5000, help="solver ms per query")
    ap.add_argument("--rlimit", type=int, default=None, help="solver steps per query")
    ap.add_argument("--hard-timeout", type=int, default=None, help="watchdog ms, 0 disables")
    args = ap.parse_args()

    doc, var_model, schema, binding = load()

    from uo_init import key_reachability as kr
    from uo_init.key_reachability import KeyReachability
    from uo_init.materialize_tiling import build_legal_key_rows

    reach = KeyReachability.from_derivation(
        doc,
        var_model,
        timeout_ms=args.timeout,
        rlimit=kr.DEFAULT_RLIMIT if args.rlimit is None else args.rlimit,
        hard_timeout_ms=(
            kr.DEFAULT_HARD_TIMEOUT_MS if args.hard_timeout is None else args.hard_timeout
        ),
    )

    summary = reach.summary()
    omitted = summary["omitted"]
    print(
        f"dimensions modelled : {summary['dimensions_compiled']}/{summary['dimensions_total']}"
        f"  (exact {summary['dimensions_exact']})"
    )
    blockers = summary.get("blockers") or {}
    print(f"dimensions omitted  : {len(omitted)}")
    for name, why in sorted(omitted.items()):
        rest = sorted(set(blockers.get(name, {})) - {_first_symbol(why)})
        tail = f"  (+{len(rest)}: {', '.join(rest)})" if rest else ""
        print(f"  - {name}: {why}{tail}")

    softened = summary.get("softened") or {}
    if softened:
        print(f"\ndimensions on free variables: {len(softened)}")
        for name, names in sorted(softened.items()):
            print(f"  {name:16} {', '.join(names)}")

    if blockers:
        # Sorted by how many dimensions a symbol blocks: closing one that only
        # ever appears alongside others buys nothing on its own.
        cost: Counter[str] = Counter()
        for names in blockers.values():
            cost.update(names.keys())
        print("\nblocking symbols, by dimensions blocked:")
        for symbol, count in cost.most_common():
            where = sorted(n for n, names in blockers.items() if symbol in names)
            print(f"  {count}  {symbol:28} {', '.join(where)}")
    if summary.get("identity_isolated"):
        print(f"identity isolated   : {len(summary['identity_isolated'])}")

    rows = build_legal_key_rows(
        schema, binding=binding, blocker_ids=[], reachability=reach
    )
    if args.limit:
        rows = rows[: args.limit]

    status = Counter(r.status for r in rows)
    print(f"\nlegal keys          : {len(rows)}")
    for name, count in status.most_common():
        print(f"  {name:14} {count:6}  {100 * count / len(rows):5.1f}%")

    detail = Counter(r.detail for r in rows if r.detail)
    if detail:
        print("\ntop verdict reasons:")
        for text, count in detail.most_common(8):
            print(f"  {count:6}  {text[:110]}")

    if args.limit:
        # A partial sweep would read as a collapse in the history.
        return 0

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "op": doc.op_name,
        "arch": doc.architecture,
        "dimensions_total": summary["dimensions_total"],
        "dimensions_compiled": summary["dimensions_compiled"],
        "omitted": omitted,
        "blockers": blockers,
        "legal_keys": len(rows),
        "status": dict(status),
    }
    CACHE.mkdir(parents=True, exist_ok=True)
    REACH.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"\nwrote {REACH}, {HISTORY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
