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
    by_hint = {f.path.name: f.role_hints for f in scope.files}
    assert by_role["aclnn_widget.cpp"] == ss.ROLE_API
    assert by_role["widget_def.cpp"] == ss.ROLE_HOST_OTHER
    assert ss.HINT_DEF in by_hint["widget_def.cpp"]
    assert by_role["widget_infershape.cpp"] == ss.ROLE_HOST_OTHER
    assert ss.HINT_INFERSHAPE in by_hint["widget_infershape.cpp"]
    assert by_role["widget_tiling.cpp"] == ss.ROLE_HOST_OTHER
    assert ss.HINT_TILING in by_hint["widget_tiling.cpp"]
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


def test_op_tiling_directory_is_host_tiling_even_without_tiling_in_name(tmp_path: Path) -> None:
    root = tmp_path / "mc2"
    _write(root, "widget/op_host/op_tiling/widget_tilling.cpp")
    _write(root, "widget/op_kernel/arch22/widget.cpp")
    scope = ss.scan(root / "widget", arch_dir="arch22")
    by_role = {f.path.name: f.role for f in scope.files}
    tilling = next(f for f in scope.files if f.path.name == "widget_tilling.cpp")
    assert by_role["widget_tilling.cpp"] == ss.ROLE_HOST_OTHER
    assert ss.HINT_TILING in tilling.role_hints
    tiling = scope.paths(role=ss.ROLE_HOST_TILING, tu_only=True)
    assert {p.name for p in tiling} == {"widget_tilling.cpp"}


def test_membership_ignores_how_a_path_is_spelt(domain: Path) -> None:
    """Clang reports the path it opened, which need not match how we walked to
    it: separators and case both differ on Windows."""
    scope = ss.scan(domain, arch_dir="arch35")
    entry = scope.paths(role=ss.ROLE_KERNEL_ENTRY, tu_only=True)[0]
    assert scope.contains(entry)
    assert scope.contains(entry.as_posix())
    assert scope.contains(str(entry).replace("/", "\\"))
    assert scope.contains(str(entry).upper())
    dotted = entry.as_posix().rsplit("/", 1)
    assert scope.contains(f"{dotted[0]}/./{dotted[1]}")
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


def test_classify_path_separates_owned_shared_external(domain: Path) -> None:
    scope = ss.scan(domain, arch_dir="arch35")
    owned = next(f.path for f in scope.files if not f.shared)
    shared = next(f.path for f in scope.files if f.shared)
    assert (
        ss.classify_path(
            owned, op_dir=scope.op_dir, workspace_root=scope.workspace_root
        )
        == ss.KIND_OWNED
    )
    assert (
        ss.classify_path(
            shared, op_dir=scope.op_dir, workspace_root=scope.workspace_root
        )
        == ss.KIND_SHARED
    )
    assert (
        ss.classify_path(
            "/opt/cann-asc-devkit/include/foo.h",
            op_dir=scope.op_dir,
            workspace_root=scope.workspace_root,
        )
        == ss.KIND_EXTERNAL
    )


def test_enrich_with_clang_replaces_regex_shared(domain: Path) -> None:
    """Clang shared closure replaces regex shared — it is not a union."""
    scope = ss.scan(domain, arch_dir="arch35")
    regex_shared = {f.path.name for f in scope.files if f.shared}
    assert "mask.h" in regex_shared
    assert "buffer.h" in regex_shared

    extra_shared = domain.parent / "common" / "op_kernel" / "arch35" / "extra_clang.h"
    extra_shared.parent.mkdir(parents=True, exist_ok=True)
    extra_shared.write_text("// clang-only\n", encoding="utf-8")
    external = Path("/opt/cann-asc-devkit/include/ghost.h")

    def _fake_includes(tu_path, args, op_dir="", **_kwargs):
        return ss.ClangIncludeResult(ok=True, paths=[extra_shared, external])

    old = ss.clang_include_paths
    ss.clang_include_paths = _fake_includes  # type: ignore[assignment]
    try:
        enrichment = ss.enrich_with_clang(
            scope,
            host_args=[],
            kernel_args=[],
            host_tus=scope.paths(role=ss.ROLE_HOST_TILING, tu_only=True),
            kernel_tu=None,
        )
    finally:
        ss.clang_include_paths = old  # type: ignore[assignment]

    assert enrichment.complete
    assert enrichment.tus_parsed == enrichment.tus_expected
    shared_names = {f.path.name for f in enrichment.scope.files if f.shared}
    assert shared_names == {"extra_clang.h"}
    assert "mask.h" not in shared_names
    assert "buffer.h" not in shared_names
    hit = next(f for f in enrichment.scope.files if f.path.name == "extra_clang.h")
    assert hit.provenance == "clang_include"
    assert not any("cann-asc-devkit" in f.path.as_posix() for f in enrichment.scope.files)
    # Layout-owned files Clang never referenced must not remain in scope.
    names = {f.path.name for f in enrichment.scope.files}
    assert "widget_def.cpp" not in names
    assert "unused.h" not in names
    for f in enrichment.scope.files:
        assert f.provenance in {"clang_tu", "clang_include"}
    assert "confirmed_source_files" in enrichment.scope.to_dict()
    assert enrichment.scope.confirmed_source_files()


def test_enrich_with_clang_incomplete_when_parse_fails(domain: Path) -> None:
    scope = ss.scan(domain, arch_dir="arch35")

    def _fail(tu_path, args, op_dir="", **_kwargs):
        return ss.ClangIncludeResult(ok=False, error=f"clang_parse_failed:{Path(tu_path).name}")

    old = ss.clang_include_paths
    ss.clang_include_paths = _fail  # type: ignore[assignment]
    try:
        enrichment = ss.enrich_with_clang(
            scope,
            host_args=[],
            host_tus=scope.paths(role=ss.ROLE_HOST_TILING, tu_only=True)[:1],
        )
    finally:
        ss.clang_include_paths = old  # type: ignore[assignment]

    assert not enrichment.complete
    assert enrichment.status == "incomplete"
    assert enrichment.tus_parsed == 0
    assert not any(f.shared for f in enrichment.scope.files)


