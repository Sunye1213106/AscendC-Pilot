# -*- coding: utf-8 -*-
"""Make the replay package importable, and say when the operator tree is absent.

`replay` is not an installed distribution -- it lives under `scripts/` and its
callers reach it by putting that directory on the path, so the tests do the
same rather than pretending there is a wheel.

Run from this directory's parent:

    cd scripts; python -m pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

REPO = SCRIPTS.parent
sys.path.insert(0, str(REPO / "engines" / "understand-operator" / "src"))


@pytest.fixture(scope="session")
def tpl_header() -> Path:
    """The TilingKey header, or a skip when the operator sources are missing.

    Anything that needs the key layout needs the operator checkout; the point
    of the accessors in `replay.runner` is that everything else does not.
    """
    from replay import runner

    try:
        header = runner.tpl_path()
    except SystemExit as exc:
        pytest.skip(str(exc))
    if not header.is_file():
        pytest.skip(f"no TilingKey header at {header}")
    return header
