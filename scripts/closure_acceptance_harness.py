#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Acceptance harness for the TilingKey closure loop.

Two modes, same report schema:

``dry`` (default, no NPU, no API key)
    Drives the loop directly on ``_synthetic_toy`` with a deterministic oracle.
    This is the CI gate: it proves the loop closes a gap rather than that its
    steps return ``ok``.

``agent`` (opt-in, needs ``cursor-sdk`` and credentials)
    Hands the same workspace to a headless Cursor agent and lets it drive
    ``tg-closure`` itself. That is the Composer 2.5 measurement the plan asks
    for; the dry mode stays the regression gate because it needs nothing.

Run N times and report the distribution, not one sample::

    python scripts/closure_acceptance_harness.py --runs 5
    python scripts/closure_acceptance_harness.py --mode agent --runs 5 \
        --model composer-2.5 --operator-root <op>

Exit code is non-zero when any run fails its acceptance criteria.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


REPO = Path(__file__).resolve().parents[1]

#: The toy key has one 3-bit dimension with five declared values. Keys encode
#: the *index* of the chosen value, so the declared set is 0..4 and key 0 is a
#: legal key like any other.
_TOY_DIM_VALUES = (0, 1, 2, 3, 4)

#: Inverse of ``construction_hints.n_for``: which key the toy's `n` knob spells.
_N_TO_KEY = {1: 0, 2: 1, 4: 2, 8: 3, 16: 4}

_TOY_TPL = """
ASCENDC_TPL_ARGS_DECL(_synthetic_toy,
    ASCENDC_TPL_UINT_DECL(A, ASCENDC_TPL_3_BW, ASCENDC_TPL_UI_LIST, %(values)s),
)
ASCENDC_TPL_ARGS_SEL(
    ASCENDC_TPL_UINT_SEL(A, ASCENDC_TPL_UI_LIST, %(values)s),
)
""" % {"values": ", ".join(str(v) for v in _TOY_DIM_VALUES)}


def _ensure_paths() -> None:
    for p in (
        REPO / "engines" / "testcase-generation",
        REPO / "engines" / "understand-operator" / "src",
        REPO / "pilot",
        REPO / "scripts",
    ):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


class ToyOracle:
    """Answers with the key the case actually spells, not with a fixed list.

    ``StubOracle`` maps by position, which cannot tell "the loop constructed
    the target" from "the loop constructed anything at all". Deriving the key
    from the ``n`` knob makes the arm's hit counters mean something.
    """

    def __init__(self) -> None:
        from testcase_agent.closure.oracle import accounting

        self.calls = 0
        self.judged_cases = 0
        self.last_accounting: dict[str, int] = accounting(())

    def judge(self, cases: Sequence[Any], *, tag: str = "") -> list:
        from testcase_agent.closure.oracle import Verdict, accounting

        self.calls += 1
        self.judged_cases += len(cases)
        out = []
        for i, case in enumerate(cases):
            key = _N_TO_KEY.get(int(getattr(case, "n", 0) or 0))
            out.append(
                Verdict(
                    case_id=f"{tag}_{i}",
                    ok=key is not None,
                    key=int(key) if key is not None else -1,
                    judged=True,
                )
            )
        self.last_accounting = accounting(
            out, generated=len(cases), serialized=len(cases)
        )
        return out


