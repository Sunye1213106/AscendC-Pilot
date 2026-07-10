from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from understand_operator._operator.kb_compiler import main as _compiler_main


def main(argv: list[str] | None = None) -> int:
    print("warning: uo-compile-kb is deprecated; use uo-kb-compile", file=sys.stderr)
    return _compiler_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
