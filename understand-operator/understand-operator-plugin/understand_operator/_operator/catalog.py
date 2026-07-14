from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Any


class CatalogMatchError(ValueError):
    def __init__(self, code: str, message: str, requested_path: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.requested_path = requested_path


@dataclass(frozen=True)
class CatalogMatch:
    requested_path: str
    pattern: str
    entry: dict[str, Any]


def match_catalog_entry(spec: dict[str, Any], requested_path: str, *, writable_only: bool = False) -> CatalogMatch | None:
    requested = _norm_path(requested_path)
    entries = (spec.get("file_catalog") or {}).get("files") if isinstance(spec.get("file_catalog"), dict) else []
    candidates: list[tuple[tuple[int, int, int], CatalogMatch]] = []
    for raw_entry in entries or []:
        if not isinstance(raw_entry, dict):
            continue
        if writable_only and (
            raw_entry.get("legacy") is True
            or raw_entry.get("migration_only") is True
            or raw_entry.get("writable") is False
        ):
            continue
        pattern = _norm_path(str(raw_entry.get("path") or ""))
        if not pattern:
            continue
        if requested == pattern:
            score = (1, len(pattern), 0)
        elif fnmatch.fnmatch(requested, pattern):
            score = (0, _fixed_prefix_len(pattern), -_wildcard_count(pattern))
        else:
            continue
        candidates.append((score, CatalogMatch(requested, pattern, raw_entry)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    best_score = candidates[0][0]
    best = [match for score, match in candidates if score == best_score]
    if len(best) > 1:
        patterns = ", ".join(match.pattern for match in best)
        raise CatalogMatchError("CATALOG_PATTERN_AMBIGUOUS", f"{requested} matches equally specific catalog patterns: {patterns}", requested)
    return best[0]


def is_active_catalog_entry(entry: dict[str, Any]) -> bool:
    return not (entry.get("legacy") is True or entry.get("migration_only") is True or entry.get("writable") is False)


def _norm_path(value: str) -> str:
    return value.replace("\\", "/").strip("/")


def _fixed_prefix_len(pattern: str) -> int:
    first = min([index for index in (pattern.find("*"), pattern.find("?"), pattern.find("[")) if index >= 0] or [len(pattern)])
    return first


def _wildcard_count(pattern: str) -> int:
    return sum(1 for char in pattern if char in "*?[")