def _write_toy_domain_codemap(
    product: Path,
    *,
    op_name: str,
    arch: str,
    kernel_doc: dict,
    tiling_doc: dict,
) -> None:
    """Persist a tiny CodeMap whose TG projections match the toy kernel/tiling views."""
    from uo_init.ir.codemap import CodeMap
    from uo_init.ir.entity import Entity, EntityKind
    from uo_init.ir.relation import RelationKind
    from uo_init.store.writer import write_codemap

    cm = CodeMap(op_name=op_name, architecture=arch)
    cm.add_entity(Entity(id=f"ARCH_{arch}", kind=EntityKind.ARCH, name=arch))
    for branch in kernel_doc.get("branches") or []:
        if not isinstance(branch, dict) or not branch.get("id"):
            continue
        cm.add_entity(
            Entity(
                id=str(branch["id"]),
                kind=EntityKind.BRANCH,
                name=str(branch.get("name") or branch["id"]),
                attrs={
                    "condition": branch.get("condition") or "",
                    "dimensions": list(branch.get("dimensions") or []),
                    "finite_predicate": branch.get("finite_predicate"),
                    "stage": branch.get("stage") or "constexpr",
                },
            )
        )
    for st in tiling_doc.get("structs") or []:
        if not isinstance(st, dict):
            continue
        owner = str(st.get("name") or "TilingData")
        for fld in st.get("fields") or []:
            if not isinstance(fld, dict) or not fld.get("name"):
                continue
            name = str(fld["name"])
            field_id = f"TDF_{owner}_{name}"
            cm.add_entity(
                Entity(
                    id=field_id,
                    kind=EntityKind.TILING_FIELD,
                    name=name,
                    attrs={
                        "owner": owner,
                        "struct": owner,
                        "host_writer_sites": list(fld.get("writers") or []),
                    },
                )
            )
            for reader in fld.get("readers") or []:
                if not isinstance(reader, dict):
                    continue
                fn = str(reader.get("function") or reader.get("name") or "")
                if not fn:
                    continue
                fn_id = f"FN_{fn}"
                if fn_id not in cm.entities:
                    cm.add_entity(Entity(id=fn_id, kind=EntityKind.FUNCTION, name=fn))
                cm.link(RelationKind.READS, fn_id, field_id, attrs={"function": fn})
    write_codemap(cm, product)


def _seed_domain_uo(root: Path, arch: str = "arch0") -> Path:
    """Write a tiny UO product so kernel / tilingdata domains join per key.

    Prefer a real ``.uo`` CodeMap product.
    """
    uo = root / ".ascendc-pilot" / arch / "uo"
    uo.mkdir(parents=True, exist_ok=True)
    kernel_doc = {
        "schema": "uo-view-kernel/v1",
        "branches": [
            {
                "id": "KB_A1",
                "condition": "A == 1",
                "dimensions": ["A"],
                "stage": "constexpr",
                "finite_predicate": {"op": "eq", "field": "A", "value": 1},
            }
        ],
    }
    tiling_doc = {
        "schema": "uo-view-tilingdata/v1",
        "version": 1,
        "status": "extracted",
        "structs": [
            {
                "name": "ToyTile",
                "fields": [
                    {
                        "name": "len",
                        "writers": [
                            {
                                "dimensions": ["A"],
                                "finite_predicate": {
                                    "op": "eq",
                                    "field": "A",
                                    "value": 2,
                                },
                            }
                        ],
                        "readers": [{"name": "kernel_read"}],
                    }
                ],
            }
        ],
        "defects": {},
    }
    product = uo / f"_synthetic_toy.{arch}.uo"
    _write_toy_domain_codemap(
        product,
        op_name="_synthetic_toy",
        arch=arch,
        kernel_doc=kernel_doc,
        tiling_doc=tiling_doc,
    )
    return uo


def _seed_synthetic_workspace(root: Path) -> Path:
    """Minimal op root: toy TPL header, domain UO, empty closure state."""
    arch = "arch0"
    header = root / "op_kernel" / arch / "_synthetic_toy_template_tiling_key.h"
    header.parent.mkdir(parents=True, exist_ok=True)
    header.write_text(_TOY_TPL, encoding="utf-8")
    _seed_domain_uo(root, arch=arch)
    tg = root / ".ascendc-pilot" / arch / "tg" / "closure"
    tg.mkdir(parents=True, exist_ok=True)
    (tg / "R.txt").write_text("", encoding="utf-8")
    (tg / "excluded.txt").write_text("", encoding="utf-8")
    (tg / "lemmas").mkdir(exist_ok=True)
    return tg


def _prepare_env(root: Path, state: Path) -> None:
    os.environ["UO_OPERATOR"] = "_synthetic_toy"
    os.environ["UO_ARCH"] = "arch0"
    os.environ["TG_CLOSURE_CI"] = "1"
    os.environ["ASCENDC_PROJECT_ROOT"] = str(root)
    os.environ["UO_OP_DIR"] = str(root)
    os.environ["TG_CLOSURE_STATE"] = str(state)
    # Package-side input_semantics / log_protocol live in test fixtures,
    # not under the ephemeral operator root.
    repo = Path(__file__).resolve().parents[1]
    fixture_pkg = repo / "tests" / "fixtures" / "_synthetic_toy" / "arch0"
    if fixture_pkg.is_dir():
        os.environ["UO_PACKAGE_DIR"] = str(fixture_pkg)


