# -*- coding: utf-8 -*-
"""What the analysis is allowed to read, and why each file earns its place.

Two ways to get scope wrong, and they fail differently. Too narrow and a header
the operator compiles goes missing, so whatever it defines reads as unknown --
silent, and it looks like a gap in the analysis rather than a gap in the input.
Too wide and a sibling operator's tiling walks in, so writes appear that no run
of this operator performs.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from uo_init import scope_scan as ss


def _write(root: Path, rel: str, text: str = "") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def domain(tmp_path: Path) -> Path:
    """A domain laid out the way Ascend C repositories are: operators side by
    side, shared code in a `common` beside them, two architectures."""
    root = tmp_path / "attention"
    _write(root, "widget/op_api/aclnn_widget.cpp", '#include "widget.h"\n')
    _write(root, "widget/op_api/widget.h")
    _write(root, "widget/op_graph/widget_proto.h")
    _write(root, "widget/op_host/widget_def.cpp")
    _write(root, "widget/op_host/widget_infershape.cpp")
    _write(root, "widget/op_host/widget_tiling.cpp")
    _write(root, "widget/op_host/arch35/widget_tiling_regbase.cpp")
    _write(root, "widget/op_host/arch22/widget_tiling_old.cpp")
    _write(
        root,
        "widget/op_kernel/widget_apt.cpp",
        '#include "arch35/widget_kernel.h"\n',
    )
    _write(
        root,
        "widget/op_kernel/widget.cpp",
        '#include "arch22/widget_kernel_old.h"\n',
    )
    _write(
        root,
        "widget/op_kernel/arch35/widget_kernel.h",
        '#include "../../../common/op_kernel/arch35/mask.h"\n',
    )
    _write(root, "widget/op_kernel/arch22/widget_kernel_old.h")
    _write(root, "widget/tests/ut/test_widget_tiling.cpp")
    _write(root, "widget/examples/demo_widget.cpp")

    # Shared: one reached directly, one reached only through the first, one
    # never named, plus an arch22-only file.
    _write(
        root,
        "common/op_kernel/arch35/mask.h",
        '#include "../buffer.h"\n',
    )
    _write(root, "common/op_kernel/buffer.h")
    _write(root, "common/op_kernel/arch35/unused.h")
    _write(root, "common/op_kernel/arch22/mask_old.h")

    # A sibling operator, to prove scope stops at the operator boundary.
    _write(root, "gadget/op_host/gadget_tiling.cpp")
    return root / "widget"


def _rels(scope: ss.ScopeSet) -> set[str]:
    return {f.path.relative_to(scope.workspace_root).as_posix() for f in scope.files}


def test_the_four_layout_directories_are_taken_whole(domain: Path) -> None:
    got = _rels(ss.scan(domain, arch_dir="arch35"))
    assert "widget/op_api/aclnn_widget.cpp" in got
    assert "widget/op_graph/widget_proto.h" in got
    assert "widget/op_host/widget_def.cpp" in got
    assert "widget/op_kernel/arch35/widget_kernel.h" in got


def test_a_file_earns_its_place_by_directory_not_by_name(tmp_path: Path) -> None:
    """The operator is `widget`; this file is not named after it and is still
    the operator's own tiling."""
    root = tmp_path / "attention"
    _write(root, "widget/op_host/regbase_common.cpp")
    _write(root, "widget/op_kernel/entry.cpp")
    got = _rels(ss.scan(root / "widget", arch_dir="arch35"))
    assert "widget/op_host/regbase_common.cpp" in got


def test_tests_and_examples_never_enter(domain: Path) -> None:
    got = _rels(ss.scan(domain, arch_dir="arch35"))
    assert not [p for p in got if "/tests/" in p or "/examples/" in p]


def test_a_sibling_operator_stays_out(domain: Path) -> None:
    got = _rels(ss.scan(domain, arch_dir="arch35"))
    assert not [p for p in got if p.startswith("gadget/")]


def test_only_the_requested_architecture_survives(domain: Path) -> None:
    got = _rels(ss.scan(domain, arch_dir="arch35"))
    assert "widget/op_host/arch35/widget_tiling_regbase.cpp" in got
    assert "widget/op_host/arch22/widget_tiling_old.cpp" not in got
    assert "common/op_kernel/arch22/mask_old.h" not in got


def test_architecture_neutral_paths_are_kept(domain: Path) -> None:
    """`op_host/widget_tiling.cpp` sits above the arch folders and is compiled
    whichever architecture is being built."""
    got = _rels(ss.scan(domain, arch_dir="arch35"))
    assert "widget/op_host/widget_tiling.cpp" in got


def test_a_kernel_entry_for_another_architecture_is_dropped(domain: Path) -> None:
    """Entries sit above the arch folders, so the path says nothing. What each
    one includes does."""
    scope = ss.scan(domain, arch_dir="arch35")
    got = _rels(scope)
    assert "widget/op_kernel/widget_apt.cpp" in got
    assert "widget/op_kernel/widget.cpp" not in got
    assert any("builds arch22" in n for n in scope.notes)


