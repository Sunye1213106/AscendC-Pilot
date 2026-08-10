#!/usr/bin/env python3
import yaml
from pathlib import Path

p = Path("/work/ops-transformer/attention/flash_attention_score_grad/.ascendc-pilot/arch35/tg/closure/lemmas/leads.yaml")
doc = yaml.safe_load(p.read_text(encoding="utf-8"))
print("lead_count", doc.get("lead_count"))
for i, L in enumerate(doc.get("leads") or []):
    print(
        f"{i}: id={L.get('id')} kind={L.get('kind')} "
        f"support={L.get('support')} mismatch={L.get('mismatch_dims')} "
        f"rewrite={L.get('rewrite_to')} when={L.get('when')} "
        f"affected={L.get('affected_open_keys')} family={L.get('family')}"
    )
