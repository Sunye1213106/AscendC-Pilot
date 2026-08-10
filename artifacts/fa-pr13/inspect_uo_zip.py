# -*- coding: utf-8 -*-
import zipfile
from pathlib import Path

p = Path("/work/ops-transformer/attention/flash_attention_score_grad/.ascendc-pilot/uo/flash_attention_score_grad.arch35.uo")
z = zipfile.ZipFile(p)
names = z.namelist()
print("entries", len(names), "size_mb", round(p.stat().st_size / 1e6, 1))
for key in ("views/", "indexes/", "tilingdata", "kernel.yaml", "kb_graph", "exhaustive"):
    hits = [n for n in names if key in n]
    print(f"{key}: {len(hits)}")
    for h in hits[:12]:
        print(" ", h)