def test_classify_path_marks_workspace_non_owned_as_shared(domain: Path) -> None:
    scope = ss.scan(domain, arch_dir="arch35")
    other = scope.workspace_root / "shared" / "util.h"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("//\n", encoding="utf-8")
    assert (
        ss.classify_path(other, op_dir=scope.op_dir, workspace_root=scope.workspace_root)
        == ss.KIND_SHARED
    )


def test_enrich_with_clang_collects_probes(domain: Path) -> None:
    scope = ss.scan(domain, arch_dir="arch35")

    def _fake(tu_path, args, op_dir="", **_kwargs):
        return ss.ClangIncludeResult(
            ok=True,
            paths=[],
            probe={
                "error_count": 0,
                "fatal_count": 0,
                "operator_error_count": 0,
                "probe_relevant_errors": 0,
                "samples": [],
                "skipped_bodies": False,
            },
        )

    old = ss.clang_include_paths
    ss.clang_include_paths = _fake  # type: ignore[assignment]
    try:
        enrichment = ss.enrich_with_clang(
            scope,
            host_args=[],
            kernel_args=[],
            host_tus=scope.paths(role=ss.ROLE_HOST_TILING, tu_only=True)[:1],
            kernel_tu=None,
        )
    finally:
        ss.clang_include_paths = old  # type: ignore[assignment]

    assert enrichment.complete
    assert enrichment.probes
    assert enrichment.probes[0]["probe_relevant_errors"] == 0
    assert enrichment.probes[0]["file"]


def test_load_prepared_scope_reuses_complete_receipt(tmp_path: Path) -> None:
    import yaml

    op = tmp_path / "widget"
    uo = op / ".ascendc-pilot" / "arch35" / "uo" / "summary"
    uo.mkdir(parents=True)
    payload = {
        "op_dir": str(op),
        "workspace_root": str(tmp_path),
        "arch_dir": "arch35",
        "files": [
            {
                "path": str(op / "a.cpp"),
                "role": "host",
                "side": "host",
                "is_tu": True,
                "shared": False,
            }
        ],
        "notes": [],
    }
    (uo / "scope_set.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")
    (uo / "scope_candidates.yaml").write_text(
        yaml.safe_dump({"clang_scope_status": "complete"}), encoding="utf-8"
    )
    got = ss.load_prepared_scope(op, "arch35")
    assert got is not None
    assert len(got.files) == 1


def test_load_prepared_scope_rejects_incomplete(tmp_path: Path) -> None:
    import yaml

    op = tmp_path / "widget"
    uo = op / ".ascendc-pilot" / "arch35" / "uo" / "summary"
    uo.mkdir(parents=True)
    payload = {
        "op_dir": str(op),
        "workspace_root": str(tmp_path),
        "arch_dir": "arch35",
        "files": [
            {
                "path": str(op / "a.cpp"),
                "role": "host",
                "side": "host",
                "is_tu": True,
                "shared": False,
            }
        ],
        "notes": [],
    }
    (uo / "scope_set.yaml").write_text(yaml.safe_dump(payload), encoding="utf-8")
    (uo / "scope_candidates.yaml").write_text(
        yaml.safe_dump({"clang_scope_status": "incomplete"}), encoding="utf-8"
    )
    assert ss.load_prepared_scope(op, "arch35") is None


def test_load_prepared_scope_force_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("UO_FORCE_SCOPE_ENRICH", "1")
    assert ss.load_prepared_scope(tmp_path, "arch35") is None


def test_arch_folder_kernel_cpp_is_kept_even_if_it_includes_another_arch(
    tmp_path: Path,
) -> None:
    """A2/A3 share a pipeline header named *_arch35.h; the TU still lives in arch22/."""
    root = tmp_path / "mc2"
    _write(
        root,
        "widget/op_kernel/arch22/widget.cpp",
        '#include "../widget_arch35.h"\n'
        '__global__ __aicore__ void widget() {}\n',
    )
    _write(root, "widget/op_kernel/widget_arch35.h")
    _write(
        root,
        "widget/op_kernel/arch35/widget_apt.cpp",
        '#include "widget_arch35.h"\n'
        '__global__ __aicore__ void widget() {}\n',
    )
    scope = ss.scan(root / "widget", arch_dir="arch22")
    tus = {p.name for p in scope.paths(role=ss.ROLE_KERNEL_ENTRY, tu_only=True)}
    assert tus == {"widget.cpp"}
    assert not any("kernel_entry_other_arch" in n for n in scope.notes)


def test_last_root_kernel_tu_is_kept_when_includes_name_another_arch(
    tmp_path: Path,
) -> None:
    root = tmp_path / "mc2"
    _write(
        root,
        "widget/op_kernel/widget.cpp",
        '#include "arch35/widget_arch35.h"\n'
        '__global__ __aicore__ void widget() {}\n',
    )
    _write(root, "widget/op_kernel/arch22/widget_arch22.h")
    _write(root, "widget/op_kernel/arch35/widget_arch35.h")
    scope = ss.scan(root / "widget", arch_dir="arch22")
    tus = {p.name for p in scope.paths(role=ss.ROLE_KERNEL_ENTRY, tu_only=True)}
    assert tus == {"widget.cpp"}
    assert any("kernel_entry_kept_last_tu" in n for n in scope.notes)

