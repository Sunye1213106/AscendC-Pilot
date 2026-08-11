# -*- coding: utf-8 -*-
"""The analysis must not know which operator it is looking at.

This repository is developed against one operator but is meant to run on all of
them. Every operator-specific name that reaches the product code is a place
where the next operator silently gets a different answer, and the only way that
stays true is if something checks.

Comments and docstrings are exempt on purpose: explaining a design decision by
naming the case that motivated it is how the reasoning stays reviewable. What
is banned is an operator name the code *acts on* -- a branch, a lookup key, a
default path.
"""

from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path

import pytest

from uo_init import paths

#: Every directory whose code has to work on an operator it has never seen.
#: The analysis engine was the original scope; the closure ledger, the replay
#: driver and the control plane make the same promise and were unguarded, which
#: is how a per-operator alias survived in the replay adapter.
#: Specialisation belongs only under the analysed operator's
#: ``.ascendc-pilot/<arch>/local/`` (Local Extension), never in UO/TG engines.
PRODUCT_DIRS = (
    Path("engines/understand-operator/src/uo_init"),
    Path("engines/testcase-generation/testcase_agent"),
    Path("scripts/replay"),
    Path("pilot/ascendc_pilot"),
)

#: Abbreviations no rule can derive from a directory name.
EXTRA_TOKENS = {"fag", "FAG"}

#: Operator names to look for even when ops-transformer is not on this machine,
#: so the gate never passes merely because it had nothing to check.
SEED_OPERATORS = {
    "flash_attention_score_grad",
    "flash_attention_score",
    "FlashAttentionScoreGrad",
    "FlashAttentionScore",
}

#: Exceptions, each with the reason it is not specialisation. Keep this short:
#: an entry here is a place the claim above is weaker than it sounds.
ALLOWLIST: dict[str, set[str]] = {}


def _operator_tokens() -> set[str]:
    """Names that identify one operator, in the spellings source code uses.

    Single-word directory names (`common`, `compressor`, `ffn`) are skipped:
    they collide with ordinary English and would make the gate mostly noise.
    """
    tokens = set(SEED_OPERATORS) | EXTRA_TOKENS
    ops = paths.ops_root()
    if ops is not None:
        for host in ops.rglob("op_host"):
            if not host.is_dir():
                continue
            name = host.parent.name
            if "_" not in name:
                continue
            tokens.add(name)
            tokens.add("".join(part.capitalize() for part in name.split("_")))
    return tokens


def _code_without_prose(path: Path) -> str:
    """The file's source with comments and docstrings removed.

    String *literals* stay: `if op == "FlashAttentionScoreGrad"` is exactly the
    thing being looked for, and it is a literal.
    """
    # ``utf-8-sig``: a byte-order mark makes ``ast.parse`` raise, and a file the
    # gate cannot parse is a file the gate cannot check.
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines(keepends=True)

    drop: set[int] = set()
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT:
            drop.update(range(tok.start[0], tok.end[0] + 1))

    tree = ast.parse(text)
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

    kept = []
    for number, line in enumerate(lines, start=1):
        kept.append("\n" if number in drop else line)
    return "".join(kept)


def _sources() -> list[Path]:
    root = paths.repo_root()
    out: list[Path] = []
    for rel in PRODUCT_DIRS:
        base = root / rel
        out.extend(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)
    return sorted(out)


def test_the_gate_has_something_to_check():
    root = paths.repo_root()
    for rel in PRODUCT_DIRS:
        assert sorted((root / rel).rglob("*.py")), f"no product sources under {rel}"
    tokens = _operator_tokens()
    assert len(tokens) >= len(SEED_OPERATORS)


def test_product_code_names_no_operator():
    tokens = _operator_tokens()
    root = paths.repo_root()
    offenders: list[str] = []
    for path in _sources():
        allowed = ALLOWLIST.get(path.name, set())
        code = _code_without_prose(path)
        lowered = code.lower()
        for token in tokens:
            if token in allowed:
                continue
            if token.lower() not in lowered:
                continue
            for number, line in enumerate(code.splitlines(), start=1):
                if token.lower() in line.lower():
                    offenders.append(
                        f"{path.relative_to(root)}:{number}: {token}: {line.strip()[:100]}"
                    )
    assert not offenders, (
        "product code refers to a specific operator; move it to configuration "
        "or to the tests:\n  " + "\n  ".join(sorted(set(offenders)))
    )


@pytest.mark.parametrize(
    "snippet,expected",
    [
        ('x = "FlashAttentionScoreGrad"\n', True),
        ('# FlashAttentionScoreGrad motivated this\nx = 1\n', False),
        ('"""FlashAttentionScoreGrad is the example."""\nx = 1\n', False),
        ('def f():\n    """About FlashAttentionScoreGrad."""\n    return 1\n', False),
    ],
)
def test_prose_is_stripped_but_code_is_not(tmp_path, snippet, expected):
    """The exemption is what makes this gate usable; it must be exact."""
    path = tmp_path / "sample.py"
    path.write_text(snippet, encoding="utf-8")
    code = _code_without_prose(path)
    assert ("FlashAttentionScoreGrad" in code) is expected
