"""Process-local caches shared by validation and graph compilation."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .document_store import DocumentStore
from .source_reader import SourceReader
from .spec import load_spec


class ValidationContext:
    """The one-pass view of a KB used by a stage validator/compiler."""
    def __init__(self, repo_root: Path, kb_root: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.kb_root = kb_root.resolve()
        self.spec: dict[str, Any] = load_spec()
        self.documents = DocumentStore(self.kb_root)
        self.source_reader = SourceReader(self.repo_root)
        self.id_index: dict[str, dict[str, Any]] = {}
        self.kind_index: dict[str, list[str]] = {}
        self.relation_index: dict[str, dict[str, Any]] = {}
        self.source_index: dict[str, list[str]] = {}
