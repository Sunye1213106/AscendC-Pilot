#!/usr/bin/env bash
# Clear products and run full uo-init skill stages on FlashAttentionScoreGrad arch35.
set -euo pipefail

REPO="/mnt/d/TEST/AscendC-Pilot"
OP="/mnt/d/TEST/ops-transformer/attention/flash_attention_score_grad"
ARCH="arch35"
LOG="$REPO/_uo_init_full_run.log"

exec > >(tee -a "$LOG") 2>&1

echo "===== $(date -Iseconds) uo-init full run ====="
echo "REPO=$REPO"
echo "OP=$OP"

cd "$REPO"

echo
echo "===== 1) Clear products ====="
rm -rf \
  "$REPO/.ascendc-Pilot" \
  "$REPO/.ascendc-pilot" \
  "$REPO/.probe_cache" \
  "$OP/.ascendc-pilot" \
  "$OP/.probe_cache" \
  2>/dev/null || true
# also clear any leftover nested uo under repo accidental paths
find "$REPO" "$OP" -maxdepth 3 -type d -name '.ascendc-pilot' -print -exec rm -rf {} + 2>/dev/null || true
find "$REPO" "$OP" -maxdepth 3 -type d -name '.probe_cache' -print -exec rm -rf {} + 2>/dev/null || true
echo "cleared"

echo
echo "===== 2) Python / deps ====="
python3 --version
python3 -m pip install -q --upgrade pip
python3 -m pip install -q -r "$REPO/requirements.txt"
python3 -m pip install -q -e "$REPO/engines/common"
python3 -m pip install -q -e "$REPO/engines/understand-operator"
python3 -m pip install -q -e "$REPO/pilot"
python3 -c "import yaml, uo_init, ascendc_pilot; print('imports ok', uo_init.__file__)"

export PYTHONPATH="$REPO/engines/understand-operator/src:$REPO/engines/common:$REPO/pilot:${PYTHONPATH:-}"
export UO_ARCH="$ARCH"

echo
echo "===== 3) Check clang / libclang ====="
python3 - <<'PY'
import os, sys
try:
    import clang.cindex as ci
    print("clang.cindex ok", getattr(ci, '__file__', ci))
except Exception as e:
    print("clang import failed:", e)
    sys.exit(0)
PY
ls /usr/lib/llvm*/lib/libclang.so* 2>/dev/null | head || true
ls /usr/lib/x86_64-linux-gnu/libclang* 2>/dev/null | head || true

echo
echo "===== 4) Drive uo-init via engines (skill stages) ====="
python3 - <<'PY'
from __future__ import annotations

import json
import traceback
from pathlib import Path

from uo_init.codemap_engines import (
    prepare,
    extract,
    analyze,
    apply_gap_patch,
    commit,
    review,
)
from uo_init import pilot_engines as pe

OP = Path("/mnt/d/TEST/ops-transformer/attention/flash_attention_score_grad")
ARCH = "arch35"
ctx = {
    "op_name": "flash_attention_score_grad",
    "architecture": ARCH,
    "arch_dir": ARCH,
    "auto_accept_clean": True,
}

stages = [
    ("prepare", prepare),
    ("extract", extract),
    ("analyze", analyze),
]

results = {}
for name, fn in stages:
    print(f"\n----- {name} -----", flush=True)
    try:
        out = fn(OP, ctx)
    except Exception as exc:
        traceback.print_exc()
        out = {"ok": False, "engine": name, "error": str(exc)[:800]}
    results[name] = {k: out.get(k) for k in ("ok", "engine", "error", "failed_step", "path", "steps") if k in out or True}
    # keep useful context
    for key in ("op_name", "architecture", "arch_dir", "run_id"):
        if out.get(key):
            ctx[key] = out[key]
    print(json.dumps(results[name], ensure_ascii=False, indent=2, default=str)[:4000], flush=True)
    if not out.get("ok"):
        print(f"STOP at {name}", flush=True)
        break
else:
    # resolve: if unresolved gaps empty, skip agent and run apply_gap_patch with empty/no-op
    print("\n----- resolve (deterministic empty-or-patch path) -----", flush=True)
    uo = pe._uo_root(OP, arch=ARCH)
    unresolved = uo / "ir" / "unresolved.yaml"
    print("uo_root=", uo, "unresolved_exists=", unresolved.is_file(), flush=True)
    if unresolved.is_file():
        text = unresolved.read_text(encoding="utf-8", errors="replace")
        print("unresolved preview:\n", text[:2000], flush=True)

    # Try apply_gap_patch; if no producer patch, engine should accept empty merge or report clearly
    try:
        gap_out = apply_gap_patch(OP, ctx)
    except Exception as exc:
        traceback.print_exc()
        gap_out = {"ok": False, "engine": "apply_gap_patch", "error": str(exc)[:800]}
    results["apply_gap_patch"] = {k: gap_out.get(k) for k in ("ok", "engine", "error", "failed_step")}
    print(json.dumps(results["apply_gap_patch"], ensure_ascii=False, indent=2, default=str), flush=True)

    # Even if gap patch fails due to missing agent patch, attempt commit/review if analyze produced enough
    for name, fn in (("commit", commit), ("review", review)):
        print(f"\n----- {name} -----", flush=True)
        try:
            out = fn(OP, ctx)
        except Exception as exc:
            traceback.print_exc()
            out = {"ok": False, "engine": name, "error": str(exc)[:800]}
        results[name] = {k: out.get(k) for k in ("ok", "engine", "error", "path", "summary", "blocking") if True}
        print(json.dumps(results[name], ensure_ascii=False, indent=2, default=str)[:4000], flush=True)
        if not out.get("ok"):
            print(f"STOP at {name}", flush=True)
            break

# product inventory
print("\n===== 5) Product inventory =====", flush=True)
root = OP / ".ascendc-pilot"
if root.exists():
    for p in sorted(root.rglob("*")):
        if p.is_file():
            print(f"{p.relative_to(OP)}  {p.stat().st_size}", flush=True)
else:
    print("no .ascendc-pilot under operator", flush=True)

summary_path = Path("/mnt/d/TEST/AscendC-Pilot/_uo_init_full_summary.json")
summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print("summary ->", summary_path, flush=True)
print("ALL_DONE", flush=True)
PY

echo "===== finished $(date -Iseconds) ====="
