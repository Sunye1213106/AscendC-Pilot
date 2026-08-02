# -*- coding: utf-8 -*-
"""Ablate with OLD leaf semantics: no call sites => Const(True) (ignore encode_path).

Also dumps unresolved notes for the Const(True)-everything failure mode.

    python scripts/_probe_reached_oldleaf.py
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "engines" / "understand-operator" / "src"
sys.path.insert(0, str(SRC))

CACHE = ROOT / ".probe_cache"
FIELDS = ["SplitAxis", "DeterType", "IsBn2MultiBlk"]


def prefix_of(var: str) -> str:
    for p in ("VAR_INIT_", "VAR_UNDECIDED_", "VAR_LOOPELEM_", "VAR_REACHED_", "VAR_SCHED_"):
        if var.startswith(p):
            return p.rstrip("_")
    return "OTHER"


def stats(doc, names):
    want = set(names)
    fields = [f for f in doc.fields if f.name in want]
    free = set()
    for f in fields:
        free.update(f.free_vars or [])
    und_blk = Counter()
    for f in fields:
        for g in f.undecided_guards or []:
            und_blk[g.blocked_on or "?"] += 1
    return {
        "exactness": {f.name: f.exactness for f in fields},
        "notes": {f.name: f.note for f in fields},
        "status": {f.name: f.status for f in fields},
        "distinct_free": len(free),
        "by_prefix": dict(Counter(prefix_of(v) for v in free)),
        "implicit_defaults": sum(len(f.implicit_defaults or []) for f in fields),
        "undecided_blocked_on": dict(und_blk.most_common(8)),
        "free_per_field": {f.name: sorted(f.free_vars or []) for f in fields},
        "unresolved": {
            f.name: list(f.unresolved or []) for f in fields if f.unresolved
        },
    }


def main() -> int:
    import importlib.util

    from uo_init.derive_key_fields import (
        REACHED_PREFIX,
        Bin,
        Const,
        KeyFieldDeriver,
        Ref,
        _conjoin_text,
        _is_true,
    )
    from uo_init.host_derivation import derive_host_fields

    spec = importlib.util.spec_from_file_location(
        "_probe_derive_mod", ROOT / "scripts" / "_probe_derive.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(mod)
    bundle = mod.load_bundle()

    orig = KeyFieldDeriver._reached

    def _reached_old_leaf(self, scope, depth):  # noqa: ANN001
        """Current logic, but orphan (no call sites) => Const(True) always."""
        short = scope.split("::")[-1]
        if short in self._reach_stack:
            return Ref(f"{REACHED_PREFIX}{scope}")
        hit = self._reach_cache.get(short)
        if hit is not None:
            return hit
        sites = self.ir.calls_to(short) if hasattr(self.ir, "calls_to") else []
        if not sites:
            out: object = Const(True)  # OLD leaf
            self._reach_cache[short] = out
            return out
        self._reach_stack.add(short)
        try:
            terms = []
            for site in sites:
                conds = tuple(getattr(site, "path_conditions", ()))
                guard_text = _conjoin_text(
                    tuple(c.pretty() for c in conds if not c.is_opaque)
                )
                up = self._reached(site.caller, depth + 1)
                if not guard_text:
                    term = up
                elif _is_true(up):
                    term = self._expand_text(guard_text, site.caller, depth + 1)
                else:
                    here = self._expand_text(guard_text, site.caller, depth + 1)
                    term = Bin("&&", up, here)
                if any(getattr(c, "is_opaque", False) for c in conds):
                    unread = Ref(
                        f"{REACHED_PREFIX}{site.caller}@{getattr(site, 'line', 0)}"
                    )
                    term = unread if _is_true(term) else Bin("&&", term, unread)
                if _is_true(term):
                    self._reach_cache[short] = Const(True)
                    return Const(True)
                terms.append(term)
        finally:
            self._reach_stack.discard(short)
        out = terms[0]
        for t in terms[1:]:
            out = Bin("||", out, t)
        self._reach_cache[short] = out
        return out

    modes = [
        ("current", None),
        ("old_orphan_const_true", _reached_old_leaf),
    ]
    results = {}
    for name, patch in modes:
        KeyFieldDeriver._reached = patch or orig
        t0 = time.perf_counter()
        try:
            doc = derive_host_fields(
                bundle,
                timeout=90,
                max_helper_guards=4,
                isolate=False,
                only=FIELDS,
            )
            s = stats(doc, FIELDS)
            s["seconds"] = round(time.perf_counter() - t0, 2)
            results[name] = s
            print(
                f"[{name}] free={s['distinct_free']} by={s['by_prefix']} "
                f"implicit={s['implicit_defaults']} t={s['seconds']}s",
                flush=True,
            )
            print(f"  exactness={s['exactness']}", flush=True)
            print(f"  status={s['status']}", flush=True)
            if s["notes"]:
                print(f"  notes={s['notes']}", flush=True)
            if s["unresolved"]:
                print(f"  unresolved={s['unresolved']}", flush=True)
            print(f"  blocked_on={s['undecided_blocked_on']}", flush=True)
        except Exception as exc:  # noqa: BLE001
            import traceback

            results[name] = {
                "error": str(exc),
                "trace": traceback.format_exc()[-800:],
            }
            print(f"[{name}] ERROR {exc}", flush=True)
        finally:
            KeyFieldDeriver._reached = orig

    out = CACHE / "reached_oldleaf.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
