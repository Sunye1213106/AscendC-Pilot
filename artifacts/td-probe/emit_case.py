# -*- coding: utf-8 -*-
"""Emit one replay CSV line so the driver change can be checked by hand."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("UO_OPERATOR", "flash_attention_score_grad")
os.environ.setdefault("UO_ARCH", "arch35")
os.environ.setdefault("UO_OPS_ROOT", str(ROOT.parent / "TEST" / "ops-transformer"))
sys.path.insert(0, str(ROOT / "scripts"))

from replay import inputs as I  # noqa: E402

case = I.Case(layout="BSND", dtype="FLOAT16", b=2, s1=1024, s2=1024,
              n2=2, g=2, d=128, tag="td_probe")
out = Path(sys.argv[1] if len(sys.argv) > 1 else "td_in.csv")
out.write_text(I.to_csv_line(case.normalised(), "probe0") + "\n",
               encoding="utf-8", newline="\n")
print(out.read_text(encoding="utf-8"))
