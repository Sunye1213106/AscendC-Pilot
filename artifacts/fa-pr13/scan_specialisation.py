# -*- coding: utf-8 -*-
"""Scan for operator specialisation outside the directory the gate already guards.

Reuses the gate's own prose-stripping so comments and docstrings stay exempt:
what is reported is an operator name the code *acts on*.
"""

from __future__ import annotations

import ast
import io
import sys
import tokenize
from pathlib import Path

ROOT = Path("/mnt/d/PR-review/AscendC-Pilot")

TARGETS = [
    "engines/testcase-generation/testcase_agent",
    "scripts/replay",
    "pilot/ascendc_pilot",
    "engines/understand-operator/src/uo_init",
]

SEED = {
    "flash_attention_score_grad",
    "flash_attention_score",
    "FlashAttentionScoreGrad",
    "FlashAttentionScore",
    "flash_attn",
    "fag",
}


def code_without_prose(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    drop: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                drop.update(range(tok.start[0], tok.end[0] + 1))
        tree = ast.parse(text)
    except SyntaxError:
        return text
    for node in ast.walk(tree):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            drop.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return "".join(
        "\n" if n in drop else line for n, line in enumerate(lines, start=1)
    )


def main() -> int:
    total = 0
    for target in TARGETS:
        base = ROOT / target
        hits: list[str] = []
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            code = code_without_prose(path)
            for n, line in enumerate(code.splitlines(), start=1):
                low = line.lower()
                for tok in SEED:
                    if tok.lower() in low:
                        hits.append(
                            f"{path.relative_to(base)}:{n}: {tok}: {line.strip()[:120]}"
                        )
                        break
        print(f"\n=== {target}: {len(hits)} code-level hits ===")
        for h in hits:
            print("  " + h)
        total += len(hits)
    print(f"\nTOTAL={total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
