from __future__ import annotations

from pathlib import Path

from uo.scripts.source_include_closure import expand_local_include_closure


def test_follows_relative_project_include_and_stops_at_system_header(tmp_path: Path) -> None:
    seed = tmp_path / "op" / "arch35" / "kernel.h"
    common = tmp_path / "common" / "helper.h"
    seed.parent.mkdir(parents=True)
    common.parent.mkdir(parents=True)
    seed.write_text(
        '#include "../../common/helper.h"\n#include <kernel_operator.h>\n',
        encoding="utf-8",
    )
    common.write_text("inline int Helper() { return 1; }\n", encoding="utf-8")

    result = expand_local_include_closure(tmp_path, [seed], architecture="arch35")

    assert result.files == sorted([seed.resolve(), common.resolve()], key=lambda p: p.as_posix())
    assert any(edge["target"] == "common/helper.h" for edge in result.edges)
    assert not any(item.get("include") == "kernel_operator.h" for item in result.unresolved)
    assert not result.truncated


def test_excludes_other_architecture_files(tmp_path: Path) -> None:
    seed = tmp_path / "op" / "arch35" / "kernel.h"
    other = tmp_path / "op" / "arch22" / "helper.h"
    seed.parent.mkdir(parents=True)
    other.parent.mkdir(parents=True)
    seed.write_text('#include "../arch22/helper.h"\n', encoding="utf-8")
    other.write_text("inline int WrongArch() { return 0; }\n", encoding="utf-8")

    result = expand_local_include_closure(tmp_path, [seed], architecture="arch35")

    assert other.resolve() not in result.files
    assert any(item["kind"] == "include_target_missing" for item in result.unresolved)


def test_ambiguous_suffix_fails_closed(tmp_path: Path) -> None:
    seed = tmp_path / "op" / "kernel.h"
    a = tmp_path / "a" / "shared" / "helper.h"
    b = tmp_path / "b" / "shared" / "helper.h"
    seed.parent.mkdir(parents=True)
    a.parent.mkdir(parents=True)
    b.parent.mkdir(parents=True)
    seed.write_text('#include "shared/helper.h"\n', encoding="utf-8")
    a.write_text("// a\n", encoding="utf-8")
    b.write_text("// b\n", encoding="utf-8")

    result = expand_local_include_closure(tmp_path, [seed])

    assert a.resolve() not in result.files and b.resolve() not in result.files
    item = next(row for row in result.unresolved if row["kind"] == "include_target_ambiguous")
    assert sorted(item["candidates"]) == ["a/shared/helper.h", "b/shared/helper.h"]


def test_cycle_is_deduplicated(tmp_path: Path) -> None:
    a = tmp_path / "a.h"
    b = tmp_path / "b.h"
    a.write_text('#include "b.h"\n', encoding="utf-8")
    b.write_text('#include "a.h"\n', encoding="utf-8")

    result = expand_local_include_closure(tmp_path, [a])

    assert result.files == sorted([a.resolve(), b.resolve()], key=lambda p: p.as_posix())
    assert len(result.edges) == 2
