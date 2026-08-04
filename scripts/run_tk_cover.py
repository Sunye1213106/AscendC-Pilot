# -*- coding: utf-8 -*-
"""Single entry for tk-cover: reset artifacts → drive acp → real coverage gate.

Composer / weak models should run only this script (plus optionally mining
recipes into the mine_recipe parts dir before --continue-close).

    python scripts/run_tk_cover.py --reset
    # optional: write recipes into runs/.../mine_recipe/parts/part_0.yaml
    python scripts/run_tk_cover.py --from-close

Always use ``python -m ascendc_pilot.cli`` via this script — never the
packaged ``acp.exe`` (it ignores local pilot changes).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[1]


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = ";".join([
        str(PROJ / "pilot"),
        str(PROJ / "engines" / "understand-operator" / "src"),
        str(PROJ / "engines" / "common" / "src"),
        str(PROJ / "scripts"),
    ])
    env.setdefault("UO_REPLAY_DISTRO", "Ubuntu-2204")
    return env


def acp(*args: str) -> dict:
    cmd = [sys.executable, "-m", "ascendc_pilot.cli", *args, "--project", str(PROJ)]
    p = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        errors="replace", env=_env(), cwd=str(PROJ),
    )
    out = (p.stdout or "") + (p.stderr or "")
    i = out.find("{")
    if i < 0:
        return {"ok": False, "raw": out[:800], "returncode": p.returncode}
    depth = 0
    end = i
    for j, ch in enumerate(out[i:], i):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = j + 1
                break
    try:
        doc = json.loads(out[i:end])
    except json.JSONDecodeError:
        return {"ok": False, "raw": out[i:i + 400], "returncode": p.returncode}
    doc.setdefault("returncode", p.returncode)
    return doc


def summarize(label: str, doc: dict) -> None:
    fin = doc.get("finalize") or {}
    chk = fin.get("checker_result") or doc.get("checker_result") or {}
    gates = chk.get("gates") or []
    oc = chk.get("output_contract") or {}
    print(
        f"{label}: ok={doc.get('ok')} status={doc.get('status') or fin.get('status')} "
        f"fin={fin.get('ok')} oc={oc.get('ok')} "
        f"gates={[(g.get('gate'), g.get('ok')) for g in gates]} "
        f"err={doc.get('error') or fin.get('message_zh') or ''}",
        flush=True,
    )


def reset_artifacts(*, wipe_runs: bool = True) -> None:
    """Clear tk-cover outputs so a fresh run owns the receipts."""
    tk = PROJ / ".ascendc-pilot" / "uo" / "tk"
    if tk.is_dir():
        shutil.rmtree(tk)
        print(f"removed {tk}", flush=True)
    # Leave ir/codemap + derive cache; re-exported each run.
    residual = PROJ / ".probe_cache" / "replay" / "coverage_closure.yaml"
    if residual.is_file():
        residual.unlink()
        print(f"removed {residual}", flush=True)
    if wipe_runs:
        runs = PROJ / ".ascendc-pilot" / "runs"
        if runs.is_dir():
            # Only wipe dirs that look like tk-cover runs (keep other workflows).
            for child in list(runs.iterdir()):
                marker = child / "workflow_id.txt"
                wipe = False
                if (child / "actions" / "mine_recipe").is_dir():
                    wipe = True
                if (child / "actions" / "coverage_gate").is_dir():
                    wipe = True
                if wipe:
                    shutil.rmtree(child, ignore_errors=True)
                    print(f"removed run {child.name}", flush=True)
    # Abort any stuck active workflow so --force-new can reinit cleanly.
    st = acp("status")
    if st.get("workflow_id") == "tk-cover" and st.get("status") not in (
        None, "idle", "passed", "failed", "aborted",
    ):
        print("abort active tk-cover", flush=True)
        summarize("ABORT", acp("abort", "--reason", "tk-cover reset"))


def _fin_ok(doc: dict) -> bool:
    fin = doc.get("finalize") or {}
    if fin.get("ok"):
        return True
    chk = doc.get("checker_result") or fin.get("checker_result") or {}
    if isinstance(chk, dict) and chk.get("ok"):
        return True
    return bool(doc.get("ok") and doc.get("receipt"))


def _stamp_mine_identity(prepare: dict) -> None:
    import yaml

    run_id = str(prepare.get("run_id") or "")
    identity = dict(prepare.get("identity") or {})
    if not identity.get("run_id"):
        identity.update({
            "run_id": run_id,
            "workflow_id": "tk-cover",
            "action_id": "mine_recipe",
            "phase": "close",
        })
    # Ensure staging exists (deterministic prepare).
    from uo_init.tk_cover_engines import mine_recipe as mine_engine
    mine_engine(PROJ, {"run_id": run_id})
    staging_dir = PROJ / ".ascendc-pilot" / "runs" / run_id / "actions" / "mine_recipe"
    for path in [staging_dir / "staging.yaml", staging_dir / "parts" / "part_0.yaml"]:
        if not path.is_file():
            continue
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        doc["artifact_identity"] = identity
        doc["run_id"] = identity.get("run_id") or run_id
        path.write_text(
            yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        print(f"stamped {path.name}", flush=True)


def drive(*, from_close: bool = False) -> int:
    if not from_close:
        summarize(
            "START",
            acp(
                "start", "tk-cover",
                "--op-name", "FlashAttentionScoreGrad",
                "--architecture", "arch35",
                "--force-new",
            ),
        )
        summarize("ENV", acp("run-action", "env_probe"))
        summarize("ADV_DERIVE", acp("advance", "derive"))
        d = acp("run-action", "derive_fields")
        summarize("DERIVE", d)
        if not _fin_ok(d):
            return 1
        summarize("EXPORT", acp("run-action", "export_codemap"))
        summarize("ADV_CLOSE", acp("advance", "close"))

    m = acp("run-action", "mine_recipe")
    summarize("MINE_PREPARE", m)
    _stamp_mine_identity(m)
    fin = acp("run-action", "mine_recipe", "--finalize")
    summarize("MINE_FIN", fin)
    if not _fin_ok(fin):
        print(json.dumps(fin, ensure_ascii=False, indent=2)[:2000], flush=True)
        return 1
    summarize("APPLY", acp("run-action", "apply_recipe"))
    summarize("ADV_CERT", acp("advance", "certify"))
    g = acp("run-action", "coverage_gate")
    summarize("GATE", g)
    st = acp("status")
    print(
        f"STATUS phase={st.get('phase')} status={st.get('status')} "
        f"gates={st.get('passed_gates')}",
        flush=True,
    )
    # Surface residual for the operator.
    residual = PROJ / ".ascendc-pilot" / "uo" / "tk" / "residual.yaml"
    gate_doc = PROJ / ".ascendc-pilot" / "uo" / "tk" / "coverage_gate.yaml"
    if gate_doc.is_file():
        print("--- coverage_gate.yaml ---", flush=True)
        text = gate_doc.read_text(encoding="utf-8")[:1500]
        sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
        sys.stdout.buffer.write(b"\n")
    if residual.is_file():
        print("--- residual.yaml ---", flush=True)
        text = residual.read_text(encoding="utf-8")[:1500]
        sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
        sys.stdout.buffer.write(b"\n")
    complete = False
    gate_pass = False
    if gate_doc.is_file():
        import yaml
        doc = yaml.safe_load(gate_doc.read_text(encoding="utf-8")) or {}
        complete = bool(doc.get("complete"))
        gate_pass = bool(doc.get("ok") or doc.get("gate_pass"))
        if not gate_pass:
            return 2
    # Mark workflow terminal when certify gates are done.
    done = acp("complete")
    summarize("COMPLETE", done)
    st2 = acp("status")
    print(
        f"FINAL status={st2.get('status')} phase={st2.get('phase')} "
        f"complete={complete} gate_pass={gate_pass}",
        flush=True,
    )
    # complete=False with gate PASS is an expected residual, not a harness failure.
    if st2.get("status") == "passed" or gate_pass:
        return 0 if complete else 3
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reset", action="store_true",
                    help="Wipe uo/tk + tk runs + closure, then drive from prepare")
    ap.add_argument("--from-close", action="store_true",
                    help="Resume at mine_recipe (after composer wrote parts)")
    ap.add_argument("--reset-only", action="store_true",
                    help="Only wipe artifacts; do not drive")
    args = ap.parse_args()
    if args.reset or args.reset_only:
        reset_artifacts()
        if args.reset_only:
            return 0
    return drive(from_close=bool(args.from_close))


if __name__ == "__main__":
    raise SystemExit(main())
