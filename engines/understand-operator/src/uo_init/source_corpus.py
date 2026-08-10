"""Persistent source facts separated from process-local Clang objects."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_INCLUDE = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', re.MULTILINE)


@dataclass
class SourceCorpus:
    root: Path
    files: dict[str, dict[str, Any]] = field(default_factory=dict)
    include_graph: dict[str, list[str]] = field(default_factory=dict)

    def add(self, path: Path, *, role: str) -> None:
        path = Path(path)
        data = path.read_bytes()
        text = data.decode("utf-8", errors="replace")
        rel = path.resolve().relative_to(self.root.resolve()).as_posix()
        self.files[rel] = {
            "role": role,
            "bytes": data,
            "text": text,
            "sha256": hashlib.sha256(data).hexdigest(),
            "line_index": [0] + [index + 1 for index, char in enumerate(text) if char == "\n"],
            "span": {"start_line": 1, "end_line": text.count("\n") + 1},
        }
        self.include_graph[rel] = _INCLUDE.findall(text)

    def function_fingerprint(
        self,
        rel: str,
        *,
        macro_hash: str = "",
        template_fingerprint: str = "",
        flags: str = "",
        clang_version: str = "",
        cann_header_version: str = "",
        extractor_version: str = "",
        schema_version: str = "",
    ) -> str:
        row = self.files[rel]
        payload = "\0".join(
            [row["sha256"], *sum((self.include_graph.get(rel, []),), []), macro_hash, template_fingerprint, flags, clang_version, cann_header_version, extractor_version, schema_version]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class ProcessLocalClangCache:
    """Never serialize this cache: it may contain TU/cursor/native pointers.

    Durable warm re-runs use :mod:`uo_init.tu_cache` (serialized WalkResult IR
    under ``uo/cache/tu/``), not this process-local map.
    """

    translation_units: dict[str, Any] = field(default_factory=dict)
    cursors: dict[str, Any] = field(default_factory=dict)
    tokens: dict[str, Any] = field(default_factory=dict)

    def clear(self) -> None:
        self.translation_units.clear()
        self.cursors.clear()
        self.tokens.clear()
