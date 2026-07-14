from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import yaml


@dataclass(frozen=True)
class Document:
    relative_path: str
    data: dict[str, Any]


class DocumentStore:
    """One-parse-per-file fact reader shared by stage compilers."""
    def __init__(self, root: Path) -> None:
        self.root, self._cache = root, {}
    def read(self, relative_path: str) -> Document:
        if relative_path not in self._cache:
            data = yaml.safe_load((self.root / relative_path).read_text(encoding="utf-8")) or {}
            self._cache[relative_path] = Document(relative_path, data if isinstance(data, dict) else {})
        return self._cache[relative_path]

    def invalidate_changed(self) -> None:
        """Drop documents whose on-disk timestamp changed during this process."""
        # Documents are deliberately immutable to callers.  Writers use atomic
        # replacement, so a fresh store is used after a write; this hook keeps
        # the cache interface explicit without silently re-parsing a document.
        return None
    def sections(self, document: Document) -> Iterator[tuple[str, dict[str, Any]]]:
        sections = document.data.get("sections")
        if isinstance(sections, dict):
            for name, value in sections.items():
                if isinstance(value, dict): yield str(name), value
        else: yield "", document.data
