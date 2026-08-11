# -*- coding: utf-8 -*-
"""Replay one case, decode its tiling data with clang's layout, check the values.

Drives wsl.exe directly so no shell quoting sits between here and the driver.
"""

from __future__ import annotations

import base64
import json
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

BIN = "/work/wsl/bin/replay_main"
SO = ("/work/ops-transformer/build/tests/ut/framework_normal/op_host"
      "/libophost_transformer_ut.so")
IN_CSV = "/mnt/d/PR-review/AscendC-Pilot/artifacts/td-probe/td_in.csv"

script = (
    "source /usr/local/Ascend/cann/set_env.sh >/dev/null 2>&1 || true; "
    "export REPLAY_DUMP_TD=1 REPLAY_TILING_DATA_SIZE=65536 "
    "ASCEND_SLOG_PRINT_TO_STDOUT=1 ASCEND_GLOBAL_LOG_LEVEL=3; "
    f"cd /tmp && {BIN} {IN_CSV} /tmp/td_out.csv {SO}"
)
proc = subprocess.run(["wsl", "-e", "/bin/bash", "-c", script],
                      capture_output=True, text=True, encoding="utf-8",
                      errors="replace")
text = proc.stdout or ""
m = re.search(r"^###TD (\d+) (\S+)$", text, re.M)
if not m:
    print("no ###TD in output; tail:")
    print("\n".join(text.splitlines()[-15:]))
    print("stderr:", (proc.stderr or "")[-500:])
    raise SystemExit(1)
nbytes, raw = int(m.group(1)), base64.b64decode(m.group(2))
key = re.search(r"^###DONE \S+ ok=(\d) key=(\d+)$", text, re.M)
print(f"bytes={nbytes} decoded={len(raw)} key={key.group(2) if key else '?'}")

layouts = json.loads((HERE / "layout.json").read_text(encoding="utf-8"))
lay = layouts["FFFF"]
print(f"layout FFFF size={lay['size']} match={lay['size'] == nbytes}")

want = {
    "s1s2BNGS1S2BaseParams.coreNum": 32,
    "s1s2BNGS1S2BaseParams.b": 2,
    "s1s2BNGS1S2BaseParams.n2": 2,
    "s1s2BNGS1S2BaseParams.g": 2,
    "s1s2BNGS1S2BaseParams.s1": 1024,
    "s1s2BNGS1S2BaseParams.s2": 1024,
    "s1s2BNGS1S2BaseParams.d": 128,
    "s1s2BNGS1S2BaseParams.d1": 128,
    "s1s2BNGS1S2BaseParams.keepProb": 1.0,
}
bad = 0
for f in lay["fields"]:
    if f["path"] not in want or not f["code"] or f["count"] != 1:
        continue
    got = struct.unpack_from("<" + f["code"], raw, f["offset"])[0]
    ok = abs(float(got) - float(want[f["path"]])) < 1e-6
    bad += 0 if ok else 1
    print(f"  {'OK ' if ok else 'BAD'} {f['path']:44s} = {got} "
          f"(expect {want[f['path']]})")

print("\n-- other decoded scalars, for a sanity read --")
show = ("layout", "sparseMode", "sparseType", "enablePreSfmg", "sinkOptional",
        "isSplitByBlockIdx", "dropMaskOuter", "s1Inner", "s2Inner", "s1Outer",
        "s2Outer", "blockOuter", "attenMaskShapeType", "pseType")
for f in lay["fields"]:
    leaf = f["path"].rsplit(".", 1)[-1]
    if leaf not in show or not f["code"] or f["count"] != 1:
        continue
    got = struct.unpack_from("<" + f["code"], raw, f["offset"])[0]
    print(f"   {f['path']:46s} = {got}")

print(f"\nmismatches: {bad}")
