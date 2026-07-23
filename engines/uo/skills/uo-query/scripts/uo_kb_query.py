"""Forwarder stub: resolve to engines/uo/uo/scripts/uo_kb_query.py."""
from __future__ import annotations

from pathlib import Path


def _resolve_real_script() -> Path:
    here = Path(__file__).resolve()
    # engines/uo/skills/uo-query/scripts -> engines/uo/uo/scripts
    return here.parents[3] / "uo" / "scripts" / "uo_kb_query.py"


if __name__ == "__main__":
    import runpy
    import sys

    real = _resolve_real_script()
    sys.argv[0] = str(real)
    runpy.run_path(str(real), run_name="__main__")
