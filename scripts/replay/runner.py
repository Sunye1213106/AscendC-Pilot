# -*- coding: utf-8 -*-
"""Drive the replay executable and read back both the key and its 19 dimensions.

Decoding the key gives the dimension values, but the tiling also logs them
before packing, along with the intermediates that decide the hard ones
(isExceedL2Cache, enableSwizzle, sparseType). Those say *why* a dimension did
not flip, which is what makes a coverage search directed rather than blind.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.tpl_dsl import parse_file  # noqa: E402

from . import inputs as I  # noqa: E402

CACHE = ROOT / ".probe_cache" / "replay"
DISTRO = "Ubuntu-2204"
SCRIPT = "/mnt/e/wsl/setup/run_replay.sh"
TPL = Path(
    "d:/TEST/ops-transformer/attention/flash_attention_score_grad/op_kernel/arch35/"
    "flash_attention_score_grad_template_tiling_key.h"
)

SCHEMA = parse_file(TPL)
DIM_NAMES = [d.name for d in SCHEMA.dims]

#: The order the tiling logs its semantic values in, mapped onto TPL dim names.
LOG_FIELDS = [
    "splitAxis", "inputDtype", "isTnd", "dropValue", "pseValue", "attenMaskCfg",
    "s1TemplateType", "s2TemplateType", "dTemplateType", "isDeterministic",
    "nEqual", "isBn2MultiBlk", "dNoEqual", "hasRope", "outDtype", "isNzOut",
    "isTndSwizzle", "isRegbasePlatformValue",
]

_CASE_MARK = re.compile(r"^###CASE (\S+)")
_DONE_MARK = re.compile(r"^###DONE (\S+) ok=(\d+) key=(\d+)")
_KV = re.compile(r"(\w+)\s*=?\s*\[(-?\d+)\]")


@dataclass
class Result:
    case_id: str
    ok: bool = False
    key: int = 0
    dims: dict = field(default_factory=dict)      # decoded from the key
    logged: dict = field(default_factory=dict)    # read off the tiling's own log
    diag: dict = field(default_factory=dict)      # intermediates
    reject: str = ""                              # why tiling refused, if it did


def _parse_log(text: str) -> dict[str, Result]:
    out: dict[str, Result] = {}
    cur: Result | None = None
    for line in text.splitlines():
        m = _CASE_MARK.match(line)
        if m:
            cur = Result(case_id=m.group(1))
            out[cur.case_id] = cur
            continue
        m = _DONE_MARK.match(line)
        if m and cur is not None:
            cur.ok = m.group(2) == "1"
            cur.key = int(m.group(3))
            cur = None
            continue
        if cur is None:
            continue
        if "GetTilingKey" in line and "splitAxis[" in line:
            got = dict(_KV.findall(line))
            cur.logged = {k: int(v) for k, v in got.items() if k in LOG_FIELDS}
        elif "isExceedL2Cache" in line:
            cur.diag.update({k: int(v) for k, v in _KV.findall(line)})
        elif "[ERROR]" in line and not cur.reject:
            cur.reject = line.split("OpName:")[-1].strip()[:160]
    return out


def preflight(cases: dict[str, I.Case]) -> dict[str, Result]:
    """Cases the host's own premises say it will refuse.

    The premises are extracted from the same source that does the refusing, so
    a case failing one produces no key however it is run. Filtering here costs
    a dictionary lookup and saves a round trip through WSL; more usefully, the
    result names the check that refused it and the line that states it, which
    an error string from the host does not.
    """
    from . import bridge as B

    out: dict[str, Result] = {}
    for cid, case in cases.items():
        bad = B.refused_by(case)
        if bad:
            p = bad[0]
            where = f"{Path(str(p.get('file', ''))).name}:{p.get('line')}"
            out[cid] = Result(
                case_id=cid,
                reject=f"PREFLIGHT {where} {str(p.get('text', ''))[:120]}",
            )
    return out


def run(cases: dict[str, I.Case], *, with_log: bool = True,
        tag: str = "batch", check: bool = True) -> dict[str, Result]:
    """Replay every case and return one result each, keyed by case id."""
    CACHE.mkdir(parents=True, exist_ok=True)
    in_csv = CACHE / f"{tag}_in.csv"
    out_csv = CACHE / f"{tag}_out.csv"
    log_txt = CACHE / f"{tag}_log.txt"

    refused = preflight(cases) if check else {}
    send = {cid: c for cid, c in cases.items() if cid not in refused}
    if not send:
        return dict(refused)

    in_csv.write_text(
        "\n".join(I.to_csv_line(c, cid) for cid, c in send.items()) + "\n",
        encoding="utf-8", newline="\n",
    )

    def _wsl(p: Path) -> str:
        s = str(p).replace("\\", "/")
        return "/mnt/" + s[0].lower() + s[2:]

    proc = subprocess.run(
        ["wsl", "-d", DISTRO, "-e", "bash", SCRIPT,
         _wsl(in_csv), _wsl(out_csv), _wsl(log_txt), "1" if with_log else "0"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if "BATCH_DONE" not in (proc.stdout or ""):
        raise RuntimeError(f"replay did not finish: {proc.stdout}\n{proc.stderr}")

    results = _parse_log(log_txt.read_text(encoding="utf-8", errors="replace"))
    results.update(refused)
    for cid in cases:
        r = results.setdefault(cid, Result(case_id=cid))
        if r.ok and r.key:
            r.dims = SCHEMA.decode_tiling_key(r.key)
    return results


def wide_header() -> list[str]:
    """Columns of the wide table: what was fed in, and what came out."""
    case_cols = list(I.describe(I.Case()).keys())
    return (
        ["case_id"] + case_cols
        + ["ok", "tiling_key"]
        + [f"dim_{n}" for n in DIM_NAMES]
        + ["log_" + n for n in LOG_FIELDS]
        + ["isExceedL2Cache", "enableSwizzle", "sparseType", "reject"]
    )


def wide_row(cid: str, case: I.Case, r: Result) -> list[str]:
    desc = I.describe(case)
    row = [cid] + [str(v) for v in desc.values()]
    row += ["1" if r.ok else "0", str(r.key)]
    row += [str(r.dims.get(n, "")) for n in DIM_NAMES]
    row += [str(r.logged.get(n, "")) for n in LOG_FIELDS]
    row += [
        str(r.diag.get("isExceedL2Cache", "")),
        str(r.diag.get("enableSwizzle", "")),
        str(r.diag.get("sparseType", "")),
        r.reject.replace(",", " "),
    ]
    return row


def write_wide(path: Path, cases: dict[str, I.Case],
               results: dict[str, Result]) -> None:
    lines = [",".join(wide_header())]
    for cid, case in cases.items():
        lines.append(",".join(wide_row(cid, case.normalised(), results[cid])))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
