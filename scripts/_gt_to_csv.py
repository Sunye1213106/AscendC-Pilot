# -*- coding: utf-8 -*-
"""Turn the arch35 UT cases into the replay driver's CSV.

Running the eleven known cases through the standalone driver and getting the
same keys the tests assert is what shows the driver reproduces the real host
tiling, rather than merely compiling against it.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from _gt_compare import DTYPE, IN_ORDER, OUT_ORDER, UT, _CASE, _KEY, _TENSOR  # noqa: E402

OUT_CSV = ROOT / ".probe_cache" / "replay_in.csv"
OUT_EXPECT = ROOT / ".probe_cache" / "replay_expected.csv"

# int64_t actual_seq_qlist[4] = {128, 384, 768, 974};
_ARRAY = re.compile(r"\b(?:int64_t|uint64_t|int32_t)\s+(\w+)\s*\[\s*\d*\s*\]\s*=\s*\{([^}]*)\}")


def _dims(text: str) -> list[int]:
    text = text.strip()
    return [int(x) for x in re.findall(r"-?\d+", text)] if text else []


def cases_with_consts(text: str) -> list[dict]:
    marks = [(m.start(), m.group(1)) for m in _CASE.finditer(text)]
    out = []
    for i, (pos, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        body = text[pos:end]
        km = _KEY.search(body)
        if not km:
            continue
        arrays = {m.group(1): _dims(m.group(2)) for m in _ARRAY.finditer(body)}
        tensors = []
        for m in _TENSOR.finditer(body):
            tail = m.group(5) or ""
            payload: list[int] = []
            for var, vals in arrays.items():
                if re.search(rf"\b{re.escape(var)}\b", tail):
                    payload = vals
                    break
            tensors.append(
                {"shape": _dims(m.group(1)), "dtype": m.group(3), "const": payload}
            )
        attrs = {}
        for m in re.finditer(
            r'\{\s*"(\w+)"\s*,\s*Ops::Transformer::AnyValue::CreateFrom<([\w:]+)>\s*'
            r'\(\s*([^)]*?)\s*\)\s*\}',
            body,
        ):
            k, ty, raw = m.group(1), m.group(2), m.group(3).strip()
            if "string" in ty:
                attrs[k] = ("s", raw.strip('"'))
            elif ty == "float":
                attrs[k] = ("f", raw.rstrip("f"))
            else:
                attrs[k] = ("i", raw)
        out.append(
            {
                "name": name,
                "key": int(km.group(1)),
                "inputs": tensors[: len(IN_ORDER)],
                "outputs": tensors[len(IN_ORDER): len(IN_ORDER) + len(OUT_ORDER)],
                "attrs": attrs,
            }
        )
    return out


def _tensor_field(t: dict) -> str:
    s = "|".join(str(d) for d in t["shape"])
    if t["const"]:
        s += "@" + "/".join(str(v) for v in t["const"])
    return s


def main() -> int:
    cases = cases_with_consts(UT.read_text(encoding="utf-8", errors="replace"))
    lines, expect = [], ["id,expected_key"]
    for c in cases:
        tag = c["name"].rsplit("_", 1)[-1]
        if len(c["inputs"]) != len(IN_ORDER) or len(c["outputs"]) != len(OUT_ORDER):
            print(f"skip {tag}: parsed {len(c['inputs'])} in / {len(c['outputs'])} out")
            continue
        lines.append(
            ";".join(
                [
                    tag,
                    ",".join(_tensor_field(t) for t in c["inputs"]),
                    ",".join(str(DTYPE.get(t["dtype"], 0)) for t in c["inputs"]),
                    ",".join(_tensor_field(t) for t in c["outputs"]),
                    ",".join(str(DTYPE.get(t["dtype"], 0)) for t in c["outputs"]),
                    "&".join(f"{k}={kind}:{v}" for k, (kind, v) in c["attrs"].items()),
                ]
            )
        )
        expect.append(f"{tag},{c['key']}")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    OUT_CSV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    OUT_EXPECT.write_text("\n".join(expect) + "\n", encoding="utf-8")
    print(f"wrote {len(lines)} cases -> {OUT_CSV}")
    print(f"wrote expectations -> {OUT_EXPECT}")
    consts = sum(1 for c in cases for t in c["inputs"] if t["const"])
    print(f"{consts} tensors carry constant data (sequence lengths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
