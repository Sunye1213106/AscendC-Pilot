"""YAML literal-block sanitize — prefer Pilot shared implementation when installed."""

from __future__ import annotations

from typing import Any

try:
    from ascendc_pilot.yaml_literal_sanitize import (  # type: ignore[import-not-found]
        safe_load_yaml_file,
        safe_load_yaml_text,
        sanitize_literal_block_indents,
    )
except ImportError:  # pragma: no cover — standalone UO without Pilot
    import re

    _LITERAL_KEY_RE = re.compile(r"^([ \t]*)([A-Za-z_][\w-]*)\s*:\s*\|[+-]?(?:[1-9])?\s*$")
    _YAML_KEY_RE = re.compile(r"^([ \t]*)([A-Za-z_][\w-]*)\s*:")

    def sanitize_literal_block_indents(text: str) -> str:
        lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        out: list[str] = []
        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]
            m = _LITERAL_KEY_RE.match(line)
            if not m:
                out.append(line)
                i += 1
                continue
            key_indent = len(m.group(1).replace("\t", "  "))
            out.append(line)
            i += 1
            content_base: int | None = None
            while i < n:
                cur = lines[i]
                if not cur.strip():
                    out.append(cur)
                    i += 1
                    continue
                expanded = cur.replace("\t", "  ")
                lead = len(expanded) - len(expanded.lstrip(" "))
                km = _YAML_KEY_RE.match(cur)
                if km and lead <= key_indent:
                    break
                if content_base is None:
                    content_base = lead
                    out.append(cur)
                    i += 1
                    continue
                if lead < content_base:
                    out.append((" " * content_base) + cur.lstrip())
                else:
                    out.append(cur)
                i += 1
        return "\n".join(out)

    def safe_load_yaml_text(text: str) -> Any:
        import yaml

        return yaml.safe_load(sanitize_literal_block_indents(text))

    def safe_load_yaml_file(path: Any) -> Any:
        from pathlib import Path

        return safe_load_yaml_text(Path(path).read_text(encoding="utf-8"))

__all__ = [
    "sanitize_literal_block_indents",
    "safe_load_yaml_text",
    "safe_load_yaml_file",
]
