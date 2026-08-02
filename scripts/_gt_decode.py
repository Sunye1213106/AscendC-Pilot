# -*- coding: utf-8 -*-
"""Decode the arch35 UT's expected tiling keys into their 19 dimensions.

The unit tests carry the only input->key pairs that came out of the real host
tiling, so they are the one place a derivation can be checked against ground
truth rather than against itself.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.tpl_dsl import parse_file  # noqa: E402

OPS = Path(r"D:\TEST\ops-transformer")
UT = (
    OPS
    / "attention/flash_attention_score_grad/tests/ut/op_host/arch35"
    / "test_flash_attention_score_grad_tiling.cpp"
)
TPL = (
    OPS
    / "attention/flash_attention_score_grad/op_kernel/arch35"
    / "flash_attention_score_grad_template_tiling_key.h"
)

_CASE = re.compile(r"TEST_F\(\s*\w+\s*,\s*(\w+)\s*\)")
_KEY = re.compile(r"expectTilingKey\s*=\s*(\d+)")


def cases(text: str) -> list[tuple[str, int]]:
    """Pair each test name with the key asserted inside its body."""
    out: list[tuple[str, int]] = []
    marks = [(m.start(), m.group(1)) for m in _CASE.finditer(text)]
    for i, (pos, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        found = _KEY.search(text, pos, end)
        if found:
            out.append((name, int(found.group(1))))
    return out


def main() -> int:
    if not UT.is_file():
        print(f"missing UT file: {UT}")
        return 1
    if not TPL.is_file():
        print(f"missing TPL header: {TPL}")
        return 1

    schema = parse_file(TPL)
    order = [d.name for d in schema.dims]
    print(f"TPL: {len(order)} dims, {schema.total_bits} bits")
    for d in schema.dims:
        print(f"  bit {d.bit_lo:>2}-{d.bit_hi:<2} {d.name:<18} {d.kind:<5} {d.value_domain}")
    print()

    rows = cases(UT.read_text(encoding="utf-8", errors="replace"))
    print(f"found {len(rows)} ground-truth pairs\n")

    decoded: list[tuple[str, int, dict]] = []
    for name, key in rows:
        d = schema.decode_tiling_key(key)
        decoded.append((name, key, d))
        # Round-trip proves the decode is not silently dropping bits.
        back = schema.encode_tiling_key(d)
        ok = "ok" if back == key else f"MISMATCH re-encoded={back}"
        print(f"{name}  key={key}  roundtrip={ok}")

    print("\n" + "=" * 110)
    short = {n: n.replace("Template", "T").replace("Num", "") for n in order}
    hdr = f"{'case':>6}  " + "  ".join(f"{short[n][:9]:>9}" for n in order)
    print(hdr)
    print("-" * len(hdr))
    for name, _key, d in decoded:
        tag = name.rsplit("_", 1)[-1]
        print(f"{tag:>6}  " + "  ".join(f"{str(d[n])[:9]:>9}" for n in order))

    print("\n=== 每维在这 11 组里出现过的取值 vs 声明域 ===")
    for dim in schema.dims:
        seen = sorted({str(d[dim.name]) for _, _, d in decoded})
        dom = [str(v) for v in dim.value_domain]
        cover = "全覆盖" if set(seen) >= set(dom) else f"覆盖 {len(seen)}/{len(dom)}"
        print(f"  {dim.name:<18} 出现={str(seen):<28} 声明域={dom}  {cover}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
