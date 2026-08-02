# -*- coding: utf-8 -*-
"""Diagnose K6 `canceled` unknowns: which group queries, how nonlinear, relax?

Read-only against the library. Writes its own cache under `.probe_cache/`.

Phases:
  A  enumerate unique group queries + solve them (cached)
  B  quantify mul/div/mod in the compiled IR of canceled groups
  C  relax nonlinear ops on a canceled query and re-solve

    python scripts/_probe_cancel_nia.py              # full (uses cache)
    python scripts/_probe_cancel_nia.py --phase A    # only solve unique queries
    python scripts/_probe_cancel_nia.py --phase B
    python scripts/_probe_cancel_nia.py --phase C
    python scripts/_probe_cancel_nia.py --fresh      # ignore solve cache
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "engines" / "understand-operator" / "src"
COMMON = ROOT / "engines" / "common"
sys.path[:0] = [str(SRC), str(COMMON), str(Path(__file__).resolve().parent)]

from _probe_reach import load  # noqa: E402

CACHE = ROOT / ".probe_cache"
SOLVE_CACHE = CACHE / "fag_cancel_queries.json"
REPORT = CACHE / "fag_cancel_nia_report.json"


def _is_const(node: Any) -> bool:
    if isinstance(node, (int, bool)):
        return True
    if not isinstance(node, dict):
        return False
    if node.get("op") == "lit":
        return isinstance(node.get("value"), (int, bool))
    return False


def _pretty_atom(node: Any) -> str:
    """One-level label only — never recurse into arithmetic children."""
    if isinstance(node, (int, bool)) or node is None:
        return str(node)
    if isinstance(node, str):
        return node[:40]
    if isinstance(node, dict):
        if "var" in node and "op" not in node:
            return f"var:{node['var']}"
        op = node.get("op")
        if op == "lit":
            return f"lit:{node.get('value')}"
        if op in {"add", "sub", "mul", "div", "mod"}:
            n = len(node.get("args") or [])
            return f"{op}/arity{n}"
        if op == "if_then_else":
            return "ite"
        if op:
            return str(op)
        return "dict"
    if isinstance(node, list):
        return f"list/{len(node)}"
    return type(node).__name__


def _pretty(node: Any, budget: int = 120) -> str:
    """Shallow structural sketch — never expand a DAG into a tree."""
    if isinstance(node, dict) and node.get("op") in {"add", "sub", "mul", "div", "mod"}:
        args = node.get("args") or []
        parts = [_pretty_atom(a) for a in args[:4]]
        more = ",..." if len(args) > 4 else ""
        text = f"{node['op']}(" + ",".join(parts) + more + ")"
        return text if len(text) <= budget else text[: budget - 3] + "..."
    return _pretty_atom(node)


def dag_stats(root: Any) -> dict[str, Any]:
    """Count DAG nodes and expanded tree size (memoised).

    Expanded size can have hundreds of digits; keep it as a decimal string and
    also report digit-length so JSON serialisation cannot hang the process.
    """
    seen: set[int] = set()
    dag = 0
    stack = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, (dict, list)):
            if id(node) in seen:
                continue
            seen.add(id(node))
            dag += 1
            stack.extend(node.values() if isinstance(node, dict) else node)
        else:
            dag += 1
    tree_memo: dict[int, int] = {}

    def tree(node: Any) -> int:
        if not isinstance(node, (dict, list)):
            return 1
        hit = tree_memo.get(id(node))
        if hit is not None:
            return hit
        kids = node.values() if isinstance(node, dict) else node
        total = 1 + sum(tree(k) for k in kids)
        tree_memo[id(node)] = total
        return total

    sys.setrecursionlimit(200000)
    t = tree(root)
    t_str = str(t)
    return {
        "dag_nodes": dag,
        "tree_nodes": t if len(t_str) <= 18 else None,
        "tree_nodes_digits": len(t_str),
        "tree_nodes_sci": f"{t_str[0]}.{t_str[1:4]}e{len(t_str)-1}" if len(t_str) > 4 else t_str,
    }


def walk_arith(root: Any) -> dict[str, Any]:
    """Collect mul/div/mod sites in a DAG (identity-deduped, iterative)."""
    seen: set[int] = set()
    var_mul: list[dict[str, Any]] = []
    const_mul = 0
    divs: list[dict[str, Any]] = []
    mods: list[dict[str, Any]] = []
    ops: Counter[str] = Counter()
    stack: list[Any] = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if id(node) in seen:
                continue
            seen.add(id(node))
            op = node.get("op")
            if isinstance(op, str):
                ops[op] += 1
            if op == "mul":
                args = list(node.get("args") or [])
                nonconst = [a for a in args if not _is_const(a)]
                if len(nonconst) >= 2:
                    var_mul.append({"args": [_pretty(a, 80) for a in args], "n_args": len(args)})
                else:
                    const_mul += 1
            elif op == "div":
                args = list(node.get("args") or [])
                divisor = args[1] if len(args) > 1 else None
                divs.append(
                    {
                        "divisor_const": _is_const(divisor),
                        "divisor": _pretty(divisor, 60),
                        "dividend": _pretty(args[0], 60) if args else "",
                    }
                )
            elif op == "mod":
                args = list(node.get("args") or [])
                modulus = args[1] if len(args) > 1 else None
                mods.append(
                    {
                        "modulus_const": _is_const(modulus),
                        "modulus": _pretty(modulus, 60),
                        "lhs": _pretty(args[0], 60) if args else "",
                    }
                )
            stack.extend(node.values())
        elif isinstance(node, list):
            if id(node) in seen:
                continue
            seen.add(id(node))
            stack.extend(node)
    return {
        "ops": dict(ops),
        "var_mul_count": len(var_mul),
        "const_mul_count": const_mul,
        "var_mul_samples": var_mul[:12],
        "div_count": len(divs),
        "div_var_divisor": sum(1 for d in divs if not d["divisor_const"]),
        "div_const_divisor": sum(1 for d in divs if d["divisor_const"]),
        "div_samples": divs[:12],
        "mod_count": len(mods),
        "mod_var_modulus": sum(1 for m in mods if not m["modulus_const"]),
        "mod_const_modulus": sum(1 for m in mods if m["modulus_const"]),
        "mod_samples": mods[:12],
    }


def collect_vars(node: Any) -> set[str]:
    out: set[str] = set()
    seen: set[int] = set()

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            if id(item) in seen:
                return
            seen.add(id(item))
            name = item.get("var")
            if isinstance(name, str):
                out.add(name)
            for v in item.values():
                walk(v)
        elif isinstance(item, list):
            if id(item) in seen:
                return
            seen.add(id(item))
            for v in item:
                walk(v)

    walk(node)
    return out


def classify_var(name: str) -> str:
    if name.startswith("VAR_SHAPE") or "SHAPE" in name or "DIM" in name and "KEYDIM" not in name:
        if name.startswith("VAR_KEYDIM_"):
            return "keydim"
        if "SHAPE" in name or name.startswith("VAR_TDF_") and any(
            x in name for x in ("S1", "S2", "N2", "G", "D", "B", "SEQ")
        ):
            return "shapeish"
    if name.startswith("VAR_KEYDIM_"):
        return "keydim"
    if name.startswith(("VAR_INIT_", "VAR_UNDECIDED_", "VAR_LOCAL_", "VAR_LOOPELEM_")):
        return "free_soft"
    if name.startswith(("VAR_ATTR_", "VAR_OPT_", "VAR_SESSION_", "VAR_PLATFORM_", "VAR_COMPILE_")):
        return "inputish"
    if name.startswith("VAR_TDF_"):
        return "tiling_data"
    if name.startswith("VAR_"):
        return "other_var"
    return "other"


# ---------------------------------------------------------------------------
# Phase A: solve unique group queries
# ---------------------------------------------------------------------------


def legal_keys(schema) -> list[dict[str, str]]:
    from uo_init.materialize_tiling import expand_legal_with_groups

    out = []
    for _index, (_gi, dims) in enumerate(expand_legal_with_groups(schema)):
        out.append({d.name: str(dims.get(d.name, d.value_domain[0])) for d in schema.dims})
    return out


def unique_group_queries(reach, keys: list[dict[str, str]]):
    from uo_init.key_reachability import _target_value

    per_group: list[dict[str, Any]] = []
    for gi, group in enumerate(reach._groups):
        combos: dict[tuple, int] = Counter()
        for k in keys:
            vals = []
            ok = True
            for name in group:
                if name not in k:
                    ok = False
                    break
                v = _target_value(k[name])
                if v is None:
                    ok = False
                    break
                vals.append((name, v))
            if ok:
                combos[tuple(vals)] += 1
        per_group.append(
            {
                "group_index": gi,
                "dims": list(group),
                "unique": len(combos),
                "combos": [
                    {"values": list(vals), "key_count": n}
                    for vals, n in sorted(combos.items(), key=lambda kv: -kv[1])
                ],
            }
        )
    return per_group


def solve_all_unique(reach, per_group, *, fresh: bool) -> dict[str, Any]:
    if SOLVE_CACHE.is_file() and not fresh:
        cached = json.loads(SOLVE_CACHE.read_text(encoding="utf-8"))
        print(f"loaded solve cache {SOLVE_CACHE} ({len(cached.get('results') or [])} rows)", flush=True)
        return cached

    results = []
    t0 = time.time()
    for ginfo in per_group:
        gi = ginfo["group_index"]
        dims = ginfo["dims"]
        print(f"\n=== group[{gi}] {dims}  unique={ginfo['unique']} ===", flush=True)
        for i, combo in enumerate(ginfo["combos"]):
            values = tuple((n, v) for n, v in combo["values"])
            began = time.time()
            hit = reach._solve_group(values)
            elapsed = time.time() - began
            status = str(hit.get("status") or "unknown")
            reason = str(hit.get("reason") or "")
            row = {
                "group_index": gi,
                "dims": dims,
                "values": list(values),
                "key_count": combo["key_count"],
                "status": status,
                "reason": reason,
                "seconds": round(elapsed, 3),
            }
            results.append(row)
            mark = "!" if status not in ("sat", "unsat") else " "
            if i < 5 or status not in ("sat", "unsat") or i % 50 == 0:
                print(
                    f"  {mark}[{i+1}/{ginfo['unique']}] {status:8} {elapsed:6.2f}s "
                    f"keys={combo['key_count']:4} reason={reason[:60]}",
                    flush=True,
                )
    out = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_seconds": round(time.time() - t0, 2),
        "results": results,
    }
    CACHE.mkdir(parents=True, exist_ok=True)
    SOLVE_CACHE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {SOLVE_CACHE}", flush=True)
    return out


def summarise_solve(solve_doc: dict[str, Any], per_group) -> dict[str, Any]:
    results = solve_doc["results"]
    by_status = Counter(r["status"] for r in results)
    by_reason = Counter(r["reason"] for r in results)
    # Keys whose *weakest* group answer is unknown/canceled
    # Reconstruct: a key is unknown iff no group is unsat AND at least one is unknown.
    # We approximate via the big-group cancels: for each canceled combo, all its keys
    # are unknown UNLESS some other group is unsat for those keys.
    # Safer: report canceled queries and the key_count they cover; then compute
    # exact unknown attribution by replaying group results over legal keys later.

    canceled = [r for r in results if r["status"] not in ("sat", "unsat")]
    canceled_keys_raw = sum(r["key_count"] for r in canceled)
    per_g = []
    for ginfo in per_group:
        gi = ginfo["group_index"]
        rows = [r for r in results if r["group_index"] == gi]
        st = Counter(r["status"] for r in rows)
        canc = [r for r in rows if r["status"] not in ("sat", "unsat")]
        per_g.append(
            {
                "group_index": gi,
                "dims": ginfo["dims"],
                "unique": len(rows),
                "status": dict(st),
                "canceled_queries": len(canc),
                "canceled_key_occurrences": sum(r["key_count"] for r in canc),
                "avg_seconds": round(sum(r["seconds"] for r in rows) / max(len(rows), 1), 3),
                "max_seconds": max((r["seconds"] for r in rows), default=0),
                "canceled_reasons": dict(Counter(r["reason"] for r in canc)),
            }
        )
    return {
        "query_status": dict(by_status),
        "query_reasons": dict(by_reason.most_common(20)),
        "canceled_queries": len(canceled),
        "canceled_key_occurrences_sum": canceled_keys_raw,
        "per_group": per_g,
        "total_solve_seconds": solve_doc.get("total_seconds"),
    }


def attribute_keys(reach, keys, solve_doc) -> dict[str, Any]:
    """Replay cached group answers over every legal key (no Z3)."""
    from uo_init.key_reachability import _target_value

    cache: dict[tuple, dict] = {}
    for r in solve_doc["results"]:
        key = (r["group_index"], tuple((n, v) for n, v in r["values"]))
        cache[key] = r

    status_c = Counter()
    unknown_blame: Counter[str] = Counter()  # which group indexes canceled
    unknown_by_canceled_groups: Counter[tuple] = Counter()
    examples = []

    for k in keys:
        weakest = "sat"
        canceled_groups = []
        unsat = False
        for gi, group in enumerate(reach._groups):
            vals = []
            ok = True
            for name in group:
                if name not in k:
                    ok = False
                    break
                v = _target_value(k[name])
                if v is None:
                    ok = False
                    break
                vals.append((name, v))
            if not ok:
                continue
            hit = cache.get((gi, tuple(vals)))
            if hit is None:
                continue
            st = hit["status"]
            if st == "unsat":
                unsat = True
                break
            if st != "sat":
                weakest = "unknown"
                canceled_groups.append(gi)
        if unsat:
            status_c["unreachable"] += 1
        elif weakest == "sat":
            status_c["reachable_or_sat_unknown"] += 1
        else:
            status_c["unknown"] += 1
            for gi in canceled_groups:
                unknown_blame[f"group[{gi}]"] += 1
            unknown_by_canceled_groups[tuple(canceled_groups)] += 1
            if len(examples) < 5:
                examples.append({"dims": {n: k[n] for n in sorted(k)}, "canceled_groups": canceled_groups})

    return {
        "legal_keys": len(keys),
        "status": dict(status_c),
        "unknown_blamed_on_group": dict(unknown_blame),
        "unknown_by_canceled_group_set": {
            str(list(k)): v for k, v in unknown_by_canceled_groups.most_common(20)
        },
        "unknown_examples": examples,
    }


# ---------------------------------------------------------------------------
# Phase B: nonlinearity of compiled IR
# ---------------------------------------------------------------------------


def analyse_ir(reach, group_dims: list[str] | None = None) -> dict[str, Any]:
    """Walk compiled derived definitions in the backend IR."""
    backend = reach._backend
    variables = backend.ir.get("variables") or []
    dim_vars = set()
    for name, spec in reach._dims.items():
        if group_dims is None or name in group_dims:
            dim_vars.add(spec["var"])

    # Collect definitions that feed the selected dimensions (closure).
    by_id = {v["id"]: v for v in variables if isinstance(v, dict) and "id" in v}
    needed: set[str] = set(dim_vars)
    changed = True
    while changed:
        changed = False
        for vid in list(needed):
            spec = by_id.get(vid)
            if not spec or not spec.get("derived"):
                continue
            for ref in collect_vars(spec.get("definition")):
                if ref not in needed:
                    needed.add(ref)
                    changed = True

    free = []
    derived = []
    for vid in sorted(needed):
        spec = by_id.get(vid) or {"id": vid}
        if spec.get("derived"):
            derived.append(vid)
        elif vid != "UO_CONST_TRUE":
            free.append(vid)

    # Concatenate definitions for arith walk (as a fake and of equalities' RHSs)
    roots = []
    for vid in derived:
        defn = by_id[vid].get("definition")
        if defn is not None:
            roots.append(defn)
    bundle = {"op": "bundle", "args": roots} if roots else {"op": "lit", "value": 0}
    arith = walk_arith(bundle)
    sizes = [dag_stats(by_id[v].get("definition")) for v in derived if by_id[v].get("definition") is not None]
    var_classes = Counter(classify_var(v) for v in free)

    # Per-dimension breakdown
    per_dim = {}
    for name, spec in sorted(reach._dims.items()):
        if group_dims is not None and name not in group_dims:
            continue
        defn = by_id.get(spec["var"], {}).get("definition")
        if defn is None:
            continue
        a = walk_arith(defn)
        s = dag_stats(defn)
        vs = collect_vars(defn)
        per_dim[name] = {
            "dag_nodes": s["dag_nodes"],
            "tree_nodes": s["tree_nodes"],
            "tree_nodes_sci": s["tree_nodes_sci"],
            "tree_nodes_digits": s["tree_nodes_digits"],
            "var_mul": a["var_mul_count"],
            "div": a["div_count"],
            "mod": a["mod_count"],
            "free_soft": sorted(v for v in vs if classify_var(v) == "free_soft"),
            "n_vars": len(vs),
        }

    return {
        "group_dims": group_dims,
        "n_free_vars": len(free),
        "n_derived": len(derived),
        "free_var_classes": dict(var_classes),
        "free_vars_sample": free[:40],
        "arith": {
            "var_mul_count": arith["var_mul_count"],
            "const_mul_count": arith["const_mul_count"],
            "div_count": arith["div_count"],
            "div_var_divisor": arith["div_var_divisor"],
            "div_const_divisor": arith["div_const_divisor"],
            "mod_count": arith["mod_count"],
            "mod_var_modulus": arith["mod_var_modulus"],
            "mod_const_modulus": arith["mod_const_modulus"],
            "ops": arith["ops"],
        },
        "var_mul_samples": arith["var_mul_samples"],
        "div_samples": arith["div_samples"],
        "mod_samples": arith["mod_samples"],
        "size_sum_dag": sum(s["dag_nodes"] for s in sizes),
        "size_max_dag": max((s["dag_nodes"] for s in sizes), default=0),
        "size_max_tree_digits": max((s["tree_nodes_digits"] for s in sizes), default=0),
        "per_dim": per_dim,
    }


def host_sources(doc) -> dict[str, Any]:
    out = {}
    for fld in doc.fields:
        out[fld.name] = {
            "host_expr": getattr(fld, "host_expr", None),
            "def_sites": list(getattr(fld, "def_sites", None) or []),
            "exactness": getattr(fld, "exactness", None),
            "free_vars": list(getattr(fld, "free_vars", None) or []),
            "implicit_defaults": len(getattr(fld, "implicit_defaults", None) or []),
        }
    return out


# ---------------------------------------------------------------------------
# Phase C: relax nonlinear ops
# ---------------------------------------------------------------------------


def _rewrite_relax(
    node: Any,
    *,
    drop_var_mul: bool,
    drop_divmod: bool,
    fresh_vars: list[dict[str, Any]],
    counter: list[int],
    memo: dict[int, Any],
) -> Any:
    if not isinstance(node, (dict, list)):
        return node
    if id(node) in memo:
        return memo[id(node)]
    if isinstance(node, list):
        out = [
            _rewrite_relax(
                x,
                drop_var_mul=drop_var_mul,
                drop_divmod=drop_divmod,
                fresh_vars=fresh_vars,
                counter=counter,
                memo=memo,
            )
            for x in node
        ]
        memo[id(node)] = out
        return out

    op = node.get("op")
    if op == "mul" and drop_var_mul:
        args = list(node.get("args") or [])
        nonconst = [a for a in args if not _is_const(a)]
        if len(nonconst) >= 2:
            counter[0] += 1
            name = f"VAR_RELAX_MUL_{counter[0]}"
            fresh_vars.append({"id": name, "type": "int"})
            out = {"var": name}
            memo[id(node)] = out
            return out
    if op in {"div", "mod"} and drop_divmod:
        counter[0] += 1
        name = f"VAR_RELAX_{op.upper()}_{counter[0]}"
        fresh_vars.append({"id": name, "type": "int"})
        out = {"var": name}
        memo[id(node)] = out
        return out

    out = {}
    memo[id(node)] = out
    for k, v in node.items():
        out[k] = _rewrite_relax(
            v,
            drop_var_mul=drop_var_mul,
            drop_divmod=drop_divmod,
            fresh_vars=fresh_vars,
            counter=counter,
            memo=memo,
        )
    return out


def build_relaxed_backend(reach, *, drop_var_mul: bool, drop_divmod: bool, timeout_ms: int, rlimit: int, hard_timeout_ms: int):
    """Rebuild a backend with nonlinear sites replaced.

    Must NOT deepcopy the IR: definitions are DAGs whose expanded trees are
    astronomical (`SplitAxis` ~1e22). Deepcopy would materialise that tree.
    Rewrite with identity-memo instead, so sharing is preserved.
    """
    from acp_common.z3_backend import SolveConfig, Z3Backend

    src = reach._backend.ir
    fresh: list[dict[str, Any]] = []
    counter = [0]
    memo: dict[int, Any] = {}
    new_vars: list[dict[str, Any]] = []
    for spec in src.get("variables") or []:
        if not isinstance(spec, dict):
            continue
        if not spec.get("derived") or spec.get("definition") is None:
            new_vars.append(spec)
            continue
        new_def = _rewrite_relax(
            spec["definition"],
            drop_var_mul=drop_var_mul,
            drop_divmod=drop_divmod,
            fresh_vars=fresh,
            counter=counter,
            memo=memo,
        )
        cloned = dict(spec)
        cloned["definition"] = new_def
        new_vars.append(cloned)
    new_vars.extend(fresh)
    ir = {
        "variables": new_vars,
        "constraints": list(src.get("constraints") or []),
    }
    backend = Z3Backend(
        ir,
        SolveConfig(timeout_ms=timeout_ms, rlimit=rlimit, hard_timeout_ms=hard_timeout_ms),
    )
    backend.exposed_derived_prefixes = ("VAR_KEYDIM_",)
    return backend, counter[0], [v["id"] for v in fresh]


def run_relax_experiments(reach, solve_doc, *, timeout_ms: int, rlimit: int, hard_timeout_ms: int, limit: int = 8):
    canceled = [r for r in solve_doc["results"] if r["status"] not in ("sat", "unsat")]
    # Prefer the large group, highest key_count first
    canceled.sort(key=lambda r: (-(1 if r["group_index"] == 0 else 0), -r["key_count"], r["seconds"]), reverse=False)
    canceled.sort(key=lambda r: (0 if r["group_index"] == 0 else 1, -r["key_count"]))
    sample = canceled[:limit]
    if not sample:
        return {"note": "no canceled queries to relax", "experiments": []}

    modes = [
        ("baseline", False, False),
        ("relax_var_mul", True, False),
        ("relax_var_mul_and_divmod", True, True),
        ("relax_divmod_only", False, True),
    ]
    experiments = []
    for row in sample:
        values = tuple((n, v) for n, v in row["values"])
        args = [{"op": "eq", "var": reach._dims[n]["var"], "value": v} for n, v in values]
        expr = args[0] if len(args) == 1 else {"op": "and", "args": args}
        entry = {
            "group_index": row["group_index"],
            "dims": row["dims"],
            "values": list(values),
            "key_count": row["key_count"],
            "original_status": row["status"],
            "original_reason": row["reason"],
            "modes": {},
        }
        for mode_name, drop_mul, drop_div in modes:
            print(f"  relax {mode_name} on group[{row['group_index']}] keys={row['key_count']}...", flush=True)
            t0 = time.time()
            backend, n_replaced, fresh_ids = build_relaxed_backend(
                reach,
                drop_var_mul=drop_mul,
                drop_divmod=drop_div,
                timeout_ms=timeout_ms,
                rlimit=rlimit,
                hard_timeout_ms=hard_timeout_ms,
            )
            build_s = time.time() - t0
            t1 = time.time()
            hit = backend.solve_expr(expr, label="relax")
            solve_s = time.time() - t1
            entry["modes"][mode_name] = {
                "status": hit.get("status"),
                "reason": hit.get("reason"),
                "replaced_sites": n_replaced,
                "fresh_vars": len(fresh_ids),
                "build_seconds": round(build_s, 3),
                "solve_seconds": round(solve_s, 3),
            }
            print(
                f"    -> {hit.get('status')} ({solve_s:.2f}s) replaced={n_replaced} "
                f"reason={str(hit.get('reason') or '')[:50]}",
                flush=True,
            )
        experiments.append(entry)
    return {"sample_size": len(sample), "experiments": experiments}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phase", choices=["A", "B", "C", "all"], default="all")
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--timeout", type=int, default=5000)
    ap.add_argument("--rlimit", type=int, default=None)
    ap.add_argument("--hard-timeout", type=int, default=None)
    ap.add_argument("--relax-limit", type=int, default=6)
    args = ap.parse_args()

    import uo_init.key_reachability as kr
    from uo_init.key_reachability import KeyReachability

    rlimit = kr.DEFAULT_RLIMIT if args.rlimit is None else args.rlimit
    hard = kr.DEFAULT_HARD_TIMEOUT_MS if args.hard_timeout is None else args.hard_timeout

    print(
        f"config: timeout_ms={args.timeout} rlimit={rlimit} hard_timeout_ms={hard}",
        flush=True,
    )
    print("loading derivation...", flush=True)
    doc, vm, schema, _binding = load()
    print("building KeyReachability...", flush=True)
    t0 = time.time()
    reach = KeyReachability.from_derivation(
        doc, vm, timeout_ms=args.timeout, rlimit=rlimit, hard_timeout_ms=hard
    )
    print(f"built in {time.time()-t0:.1f}s", flush=True)
    summary = reach.summary()
    print("groups:")
    for g in summary["groups"]:
        print(f"  [{len(g)}] {g}")

    print("expanding legal keys...", flush=True)
    keys = legal_keys(schema)
    print(f"legal keys: {len(keys)}", flush=True)
    per_group = unique_group_queries(reach, keys)
    for g in per_group:
        print(f"  group[{g['group_index']}] unique={g['unique']} dims={g['dims']}")

    report: dict[str, Any] = {
        "config": {
            "timeout_ms": args.timeout,
            "rlimit": rlimit,
            "hard_timeout_ms": hard,
            "DEFAULT_RLIMIT": kr.DEFAULT_RLIMIT,
            "DEFAULT_HARD_TIMEOUT_MS": kr.DEFAULT_HARD_TIMEOUT_MS,
        },
        "groups": summary["groups"],
        "host_sources": host_sources(doc),
    }

    solve_doc = None
    if args.phase in ("A", "all", "C"):
        print("\n=== Phase A: solve unique group queries ===", flush=True)
        solve_doc = solve_all_unique(reach, per_group, fresh=args.fresh)
        report["solve_summary"] = summarise_solve(solve_doc, per_group)
        report["key_attribution"] = attribute_keys(reach, keys, solve_doc)
        print("\nsolve summary:", json.dumps(report["solve_summary"], ensure_ascii=False, indent=2))
        print("\nkey attribution:", json.dumps(report["key_attribution"], ensure_ascii=False, indent=2))

    if args.phase in ("B", "all"):
        print("\n=== Phase B: nonlinearity of compiled IR ===", flush=True)
        big = list(reach._groups[0])
        report["ir_all"] = analyse_ir(reach, None)
        report["ir_big_group"] = analyse_ir(reach, big)
        # Also singleton exact dims for contrast
        singles = [g[0] for g in reach._groups[1:4]]
        report["ir_sample_singletons"] = {n: analyse_ir(reach, [n]) for n in singles}
        print(
            "big group arith:",
            json.dumps(report["ir_big_group"]["arith"], ensure_ascii=False, indent=2),
        )
        print(
            "big group sizes dag:",
            report["ir_big_group"]["size_sum_dag"],
            "max_tree_digits:",
            report["ir_big_group"]["size_max_tree_digits"],
            "free",
            report["ir_big_group"]["n_free_vars"],
        )
        print("per_dim:", json.dumps(report["ir_big_group"]["per_dim"], ensure_ascii=False, indent=2))

    if args.phase in ("C", "all"):
        if solve_doc is None:
            if not SOLVE_CACHE.is_file():
                raise SystemExit("need Phase A cache first")
            solve_doc = json.loads(SOLVE_CACHE.read_text(encoding="utf-8"))
        print("\n=== Phase C: relax nonlinear ops ===", flush=True)
        report["relax"] = run_relax_experiments(
            reach,
            solve_doc,
            timeout_ms=args.timeout,
            rlimit=rlimit,
            hard_timeout_ms=hard,
            limit=args.relax_limit,
        )
        print(json.dumps(report["relax"], ensure_ascii=False, indent=2))

    CACHE.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {REPORT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
