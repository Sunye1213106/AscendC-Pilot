"""Compile/compose entry: skills-src + prompts-src + agents-src → generated/<host>/."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from compose_runtime import compose_all  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compose compositional sources → generated/<host>/")
    parser.add_argument("--repo", type=Path, default=None)
    parser.add_argument("--host", action="append", default=[])
    args = parser.parse_args(argv)
    repo = args.repo or Path(__file__).resolve().parents[1]
    result = compose_all(repo, hosts=args.host or None)
    print(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
