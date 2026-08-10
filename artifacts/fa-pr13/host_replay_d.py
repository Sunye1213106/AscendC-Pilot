#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Construct cases from D and Host-replay them inside WSL (native entry).

Bypasses ReplayRunner's nested ``wsl.exe`` launch: when already in Linux,
call ``run_replay.sh`` / parse logs the same way the runner would.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

PILOT = Path("/mnt/d/PR-review/AscendC-Pilot")
OP = Path("/work/ops-transformer/attention/flash_attention_score_grad")
ARCH = "arch35"
OP_NAME = "flash_attention_score_grad"
OUT = PILOT / "artifacts" / "fa-pr13"
LOG = OUT / "host_replay_d.log"
ENTRY = "/work/wsl/setup/run_replay.sh"

# Batch sizing: full D=8705 is long; start with stratified sample then expand.
SAMPLE = int(os.environ.get("TG_REPLAY_SAMPLE", "64"))
BATCH = int(os.environ.get("TG_REPLAY_BATCH", "8"))
FULL = os.environ.get("TG_REPLAY_FULL", "0").strip() in {"1", "true", "yes"}


def log(msg: str) -> None:
    text = msg if msg.endswith("\n") else msg + "\n"
    sys.stdout.write(text)
    sys.stdout.flush()
    with LOG.open("a", encoding="utf-8") as f:
        f.write(text)


def setup_env() -> None:
    sys.path[:0] = [
        str(PILOT / "pilot"),
        str(PILOT / "engines" / "testcase-generation"),
        str(PILOT / "engines" / "understand-operator" / "src"),
        str(PILOT / "scripts"),
    ]
    os.environ.update(
        {
            "ASCENDC_PROJECT_ROOT": str(OP),
            "UO_OP_DIR": str(OP),
            "UO_OPERATOR": OP_NAME,
            "UO_ARCH": ARCH,
            "UO_OPS_ROOT": "/work/ops-transformer",
            "OPS_TRANSFORMER_ROOT": "/work/ops-transformer",
        }
    )