def _fresh_workspace(root: Path | None):
    """A workspace whose schema / corpus caches see this run's header."""
    from testcase_agent.closure import workspace as W
    from replay import package_data

    if root is None:
        root = Path(tempfile.mkdtemp(prefix="closure_harness_"))
    root = Path(root).resolve()
    state = _seed_synthetic_workspace(root)
    _prepare_env(root, state)
    # Operator identity and the declared set are both cached per process.
    package_data.clear_caches()
    for name in ("declared", "_replay", "dim_names"):
        fn = getattr(W, name, None)
        clear = getattr(fn, "cache_clear", None)
        if clear is not None:
            clear()
    return root, state, W.Workspace(root=root, artifacts=state, state=state).ensure()


def run_dry(
    root: Path | None = None,
    *,
    budget: int = 8,
    seed: int = 0,
    max_rounds: int = 6,
) -> dict[str, Any]:
    """Drive the loop to gap=0 with a deterministic oracle."""
    _ensure_paths()
    from testcase_agent.closure import cold_start as CS
    from testcase_agent.closure import ledger
    from testcase_agent.closure import oracle as O
    from testcase_agent.closure import report as closure_report
    from testcase_agent.closure import search_round

    root, state, ws = _fresh_workspace(root)
    report: dict[str, Any] = {
        "schema": "tg-closure-acceptance/v2",
        "mode": "deterministic_dry",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "seed": seed,
        "steps": [],
        "rounds": [],
        "gate_failures": [],
    }

    cold = CS.cold_start(ws, clear_rounds=True)
    report["steps"].append(
        {"step": "cold-start", "ok": bool(cold.get("ok")), "fingerprint": cold.get("fingerprint")}
    )
    if not cold.get("ok"):
        report["gate_failures"].append("cold_start")

    start = ledger.state(ws)
    report["declared"] = start["declared"]
    report["initial_gap"] = start["gap"]
    if start["declared"] <= 0:
        report["gate_failures"].append("declared_set_empty")
    if start["R"] != 0 or start["E"] != 0:
        report["gate_failures"].append("cold_start_left_ledger_non_empty")

    oracle = ToyOracle()
    gap = start["gap"]
    for i in range(max_rounds):
        if gap == 0:
            break
        try:
            out = search_round.run_round(ws, budget=budget, seed=seed + i, oracle=oracle)
        except Exception as exc:  # noqa: BLE001
            report["gate_failures"].append(f"search_round_raised:{type(exc).__name__}:{exc}"[:200])
            break
        progress = out.get("progress") or {}
        st = ledger.state(ws)
        gap = st["gap"]
        report["rounds"].append(
            {
                "round": i + 1,
                "candidates": int((progress.get("model_arm") or {}).get("candidates") or 0)
                + int((progress.get("random_arm") or {}).get("candidates") or 0),
                "judged": int((progress.get("model_arm") or {}).get("judged") or 0)
                + int((progress.get("random_arm") or {}).get("judged") or 0),
                "new_R": int(progress.get("new_R") or 0),
                "R": st["R"],
                "gap": gap,
                "route_hint": out.get("route_hint"),
            }
        )

    report["rounds_used"] = len(report["rounds"])
    report["final_gap"] = gap
    report["R"] = ledger.state(ws)["R"]
    report["oracle_calls"] = oracle.calls
    report["oracle_judged_cases"] = oracle.judged_cases

    # A loop that never asked the oracle anything has not been exercised, no
    # matter what its steps returned. This is the check the old harness lacked.
    if oracle.calls == 0 or oracle.judged_cases == 0:
        report["gate_failures"].append("oracle_never_invoked")
    if not any(r["candidates"] for r in report["rounds"]):
        report["gate_failures"].append("no_candidates_constructed")
    if gap != 0:
        report["gate_failures"].append(f"gap_not_closed:{gap}")

    prov = CS.check_e_provenance(ws)
    report["steps"].append({"step": "provenance", "ok": bool(prov.get("ok")), "issues": prov.get("issues")})
    if not prov.get("ok"):
        report["gate_failures"].append("provenance")

    # Oracle self-check must flag a deliberate sent/DONE mismatch.
    sc = O.selfcheck(sent=4, done_count=2, ws=ws)
    report["steps"].append(
        {"step": "oracle_selfcheck_mismatch", "detected": sc.get("ok") is False, "issues": sc.get("issues")}
    )
    if sc.get("ok") is not False:
        report["gate_failures"].append("expected_oracle_suspect_not_raised")
    # The flag it drops would poison later rounds; clear it after asserting.
    flag = Path(ws.state) / "oracle_suspect"
    if flag.exists():
        flag.unlink()

    try:
        cert = closure_report.certify_invariants(ws)
        report["steps"].append({"step": "certify", "ok": bool(cert.get("ok")), "checks": sorted(cert.get("checks") or {})})
        if not cert.get("ok"):
            report["gate_failures"].append("certify_invariants")
        # Three-domain join: at least one key must name a kernel branch or field.
        rep = closure_report.report(ws, refresh=False)
        report["steps"].append(
            {
                "step": "tri_domain_report",
                "ok": bool(rep.get("ok")),
                "keys_with_kernel_branches": rep.get("keys_with_kernel_branches"),
                "keys_with_tilingdata_fields": rep.get("keys_with_tilingdata_fields"),
            }
        )
        if not (
            int(rep.get("keys_with_kernel_branches") or 0)
            or int(rep.get("keys_with_tilingdata_fields") or 0)
        ):
            report["gate_failures"].append("tri_domain_columns_empty")
    except Exception as exc:  # noqa: BLE001
        report["gate_failures"].append(f"certify_raised:{type(exc).__name__}")

    report["ok"] = not report["gate_failures"]
    out_path = Path(state) / "acceptance_harness_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(out_path)
    return report


