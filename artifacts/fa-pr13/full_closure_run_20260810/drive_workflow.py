#!/usr/bin/env python3
"""Drive one acp workflow until passed/blocked — subprocess acp only."""
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
OP, ARCH = "flash_attention_score_grad", "arch35"
LOG_DIR = RUN_LOG / "logs"
TIMELINE = RUN_LOG / "timeline.md"
FINALIZE_ACTIONS = frozenset({"human_confirm", "plan_intent", "plan_approve"})
SUBAGENT = frozenset({"init_audit", "lemma_mine", "lemma_review", "closure_audit", "resolve", "semantic_bind"})

# tg-init phase order after confirm
TG_INIT_PHASES = ["intent", "kb_ready", "contract", "bind", "gate", "confirm", "merge", "nest"]
TG_PLAN_PHASES = ["intent", "scope", "gate", "build", "approve"]
TG_SOLVE_PHASES = ["gate", "oracle", "ledger", "search", "residual", "construct", "lemma", "audit", "certify"]


def env() -> dict[str, str]:
    return {
        **os.environ,
        "PATH": f"/work/venv-acp/bin:/usr/bin:/bin",
        "PYTHONPATH": ":".join([
            str(PILOT), str(PILOT / "pilot"), str(PILOT / "engines/testcase-generation"),
            str(PILOT / "engines/understand-operator/src"), str(PILOT / "scripts"),
        ]),
        "ASCENDC_PROJECT_ROOT": str(PROJECT),
        "UO_OP_DIR": str(PROJECT),
        "UO_OPERATOR": OP,
        "UO_ARCH": ARCH,
        "UO_OPS_ROOT": "/work/ops-transformer",
        "OPS_TRANSFORMER_ROOT": "/work/ops-transformer",
        "UO_REPLAY_DISTRO": "Ubuntu-2204",
        "UO_REPLAY_HOST": "native",
    }


def log_line(msg: str) -> None:
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def ts_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def append_timeline(t0: str, phase: str, wall: float, metrics: str, artifact: str, notes: str) -> None:
    with TIMELINE.open("a", encoding="utf-8") as f:
        f.write(f"| {t0} | {phase} | {wall:.1f} | {metrics} | {artifact} | {notes} |\n")


def acp(*args: str) -> dict:
    cmd = ["acp", *args, "--project", str(PROJECT)]
    t0, t0e = ts_iso(), time.time()
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    label = "_".join(a for a in args if not a.startswith("-"))[:60]
    logf = LOG_DIR / f"{label}_{stamp}.log"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(cmd, capture_output=True, text=True, env=env())
    text = (p.stdout or "") + (p.stderr or "")
    logf.write_text(text, encoding="utf-8")
    data: dict = {}
    i = text.find("{")
    if i >= 0:
        try:
            data = json.loads(text[i:])
        except json.JSONDecodeError:
            # trailing noise after valid JSON
            for end in range(len(text), i, -1):
                if text[end - 1] in "}\n":
                    try:
                        data = json.loads(text[i:end])
                        break
                    except json.JSONDecodeError:
                        continue
            if not data:
                data = {"parse_error": True, "tail": text[-800:]}
    data["_ec"] = p.returncode
    data["_log"] = logf.as_posix()
    append_timeline(t0, " ".join(args[:3]), time.time() - t0e, f"ec={p.returncode}", logf.name, "")
    return data


def run_action(action: str, finalize: bool = False) -> dict:
    args = ["run-action", action]
    if finalize:
        args.append("--finalize")
    return acp(*args)


def drive_workflow(wf: str, *, max_steps: int = 300) -> dict:
    summary: dict = {"workflow": wf, "steps": []}
    acp("start", wf, "--op-name", OP, "--architecture", ARCH, "--level", "L0")
    for step in range(max_steps):
        nxt = acp("next")
        summary["steps"].append({"step": step, "next_ok": nxt.get("ok"), "phase": nxt.get("phase"), "status": nxt.get("status")})
        if not nxt.get("ok"):
            summary["stop"] = nxt
            break
        status = str(nxt.get("status") or "")
        if status in {"passed", "blocked", "failed"}:
            summary["final_status"] = status
            summary["ok"] = status == "passed"
            break
        rec = nxt.get("recommended_next_action") or {}
        reason = str(rec.get("reason") or "")
        if reason == "pipeline_complete":
            phase = str(nxt.get("phase") or "")
            # Find next phase from workflow meta
            phases = {"tg-init": TG_INIT_PHASES, "tg-plan": TG_PLAN_PHASES, "tg-solve": TG_SOLVE_PHASES}.get(wf, [])
            nphase = None
            if phase in phases:
                idx = phases.index(phase)
                if idx + 1 < len(phases):
                    nphase = phases[idx + 1]
            if nphase:
                adv = acp("advance", nphase)
                summary["steps"].append({"advance": nphase, "ok": adv.get("ok")})
                if not adv.get("ok"):
                    # try complete
                    comp = acp("complete")
                    if comp.get("ok"):
                        summary["ok"] = True
                        summary["final_status"] = "passed"
                    break
                continue
            comp = acp("complete")
            summary["steps"].append({"complete": comp.get("ok")})
            summary["ok"] = bool(comp.get("ok"))
            summary["final_status"] = "passed" if comp.get("ok") else status
            break
        action = str(rec.get("id") or rec.get("action_id") or "")
        if not action:
            al = nxt.get("allowed_actions") or []
            if al and isinstance(al[0], dict):
                action = str(al[0].get("id") or "")
        if not action:
            summary["stop"] = nxt
            break
        log_line(f"  run-action {action}")
        res = run_action(action)
        summary["steps"].append({"action": action, "ok": res.get("ok"), "error": res.get("error")})
        if action in FINALIZE_ACTIONS:
            fin = run_action(action, finalize=True)
            summary["steps"].append({"action": f"{action}--finalize", "ok": fin.get("ok"), "notes": "user authorized T=D/full coverage"})
        elif action in SUBAGENT:
            fin = run_action(action, finalize=True)
            summary["steps"].append({"action": f"{action}--finalize", "ok": fin.get("ok")})
        if res.get("auto_finalize"):
            summary["steps"][-1]["auto_finalize_ok"] = (res.get("finalize") or {}).get("ok")
        # Early exit for tg-solve if gap=0
        if wf == "tg-solve":
            cert = PROJECT / ".ascendc-pilot/arch35/tg/closure/certificate.yaml"
            if cert.is_file():
                import yaml
                d = yaml.safe_load(cert.read_text()) or {}
                gap = (d.get("state") or {}).get("gap", d.get("gate", {}).get("gap"))
                if gap == 0 and action == "closure_certify":
                    acp("complete")
                    summary["ok"] = True
                    summary["final_status"] = "passed"
                    break
    return summary


def main() -> int:
    wf = sys.argv[1] if len(sys.argv) > 1 else "tg-init"
    log_line(f"=== drive {wf} ===")
    summary = drive_workflow(wf)
    out = RUN_LOG / f"summary_{wf}.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    log_line(json.dumps({"workflow": wf, "ok": summary.get("ok"), "final": summary.get("final_status")}))
    return 0 if summary.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
