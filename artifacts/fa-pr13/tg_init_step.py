#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Drive tg-init via Python engines + minimal acp phase advances. UTF-8 logs."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

OP = Path("/work/ops-transformer/attention/flash_attention_score_grad")
PILOT = Path("/mnt/d/PR-review/AscendC-Pilot")
ARCH = "arch35"
OP_NAME = "flash_attention_score_grad"
LOG = PILOT / "artifacts/fa-pr13/tg_init_step.log"


def log(msg: str) -> None:
    text = msg if msg.endswith("\n") else msg + "\n"
    sys.stdout.write(text)
    sys.stdout.flush()
    with LOG.open("a", encoding="utf-8") as f:
        f.write(text)


def env() -> dict[str, str]:
    e = os.environ.copy()
    e.update(
        {
            "PATH": f"/work/venv-acp/bin:{e.get('PATH','')}",
            "PYTHONPATH": ":".join(
                [
                    str(PILOT),
                    str(PILOT / "engines/testcase-generation"),
                    str(PILOT / "scripts"),
                    str(PILOT / "engines/understand-operator/src"),
                    str(PILOT / "pilot"),
                    e.get("PYTHONPATH", ""),
                ]
            ),
            "ASCENDC_PROJECT_ROOT": str(OP),
            "UO_OP_DIR": str(OP),
            "UO_OPERATOR": OP_NAME,
            "UO_ARCH": ARCH,
            "UO_OPS_ROOT": "/work/ops-transformer",
            "OPS_TRANSFORMER_ROOT": "/work/ops-transformer",
        }
    )
    return e


def acp(*args: str) -> dict:
    cmd = ["acp", *args, "--project", str(OP)]
    log(f"$ {' '.join(cmd)}")
    p = subprocess.run(cmd, capture_output=True, text=True, env=env())
    out = (p.stdout or "") + (p.stderr or "")
    # try parse last json object
    data = {}
    try:
        start = out.rfind("{")
        if start >= 0:
            data = json.loads(out[start:])
    except Exception:
        data = {"raw": out[-2000:], "returncode": p.returncode}
    log(json.dumps({"returncode": p.returncode, "ok": data.get("ok"), "phase": data.get("phase"), "error": data.get("error"), "message_zh": data.get("message_zh")}, ensure_ascii=False))
    return data


def run_action(action: str) -> dict:
    prep = acp("run-action", action)
    fin = acp("run-action", action, "--finalize")
    return {"prepare": prep, "finalize": fin}


def main() -> int:
    LOG.write_text("", encoding="utf-8")
    # ensure uo present
    uo = OP / ".ascendc-pilot/uo" / f"{OP_NAME}.{ARCH}.uo"
    fresh = PILOT / "artifacts/fa-pr13/flash_attention_score_grad.arch35.uo"
    uo.parent.mkdir(parents=True, exist_ok=True)
    if not uo.is_file() or uo.stat().st_size != fresh.stat().st_size:
        import shutil

        shutil.copy2(fresh, uo)
    log(f"uo={uo} size={uo.stat().st_size}")

    # Prefer engine API for deterministic steps to avoid lease/phase footguns,
    # but keep acp start for state machine identity.
    os.environ.update(env())
    sys.path[:0] = [
        str(PILOT / "pilot"),
        str(PILOT / "engines/testcase-generation"),
        str(PILOT / "engines/understand-operator/src"),
        str(PILOT / "scripts"),
    ]

    from ascendc_pilot.actions import engines as E
    from ascendc_pilot.paths import tg_root, ensure_agent_layout

    ensure_agent_layout(OP, arch=ARCH)
    ctx = {
        "op_name": OP_NAME,
        "architecture": ARCH,
        "mode": "tilingkey_full_coverage",
        "level": "L0",
    }

    log("== init_intent ==")
    r = E._run_tg_init_intent(OP, ctx)
    log(json.dumps(r, ensure_ascii=False)[:2000])

    log("== kb_check ==")
    # kb_check engine name may vary
    for name in ("_run_tg_kb_check", "_run_kb_check"):
        fn = getattr(E, name, None)
        if fn:
            r = fn(OP, ctx)
            log(json.dumps(r, ensure_ascii=False)[:2000])
            break
    else:
        log("kb_check engine not found; using find_uo_product")
        from uo_init.store.reader import find_uo_product

        p = find_uo_product(OP, op_name=OP_NAME, architecture=ARCH)
        log(f"find_uo_product={p}")

    log("== contract_build ==")
    r = E._run_tg_contract_build(OP, ctx)
    log(json.dumps(r, ensure_ascii=False)[:4000])

    log("== semantic_bind ==")
    r = E._run_tg_semantic_bind(OP, ctx)
    log(json.dumps(r, ensure_ascii=False)[:4000])

    # optional merge/nest only if present for mode
    for name in ("_run_tg_bind_merge", "_run_tg_mid_nest"):
        fn = getattr(E, name, None)
        if fn:
            log(f"== {name} ==")
            try:
                r = fn(OP, ctx)
                log(json.dumps(r, ensure_ascii=False)[:2000])
            except Exception as exc:
                log(f"{name} failed: {exc}")

    log("== integrity_gate ==")
    r = E._run_tg_integrity(OP, ctx)
    log(json.dumps(r, ensure_ascii=False)[:4000])

    tg = tg_root(OP, arch=ARCH)
    log("== artifacts ==")
    for p in sorted(tg.rglob("*")):
        if p.is_file() and p.suffix in {".yaml", ".yml", ".json", ".csv"}:
            log(str(p.relative_to(OP)))

    # summarize key binding/contract files
    for rel in [
        "tg/init/init_intent.yaml",
        "tg/contract/tilingkey_contract.yaml",
        "tg/realization/binding_inventory.yaml",
        "tg/snapshot/understand_contract.json",
        "tg/init/integrity.yaml",
        "tg/init/audit_report.yaml",
    ]:
        path = OP / ".ascendc-pilot" / ARCH / rel
        if not path.is_file():
            # also try flat tg_root
            path = tg / Path(rel).relative_to("tg")
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            log(f"\n----- {path} ({len(text)} bytes) -----")
            log(text[:3000])
        else:
            log(f"MISSING {rel}")

    log("DONE_TG_INIT_ENGINES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
