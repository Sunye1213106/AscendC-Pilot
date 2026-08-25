# -*- coding: utf-8 -*-
import json
import re
from pathlib import Path

root = Path(r"C:\Users\sunye\.cursor\projects\d-PR-review\agent-transcripts\ee7a6c5f-2544-46e2-b134-65e2de365fd9\subagents")
cases = {
    "74eda63b-efef-45fe-b947-b4c77d4e0e52": Path(
        r"D:\PR-review\AscendC-Pilot\evals\fixtures\tg-plan\pr-9851-fag-deter-band\session\trial-c25-live6.yaml"
    ),
    "851337d9-67a0-4f87-bfb8-0e57ea71e230": Path(
        r"D:\PR-review\AscendC-Pilot\evals\fixtures\tg-plan\pr-9851-fag-deter-band\session\trial-c25-live7.yaml"
    ),
    "3945bacb-8560-4e06-aa6d-9c7ac4557ac2": Path(
        r"D:\PR-review\AscendC-Pilot\evals\fixtures\tg-plan\pr-9851-fag-deter-band\session\trial-c25-live8.yaml"
    ),
    "9b01d034-8c1b-4a70-8770-1b8e0c1ef345": Path(
        r"D:\PR-review\AscendC-Pilot\evals\fixtures\tg-plan\pr-10335-fag-tnd-dense-swizzle\session\trial-c25-live6.yaml"
    ),
    "f1193d0d-86ae-4734-88c2-9ed5cdb37ce3": Path(
        r"D:\PR-review\AscendC-Pilot\evals\fixtures\tg-plan\pr-10335-fag-tnd-dense-swizzle\session\trial-c25-live7.yaml"
    ),
    "8e31b67d-780c-4bfa-a769-8d2f868c3f79": Path(
        r"D:\PR-review\AscendC-Pilot\evals\fixtures\tg-plan\pr-10335-fag-tnd-dense-swizzle\session\trial-c25-live8.yaml"
    ),
    "48e1c7c3-e0cd-40b4-9780-85e155570131": Path(
        r"D:\PR-review\AscendC-Pilot\evals\fixtures\tg-plan\pr-10295-fag-gqa-dense-swizzle\session\trial-c25-live6.yaml"
    ),
    "5dac0ce7-ab41-4f41-87d6-688666f6a64c": Path(
        r"D:\PR-review\AscendC-Pilot\evals\fixtures\tg-plan\pr-10546-fag-tnd-sparse-deter\session\trial-c25-live6.yaml"
    ),
    "b91f00af-ff71-4029-9aa1-07794086625f": Path(
        r"D:\PR-review\AscendC-Pilot\evals\fixtures\tg-plan\pr-10546-fag-tnd-sparse-deter\session\trial-c25-live7.yaml"
    ),
    "04adfede-d8ec-4a5a-ba00-56d564605a3b": Path(
        r"D:\PR-review\AscendC-Pilot\evals\fixtures\tg-plan\pr-9851-fag-deter-band\session\trial-c25-fill1.yaml"
    ),
    "2dc3bd81-5d22-4ad1-a8a8-94470d70f3a9": Path(
        r"D:\PR-review\AscendC-Pilot\evals\fixtures\tg-plan\pr-10335-fag-tnd-dense-swizzle\session\trial-c25-fill1.yaml"
    ),
    "026b7d06-43bb-4299-abed-e1d4c95232df": Path(
        r"D:\PR-review\AscendC-Pilot\evals\fixtures\tg-plan\pr-10335-fag-tnd-dense-swizzle\session\trial-c25-fill2.yaml"
    ),
    "05677d7f-1570-47cb-925d-1fc5f1b73219": Path(
        r"D:\PR-review\AscendC-Pilot\evals\fixtures\tg-plan\pr-10295-fag-gqa-dense-swizzle\session\trial-c25-fill1.yaml"
    ),
    "31a2297d-2f36-4963-a952-e57b753da0b6": Path(
        r"D:\PR-review\AscendC-Pilot\evals\fixtures\tg-plan\pr-10295-fag-gqa-dense-swizzle\session\trial-c25-fill2.yaml"
    ),
    "0e61254d-9e55-469c-8a99-a74fe9a7b091": Path(
        r"D:\PR-review\AscendC-Pilot\evals\fixtures\tg-plan\pr-10295-fag-gqa-dense-swizzle\session\trial-c25-fill3.yaml"
    ),
    "382e3d3e-22b6-4a19-b20d-e0546e6ba21c": Path(
        r"D:\PR-review\AscendC-Pilot\evals\fixtures\tg-plan\pr-10546-fag-tnd-sparse-deter\session\trial-c25-fill1.yaml"
    ),
}
fence = re.compile(r"```ya?ml\s*\n(.*?)```", re.S | re.I)
for aid, out in cases.items():
    p = root / f"{aid}.jsonl"
    texts = []
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
        if (body.startswith("schema: tg-plan/v3") or body.startswith("schema: tg-plan-fill/v1")) and (
            "requirement:" in body or "target:" in body
        ) and ("dimensions:" in body):
            yaml_text = body + "\n"
    if yaml_text is None:
        marker = "schema: tg-plan"
        idx = blob.rfind(marker)
        if idx >= 0:
            yaml_text = blob[idx:].split("[REDACTED]")[0].strip() + "\n"
        else:
            yaml_text = blob.strip() + "\n"
    if yaml_text.rstrip().endswith("```"):
        yaml_text = yaml_text.rstrip()[: yaml_text.rstrip().rfind("```")].rstrip() + "\n"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml_text, encoding="utf-8")
    print(aid[:8], "bytes", len(yaml_text.encode("utf-8")), "->", out)