_AGENT_PROMPT = """\
You are driving the TilingKey closure loop for operator {operator} (arch {arch}).

Working directory: {root}

Use only the `tg-closure` CLI. Do not edit source or state files by hand.

1. `python -m testcase_agent.closure.cli cold-start`
2. Loop: `route` → run the action it names (`search-round --stub`, `construct`,
   or `lemma-evidence` + `lemma_review`) → `state`.
3. Stop when `state` reports `gap: 0`, or when `route` reports no progress twice.

Report the final `state` JSON as your last message.
"""


def run_agent(
    root: Path | None = None,
    *,
    model: str = "composer-2.5",
    seed: int = 0,
    timeout_s: float = 900.0,
) -> dict[str, Any]:
    """Let a headless Cursor agent drive the same loop.

    Opt-in: needs ``pip install cursor-sdk``, ``CURSOR_API_KEY``, and working
    credentials. Acceptance criteria match :func:`run_dry` — the measurement
    is whether a cheaper model reaches gap=0 unaided.
    """
    _ensure_paths()
    from testcase_agent.closure import ledger

    root, state, ws = _fresh_workspace(root)
    # Point the agent at the same PYTHONPATH the dry path uses.
    path_bits = [
        str(REPO / "engines" / "testcase-generation"),
        str(REPO / "engines" / "understand-operator" / "src"),
        str(REPO / "pilot"),
        str(REPO / "scripts"),
        os.environ.get("PYTHONPATH", ""),
    ]
    os.environ["PYTHONPATH"] = os.pathsep.join(p for p in path_bits if p)
    os.environ.setdefault("UO_OPERATOR", "_synthetic_toy")
    os.environ.setdefault("UO_ARCH", "arch0")
    os.environ["ASCENDC_PROJECT_ROOT"] = str(root)
    os.environ["UO_OP_DIR"] = str(root)
    os.environ["TG_CLOSURE_STATE"] = str(state)

    report: dict[str, Any] = {
        "schema": "tg-closure-acceptance/v2",
        "mode": "agent",
        "model": model,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "seed": seed,
        "gate_failures": [],
    }
    try:
        from cursor_sdk import Agent, AgentOptions, LocalAgentOptions  # type: ignore
    except Exception as exc:  # noqa: BLE001
        report["ok"] = False
        report["skipped"] = True
        report["reason"] = f"cursor-sdk unavailable: {exc}"
        return report

    api_key = (os.environ.get("CURSOR_API_KEY") or "").strip()
    if not api_key:
        report["ok"] = False
        report["skipped"] = True
        report["reason"] = "CURSOR_API_KEY unset"
        return report

    prompt = _AGENT_PROMPT.format(
        operator="_synthetic_toy", arch="arch0", root=str(root)
    )
    try:
        # Canonical one-shot shape from the Cursor SDK skill.
        result = Agent.prompt(
            prompt,
            AgentOptions(
                api_key=api_key,
                model=model,
                local=LocalAgentOptions(cwd=str(root)),
            ),
        )
        report["agent_status"] = getattr(result, "status", "")
        report["agent_result"] = str(getattr(result, "result", "") or "")[:2000]
        # Soft timeout note: Agent.prompt is synchronous; callers that need a
        # hard wall clock should wrap this process. ``timeout_s`` is retained
        # for CLI symmetry / future create+send cancellation.
        report["timeout_s"] = timeout_s
    except Exception as exc:  # noqa: BLE001
        report["gate_failures"].append(f"agent_error:{type(exc).__name__}:{exc}"[:200])

    st = ledger.state(ws)
    report.update({"declared": st["declared"], "R": st["R"], "final_gap": st["gap"]})
    if st["gap"] != 0:
        report["gate_failures"].append(f"gap_not_closed:{st['gap']}")
    report["ok"] = not report["gate_failures"]
    out_path = Path(state) / "acceptance_harness_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(out_path)
    return report


