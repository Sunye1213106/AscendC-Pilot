#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Drive uo-init to completion: acp next → run-action → advance <next_phase>."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PHASES = ("prepare", "scope", "extract", "normalize", "export", "review")


def _run(args: list[str], project: Path) -> dict:
    cmd = [sys.executable, "-m", "ascendc_pilot.cli", *args, "--project", str(project)]
    proc = subprocess.run(
        cmd,
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if err and "usage:" not in err.lower():
        print(err[-2000:], file=sys.stderr)
    doc: dict = {}
    # Walk braces from the end; stdout may contain multiple JSON objects.
    depth = 0
    end = None
    for i in range(len(out) - 1, -1, -1):
        ch = out[i]
        if ch == "}":
            if depth == 0:
                end = i
            depth += 1
        elif ch == "{":
            depth -= 1
            if depth == 0 and end is not None:
                try:
                    doc = json.loads(out[i : end + 1])
                    break
                except Exception:
                    end = None
                    continue
    if not doc:
        doc = {"ok": proc.returncode == 0, "raw": out[-1500:], "stderr": err[-800:]}
    doc["_returncode"] = proc.returncode
    return doc


def _next_phase(current: str) -> str | None:
    try:
        i = PHASES.index(current)
    except ValueError:
        return None
    if i + 1 >= len(PHASES):
        return None
    return PHASES[i + 1]


def main() -> int:
    project = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    max_steps = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    print(f"project={project}", flush=True)
    for step in range(1, max_steps + 1):
        nxt = _run(["next"], project)
        status = str(nxt.get("status") or "")
        phase = str(nxt.get("phase") or "")
        rec_obj = nxt.get("recommended_next_action") or {}
        rec = rec_obj.get("id") if isinstance(rec_obj, dict) else None
        reason = rec_obj.get("reason") if isinstance(rec_obj, dict) else ""
        if not rec:
            # Rework mode: next leaves recommended null; retry targets instead.
            targets = nxt.get("rework_targets") or []
            if targets and isinstance(targets[0], dict):
                rec = targets[0].get("action_id") or targets[0].get("id")
                reason = reason or "rework_target"
        print(f"\n[{step}] status={status} phase={phase} next={rec} reason={reason}", flush=True)

        if status in {"passed", "complete", "completed"}:
            print("UO-INIT PASSED", flush=True)
            return 0

        if rec:
            t0 = time.time()
            res = _run(["run-action", str(rec)], project)
            dt = time.time() - t0
            ok = bool(res.get("ok"))
            fin = (res.get("finalize") or {}).get("ok")
            mode = res.get("execution_mode") or ""
            print(
                f"  run-action {rec}: ok={ok} finalize={fin} mode={mode} {dt:.1f}s",
                flush=True,
            )
            if not ok:
                print(json.dumps({k: res.get(k) for k in ("ok", "error", "message_zh", "finalize")}, ensure_ascii=False, indent=2)[:4000])
                return 1
            # Interactive scope_confirm: auto-accept the scan and finalize.
            if str(rec) == "scope_confirm" and not fin:
                for args in (
                    ["uo-scope", "checkpoint", "--decision", "continue"],
                    ["uo-scope", "finalize", "--decision", "continue"],
                    ["run-action", "scope_confirm", "--finalize"],
                ):
                    step_res = _run(args, project)
                    ok = step_res.get("ok")
                    if ok is None:
                        obs = step_res.get("observation") or {}
                        ok = str(obs.get("outcome") or "") == "success" or int(
                            step_res.get("_returncode") or 1
                        ) == 0
                    print(
                        f"    {' '.join(args)} → ok={ok} "
                        f"err={step_res.get('error')}",
                        flush=True,
                    )
                    if not ok and "LEASE" not in str(step_res.get("error") or ""):
                        # finalize may still succeed after LEASE_REVOKED on stale prepare
                        if "--finalize" not in args:
                            print(json.dumps(step_res, ensure_ascii=False, indent=2)[:2000])
                            return 1
                continue

            # Deterministic actions already finalized above.
            continue

        # No recommended action → advance phase when pipeline_complete.
        nxt_phase = _next_phase(phase)
        if not nxt_phase:
            # Last phase with no more actions — try complete.
            done = _run(["complete"], project)
            print(f"  complete ok={done.get('ok')} status={done.get('status')} err={done.get('error')}", flush=True)
            return 0 if done.get("ok") or done.get("status") in {"passed", "complete"} else 1

        adv = _run(["advance", nxt_phase], project)
        print(
            f"  advance → {nxt_phase}: ok={adv.get('ok')} phase={adv.get('phase')} "
            f"err={adv.get('error')} msg={adv.get('message_zh')}",
            flush=True,
        )
        if not adv.get("ok"):
            # Dump gate failures briefly.
            print(json.dumps({
                "error": adv.get("error"),
                "message_zh": adv.get("message_zh"),
                "failed_gates": adv.get("failed_gates"),
                "open_items": adv.get("open_items"),
            }, ensure_ascii=False, indent=2)[:4000])
            return 1

    print("max steps exceeded", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