def pick_rows(rows: list[dict], n: int) -> list[dict]:
    if FULL or n >= len(rows):
        return list(rows)
    if n <= 0:
        return []
    # Stratified by index across D.
    step = max(1, len(rows) // n)
    picked = [rows[i] for i in range(0, len(rows), step)][:n]
    # Always include first/last extremes.
    if rows[0] not in picked:
        picked[0] = rows[0]
    if rows[-1] not in picked:
        picked[-1] = rows[-1]
    return picked


def classify(target: int, actual: int, ok: bool, reject: str) -> str:
    rej = (reject or "").upper()
    if rej.startswith(("HOST_CRASHED", "CRASH")):
        return "CRASH"
    if rej.startswith("NOT_RUN") or not ok and actual == 0 and not reject:
        return "NOT_RUN"
    if rej.startswith("PARSE"):
        return "PARSE_FAILED"
    if ok and actual == target:
        return "HIT"
    if ok and actual and actual != target:
        return "REWRITE"
    if reject:
        return "REFUSE"
    return "UNKNOWN"


def main() -> int:
    LOG.write_text("", encoding="utf-8")
    setup_env()

    from replay import inputs as I
    from replay.runner import default as default_runner
    from uo_init.store.reader import find_uo_product
    from uo_init.tg_projection import legal_key_rows

    product = find_uo_product(OP, op_name=OP_NAME, architecture=ARCH)
    if product is None:
        log("missing .uo")
        return 2
    rows = legal_key_rows(product)
    log(f"D={len(rows)} sample={SAMPLE} batch={BATCH} full={FULL}")

    runner = default_runner()
    cache = Path(runner.cache)
    cache.mkdir(parents=True, exist_ok=True)
    log(f"manifest distro={runner.manifest.distro} entry={runner.manifest.entry}")
    log(f"cache={cache}")
    if not Path(ENTRY).is_file():
        log(f"missing entry {ENTRY}")
        return 2

    selected = pick_rows(rows, SAMPLE if not FULL else len(rows))
    log(f"selected={len(selected)}")

    # Build cases via operator construct_case (same as construct.build hook).
    cases: list[tuple[int, object, dict]] = []
    for row in selected:
        dims = {str(k): str(v) for k, v in (row.get("dims") or {}).items()}
        target = int(row.get("tiling_key") or 0)
        built = list(I.construct_case(dims) or [])
        if not built:
            cases.append((target, None, dims))
            continue
        cases.append((target, built[0], dims))

    hist = {
        "HIT": 0,
        "REWRITE": 0,
        "REFUSE": 0,
        "CRASH": 0,
        "NOT_RUN": 0,
        "PARSE_FAILED": 0,
        "UNKNOWN": 0,
        "NO_CASE": 0,
    }
    hits: set[int] = set()
    details: list[dict] = []
    t0 = time.time()

    # Native invoke: write csv → run_replay.sh → parse_log
    pending_batch: dict[str, object] = {}
    pending_meta: dict[str, tuple[int, dict]] = {}

    def flush(tag: str) -> None:
        nonlocal pending_batch, pending_meta
        if not pending_batch:
            return
        in_csv = cache / f"{tag}_in.csv"
        out_csv = cache / f"{tag}_out.csv"
        log_txt = cache / f"{tag}_log.txt"
        in_csv.write_text(
            "\n".join(I.to_csv_line(c, cid) for cid, c in pending_batch.items()) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        env = os.environ.copy()
        # Prefer quiet logs for throughput; still capture driver stdout.
        env["ASCEND_SLOG_PRINT_TO_STDOUT"] = "0"
        env["ASCEND_GLOBAL_LOG_LEVEL"] = "3"
        proc = subprocess.run(
            ["bash", ENTRY, str(in_csv), str(out_csv), str(log_txt), "0"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        marker = proc.stdout or ""
        log(f"batch {tag}: rc_wrapper={proc.returncode} marker={marker.strip()[:120]}")
        text = ""
        if log_txt.is_file():
            text = log_txt.read_text(encoding="utf-8", errors="replace")
        parsed = runner.parse_log(text) if text else {}
        done = set(runner.finished_ids(text)) if text else set()
        for cid, case in pending_batch.items():
            target, dims = pending_meta[cid]
            r = parsed.get(cid)
            if r is None:
                kind = "NOT_RUN"
                actual = 0
                reject = "NOT_RUN:missing_in_log"
                ok = False
            else:
                actual = int(getattr(r, "key", 0) or 0)
                ok = bool(getattr(r, "ok", False))
                reject = str(getattr(r, "reject", "") or "")
                if cid not in done and not ok and not actual:
                    kind = "NOT_RUN"
                else:
                    kind = classify(target, actual, ok, reject)
            hist[kind] = hist.get(kind, 0) + 1
            if kind == "HIT":
                hits.add(target)
            details.append(
                {
                    "cid": cid,
                    "target": target,
                    "actual": actual,
                    "ok": ok,
                    "reject": reject[:200],
                    "verdict": kind,
                    "dims": dims,
                }
            )
        pending_batch = {}
        pending_meta = {}

    bi = 0
    for i, (target, case, dims) in enumerate(cases):
        if case is None:
            hist["NO_CASE"] += 1
            details.append(
                {
                    "cid": f"none_{i}",
                    "target": target,
                    "actual": 0,
                    "ok": False,
                    "reject": "NO_CASE",
                    "verdict": "NO_CASE",
                    "dims": dims,
                }
            )
            continue
        cid = f"k{i}_{target}"
        pending_batch[cid] = case
        pending_meta[cid] = (target, dims)
        if len(pending_batch) >= BATCH:
            flush(f"drep_{bi}")
            bi += 1
            log(
                f"progress judged={sum(hist.values())} HIT={hist['HIT']} "
                f"REWRITE={hist['REWRITE']} REFUSE={hist['REFUSE']} "
                f"CRASH={hist['CRASH']} NOT_RUN={hist['NOT_RUN']}"
            )
    flush(f"drep_{bi}")

    # Persist R hits under tg/closure
    from ascendc_pilot.paths import ensure_closure_layout, tg_root

    ensure_closure_layout(OP, arch=ARCH)
    r_path = tg_root(OP, arch=ARCH) / "closure" / "R.txt"
    existing = set()
    if r_path.is_file():
        for line in r_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.isdigit():
                existing.add(int(line))
    merged = sorted(existing | hits)
    r_path.write_text("".join(f"{k}\n" for k in merged), encoding="utf-8")

    report = {
        "D": len(rows),
        "selected": len(selected),
        "judged": sum(hist.values()),
        "hist": hist,
        "hit_count": len(hits),
        "hit_keys_sample": sorted(hits)[:20],
        "R_path": str(r_path),
        "R_total": len(merged),
        "elapsed_sec": round(time.time() - t0, 2),
        "details_head": details[:30],
        "details_rewrites": [d for d in details if d["verdict"] == "REWRITE"][:20],
        "details_refuse": [d for d in details if d["verdict"] == "REFUSE"][:20],
    }
    out = OUT / "host_replay_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # full details sidecar
    (OUT / "host_replay_details.jsonl").write_text(
        "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in details),
        encoding="utf-8",
    )
    log(json.dumps(report, ensure_ascii=False, indent=2)[:6000])
    log(f"WROTE {out}")
    return 0 if hist["HIT"] or hist["REWRITE"] or hist["REFUSE"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
