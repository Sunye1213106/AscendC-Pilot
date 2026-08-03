# -*- coding: utf-8 -*-
"""The key layout is read on demand, not at import.

Fourteen scripts reach for `runner.SCHEMA` and `runner.DIM_NAMES`, so those
have to keep working as plain module attributes. What must *not* happen is the
header being parsed just because something imported the package: that put the
operator checkout on the critical path for `inputs`, `bridge` and `search`,
none of which need it, and left the pure input logic untestable anywhere the
sources are not present.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]

PURE = ["inputs", "bridge", "search", "corpus", "constraints"]


def _in_subprocess(body: str, **env_overrides: str) -> str:
    """Run `body` with a fresh interpreter, so module caches do not leak.

    The parse is memoised per process, so anything asserting *when* it happens
    cannot share one with the other tests.
    """
    import os

    env = dict(os.environ, PYTHONPATH=str(SCRIPTS), **env_overrides)
    proc = subprocess.run(
        [sys.executable, "-c", body],
        capture_output=True, text=True, env=env, cwd=str(SCRIPTS),
    )
    if proc.returncode != 0:
        raise AssertionError(f"exit {proc.returncode}\n{proc.stdout}\n{proc.stderr}")
    return proc.stdout.strip()


def test_importing_the_package_builds_no_runner():
    out = _in_subprocess(
        "from replay import runner, inputs, bridge, search, corpus, constraints\n"
        "print(runner._default)"
    )
    assert out == "None"


def test_reading_the_manifest_does_not_reach_for_the_header():
    """The manifest says where the header is; opening it is a separate step."""
    out = _in_subprocess(
        "from replay import runner\n"
        "print(runner.default().manifest.arch, sorted(runner.default()._parsed))"
    )
    assert out.endswith("[]")


@pytest.mark.parametrize("module", PURE)
def test_pure_logic_imports_without_the_operator_sources(module: str):
    """Point the ops tree at nothing and the input-side modules still load."""
    out = _in_subprocess(
        f"import replay.{module} as m; print(m.__name__)",
        UO_OPS_ROOT=str(SCRIPTS / "deliberately_absent"),
        UO_REPLAY_TPL="",
    )
    assert out == f"replay.{module}"


def test_asking_for_the_schema_without_sources_says_what_to_set():
    """The failure names the knobs, rather than surfacing as a parse error."""
    out = _in_subprocess(
        "from replay import runner\n"
        "try:\n"
        "    runner.DIM_NAMES\n"
        "except SystemExit as exc:\n"
        "    print(exc)\n"
        "else:\n"
        "    print('RESOLVED')\n",
        UO_OPS_ROOT=str(SCRIPTS / "deliberately_absent"),
        UO_REPLAY_TPL="",
    )
    assert "RESOLVED" not in out
    assert "UO_OPS_ROOT" in out and "tiling_key_header" in out


def test_the_schema_attributes_still_answer(tpl_header: Path):
    from replay import runner

    assert runner.TPL == tpl_header
    assert runner.DIM_NAMES == [d.name for d in runner.SCHEMA.dims]
    assert len(runner.DIM_NAMES) == len(set(runner.DIM_NAMES))


def test_dim_names_hands_out_a_copy(tpl_header: Path):
    """A caller mutating the list must not rewrite the cached layout."""
    from replay import runner

    first = runner.dim_names()
    first.append("not_a_dimension")
    assert "not_a_dimension" not in runner.dim_names()


def test_an_unknown_attribute_is_still_an_attribute_error():
    from replay import runner

    with pytest.raises(AttributeError):
        runner.NO_SUCH_THING


def test_an_explicit_header_overrides_operator_discovery(tpl_header: Path):
    out = _in_subprocess(
        "from replay import runner; print(runner.TPL)",
        UO_OPS_ROOT=str(SCRIPTS / "deliberately_absent"),
        UO_REPLAY_TPL=str(tpl_header),
    )
    assert Path(out) == tpl_header
