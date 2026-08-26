# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from acp_common.paths import (
    canonical_path,
    peel_known_prefix,
    resolve_under_operator,
    strip_dot_slash,
)


def test_strip_dot_slash_is_not_a_character_set() -> None:
    assert strip_dot_slash("./op_host/foo.cpp") == "op_host/foo.cpp"
    assert strip_dot_slash("../common/foo.h") == "../common/foo.h"
    assert strip_dot_slash("../../common/include/util.h") == "../../common/include/util.h"
    assert "../common/foo.h".lstrip("./") == "common/foo.h"


def _layout(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path
    op = repo / "attention" / "flash_attention_score_grad"
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel").mkdir(parents=True)
    (op / "op_host" / "foo.cpp").write_text("int host = 1;\n", encoding="utf-8")
    (op / "op_host" / "foo.h").write_text("int host_h = 1;\n", encoding="utf-8")
    (op / "op_kernel" / "foo.h").write_text("int kernel_h = 1;\n", encoding="utf-8")
    common = repo / "attention" / "common"
    common.mkdir(parents=True)
    (common / "foo.h").write_text("int shared = 1;\n", encoding="utf-8")
    (op / "common").mkdir()
    (op / "common" / "foo.h").write_text("int nested = 1;\n", encoding="utf-8")
    return repo, op


def test_parent_path_does_not_collapse_into_operator_common(tmp_path: Path) -> None:
    repo, op = _layout(tmp_path)
    found = resolve_under_operator(op, "../common/foo.h", repo_root=repo)
    assert found is not None
    assert found.resolve() == (repo / "attention" / "common" / "foo.h").resolve()
    nested = resolve_under_operator(op, "common/foo.h", repo_root=repo)
    assert nested is not None
    assert nested.resolve() == (op / "common" / "foo.h").resolve()


def test_dot_slash_operator_relative(tmp_path: Path) -> None:
    repo, op = _layout(tmp_path)
    found = resolve_under_operator(op, "./op_host/foo.cpp", repo_root=repo)
    assert found is not None
    assert found.name == "foo.cpp"


def test_duplicate_basename_is_ambiguous(tmp_path: Path) -> None:
    repo, op = _layout(tmp_path)
    assert resolve_under_operator(op, "foo.h", repo_root=repo) is None
    host = resolve_under_operator(op, "op_host/foo.h", repo_root=repo)
    kernel = resolve_under_operator(op, "op_kernel/foo.h", repo_root=repo)
    assert host is not None and kernel is not None
    assert host != kernel


def test_repo_and_operator_relative_share_canonical(tmp_path: Path) -> None:
    repo, op = _layout(tmp_path)
    a = canonical_path(op, "op_host/foo.cpp", repo_root=repo)
    b = canonical_path(
        op, "attention/flash_attention_score_grad/op_host/foo.cpp", repo_root=repo
    )
    assert a is not None and b is not None
    assert a.absolute_resolved == b.absolute_resolved
    assert a.canonical_operator_rel == "op_host/foo.cpp"
    assert b.canonical_operator_rel == "op_host/foo.cpp"


def test_unknown_prefix_is_not_suffix_guessed(tmp_path: Path) -> None:
    repo, op = _layout(tmp_path)
    assert peel_known_prefix(
        "elsewhere/flash_attention_score_grad/op_host/foo.cpp",
        operator_root=op,
        repo_root=repo,
    ) == "elsewhere/flash_attention_score_grad/op_host/foo.cpp"
    assert (
        resolve_under_operator(
            op,
            "elsewhere/flash_attention_score_grad/op_host/foo.cpp",
            repo_root=repo,
        )
        is None
    )
