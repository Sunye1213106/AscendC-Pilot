# -*- coding: utf-8 -*-
"""Score a tg-init product against a golden rubric.

Generic on purpose: every operator-specific expectation lives in the rubric YAML, so
this grader scores any operator's `tg/init.yaml` and the bind-init skill never sees the
answers. What lives here are invariants that hold for *any* test-script repo.

Usage:
    python evals/tg_init/grade_init.py \
        --rubric evals/fixtures/tg-init/pr-9851-fag-deter-band/rubric.yaml \
        --product <path to tg/init.yaml> \
        [--product <extra part yaml> ...] \
        [--repo <test script root>] [--json out.json]

Exit status is 0 only when the run passes the rubric's scoring gate.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

REQUIRED_AXES = ("empty_tensor", "scalar", "inf_nan", "align_plus_1", "illegal_range")

# Statuses that stop at classification: the skill forbids a `uo.id` on them, so no check
# may demand one.
TERMINAL_STATUSES = frozenset({"unwired", "shadowed", "fallback", "result", "metadata"})


# --------------------------------------------------------------------------- utils
def _s(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip().strip("'\"")


def _norm(val: Any) -> str:
    return _s(val).lower().replace("-", "_").replace(" ", "")


def _load(path: Path) -> dict[str, Any]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return doc if isinstance(doc, dict) else {}


def _merge(docs: list[dict[str, Any]]) -> dict[str, Any]:
    """Later products win per top-level key; dict keys merge one level deep."""
    out: dict[str, Any] = {}
    for doc in docs:
        for key, value in doc.items():
            if isinstance(value, dict) and isinstance(out.get(key), dict):
                out[key] = {**out[key], **value}
            elif value not in (None, "", [], {}) or key not in out:
                out[key] = value
    return out


def _blob(value: Any) -> str:
    """Flatten any nested structure to one lowercase searchable string."""
    if isinstance(value, dict):
        return " ".join(_blob(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_blob(v) for v in value)
    return _s(value).lower()


def _numeric(text: str) -> float | None:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


class Report:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def add(self, family: str, cid: str, ok: bool, detail: str = "") -> None:
        self.checks.append(
            {"family": family, "id": cid, "ok": bool(ok), "detail": detail if not ok else ""}
        )

    def family(self, name: str) -> list[dict[str, Any]]:
        return [c for c in self.checks if c["family"] == name]

    def rate(self, name: str) -> float:
        rows = self.family(name)
        if not rows:
            return 1.0
        return sum(1 for r in rows if r["ok"]) / len(rows)


# ------------------------------------------------------------------ repo-side facts
def _module_relative_import(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return False
    return any(
        isinstance(node, ast.ImportFrom) and (node.level or 0) > 0
        for node in ast.walk(tree)
    )


def _table_readable(path: Path) -> bool:
    """Can this table be read once the reader dispatches on content, not suffix?"""
    if path.suffix.lower() in {".csv", ".tsv"}:
        try:
            return bool(path.read_text(encoding="utf-8-sig", errors="replace").strip())
        except OSError:
            return False
    try:
        magic = path.open("rb").read(8)
    except OSError:
        return False
    if magic.startswith(b"PK\x03\x04"):
        try:
            from openpyxl import load_workbook
        except ImportError:
            return False
        try:
            from io import BytesIO

            load_workbook(BytesIO(path.read_bytes()), read_only=True, data_only=True)
            return True
        except Exception:  # noqa: BLE001
            return False
    if magic.startswith(b"\xd0\xcf\x11\xe0"):
        try:
            import xlrd
        except ImportError:
            return False
        try:
            xlrd.open_workbook(str(path))
            return True
        except Exception:  # noqa: BLE001
            return False
    return False


# ----------------------------------------------------------------- generic checks
def check_invariants(doc: dict[str, Any], repo: Path | None, rep: Report) -> None:
    columns = [_s(c.get("name") if isinstance(c, dict) else c) for c in (doc.get("columns") or [])]
    columns = [c for c in columns if c]
    defaults = doc.get("defaults") if isinstance(doc.get("defaults"), dict) else {}
    domains = doc.get("domains") if isinstance(doc.get("domains"), dict) else {}
    mapping = doc.get("mapping") if isinstance(doc.get("mapping"), dict) else {}
    findings = [f for f in (doc.get("findings") or []) if isinstance(f, dict)]

    def profile_of(col: str) -> dict[str, Any]:
        row = domains.get(col) if isinstance(domains.get(col), dict) else {}
        prof = row.get("profile")
        return prof if isinstance(prof, dict) else {}

    # I1 — the profile must describe the same table the header came from, so no declared
    # column may be left unprofiled.
    if columns and domains:
        missing = [c for c in columns if not profile_of(c)]
        rep.add(
            "invariant",
            "I1-profile-covers-declared-columns",
            not missing,
            f"{len(missing)} declared columns have an empty profile: {missing[:8]}",
        )

    # I2 — a default the corpus never shows means defaults and profile came from
    # different tables.
    if columns and domains and defaults:
        bad: list[str] = []
        for col in columns:
            prof = profile_of(col)
            got = _s(defaults.get(col))
            if not prof or not got:
                continue
            if float(prof.get("empty_rate") or 0.0) >= 1.0:
                continue
            observed = {_s(t.get("value")) for t in (prof.get("topk") or []) if isinstance(t, dict)}
            if not observed:
                continue
            if got in observed or _norm(got) in {_norm(o) for o in observed}:
                continue
            num, lo, hi = _numeric(got), prof.get("min"), prof.get("max")
            if num is not None and lo is not None and hi is not None:
                if float(lo) <= num <= float(hi):
                    continue
            if prof.get("unique_truncated"):
                continue
            bad.append(f"{col}={got!r} not in {sorted(observed)[:4]}")
        rep.add(
            "invariant",
            "I2-defaults-consistent-with-profile",
            not bad,
            f"{len(bad)} defaults contradict their own column profile: {bad[:5]}",
        )

    # I3 — the declared entry must be executable as a script.
    entry = _s(doc.get("entry"))
    if entry and repo:
        target = repo / entry
        if target.is_file():
            rep.add(
                "invariant",
                "I3-entry-is-runnable",
                not _module_relative_import(target),
                f"{entry} uses package-relative imports; running it as a script raises ImportError",
            )
        else:
            rep.add("invariant", "I3-entry-is-runnable", False, f"{entry} does not exist under {repo}")

    # I5 — merging per-axis parts must not duplicate findings.
    if findings:
        keyed = Counter(
            (_s(f.get("code")), _s(f.get("column")), _s(f.get("detail"))[:80]) for f in findings
        )
        dupes = [k for k, n in keyed.items() if n > 1]
        rep.add(
            "invariant",
            "I5-findings-deduplicated",
            not dupes,
            f"{len(dupes)} findings appear more than once: {[d[0] for d in dupes][:5]}",
        )

    # I6 — never report a table as unreadable when a content-sniffing reader can open it.
    if repo and findings:
        fail_words = ("unreadable", "xlrderror", "read_failed", "读取失败", "无法读取")
        claimed: list[str] = []
        for f in findings:
            # Scan only the clauses that actually assert a failure: these details often
            # go on to list the readable tables in the same string.
            for clause in re.split(r"[。;；\n]|可用表", _s(f.get("detail"))):
                if not any(w in clause.lower() for w in fail_words):
                    continue
                for token in re.split(r"[\s,，、：:()（）]+", clause):
                    if token.lower().endswith((".xls", ".xlsx", ".csv")):
                        claimed.append(token)
        false_positive = [
            t for t in dict.fromkeys(claimed) if (repo / t).is_file() and _table_readable(repo / t)
        ]
        rep.add(
            "invariant",
            "I6-no-false-unreadable-table",
            not false_positive,
            f"reported unreadable but readable by content: {false_positive}",
        )

    # I7 — every declared column must be classified.
    if columns and mapping:
        incomplete = [
            c
            for c in columns
            if not _s((mapping.get(c) or {}).get("control", {}).get("status"))
            or not _s((mapping.get(c) or {}).get("confidence"))
        ]
        rep.add(
            "invariant",
            "I7-every-column-classified",
            not incomplete,
            f"{len(incomplete)} columns lack control.status/confidence: {incomplete[:8]}",
        )

    # I8 — two columns sharing one uo.id makes the binding ambiguous downstream.
    if mapping:
        seen: dict[str, list[str]] = {}
        for col, row in mapping.items():
            if not isinstance(row, dict):
                continue
            uid = _norm((row.get("uo") or {}).get("id"))
            if not uid:
                continue
            seen.setdefault(uid, []).append(_s(col))
        shared = {k: v for k, v in seen.items() if len(v) > 1}
        rep.add(
            "invariant",
            "I8-uo-id-not-shared",
            not shared,
            f"uo.id reused across columns: {shared}",
        )

    # I9 — `confirmed` is construct confidence. Active confirmed rows need harness
    # proof (`evidence` or `runtime.target`). Empty `uo.id` is an identity gap, not a
    # construct failure. Terminal statuses stop at classification.
    if mapping:
        unbacked = []
        for col, row in mapping.items():
            if not isinstance(row, dict):
                continue
            if _norm(row.get("confidence")) != "confirmed":
                continue
            status = _norm((row.get("control") or {}).get("status"))
            if status in TERMINAL_STATUSES:
                continue
            evidence = _s(row.get("evidence"))
            runtime = row.get("runtime") if isinstance(row.get("runtime"), dict) else {}
            target = _s((runtime or {}).get("target"))
            if not evidence and not target:
                unbacked.append(_s(col))
        rep.add(
            "invariant",
            "I9-confirmed-has-construct-evidence",
            not unbacked,
            f"confirmed without construct evidence: {unbacked[:8]}",
        )

    # I11 — thresholds must be quotable from the repo, never invented.
    compare = doc.get("compare") if isinstance(doc.get("compare"), dict) else {}
    if compare:
        declared = _s(compare.get("atol_rtol"))
        ok = declared.lower() in {"absent", "", "script-or-absent", "none"}
        if not ok and repo:
            needles = [t for t in declared.replace("=", " ").split() if _numeric(t) is not None]
            hay = "\n".join(
                p.read_text(encoding="utf-8", errors="replace")
                for p in repo.rglob("*.py")
                if p.is_file()
            )
            ok = bool(needles) and all(n in hay for n in needles)
        rep.add(
            "invariant",
            "I11-atol-rtol-not-invented",
            ok,
            f"compare.atol_rtol={declared!r} is not absent and not quotable from the repo",
        )

    # I12 — the special-value axes must each be answered, not silently skipped.
    gen = doc.get("generate_inputs") if isinstance(doc.get("generate_inputs"), dict) else {}
    if gen:
        cannot = gen.get("cannot")
        keys = set()
        if isinstance(cannot, dict):
            keys = {_norm(k) for k in cannot}
        elif isinstance(cannot, list):
            keys = {_norm(k) for k in cannot}
        missing = [a for a in REQUIRED_AXES if _norm(a) not in keys]
        rep.add(
            "invariant",
            "I12-special-value-axes-answered",
            not missing,
            f"generate_inputs.cannot does not answer: {missing}",
        )


# ------------------------------------------------------------------ rubric checks
def _is_part_product(doc: dict[str, Any]) -> bool:
    schema = _s(doc.get("schema")).lower()
    if "part" in schema:
        return True
    return isinstance(doc.get("chunk"), dict)


def _is_harness_product(doc: dict[str, Any]) -> bool:
    schema = _s(doc.get("schema")).lower()
    if "harness" in schema:
        return True
    return bool(doc.get("generate_inputs") or doc.get("golden") or doc.get("compare"))


def _is_bind_product(doc: dict[str, Any]) -> bool:
    schema = _s(doc.get("schema")).lower()
    if "bind" in schema and "harness" not in schema:
        return True
    return bool(doc.get("mapping") or doc.get("chunk"))


def check_engine(doc: dict[str, Any], rubric: dict[str, Any], repo: Path | None, rep: Report) -> None:
    if _is_part_product(doc):
        return
    want = rubric.get("engine") if isinstance(rubric.get("engine"), dict) else {}
    if not want:
        return
    for key in ("entry", "case_arg", "table_kind"):
        if key in want:
            got = _s(doc.get(key))
            rep.add("engine", f"E-{key}", got == _s(want[key]), f"{key}={got!r} want {want[key]!r}")

    columns = [_s(c.get("name") if isinstance(c, dict) else c) for c in (doc.get("columns") or [])]
    columns = [c for c in columns if c]
    if "column_count" in want:
        rep.add(
            "engine",
            "E-column-count",
            len(columns) == int(want["column_count"]),
            f"{len(columns)} columns, want {want['column_count']}",
        )

    domains = doc.get("domains") if isinstance(doc.get("domains"), dict) else {}

    def profile_of(col: str) -> dict[str, Any]:
        row = domains.get(col) if isinstance(domains.get(col), dict) else {}
        prof = row.get("profile")
        return prof if isinstance(prof, dict) else {}

    for col in want.get("columns_requiring_profile") or []:
        rep.add(
            "engine",
            f"E-profile:{col}",
            bool(profile_of(_s(col))),
            f"domains.{col}.profile is empty; the profile came from another table",
        )

    findings = [f for f in (doc.get("findings") or []) if isinstance(f, dict)]
    codes = {_norm(f.get("code")) for f in findings}
    for code in want.get("forbidden_finding_codes") or []:
        rep.add(
            "engine",
            f"E-no-finding:{code}",
            _norm(code) not in codes,
            f"finding {code!r} present; the table is readable once the reader sniffs content",
        )

    if repo:
        for rel in want.get("tables_readable_by_content_sniffing") or []:
            path = repo / _s(rel)
            rep.add(
                "engine",
                f"E-table-readable:{rel}",
                path.is_file() and _table_readable(path),
                f"{rel} could not be read",
            )


def check_harness(doc: dict[str, Any], rubric: dict[str, Any], rep: Report) -> None:
    want = rubric.get("harness") if isinstance(rubric.get("harness"), dict) else {}
    if not want:
        return
    if _is_bind_product(doc) and not _is_harness_product(doc):
        return

    call = doc.get("call") if isinstance(doc.get("call"), dict) else {}
    wcall = want.get("call") or {}
    if "kind" in wcall:
        rep.add("harness", "A-call-kind", _norm(call.get("kind")) == _norm(wcall["kind"]),
                f"call.kind={_s(call.get('kind'))!r}")
    if "api_contains" in wcall:
        rep.add("harness", "A-call-api", _s(wcall["api_contains"]) in _s(call.get("api")),
                f"call.api={_s(call.get('api'))!r}")
    if "site_file" in wcall:
        rep.add("harness", "A-call-site", _s(wcall["site_file"]) in _s(call.get("site")),
                f"call.site={_s(call.get('site'))!r}")

    modes = doc.get("modes") if isinstance(doc.get("modes"), dict) else {}
    wmodes = want.get("modes") or {}
    for slot, key in (("precision", "precision_argv_contains"), ("perf", "perf_argv_contains")):
        if key not in wmodes:
            continue
        argv = modes.get(slot)
        got = _blob(argv)
        missing = [t for t in wmodes[key] if _s(t).lower() not in got]
        rep.add("harness", f"A-modes-{slot}", not missing, f"modes.{slot}={argv!r} missing {missing}")

    compare = doc.get("compare") if isinstance(doc.get("compare"), dict) else {}
    wcmp = want.get("compare") or {}
    if "how_contains" in wcmp:
        got = _blob(compare.get("how"))
        missing = [t for t in wcmp["how_contains"] if _s(t).lower() not in got]
        rep.add("harness", "A-compare-how", not missing, f"compare.how missing {missing}")
    if "atol_rtol" in wcmp:
        rep.add("harness", "A-compare-atol-rtol",
                _norm(compare.get("atol_rtol")) == _norm(wcmp["atol_rtol"]),
                f"compare.atol_rtol={_s(compare.get('atol_rtol'))!r}")

    golden = doc.get("golden") if isinstance(doc.get("golden"), dict) else {}
    wgold = want.get("golden") or {}
    if "match_contains" in wgold:
        got = _blob(golden.get("match"))
        missing = [t for t in wgold["match_contains"] if _s(t).lower() not in got]
        rep.add("harness", "A-golden-match", not missing, f"golden.match missing {missing}")
    if wgold.get("golden_only_is_not_precision"):
        got = _blob(golden) + _blob(doc.get("findings"))
        rep.add("harness", "A-golden-only-not-precision", "golden-only" in got or "golden_only" in got,
                "nothing records that --golden-only is data generation, not an oracle")

    gen = doc.get("generate_inputs") if isinstance(doc.get("generate_inputs"), dict) else {}
    for key in want.get("generate_inputs", {}).get("cannot_keys") or []:
        cannot = gen.get("cannot")
        keys = {_norm(k) for k in (cannot if isinstance(cannot, (dict, list)) else [])}
        rep.add("harness", f"A-cannot:{key}", _norm(key) in keys, f"{key} not answered")

    findings = [f for f in (doc.get("findings") or []) if isinstance(f, dict)]
    codes = {_norm(f.get("code")) for f in findings}
    all_findings = _blob(findings)
    for code in want.get("required_finding_codes") or []:
        ok = _norm(code) in codes
        if not ok and _norm(code).startswith("call_kind_"):
            ok = _norm(call.get("kind")) == _norm(code[len("call_kind_") :])
        rep.add("harness", f"A-finding:{code}", ok, f"finding {code} missing")
    for code, needles in (want.get("findings_must_mention") or {}).items():
        scoped = _blob([f for f in findings if _norm(f.get("code")) == _norm(code)])
        hay = scoped + " " + all_findings
        missing = [n for n in needles if _s(n).lower() not in hay]
        rep.add("harness", f"A-finding-mentions:{code}", not missing,
                f"neither {code} nor other findings mention {missing}")

    if want.get("modes", {}).get("default_is_perf"):
        text = _blob(findings) + _blob(doc.get("modes"))
        rep.add("harness", "A-default-mode-is-perf", "default" in text and "perf" in text,
                "nothing records that the default mode is a perf mode")


def check_columns(doc: dict[str, Any], rubric: dict[str, Any], rep: Report) -> None:
    want = rubric.get("columns") if isinstance(rubric.get("columns"), dict) else {}
    mapping = doc.get("mapping") if isinstance(doc.get("mapping"), dict) else {}
    if not want or not mapping:
        return
    for col, spec in want.items():
        row = mapping.get(col)
        if not isinstance(row, dict):
            present = {str(k) for k in mapping}
            want_keys = {str(k) for k in want}
            if present and present < want_keys:
                continue
            rep.add("columns", f"C-{col}", False, f"{col} missing from mapping")
            continue
        status = _norm((row.get("control") or {}).get("status"))
        relation = _norm(row.get("relation"))
        uid = _norm((row.get("uo") or {}).get("id"))
        spec = spec or {}
        problems: list[str] = []
        if spec.get("status_in"):
            allowed = {_norm(v) for v in spec["status_in"]}
            if status not in allowed:
                problems.append(f"status={status!r} not in {sorted(allowed)}")
        if spec.get("relation_in"):
            allowed = {_norm(v) for v in spec["relation_in"]}
            if relation not in allowed:
                problems.append(f"relation={relation!r} not in {sorted(allowed)}")
        if spec.get("uo_ok") is not None:
            allowed = {_norm(v) for v in spec["uo_ok"]}
            if uid not in allowed:
                problems.append(f"uo.id={uid!r} not in {sorted(allowed)}")
        if spec.get("uo_ban"):
            banned = {_norm(v) for v in spec["uo_ban"]}
            if uid in banned:
                problems.append(f"uo.id={uid!r} is banned")
        rep.add("columns", f"C-{col}", not problems, "; ".join(problems))
    check_slice_call_args(doc, rubric, rep)


def check_slice_call_args(doc: dict[str, Any], rubric: dict[str, Any], rep: Report) -> None:
    slice_cfg = rubric.get("slice") if isinstance(rubric.get("slice"), dict) else {}
    if not slice_cfg.get("call_args_sources_must_be_local"):
        return
    mapping = doc.get("mapping") if isinstance(doc.get("mapping"), dict) else {}
    chunk = doc.get("chunk") if isinstance(doc.get("chunk"), dict) else {}
    local = {str(c).strip() for c in (chunk.get("columns") or []) if str(c).strip()}
    if not local and mapping:
        want = rubric.get("columns") if isinstance(rubric.get("columns"), dict) else {}
        map_keys = {str(k) for k in mapping}
        want_keys = {str(k) for k in want}
        if want_keys and map_keys < want_keys:
            local = map_keys
    if not local:
        return
    for arg in doc.get("call_args") or []:
        if not isinstance(arg, dict):
            continue
        aname = _s(arg.get("name"))
        for src in arg.get("sources") or []:
            if not isinstance(src, dict):
                continue
            col = str(src.get("column") or "").strip()
            if col and col not in local:
                rep.add(
                    "columns",
                    f"S-foreign:{aname}:{col}",
                    False,
                    f"call_args {aname!r} sources column {col!r} is not in this slice",
                )


# ------------------------------------------------------------------------- driver
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rubric", required=True, type=Path)
    ap.add_argument("--product", required=True, action="append", type=Path)
    ap.add_argument("--repo", type=Path, default=None, help="test script root (defaults to test_script_root in the product)")
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--elapsed", type=float, default=None, help="wall time of the run under test, seconds")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    rubric = _load(args.rubric)
    doc = _merge([_load(p) for p in args.product])
    repo = args.repo
    if repo is None:
        declared = _s(doc.get("test_script_root"))
        repo = Path(declared) if declared else None
    if repo is not None and not repo.is_dir():
        repo = None

    rep = Report()
    check_invariants(doc, repo, rep)
    check_engine(doc, rubric, repo, rep)
    check_harness(doc, rubric, rep)
    check_columns(doc, rubric, rep)

    scoring = rubric.get("scoring") if isinstance(rubric.get("scoring"), dict) else {}
    required = [_s(f) for f in (scoring.get("required_families") or ["engine", "invariant"])]
    min_rate = scoring.get("min_pass_rate") or {}
    budget = scoring.get("budget_seconds")

    gates: dict[str, bool] = {}
    for fam in required:
        gates[f"{fam}=1.0"] = rep.rate(fam) >= 1.0
    for fam, threshold in min_rate.items():
        gates[f"{fam}>={threshold}"] = rep.rate(_s(fam)) >= float(threshold)
    if budget is not None and args.elapsed is not None:
        gates[f"elapsed<={budget}s"] = args.elapsed <= float(budget)

    passed = all(gates.values())
    families = sorted({c["family"] for c in rep.checks})
    summary = {
        "case": _s(rubric.get("case")),
        "passed": passed,
        "gates": gates,
        "families": {
            fam: {
                "passed": sum(1 for c in rep.family(fam) if c["ok"]),
                "total": len(rep.family(fam)),
                "rate": round(rep.rate(fam), 4),
            }
            for fam in families
        },
        "failures": [f"{c['family']}/{c['id']}: {c['detail']}" for c in rep.checks if not c["ok"]],
        "elapsed_s": args.elapsed,
    }

    if not args.quiet:
        for fam in families:
            rows = rep.family(fam)
            print(f"[{fam}] {sum(1 for r in rows if r['ok'])}/{len(rows)}")
            for row in rows:
                if not row["ok"]:
                    print(f"   FAIL {row['id']}: {row['detail']}")
        print()
        for name, ok in gates.items():
            print(f"{'PASS' if ok else 'FAIL'} gate {name}")
        print(f"\n=> {'PASS' if passed else 'FAIL'}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps({"summary": summary, "checks": rep.checks}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
