# -*- coding: utf-8 -*-
"""Compare replayed tiling keys against what the unit tests assert.

Agreement on all eleven cases is the evidence that the standalone driver drives
the same host tiling the tests do, so a search can trust its answers on inputs
no test covers.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.tpl_dsl import parse_file  # noqa: E402

CACHE = ROOT / ".probe_cache"
TPL = Path(
    "d:/TEST/ops-transformer/attention/flash_attention_score_grad/op_kernel/arch35/"
    "flash_attention_score_grad_template_tiling_key.h"
)


def _read(path: Path) -> dict[str, list[str]]:
    rows = {}
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        if i == 0 or not line.strip():
            continue
        f = line.split(",")
        rows[f[0]] = f[1:]
    return rows


def main() -> int:
    got = _read(CACHE / "replay_out.csv")
    want = _read(CACHE / "replay_expected.csv")

    schema = parse_file(TPL)
    names = [d.name for d in schema.dims]

    agree, differ, failed = [], [], []
    for cid, exp in want.items():
        expected = int(exp[0])
        if cid not in got:
            failed.append((cid, "not replayed"))
            continue
        ok, key = got[cid][0], int(got[cid][1])
        if ok != "1":
            failed.append((cid, "tiling returned failure"))
        elif key == expected:
            agree.append(cid)
        else:
            differ.append((cid, expected, key))

    print(f"agree {len(agree)}/{len(want)}   differ {len(differ)}   failed {len(failed)}")
    for cid, reason in failed:
        print(f"  case {cid}: {reason}")
    for cid, expected, key in differ:
        de, dg = schema.decode_tiling_key(expected), schema.decode_tiling_key(key)
        bad = [n for n in names if de.get(n) != dg.get(n)]
        print(f"  case {cid}: expected {expected} got {key}")
        for n in bad:
            print(f"      {n}: expected {de.get(n)} got {dg.get(n)}")
    return 0 if not differ and not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
