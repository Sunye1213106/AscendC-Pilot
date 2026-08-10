# -*- coding: utf-8 -*-
"""Preprocessor helpers for BuildVariant defines / force-includes."""

from __future__ import annotations

from typing import Any


def defines_to_clang_args(defines: list[str] | dict[str, Any]) -> list[str]:
    if isinstance(defines, dict):
        items = [f"{k}={v}" if v is not None else str(k) for k, v in defines.items()]
    else:
        items = [str(x) for x in defines]
    out: list[str] = []
    for item in items:
        text = item.lstrip("-D")
        if text:
            out.append(f"-D{text}")
    return out
