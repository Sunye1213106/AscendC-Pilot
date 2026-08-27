# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import check_schema_catalog  # noqa: E402


def test_schema_catalog_aligned_with_skills() -> None:
    errors = check_schema_catalog.check()
    assert errors == [], "\n".join(errors)