def summarize(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Distribution over runs — a single sample says nothing about a model.

    Delegates to ``evals.harness.runner.summarize_runs`` when available so CI
    smoke and this harness share pass@1 / pass^k / token metrics. Falls back
    to the historical local summary if evals is not on PYTHONPATH.
    """
    try:
        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        from evals.harness.runner import summarize_runs

        return summarize_runs(runs)
    except Exception:
        gaps = [int(r.get("final_gap") or 0) for r in runs if not r.get("skipped")]
        rounds = [int(r.get("rounds_used") or 0) for r in runs if r.get("rounds_used")]
        failures: dict[str, int] = {}
        for r in runs:
            for f in r.get("gate_failures") or []:
                failures[str(f).split(":")[0]] = failures.get(str(f).split(":")[0], 0) + 1
        passed = sum(1 for r in runs if r.get("ok"))
        out: dict[str, Any] = {
            "runs": len(runs),
            "passed": passed,
            "pass_rate": round(passed / len(runs), 3) if runs else 0.0,
            "gate_failure_counts": failures,
        }
        if gaps:
            out["final_gap"] = {
                "min": min(gaps),
                "max": max(gaps),
                "mean": round(statistics.fmean(gaps), 2),
            }
        if rounds:
            out["rounds_used"] = {
                "min": min(rounds),
                "max": max(rounds),
                "mean": round(statistics.fmean(rounds), 2),
            }
        return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mode", choices=("dry", "agent"), default="dry")
    ap.add_argument("--root", default=None, help="operator root (default: temp dir per run)")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--budget", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-rounds", type=int, default=6)
    ap.add_argument("--model", default="composer-2.5", help="agent mode only")
    args = ap.parse_args(argv)

    runs: list[dict[str, Any]] = []
    for i in range(max(1, args.runs)):
        # A fresh root per run: reusing one would carry R across samples.
        root = Path(args.root) / f"run_{i:02d}" if args.root else None
        if args.mode == "agent":
            runs.append(run_agent(root, model=args.model, seed=args.seed + i))
        else:
            runs.append(
                run_dry(root, budget=args.budget, seed=args.seed + i, max_rounds=args.max_rounds)
            )

    doc = {"summary": summarize(runs), "runs": runs}
    print(json.dumps(doc, ensure_ascii=False, indent=2))
    if any(r.get("skipped") for r in runs):
        return 0
    return 0 if all(r.get("ok") for r in runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
