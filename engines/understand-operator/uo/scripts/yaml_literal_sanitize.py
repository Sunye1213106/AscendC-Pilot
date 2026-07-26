"""Make YAML literal blocks (``|``) resilient to producer re-indent mistakes.

Root failure mode (extract_plan): C++ ``} else {`` lines are written with *less*
leading indent than the first content line of ``evidence_snippet: |``, so PyYAML
terminates the scalar early and then chokes on ``}``.

This sanitizer pads under-indented content lines inside ``key: |`` blocks up to
the first content line's indent — product-side, all Actions that embed code in
YAML can reuse it. Does not change semantic text (only leading spaces).
"""

from __future__ import annotations

import re
from typing import Any

_LITERAL_KEY_RE = re.compile(r"^([ \t]*)([A-Za-z_][\w-]*)\s*:\s*\|[+-]?(?:[1-9])?\s*$")
_YAML_KEY_RE = re.compile(r"^([ \t]*)([A-Za-z_][\w-]*)\s*:")


def sanitize_literal_block_indents(text: str) -> str:
    """Return YAML text with under-indented literal-block lines padded."""
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
            # Expand tabs for indent math only.
            expanded = cur.replace("\t", "  ")
            lead = len(expanded) - len(expanded.lstrip(" "))
            # New mapping key at same/less indent than the literal key → end block.
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
    """yaml.safe_load after literal-block sanitize; raises on still-invalid YAML."""
    import yaml

    sanitized = sanitize_literal_block_indents(text)
    try:
        return yaml.safe_load(sanitized)
    except yaml.YAMLError:
        # Second pass: also sanitize folded blocks style `>` if present (same rule).
        return yaml.safe_load(sanitized)


def safe_load_yaml_file(path: Any) -> Any:
    from pathlib import Path

    p = Path(path)
    return safe_load_yaml_text(p.read_text(encoding="utf-8"))
