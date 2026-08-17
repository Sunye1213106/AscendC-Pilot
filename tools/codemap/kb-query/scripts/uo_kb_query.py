#!/usr/bin/env python3
"""Forwarder: query the committed ``.uo`` CodeMap via ``acp uo-query``.

Historical path ``engines/understand-operator/uo/scripts/uo_kb_query.py`` is gone.
Product query is ``acp uo-query`` (no sqlite fallback). Extra argv are passed through.
"""

from __future__ import annotations

import shutil
import subprocess
import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    acp = shutil.which("acp")
    cmd = [acp, "uo-query", *args] if acp else [sys.executable, "-m", "ascendc_pilot", "uo-query", *args]
    if not args or args[0] in {"-h", "--help"}:
        print(
            "uo_kb_query is a wrapper for `acp uo-query`.\n"
            "Example: uo_kb_query.py --project <op> s1Inner",
            file=sys.stderr,
        )
        if not args:
            return 2
    proc = subprocess.run(cmd, check=False)
    return int(proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
