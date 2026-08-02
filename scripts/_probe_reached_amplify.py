# -*- coding: utf-8 -*-
"""Root-cause probe: how _reached soft bool amplifies VAR_INIT / VAR_UNDECIDED.

Reads `.probe_cache/fag_bundle.pkl` + `fag_derive.json`. Optionally re-derives
selected dimensions under monkey-patches.

    python scripts/_probe_reached_amplify.py                 # cache analysis
    python scripts/_probe_reached_amplify.py --ablate        # + A/B patches
    python scripts/_probe_reached_amplify.py --ablate --fields SplitAxis DeterType
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import pickle
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "engines" / "understand-operator" / "src"
sys.path.insert(0, str(SRC))

CACHE = ROOT / ".probe_cache"
BUNDLE = CACHE / "fag_bundle.pkl"
RESULT = CACHE / "fag_derive.json"
OUT = CACHE / "reached_amplify.json"

DEFAULT_FIELDS = [
    "SplitAxis",
    "IsBn2MultiBlk",
    "IsNzOut",
    "IsTndSwizzle",
    "DeterType",
]


def prefix_of(var: str) -> str:
    for p in (
        "VAR_INIT_",
        "VAR_UNDECIDED_",
        "VAR_LOOPELEM_",
        "VAR_REACHED_",
        "VAR_SCHED_",
    ):
        if var.startswith(p):
            return p.rstrip("_")
    return "OTHER"


def encode_path_of(ir, enc: str) -> set[str]:
    out: set[str] = set()
    fn = enc.split("::")[-1] if enc else ""
    while fn and fn not in out:
        out.add(fn)
        calls = list(ir.calls_to(fn)) if hasattr(ir, "calls_to") else []
        if len(calls) != 1:
            break
        fn = str(getattr(calls[0], "caller", "") or "").split("::")[-1]
    return out


def analyze_cache(blob, ir) -> dict:
    fields = blob.get("fields") or []
    all_free: set[str] = set()
    free_occ: Counter = Counter()
    init_recs: dict[str, dict] = {}
    undecided_recs: dict[str, dict] = {}

    for fld in fields:
        for v in fld.get("free_vars") or []:
            all_free.add(v)
            free_occ[prefix_of(v)] += 1
        for d in fld.get("implicit_defaults") or []:
            vid = d.get("variable")
            if not vid:
                continue
            if vid not in init_recs:
                init_recs[vid] = {**d, "seen_in": [fld.get("name")]}
            else:
                init_recs[vid].setdefault("seen_in", []).append(fld.get("name"))
        for g in fld.get("undecided_guards") or []:
            vid = g.get("var_id")
            if not vid:
                continue
            if vid not in undecided_recs:
                undecided_recs[vid] = {**g, "seen_in": [fld.get("name")]}
            else:
                undecided_recs[vid].setdefault("seen_in", []).append(fld.get("name"))

    enc = blob.get("encode_function") or "GetTilingKey"
    epath = encode_path_of(ir, enc)

    init_rows = []
    for vid, rec in sorted(init_recs.items()):
        if vid not in all_free:
            continue
        fn = rec.get("function") or ""
        short = fn.split("::")[-1]
        calls = list(ir.calls_to(short)) if hasattr(ir, "calls_to") else []
        orphan = len(calls) == 0
        on_encode = short in epath
        # Current _reached: no sites => Const(True) iff on encode path, else soft
        # => _always_runs False. That is the covered_in failure mode for members.
        fail_ar = orphan and not on_encode
        init_rows.append(
            {
                "var": vid,
                "field": rec.get("field"),
                "function": fn,
                "file": rec.get("file"),
                "line": rec.get("line"),
                "guard": (rec.get("guard") or "")[:160],
                "seen_in": sorted(set(rec.get("seen_in") or [])),
                "n_call_sites": len(calls),
                "on_encode_path": on_encode,
                "orphan_no_calls": orphan,
                "predicted_always_runs_false": fail_ar,
                "callers": [
                    f"{getattr(c, 'caller', '?')}@{getattr(c, 'line', 0)}"
                    for c in calls[:6]
                ],
            }
        )

    und_rows = []
    for vid, g in sorted(undecided_recs.items()):
        if vid not in all_free or not vid.startswith("VAR_UNDECIDED_"):
            continue
        text = g.get("text") or ""
        reason = g.get("reason") or ""
        has_reached = "__reached_" in text or "__reached_" in reason
        und_rows.append(
            {
                "var": vid,
                "presort": g.get("presort"),
                "reason": reason[:140],
                "blocked_on": g.get("blocked_on"),
                "has___reached_": has_reached,
                "text_head": text[:200],
                "seen_in": sorted(set(g.get("seen_in") or [])),
            }
        )

    distinct_prefix = Counter(prefix_of(v) for v in all_free)
    return {
        "totals_from_cache": blob.get("totals"),
        "distinct_free": len(all_free),
        "distinct_by_prefix": dict(distinct_prefix),
        "occurrences_by_prefix": dict(free_occ),
        "encode_function": enc,
        "encode_path": sorted(epath),
        "var_init": {
            "distinct_in_free": len(init_rows),
            "predicted_always_runs_false": sum(
                1 for r in init_rows if r["predicted_always_runs_false"]
            ),
            "have_call_sites": sum(1 for r in init_rows if r["n_call_sites"] > 0),
            "on_encode_path": sum(1 for r in init_rows if r["on_encode_path"]),
            "rows": init_rows,
        },
        "var_undecided": {
            "distinct_in_free": len(und_rows),
            "with___reached_": sum(1 for r in und_rows if r["has___reached_"]),
            "without___reached_": sum(1 for r in und_rows if not r["has___reached_"]),
            "rows": und_rows,
        },
        "var_reached_free": sorted(v for v in all_free if v.startswith("VAR_REACHED_")),
    }


def print_analysis(summary: dict) -> None:
    print("=== CACHE FREE-VAR BREAKDOWN ===")
    print(
        f"distinct_free={summary['distinct_free']}  "
        f"by_prefix={summary['distinct_by_prefix']}"
    )
    print(f"occurrences={summary['occurrences_by_prefix']}")
    print(
        f"encode_function={summary['encode_function']}  "
        f"encode_path={summary['encode_path']}"
    )
    print()
    vi = summary["var_init"]
    print(
        f"VAR_INIT distinct={vi['distinct_in_free']}  "
        f"orphan&!encode(=>!_always_runs)={vi['predicted_always_runs_false']}  "
        f"have_calls={vi['have_call_sites']}  on_encode={vi['on_encode_path']}"
    )
    for r in vi["rows"]:
        if r["predicted_always_runs_false"]:
            flag = "ORPHAN→!always_runs"
        elif r["n_call_sites"]:
            flag = "HAS_CALLS"
        else:
            flag = "ON_ENCODE"
        print(
            f"  [{flag}] {r['var']}  member={r['field']!r}  "
            f"fn={r['function']} L{r['line']}  calls={r['n_call_sites']}  "
            f"dims={r['seen_in']}"
        )
    print()
    vu = summary["var_undecided"]
    print(
        f"VAR_UNDECIDED distinct={vu['distinct_in_free']}  "
        f"with___reached_={vu['with___reached_']}  "
        f"without={vu['without___reached_']}"
    )
    for r in vu["rows"]:
        tag = "HAS_REACHED" if r["has___reached_"] else "NO_REACHED"
        print(
            f"  [{tag}] {r['var']}  blocked_on={r.get('blocked_on')!r}  "
            f"{r['presort']}/{r['reason'][:70]}"
        )
        print(f"         {r['text_head'][:150]}")


def _stats_from_doc(doc, field_names: list[str]) -> dict:
    want = set(field_names)
    fields = [f for f in doc.fields if f.name in want]
    free: set[str] = set()
    for f in fields:
        free.update(f.free_vars or [])
    by = Counter(prefix_of(v) for v in free)
    init_vars = {
        d.get("variable")
        for f in fields
        for d in (f.implicit_defaults or [])
        if d.get("variable")
    }
    und_reached = 0
    und_total = 0
    for f in fields:
        for g in f.undecided_guards or []:
            und_total += 1
            blob = (g.text or "") + (g.reason or "") + (g.blocked_on or "")
            if "__reached_" in blob:
                und_reached += 1
    return {
        "n_fields": len(fields),
        "distinct_free": len(free),
        "by_prefix": dict(by),
        "implicit_defaults_records": sum(len(f.implicit_defaults or []) for f in fields),
        "implicit_default_vars": sorted(v for v in init_vars if v),
        "undecided_guards": und_total,
        "undecided_with___reached_": und_reached,
        "exactness": {f.name: f.exactness for f in fields},
        "free_per_field": {f.name: sorted(f.free_vars or []) for f in fields},
        "free_list": sorted(free),
    }


def load_probe_derive():
    spec = importlib.util.spec_from_file_location(
        "_probe_derive_mod", ROOT / "scripts" / "_probe_derive.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def ablate(field_names: list[str], timeout: int, helper: int) -> dict:
    from uo_init.derive_key_fields import Const, KeyFieldDeriver
    from uo_init.host_derivation import derive_host_fields

    mod = load_probe_derive()
    bundle = mod.load_bundle()
    results = {}
    modes = [
        ("current", None, None),
        ("reached_const_true", "reached", None),
        ("always_runs_true_only", None, "always_runs"),
    ]
    for mode_name, pr, pa in modes:
        orig_r, orig_a = KeyFieldDeriver._reached, KeyFieldDeriver._always_runs
        if pr == "reached":

            def _rt(self, scope, depth):  # noqa: ANN001
                return Const(True)

            KeyFieldDeriver._reached = _rt
        if pa == "always_runs":

            def _at(self, scope, depth):  # noqa: ANN001
                return True

            KeyFieldDeriver._always_runs = _at
        t0 = time.perf_counter()
        try:
            # isolate=False: patch must apply in-process
            doc = derive_host_fields(
                bundle,
                timeout=timeout,
                max_helper_guards=helper,
                isolate=False,
                only=field_names,
            )
            stats = _stats_from_doc(doc, field_names)
            stats["seconds"] = round(time.perf_counter() - t0, 2)
            results[mode_name] = stats
            print(
                f"[{mode_name}] free={stats['distinct_free']} by={stats['by_prefix']} "
                f"implicit_recs={stats['implicit_defaults_records']} "
                f"und_reached={stats['undecided_with___reached_']}/"
                f"{stats['undecided_guards']} t={stats['seconds']}s",
                flush=True,
            )
            for name, ex in stats["exactness"].items():
                print(
                    f"    {name:16} {ex:18} free={len(stats['free_per_field'][name])}",
                    flush=True,
                )
        except Exception as exc:  # noqa: BLE001
            import traceback

            results[mode_name] = {
                "error": f"{type(exc).__name__}: {exc}",
                "trace": traceback.format_exc()[-1200:],
            }
            print(f"[{mode_name}] ERROR: {exc}", flush=True)
        finally:
            KeyFieldDeriver._reached = orig_r
            KeyFieldDeriver._always_runs = orig_a
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ablate", action="store_true")
    ap.add_argument("--fields", nargs="*", default=DEFAULT_FIELDS)
    ap.add_argument("--timeout", type=int, default=90)
    ap.add_argument("--helper", type=int, default=4)
    args = ap.parse_args()

    if not RESULT.is_file() or not BUNDLE.is_file():
        raise SystemExit("missing cache; run scripts/_probe_derive.py first")

    blob = json.loads(RESULT.read_text(encoding="utf-8"))
    with BUNDLE.open("rb") as fh:
        bundle = pickle.load(fh)
    summary = analyze_cache(blob, bundle["host_ir"])
    print_analysis(summary)

    out: dict = {"cache_analysis": summary}
    if args.ablate:
        print("\n=== ABLATION (in-process monkey-patch, isolate=False) ===")
        print(f"fields={args.fields} timeout={args.timeout}", flush=True)
        out["ablation"] = ablate(args.fields, args.timeout, args.helper)

    CACHE.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
