#!/usr/bin/env python3
"""Strict acp pilot loop — subprocess only, no certificate forging."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RUN_LOG = Path("/mnt/d/PR-review/AscendC-Pilot/artifacts/fa-pr13/full_closure_run_20260810")
PROJECT = Path("/work/ops-transformer/attention/flash_attention_score_grad")
PILOT = Path("/mnt/d/PR-review/AscendC-Pilot")
OP_NAME = "flash_attention_score_grad"
ARCH = "arch35"
LOG_DIR = RUN_LOG / "logs"
TIMELINE = RUN_LOG / "timeline.md"
PRIMARY_FINALIZE = frozenset({"human_confirm", "plan_intent", "plan_approve"})
SUBAGENT_ACTIONS = frozenset({"init_audit", "lemma_mine", "lemma_review", "closure_audit", "resolve"})


def env() -> dict[str, str]:
    e = os.environ.copy()
    e.update(
        {
            "PATH": f"/work/venv-acp/bin:/usr/bin:/bin:{e.get('PATH', '')}",
            "PYTHONPATH": ":".join(
                [
                    str(PILOT),
                    str(PILOT / "pilot"),
                    str(PILOT / "engines/testcase-generation"),
                    str(PILOT / "engines/understand-operator/src"),
                    str(PILOT / "scripts"),
                ]
            ),
            "ASCENDC_PROJECT_ROOT": str(PROJECT),
            "UO_OP_DIR": str(PROJECT),
            "UO_OPERATOR": OP_NAME,
            "UO_ARCH": ARCH,
            "UO_OPS_ROOT": "/work/ops-transformer",
            "OPS_TRANSFORMER_ROOT": "/work/ops-transformer",
            "UO_REPLAY_DISTRO": "Ubuntu-2204",
            "UO_REPLAY_HOST": "native",
        }
    )
    return e


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def append_timeline(t0: str, phase: str, wall_s: float, metrics: str, artifact: str, notes: str) -> None:
    with TIMELINE.open("a", encoding="utf-8") as f:
        f.write(f"| {t0} | {phase} | {wall_s:.1f} | {metrics} | {artifact} | {notes} |\n")


def acp_cmd(*args: str) -> tuple[int, dict]:
    cmd = ["acp", *args, "--project", str(PROJECT)]
    t0 = time.time()
    t0_iso = now_iso()
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    label = "_".join(a for a in args if not a.startswith("-"))[:80] or "acp"
    log = LOG_DIR / f"{label}_{ts}.log"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(cmd, capture_output=True, text=True, env=env())
    out = (p.stdout or "") + (p.stderr or "")
    log.write_text(out, encoding="utf-8")
    data: dict = {}
    start = out.rfind("{")
    if start >= 0:
        try:
            data = json.loads(out[start:])
        except json.JSONDecodeError:
            data = {"raw_tail": out[-1500:]}
    wall = time.time() - t0
    append_timeline(t0_iso, " ".join(args[:3]), wall, f"ec={p.returncode}", log.as_posix(), "")
    return p.returncode, data


def run_action(action: str, *, finalize: bool = False) -> dict:
    args = ["run-action", action]
    if finalize:
        args.append("--finalize")
    _, data = acp_cmd(*args)
    return data


def start_workflow(wf: str, *, force_new: bool = True) -> dict:
    args = ["start", wf, "--op-name", OP_NAME, "--architecture", ARCH, "--level", "L0"]
    if force_new:
        args.append("--force-new")
    _, data = acp_cmd(*args)
    return data


def advance(phase: str) -> dict:
    _, data = acp_cmd("advance", phase)
    return data


def next_state() -> dict:
    _, data = acp_cmd("next")
    return data


def complete() -> dict:
    _, data = acp_cmd("complete")
    return data


def recommended_action(nxt: dict) -> str | None:
    rec = nxt.get("recommended_next_action") or {}
    if isinstance(rec, dict):
        aid = str(rec.get("id") or rec.get("action_id") or "").strip()
        if aid:
            return aid
    for item in nxt.get("allowed_actions") or []:
        if isinstance(item, dict):
            aid = str(item.get("id") or item.get("action_id") or "").strip()
            if aid:
                return aid
    return None


def pipeline_complete(nxt: dict) -> bool:
    rec = nxt.get("recommended_next_action") or {}
    return str(rec.get("reason") or "") == "pipeline_complete"


def run_workflow_until_done(wf: str, *, max_steps: int = 200) -> dict:
    summary = {"workflow": wf, "steps": [], "ok": False}
    start_workflow(wf)
    for step in range(max_steps):
        nxt = next_state()
        if not nxt.get("ok"):
            summary["stop"] = nxt
            break
        status = str(nxt.get("status") or "")
        if status in {"passed", "blocked", "failed"}:
            summary["ok"] = status == "passed"
            summary["final_status"] = status
            break
        if pipeline_complete(nxt):
            phase = str(nxt.get("phase") or "")
            # advance to next phase — use workflow transitions
            adv = advance(phase)  # may need next phase id; try complete if last
            summary["steps"].append({"advance_from": phase, "result": adv})
            if adv.get("ok") and str(adv.get("phase") or "") != phase:
                continue
            comp = complete()
            if comp.get("ok"):
                summary["ok"] = True
                summary["final_status"] = "passed"
                break
            continue
        action = recommended_action(nxt)
        if not action:
            summary["stop"] = nxt
            break
        res = run_action(action)
        summary["steps"].append({"action": action, "ok": res.get("ok"), "error": res.get("error")})
        if action in PRIMARY_FINALIZE:
            fin = run_action(action, finalize=True)
            summary["steps"].append({"action": f"{action}--finalize", "ok": fin.get("ok")})
        elif action in SUBAGENT_ACTIONS:
            fin = run_action(action, finalize=True)
            summary["steps"].append({"action": f"{action}--finalize", "ok": fin.get("ok")})
        if res.get("auto_finalize"):
            fin = res.get("finalize") or {}
            summary["steps"][-1]["auto_finalize_ok"] = fin.get("ok")
    return summary


def archive_closure() -> Path | None:
    src = PROJECT / ".ascendc-pilot/arch35/tg/closure"
    if not src.is_dir():
        return None
    dest = RUN_LOG / f"archived_closure_{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    import shutil

    shutil.copytree(src, dest)
    shutil.rmtree(src)
    src.mkdir(parents=True, exist_ok=True)
    return dest


def collect_metrics() -> dict:
    import yaml

    cert = PROJECT / ".ascendc-pilot/arch35/tg/closure/certificate.yaml"
    m: dict = {"collected_at": now_iso()}
    if cert.is_file():
        d = yaml.safe_load(cert.read_text(encoding="utf-8")) or {}
        st = d.get("state") or {}
        g = d.get("gate") or {}
        inv = d.get("invariants") or {}
        m.update(
            {
                "certificate_ok": d.get("ok"),
                "D": st.get("declared") or inv.get("declared"),
                "R": st.get("R") or g.get("R"),
                "E": st.get("E") or g.get("E"),
                "gap": st.get("gap") if st.get("gap") is not None else g.get("gap"),
                "invariants_ok": inv.get("ok"),
                "I_cold_start": (inv.get("checks") or {}).get("I_cold_start"),
            }
        )
    return m


def main() -> int:
    wf = sys.argv[1] if len(sys.argv) > 1 else "all"
    if wf in {"all", "archive"}:
        dest = archive_closure()
        append_timeline(now_iso(), "archive/closure", 0, "—", str(dest or ""), "prior untrusted closure")
    if wf == "archive":
        return 0
    if wf in {"all", "uo-init"}:
        # Review readiness: start uo-init, jump phases via commit+review if product exists
        start_workflow("uo-init")
        # Fast path: try review when product exists — advance may fail; run review at review phase
        for phase in ("prepare", "extract", "analyze", "resolve", "commit", "review"):
            nxt = next_state()
            if pipeline_complete(nxt):
                advance(str(nxt.get("phase") or phase))
            act = recommended_action(nxt) or ("review" if phase == "review" else None)
            if act:
                run_action(act)
                if act in PRIMARY_FINALIZE:
                    run_action(act, finalize=True)
                elif act in SUBAGENT_ACTIONS:
                    run_action(act, finalize=True)
            if phase != "review":
                adv = advance(phase if phase != "prepare" else "extract")
                if not adv.get("ok"):
                    # try running phase action first
                    pass
        run_action("review")
        complete()
    if wf in {"all", "tg-init"}:
        run_workflow_until_done("tg-init")
    if wf in {"all", "tg-plan"}:
        run_workflow_until_done("tg-plan")
    if wf in {"all", "tg-solve"}:
        run_workflow_until_done("tg-solve", max_steps=500)
    metrics = collect_metrics()
    (RUN_LOG / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    (RUN_LOG / "STOP_REASON.txt").write_text(
        f"Pilot loop finished workflow={wf} gap={metrics.get('gap')} cert_ok={metrics.get('certificate_ok')}\n",
        encoding="utf-8",
    )
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
