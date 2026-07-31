# -*- coding: utf-8 -*-
"""Thin CLI over ``uo_init.host_derivation`` for local FAG debugging.

Production derivation lives in the uo-init ``derive_key_fields`` action.
This script only rebuilds a cached host bundle and pretty-prints the same
artifact the workflow writes under ``uo/ir/host_derivation.yaml``.

    python scripts/_probe_derive.py                  # derive all, write report
    python scripts/_probe_derive.py --show           # print last result
    python scripts/_probe_derive.py --show IsNzOut   # one field, full detail
    python scripts/_probe_derive.py IsNzOut IsTnd    # recompute only these
    python scripts/_probe_derive.py --refresh        # re-parse with clang first
    python scripts/_probe_derive.py --timeout 60     # per-field limit, seconds
    python scripts/_probe_derive.py --helper 8       # max_helper_guards
    python scripts/_probe_derive.py --no-isolate     # in-process (no timeout)
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "engines" / "understand-operator" / "src"
sys.path.insert(0, str(SRC))

OP = Path(r"d:\PR-review\TEST\ops-transformer\attention\flash_attention_score_grad")
CANN = r"d:\PR-review\_cann\pkg"
ARCH = "arch35"

CACHE = ROOT / ".probe_cache"
BUNDLE = CACHE / "fag_bundle.pkl"
RESULT = CACHE / "fag_derive.json"
OUTDIR = ROOT / "docs" / "fag"
REPORT = OUTDIR / "fag_arch35.md"
HISTORY = ROOT / "docs" / "debug" / "history.jsonl"


def build_bundle() -> dict:
    from uo_init.assemble_kb import extract_host_bundle

    full = extract_host_bundle(
        op_dir=OP, cann_root=CANN, ops_root=str(OP.parent.parent), arch_dir=ARCH
    )
    keep = {
        k: full[k]
        for k in (
            "binding",
            "bind_error",
            "host_ir",
            "resolver",
            "var_model",
            "tpl_schema",
            "spec",
        )
    }
    CACHE.mkdir(parents=True, exist_ok=True)
    with BUNDLE.open("wb") as fh:
        pickle.dump(keep, fh)
    return keep


def load_bundle() -> dict:
    with BUNDLE.open("rb") as fh:
        bundle = pickle.load(fh)
    binding = bundle.get("binding")
    ir = bundle.get("host_ir")
    if binding is not None and ir is not None:
        from uo_init.tpl_bind import merge_literal_encode_alts

        bundle["binding"] = merge_literal_encode_alts(binding, ir)
    model = bundle.get("var_model")
    if model is not None and getattr(model, "platform_profile", None) is None:
        try:
            from uo_init.platform_ini import load_platform_profile
            from uo_init.variable_model import apply_platform_profile

            profile = load_platform_profile(CANN, arch_dir=ARCH)
            apply_platform_profile(model, profile)
            bundle["platform_profile"] = profile
        except Exception:  # noqa: BLE001
            pass
    return bundle


def _field_row(f) -> dict:
    """Probe-cache shape: keep the old keys so --show / report stay readable."""
    from uo_init.derive_key_fields import encode_expr_dag

    undecided = {g.var_id: f"{g.reason}: {g.text}" for g in f.undecided_guards}
    scheduling = {
        g.var_id: f"{g.reason}: {g.text}"
        for g in f.undecided_guards
        if g.presort == "scheduling"
    }
    return {
        "name": f.name,
        "index": f.index,
        "status": f.status,
        "exactness": f.exactness,
        "free_vars": list(f.free_vars),
        "unrecorded_free_vars": f.unrecorded_free_vars(),
        "implicit_defaults": list(f.implicit_defaults),
        "host_expr": f.host_expr,
        "domain": list(f.domain),
        # A shared DAG; dumping it as a tree is what used to exhaust memory.
        "value_expr": encode_expr_dag(f.value_expr),
        "value_leaves": list(f.value_leaves),
        "domain_violations": f.domain_violations,
        "input_roots": list(f.root_vars),
        "input_closure": f.input_closure,
        "input_derivable": f.input_derivable,
        "variables": list(f.variables),
        "def_sites": list(f.def_sites),
        "unresolved": list(f.unresolved),
        "undecided": undecided,
        "scheduling": scheduling,
        "undecided_guards": [g.to_dict() for g in f.undecided_guards],
        "note": f.note,
        "seconds": f.seconds,
        "expanded_chars": f.expanded_chars,
        "expanded": f.expanded,
    }


def run_derive(
    *,
    only: list[str] | None,
    timeout: int,
    helper: int,
    isolate: bool,
) -> dict:
    from uo_init.host_derivation import derive_host_fields

    bundle = load_bundle()
    doc = derive_host_fields(
        bundle,
        timeout=timeout,
        max_helper_guards=helper,
        isolate=isolate,
        only=only or None,
    )
    fields = [_field_row(f) for f in doc.fields]
    if only and RESULT.is_file():
        prev = json.loads(RESULT.read_text(encoding="utf-8"))
        by_name = {f["name"]: f for f in fields}
        merged = []
        for old in prev.get("fields", []):
            merged.append(by_name.pop(old["name"], old))
        merged.extend(by_name.values())
        merged.sort(key=lambda f: f["index"])
        fields = merged
    return {
        "op": doc.op_name or OP.name,
        "arch": doc.architecture or ARCH,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "encode_site": doc.encode_site,
        "encode_function": doc.encode_function,
        "max_helper_guards": helper,
        "timeout": timeout,
        "status": doc.status,
        "totals": doc.totals(),
        "fields": fields,
        "host_derivation": doc.to_dict(),
    }


MARK = {"derived": "ok", "partial": "~~", "unresolved": "XX"}

# `derived` only says a field has an expression. `closed` says that expression
# still means what the source means — that is the number being driven to 19.
CLOSED_GRADES = ("exact", "constant")


def totals(fields: list[dict]) -> dict:
    free = {v for f in fields for v in f.get("free_vars") or []}
    return {
        "closed": sum(1 for f in fields if f.get("exactness") in CLOSED_GRADES),
        # Closed *and* drivable. Lower than `closed` whenever a field bottoms out
        # in host tiling state, which closes the expression without giving a
        # generator anything to set.
        "input_derivable": sum(1 for f in fields if f.get("input_derivable")),
        # Operator-side: the host writes key values the template never declared.
        "domain_violations": sum(1 for f in fields if f.get("domain_violations")),
        "derived": sum(1 for f in fields if f["status"] == "derived"),
        "partial": sum(1 for f in fields if f["status"] == "partial"),
        "unresolved": sum(1 for f in fields if f["status"] == "unresolved"),
        "total": len(fields),
        "free_vars": len(free),
        # Must stay 0: an over-approximation with no guard record can never be
        # escalated or closed, yet still weakens the condition.
        "unrecorded": len({v for f in fields for v in f.get("unrecorded_free_vars") or []}),
        # Not over-approximations: places where a missing unguarded write was
        # closed by assuming the field defaults to zero.
        "implicit_defaults": sum(len(f.get("implicit_defaults") or []) for f in fields),
        "scheduling": sum(len(f.get("scheduling") or {}) for f in fields),
        "undecided": sum(len(f.get("undecided") or {}) for f in fields),
        "max_chars": max((f.get("expanded_chars", 0) for f in fields), default=0),
        "seconds": round(sum(f.get("seconds", 0) for f in fields), 1),
    }


def append_history(doc: dict) -> None:
    """One line per full run, so progress is a diff rather than a memory.

    Skipped for partial runs: a row mixing recomputed and stale fields would
    read as a regression that never happened.
    """
    t = totals(doc["fields"])
    row = {"timestamp": doc["timestamp"], "helper": doc["max_helper_guards"], **t}
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def print_field(f: dict, prev: dict | None) -> None:
    delta = ""
    if prev and prev.get("exactness") != f.get("exactness"):
        delta = f"  <- was {prev.get('exactness') or prev.get('status')}"
    print(
        f"  {MARK.get(f['status'], '??')} {f['index']:2} {f['name']:16} "
        f"{str(f.get('exactness') or '?'):<16} "
        f"{f.get('seconds', 0):>6.1f}s  chars={f.get('expanded_chars', 0):>9} "
        f"free={len(f.get('free_vars') or []):<3} und={len(f.get('undecided') or {}):<3} "
        f"leaves={len(f.get('value_leaves') or []):<3} "
        f"{','.join(f.get('input_roots') or []) or '-'}{delta}",
        flush=True,
    )


def print_detail(f: dict) -> None:
    print(f"\n=== {f['name']} [{f['status']}] index={f['index']} ===")
    print(f"host_expr : {f['host_expr']}")
    print(f"domain    : {f['domain']}")
    print(f"roots     : {f.get('input_roots')}")
    print(f"leaves    : {f.get('value_leaves')}")
    if f.get("note"):
        print(f"note      : {f['note']}")
    for u in f.get("unresolved") or []:
        print(f"blocked   : {u.get('reason')} {u.get('text')}")
    for g in f.get("undecided_guards") or []:
        print(
            f"guard     : {g['id']} [{g['presort']}"
            f"{' escalate' if g.get('escalate') else ''}] {g['reason']}: {g['text'][:160]}"
        )
    print(f"\n--- expanded ({f.get('expanded_chars', 0)} chars) ---")
    print(f.get("expanded") or "")


def write_report(doc: dict) -> None:
    fields = doc["fields"]
    t = totals(fields)
    site = doc.get("encode_site") or {}
    lines = [
        f"# Key field derivation - {doc['op']} ({doc['arch']})",
        "",
        "Generated by `scripts/_probe_derive.py` via `uo_init.host_derivation`.",
        "Do not edit by hand.",
        "",
        f"- run at: {doc['timestamp']}",
        f"- encode site: `{site.get('file')}:{site.get('line')}` in `{doc.get('encode_function')}`",
        f"- max_helper_guards: {doc['max_helper_guards']}",
        f"- **closed (exact or constant): {t['closed']}/{t['total']}** — "
        f"{t['free_vars']} distinct over-approximations remaining",
        f"- derived: {t['derived']}/{t['total']} "
        f"(partial {t['partial']}, unresolved {t['unresolved']}) — "
        "`derived` only means an expression exists, not that it is faithful",
        f"- over-approximations with no guard record: {t['unrecorded']} (must be 0)",
        f"- largest rendered expression: {t['max_chars']} chars",
        "",
        "| # | field | exactness | free | secs | chars | leaves | roots | undec |",
        "|---|-------|-----------|------|------|-------|--------|-------|-------|",
    ]
    for f in fields:
        lines.append(
            f"| {f['index']} | `{f['name']}` | {f.get('exactness') or '?'} | "
            f"{len(f.get('free_vars') or [])} | {f.get('seconds', 0)} | "
            f"{f.get('expanded_chars', 0)} | {len(f.get('value_leaves') or [])} | "
            f"{','.join(f.get('input_roots') or []) or '-'} | "
            f"{len(f.get('undecided') or {})} |"
        )
    lines += ["", "## Per-field detail", ""]
    for f in fields:
        lines += [
            f"### {f['name']}  ({f.get('exactness') or f['status']})",
            "",
            f"- host_expr: `{f['host_expr']}`",
            f"- domain: {f['domain']}",
            f"- value_leaves: {f.get('value_leaves')}",
            f"- input_roots: {f.get('input_roots')}",
        ]
        if f.get("free_vars"):
            lines.append(f"- free_vars: {f['free_vars']}")
        guards = f.get("undecided_guards") or []
        if guards:
            lines.append("- undecided_guards:")
            for g in guards:
                lines.append(
                    f"  - `{g['id']}` [{g['presort']}] {g['reason']}: `{g['text'][:120]}`"
                )
        lines.append("")
    OUTDIR.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("fields", nargs="*", help="optional field names to recompute")
    ap.add_argument("--show", nargs="?", const="*", help="print cached result")
    ap.add_argument("--refresh", action="store_true", help="rebuild host bundle")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--helper", type=int, default=4)
    ap.add_argument("--no-isolate", action="store_true")
    args = ap.parse_args()

    if args.show is not None:
        if not RESULT.is_file():
            print("no cached result; run without --show first", file=sys.stderr)
            return 1
        doc = json.loads(RESULT.read_text(encoding="utf-8"))
        if args.show == "*":
            for f in doc["fields"]:
                print_field(f, None)
            print(totals(doc["fields"]))
        else:
            hit = next((f for f in doc["fields"] if f["name"] == args.show), None)
            if hit is None:
                print(f"unknown field: {args.show}", file=sys.stderr)
                return 1
            print_detail(hit)
        return 0

    if args.refresh or not BUNDLE.is_file():
        print("building host bundle…", flush=True)
        t0 = time.time()
        build_bundle()
        print(f"bundle ready in {time.time() - t0:.1f}s", flush=True)

    prev = json.loads(RESULT.read_text(encoding="utf-8")) if RESULT.is_file() else None
    print("deriving…", flush=True)
    doc = run_derive(
        only=list(args.fields) or None,
        timeout=args.timeout,
        helper=args.helper,
        isolate=not args.no_isolate,
    )
    CACHE.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(doc)
    prev_by = {f["name"]: f for f in (prev or {}).get("fields", [])}
    for f in doc["fields"]:
        if args.fields and f["name"] not in args.fields:
            continue
        print_field(f, prev_by.get(f["name"]))
    t = totals(doc["fields"])
    print(
        f"\nCLOSED {t['closed']}/{t['total']}  "
        f"INPUT_DERIVABLE {t['input_derivable']}/{t['total']}  "
        f"free_vars={t['free_vars']}  "
        f"implicit_zero={t['implicit_defaults']}  "
        f"(derived {t['derived']})  max_chars={t['max_chars']}  {t['seconds']}s"
    )
    if t["unrecorded"]:
        print(f"WARNING: {t['unrecorded']} over-approximations have no guard record")
    for f in doc["fields"]:
        if f.get("domain_violations"):
            print(
                f"WARNING: {f['name']} encodes {f['domain_violations']} "
                f"but the template declares {f.get('domain')} "
                "— operator-side contract conflict, not a derivation gap"
            )
    wrote = [str(RESULT), str(REPORT)]
    if not args.fields:
        append_history(doc)
        wrote.append(str(HISTORY))
    print("wrote " + ", ".join(wrote))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
