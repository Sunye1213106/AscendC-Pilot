# -*- coding: utf-8 -*-
"""How much of E=4584 rests on a real source citation?

The certificate reported uncited_affecting=0, but that check ran under the old
audit path. This reads the rules directly: grade, whether a source_ref points at
a file that exists, and how many keys each rule removes.
"""

from __future__ import annotations

import collections
from pathlib import Path

import yaml


def main() -> int:
    from testcase_agent.closure import ledger
    from testcase_agent.closure import workspace as W

    ws = W.default_workspace().ensure()
    path = Path(ws.state) / "lemmas" / "active_rules.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules = list(doc.get("rules") or [])
    print(f"active_rules: {len(rules)}  (file: {path})")

    by_grade = collections.Counter(str(r.get("grade") or "?") for r in rules)
    print("\nby grade:", dict(by_grade))

    cited, uncited, broken = [], [], []
    for r in rules:
        refs = r.get("source_refs") or r.get("source_citations") or []
        if isinstance(refs, dict):
            refs = [refs]
        if not refs:
            uncited.append(r)
            continue
        ok_any = False
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            f = str(ref.get("file") or ref.get("path") or "")
            if f and Path(f).is_file():
                ok_any = True
        (cited if ok_any else broken).append(r)

    print(f"\ncited (file exists): {len(cited)}")
    print(f"uncited            : {len(uncited)}")
    print(f"cited but file gone: {len(broken)}")

    for label, group in (("UNCITED", uncited), ("BROKEN", broken)):
        for r in group[:8]:
            print(f"  {label} id={r.get('id')} grade={r.get('grade')} "
                  f"label={str(r.get('label'))[:70]}")

    E = ledger.load_E(ws)
    print(f"\n|E| = {len(E)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
