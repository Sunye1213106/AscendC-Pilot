# -*- coding: utf-8 -*-
"""Drive tk-cover through acp without PowerShell quoting pain."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJ = Path(r"d:\TEST\AscendC-Pilot")


def acp(*args: str) -> dict:
    cmd = [sys.executable, "-m", "ascendc_pilot.cli", *args, "--project", str(PROJ)]
    p = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={
            **dict(**{k: v for k, v in __import__("os").environ.items()}),
            "PYTHONPATH": ";".join([
                str(PROJ / "pilot"),
                str(PROJ / "engines" / "understand-operator" / "src"),
                str(PROJ / "scripts"),
            ]),
            "UO_REPLAY_DISTRO": "Ubuntu-2204",
        },
    )
    out = (p.stdout or "") + (p.stderr or "")
    i = out.find("{")
    if i < 0:
        print("NO_JSON", args, out[:500])
        return {"ok": False, "raw": out[:500]}
    # take outermost by counting braces from first {
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
        return json.loads(out[i:end])
    except json.JSONDecodeError:
        print("BAD_JSON", args, out[i:i + 400])
        return {"ok": False, "raw": out[i:i + 400]}


def summarize(doc: dict) -> str:
    fin = doc.get("finalize") or {}
    chk = fin.get("checker_result") or {}
    gates = chk.get("gates") or []
    oc = chk.get("output_contract") or {}
    return (
        f"ok={doc.get('ok')} status={doc.get('status') or fin.get('status')} "
        f"fin={fin.get('ok')} oc={oc.get('ok')} oc_msg={oc.get('message')} "
        f"gates={[(g.get('gate'), g.get('ok'), g.get('message')) for g in gates]} "
        f"err={doc.get('error') or fin.get('message_zh')}"
    )


def main() -> int:
    print("START", summarize(acp("start", "tk-cover", "--op-name", "FlashAttentionScoreGrad",
                                 "--architecture", "arch35", "--force-new")))
    print("ENV", summarize(acp("run-action", "env_probe")))
    print("ADV_DERIVE", summarize(acp("advance", "derive")))
    d = acp("run-action", "derive_fields")
    print("DERIVE", summarize(d))
    if not (d.get("finalize") or {}).get("ok"):
        fin = d.get("finalize") or {}
        print("DERIVE_DETAIL", json.dumps({
            "checker": fin.get("checker_result"),
            "observation": fin.get("observation"),
        }, ensure_ascii=False, indent=2)[:2000])
        return 1
    print("EXPORT", summarize(acp("run-action", "export_codemap")))
    print("ADV_CLOSE", summarize(acp("advance", "close")))
    m = acp("run-action", "mine_recipe")
    print("MINE_PREPARE", summarize(m), "resume", m.get("resume_required"))
    # Subagent prepare does not run the deterministic staging engine; do it here
    # so finalize has parts/staging (composer dry-run without a live miner).
    run_id = str(m.get("run_id") or "")
    from uo_init.tk_cover_engines import mine_recipe as mine_engine
    eng = mine_engine(PROJ, {"run_id": run_id})
    print("MINE_ENGINE", eng)
    # Stamp session identity onto run-scoped staging artifacts (required by contract).
    import yaml
    identity = dict(m.get("identity") or {})
    if not identity.get("run_id"):
        identity["run_id"] = run_id
        identity["workflow_id"] = "tk-cover"
        identity["action_id"] = "mine_recipe"
        identity["phase"] = "close"
    print("MINE_IDENTITY", identity)
    staging_dir = PROJ / ".ascendc-pilot" / "runs" / run_id / "actions" / "mine_recipe"
    for path in [staging_dir / "staging.yaml", staging_dir / "parts" / "part_0.yaml"]:
        if path.is_file():
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            doc["artifact_identity"] = identity
            doc["run_id"] = identity.get("run_id") or run_id
            path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True), encoding="utf-8")
            print("STAMPED", path, "run_id", doc.get("run_id"))
        else:
            print("MISSING", path)
    fin = acp("run-action", "mine_recipe", "--finalize")
    print("MINE_FIN", summarize(fin))
    # Finalize JSON may nest under top-level when --finalize is used alone.
    fin_ok = bool(
        (fin.get("finalize") or {}).get("ok")
        or (fin.get("ok") and fin.get("checker_result", {}).get("ok"))
        or (fin.get("ok") and fin.get("receipt"))
    )
    if not fin_ok and not (fin.get("finalize") or {}).get("ok"):
        # --finalize response shape: ok at top with checker_result
        chk = fin.get("checker_result") or (fin.get("finalize") or {}).get("checker_result")
        if isinstance(chk, dict) and chk.get("ok"):
            fin_ok = True
    if not fin_ok:
        print("MINE_FIN_DETAIL", json.dumps({
            "error": fin.get("error"),
            "message_zh": fin.get("message_zh"),
            "ok": fin.get("ok"),
            "checker": fin.get("checker_result")
            or (fin.get("finalize") or {}).get("checker_result"),
        }, ensure_ascii=False, indent=2)[:2500])
        return 1
    print("APPLY", summarize(acp("run-action", "apply_recipe")))
    print("ADV_CERT", summarize(acp("advance", "certify")))
    print("GATE", summarize(acp("run-action", "coverage_gate")))
    st = acp("status")
    print("STATUS", st.get("phase"), st.get("status"), st.get("passed_gates"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