def test_shared_code_comes_in_only_when_included(domain: Path) -> None:
    got = _rels(ss.scan(domain, arch_dir="arch35"))
    assert "common/op_kernel/arch35/mask.h" in got
    assert "common/op_kernel/arch35/unused.h" not in got


def test_the_include_walk_is_transitive(domain: Path) -> None:
    """`buffer.h` is named by no operator file, only by a shared header that is
    itself included."""
    got = _rels(ss.scan(domain, arch_dir="arch35"))
    assert "common/op_kernel/buffer.h" in got


def test_a_bare_file_name_does_not_attach_shared_code(tmp_path: Path) -> None:
    """`matmul.h` exists in several trees in a real repository. Matching on the
    name alone would compile in one the operator never sees."""
    root = tmp_path / "attention"
    _write(root, "widget/op_kernel/widget_apt.cpp", '#include "matmul.h"\n')
    _write(root, "widget/op_kernel/matmul.h")
    _write(root, "common/op_kernel/matmul.h")
    got = _rels(ss.scan(root / "widget", arch_dir=""))
    assert "widget/op_kernel/matmul.h" in got
    assert "common/op_kernel/matmul.h" not in got


def test_roles_separate_the_layers(domain: Path) -> None:
    scope = ss.scan(domain, arch_dir="arch35")
    by_role = {f.path.name: f.role for f in scope.files}
    assert by_role["aclnn_widget.cpp"] == ss.ROLE_API
    assert by_role["widget_def.cpp"] == ss.ROLE_HOST_DEF
    assert by_role["widget_infershape.cpp"] == ss.ROLE_HOST_INFERSHAPE
    assert by_role["widget_tiling.cpp"] == ss.ROLE_HOST_TILING
    assert by_role["widget_apt.cpp"] == ss.ROLE_KERNEL_ENTRY
    # The prototype is a header by suffix but a prototype by where it sits,
    # and `op_graph` holds nothing else. Reading it as a plain header loses
    # the one file that states the operator's declared interface.
    assert by_role["widget_proto.h"] == ss.ROLE_GRAPH


def test_only_kernel_code_asks_for_the_device_compiler(domain: Path) -> None:
    scope = ss.scan(domain, arch_dir="arch35")
    by_name = {f.path.name: f.side for f in scope.files}
    assert by_name["widget_apt.cpp"] == ss.SIDE_KERNEL
    assert by_name["mask.h"] == ss.SIDE_KERNEL
    assert by_name["aclnn_widget.cpp"] == ss.SIDE_HOST
    assert by_name["widget_tiling.cpp"] == ss.SIDE_HOST


def test_selection_narrows_to_what_a_stage_parses(domain: Path) -> None:
    scope = ss.scan(domain, arch_dir="arch35")
    host_tus = scope.paths(side=ss.SIDE_HOST, tu_only=True)
    assert all(p.suffix == ".cpp" for p in host_tus)
    assert not [p for p in host_tus if "op_kernel" in p.parts]

    tiling = scope.paths(role=ss.ROLE_HOST_TILING, tu_only=True)
    assert {p.name for p in tiling} == {
        "widget_tiling.cpp",
        "widget_tiling_regbase.cpp",
    }


def test_membership_ignores_how_a_path_is_spelt(domain: Path) -> None:
    """Clang reports the path it opened, which need not match how we walked to
    it: separators and case both differ on Windows."""
    scope = ss.scan(domain, arch_dir="arch35")
    entry = scope.paths(role=ss.ROLE_KERNEL_ENTRY, tu_only=True)[0]
    assert scope.contains(entry)
    assert scope.contains(entry.as_posix())
    assert scope.contains(str(entry).replace("/", "\\"))
    assert scope.contains(str(entry).upper())
    assert not scope.contains(entry.parent / "nowhere.cpp")
    assert not scope.contains("")


def test_a_domain_without_shared_code_still_scans(tmp_path: Path) -> None:
    root = tmp_path / "solo"
    _write(root, "op_host/solo_tiling.cpp")
    _write(root, "op_kernel/solo.cpp")
    scope = ss.scan(root, arch_dir="")
    assert len(scope.files) == 2
    assert any("no_common_tree" in n for n in scope.notes)


def test_shared_code_inside_the_operator_is_found_too(tmp_path: Path) -> None:
    root = tmp_path / "solo"
    _write(root, "op_kernel/solo.cpp", '#include "../common/op_kernel/util.h"\n')
    _write(root, "common/op_kernel/util.h")
    scope = ss.scan(root, arch_dir="")
    got = {f.path.relative_to(scope.workspace_root).as_posix() for f in scope.files}
    assert "common/op_kernel/util.h" in got
