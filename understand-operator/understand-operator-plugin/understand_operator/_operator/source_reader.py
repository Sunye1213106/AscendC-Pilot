from __future__ import annotations

"""Strict, cached source-file access used by every source-evidence workflow."""

import hashlib
from dataclasses import dataclass
from pathlib import Path


class SourceReadError(ValueError):
    def __init__(self, code: str, path: Path, message: str) -> None:
        super().__init__(message)
        self.code, self.path, self.message = code, path, message

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path.as_posix(), "message": self.message}


@dataclass(frozen=True)
class SourceFile:
    path: Path
    raw_bytes: bytes
    text: str
    lines: tuple[str, ...]
    encoding: str
    bom: bool
    newline: str
    byte_hash: str

    def span(self, start_line: int, end_line: int) -> str:
        if not isinstance(start_line, int) or not isinstance(end_line, int) or start_line < 1 or end_line < start_line:
            raise SourceReadError("SOURCE_SPAN_INVALID", self.path, "start_line/end_line must be positive and ordered")
        if end_line > len(self.lines):
            raise SourceReadError("SOURCE_SPAN_OUT_OF_RANGE", self.path, f"span {start_line}-{end_line} exceeds {len(self.lines)} lines")
        return "\n".join(self.lines[start_line - 1 : end_line])


class SourceReader:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()
        self._cache: dict[Path, SourceFile] = {}

    def read(self, relative_path: str | Path) -> SourceFile:
        path = (self.repo_root / relative_path).resolve()
        try:
            path.relative_to(self.repo_root)
        except ValueError as exc:
            raise SourceReadError("SOURCE_FILE_OUTSIDE_REPO", path, "source path escapes repository") from exc
        if path in self._cache:
            return self._cache[path]
        try:
            raw = path.read_bytes()
        except FileNotFoundError as exc:
            raise SourceReadError("SOURCE_FILE_MISSING", path, "source file does not exist") from exc
        except OSError as exc:
            raise SourceReadError("SOURCE_READ_FAILED", path, str(exc)) from exc
        bom = raw.startswith(b"\xef\xbb\xbf")
        payload = raw[3:] if bom else raw
        try:
            text, encoding = payload.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            try:
                text, encoding = payload.decode("gb18030"), "gb18030"
            except UnicodeDecodeError as exc:
                raise SourceReadError("SOURCE_DECODE_FAILED", path, "UTF-8 and GB18030 strict decoding both failed") from exc
        newline = _newline_style(text)
        result = SourceFile(path, raw, text, tuple(text.splitlines()), encoding, bom, newline, "sha256:" + hashlib.sha256(raw).hexdigest())
        self._cache[path] = result
        return result

    def registry_entry(self, relative_path: str | Path) -> dict[str, object]:
        source = self.read(relative_path)
        return {"path": source.path.relative_to(self.repo_root).as_posix(), "encoding": source.encoding, "bom": source.bom, "newline": source.newline, "byte_hash": source.byte_hash, "decode_status": "confirmed"}


def _newline_style(text: str) -> str:
    crlf = text.count("\r\n")
    lf = text.count("\n") - crlf
    if crlf and lf:
        return "mixed"
    if crlf:
        return "crlf"
    return "lf"
