#!/usr/bin/env python3
"""Skill architecture lint for the five cognitive-skill model."""

from __future__ import annotations

import sys

import check_skill_architecture_legacy as _legacy

_legacy.CONTROL_PLANE_SKILLS = ()

for _name in dir(_legacy):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_legacy, _name)

CONTROL_PLANE_SKILLS = _legacy.CONTROL_PLANE_SKILLS

if __name__ == "__main__":
    sys.exit(_legacy.main())
