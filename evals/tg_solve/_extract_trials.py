# -*- coding: utf-8 -*-
import json
import re
from pathlib import Path

root = Path(r"C:\Users\sunye\.cursor\projects\d-PR-review\agent-transcripts\ee7a6c5f-2544-46e2-b134-65e2de365fd9\subagents")
FIX = Path(r"D:\PR-review\AscendC-Pilot\evals\fixtures\tg-solve")
cases = {
    "3625163b-5c9d-411a-8903-29bd305289d3": FIX / "pr-10335-fag-tnd-dense-swizzle" / "trial-c25-fill1.yaml",
    "64c2d919-eca9-4c08-8518-535ccfa1ec96": FIX / "pr-10335-fag-tnd-dense-swizzle" / "trial-c25-fill2.yaml",
    "3f1f04e0-3075-4525-97db-94e177aeaf2d": FIX / "pr-10546-fag-tnd-sparse-deter" / "trial-c25-fill1.yaml",
    "6c4e6d81-f189-4080-9158-7e9bb47cd115": FIX / "pr-10295-fag-gqa-dense-swizzle" / "trial-c25-fill1.yaml",
    "f8726ca5-dc22-4b90-982b-54add4c26f95": FIX / "pr-9851-fag-deter-band" / "trial-c25-fill1.yaml",
}
fence = re.compile(r"```ya?ml\s*\n(.*?)```", re.S | re.I)
for aid, out in cases.items():
    p = root / f"{aid}.jsonl"
    texts = []
    if not p.is_file():
        print("missing", aid[:8])
        continue
    with p.open(encoding="utf-8") as f:
        for line in f:
            try:
                ev = json.loads(line)
            except Exception:
                continue
            msg = ev.get("message") or {}
            content = msg.get("content")
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "text":
                        texts.append(c.get("text") or "")
            elif isinstance(content, str):
                texts.append(content)
    blob = "\n".join(texts)
    yaml_text = None
    for m in fence.finditer(blob):
        body = m.group(1).strip().split("[REDACTED]")[0].strip()
        if body.startswith("schema: tg-solve-fill/v1") and "hits:" in body:
            yaml_text = body + "\n"
    if yaml_text is None:
        idx = blob.rfind("schema: tg-solve-fill")
        yaml_text = (blob[idx:] if idx >= 0 else blob).split("[REDACTED]")[0].strip() + "\n"
    if yaml_text.rstrip().endswith("```"):
        yaml_text = yaml_text.rstrip()[: yaml_text.rstrip().rfind("```")].rstrip() + "\n"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml_text, encoding="utf-8")
    print(aid[:8], "bytes", len(yaml_text.encode("utf-8")), "->", out)
