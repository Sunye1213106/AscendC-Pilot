# -*- coding: utf-8 -*-
"""Canonical source-symbol identity helpers used by Host structural passes.

The CodeMap must not treat ``this.foo.bar`` and ``foo.bar`` as different
members, nor collapse unrelated ``Other.bar`` symbols merely because their
short name is the same.  These helpers intentionally perform only lexical
normalization; type resolution remains a compiler/frontend responsibility.
"""
from __future__ import annotations

import re

_MEMBER_SEP_RE = re.compile(r"\s*(?:->|\.)\s*")


def normalize_symbol(value: str) -> str:
    """Return a stable lexical identity for a C/C++ variable/member token."""
    text = _MEMBER_SEP_RE.sub(".", str(value or "").strip())
    while text.startswith("this."):
        text = text[5:]
    # Some frontend spellings retain an explicit parenthesized this receiver.
    text = re.sub(r"^\(\s*\*\s*this\s*\)\.", "", text)
    return text


def short_symbol(value: str) -> str:
    text = normalize_symbol(value)
    return text.split(".")[-1].split("::")[-1]


def is_member_symbol(value: str) -> bool:
    return "." in normalize_symbol(value)


def canonical_candidates(values: list[str]) -> set[str]:
    return {normalize_symbol(value) for value in values if normalize_symbol(value)}
