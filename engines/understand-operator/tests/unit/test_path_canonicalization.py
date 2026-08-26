# -*- coding: utf-8 -*-
"""One spelling per file, and every spelling resolves back to that file.

Extraction produced four bases for the same tree at once -- operator-relative,
ops-root-relative, the shared sibling directory, and absolute -- so one file had
several identities and only one of them could be joined to `source_line`. Recall
maps a text hit to an entity by path equality, which made the others uncitable.
These tests pin the single canonical form and the round trip back to disk.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.paths import CANN_MARKER, resolve_operator_file
from uo_init.query.sql import _norm_file, _strip_dot_slash
from uo_init.store.writer import write_codemap


def _tree(tmp_path: Path) -> tuple[Path, Path]:
    """An operator directory with a shared sibling, as the repos are laid out."""
    ops_root = tmp_path / "attention"
    op_dir = ops_root / "flash_attention_score_grad"
    (op_dir / "op_kernel" / "arch35").mkdir(parents=True)
    (op_dir / "op_kernel" / "arch35" / "k.h").write_text("// kernel\n", encoding="utf-8")
    (ops_root / "common" / "op_kernel" / "arch35").mkdir(parents=True)
    (ops_root / "common" / "op_kernel" / "arch35" / "shared.h").write_text(
        "// shared\n", encoding="utf-8"
    )
    (tmp_path / "common" / "include").mkdir(parents=True)
    (tmp_path / "common" / "include" / "util.h").write_text("// util\n", encoding="utf-8")
    return op_dir, ops_root


def _write(op_dir: Path, files: dict[str, str]) -> Path:
    cm = CodeMap(op_name="demo", architecture="arch35")
    for eid, file in files.items():
        cm.add_entity(
            Entity(
                id=eid,
                kind=EntityKind.FUNCTION,
                name=eid.lower(),
                attrs={"decl_file": file, "write_sites": [{"file": file, "line": 3}]},
                file=file,
                line_start=1,
                line_end=1,
            )
        )
    product = op_dir / ".ascendc-pilot" / "arch35" / "uo" / "demo.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)
    return product


def _stored(product: Path) -> dict[str, tuple[str, str, str]]:
    conn = sqlite3.connect(str(product))
    try:
        rows = conn.execute("SELECT id, file, data FROM entity").fetchall()
    finally:
        conn.close()
    out = {}
    for eid, file, data in rows:
        attrs = json.loads(data or "{}")
        site = (attrs.get("write_sites") or [{}])[0]
        out[eid] = (file, str(attrs.get("decl_file") or ""), str(site.get("file") or ""))
    return out


def test_four_spellings_of_one_file_collapse_to_one(tmp_path: Path) -> None:
    op_dir, ops_root = _tree(tmp_path)
    target = "op_kernel/arch35/k.h"
    product = _write(
        op_dir,
        {
            "F_rel": target,
            "F_ops": f"flash_attention_score_grad/{target}",
            "F_abs": (op_dir / "op_kernel" / "arch35" / "k.h").as_posix(),
            "F_dots": f"op_host/arch35/../../{target}",
        },
    )
    stored = _stored(product)
    assert {row[0] for row in stored.values()} == {target}
    # An attr location is as much a citation as the column is; a reader cannot
    # join two spellings, so both go through the same canonical form.
    for eid, (file, decl, site) in stored.items():
        assert decl == target, eid
        assert site == target, eid


def test_shared_sibling_keeps_its_parents(tmp_path: Path) -> None:
    """`../common/x.h` names a real file; `common/x.h` names a different tree."""
    op_dir, _ = _tree(tmp_path)
    product = _write(
        op_dir,
        {
            "F_beside": "common/op_kernel/arch35/shared.h",
            "F_above": (tmp_path / "common" / "include" / "util.h").as_posix(),
        },
    )
    stored = _stored(product)
    assert stored["F_beside"][0] == "../common/op_kernel/arch35/shared.h"
    assert stored["F_above"][0] == "../../common/include/util.h"
    for eid, (file, _decl, _site) in stored.items():
        assert resolve_operator_file(op_dir, file) is not None, f"{eid}: {file}"


def test_stored_paths_resolve_back_to_disk(tmp_path: Path) -> None:
    op_dir, _ = _tree(tmp_path)
    product = _write(op_dir, {"F_a": "op_kernel/arch35/k.h", "F_b": "common/op_kernel/arch35/shared.h"})
    for file, _decl, _site in _stored(product).values():
        resolved = resolve_operator_file(op_dir, file)
        assert resolved is not None and resolved.is_file(), file


def test_no_stored_path_names_the_build_machine(tmp_path: Path) -> None:
    """A product spelled with a drive letter can only be read where it was built."""
    op_dir, _ = _tree(tmp_path)
    product = _write(
        op_dir,
        {
            "F_abs": (op_dir / "op_kernel" / "arch35" / "k.h").as_posix(),
            "F_beside": (tmp_path / "attention" / "common" / "op_kernel" / "arch35" / "shared.h").as_posix(),
        },
    )
    for eid, row in _stored(product).items():
        for value in row:
            assert not value.startswith(str(tmp_path.drive)), f"{eid}: {value}"
            assert ":" not in value, f"{eid}: {value}"


def test_cann_marker_round_trips_through_the_local_install(tmp_path: Path, monkeypatch) -> None:
    """Toolkit headers are outside every checkout, so they travel as a marker."""
    op_dir, _ = _tree(tmp_path)
    cann = tmp_path / "_cann" / "pkg"
    header = cann / "cann-asc-devkit" / "x86_64-linux" / "asc" / "include" / "basic_api" / "k.h"
    header.parent.mkdir(parents=True)
    header.write_text("// toolkit\n", encoding="utf-8")
    monkeypatch.setattr("uo_init.paths.cann_root", lambda *a, **k: cann)
    monkeypatch.setattr("uo_init.store.writer.cann_root", lambda *a, **k: cann)

    product = _write(op_dir, {"F_tk": header.as_posix()})
    stored = _stored(product)["F_tk"][0]
    assert stored == CANN_MARKER + "cann-asc-devkit/x86_64-linux/asc/include/basic_api/k.h"
    assert resolve_operator_file(op_dir, stored) == header


def test_norm_file_lets_a_card_round_trip_into_file_argument() -> None:
    """`--file` is copied off a card, so shortening the card breaks the lookup."""
    for canonical in (
        "op_kernel/arch35/k.h",
        "../common/op_kernel/arch35/shared.h",
        "../../common/include/util.h",
        CANN_MARKER + "cann-asc-devkit/x86_64-linux/asc/include/basic_api/k.h",
    ):
        assert _norm_file(canonical) == canonical
    # A product written before canonicalization still gets cut down to something
    # that can be found under the operator.
    assert _norm_file("D:/build/tree/op_host/arch35/t.cpp") == "op_host/arch35/t.cpp"


def test_strip_dot_slash_is_not_a_character_set() -> None:
    """`lstrip('./')` ate the parents off a sibling path and moved the file."""
    assert _strip_dot_slash("./op_kernel/k.h") == "op_kernel/k.h"
    assert _strip_dot_slash("../common/k.h") == "../common/k.h"
    assert _strip_dot_slash("../../common/include/util.h") == "../../common/include/util.h"
    assert "../common/k.h".lstrip("./") == "common/k.h"


def test_source_line_indexes_what_the_graph_cites_outside_the_operator(tmp_path: Path) -> None:
    """A shared file the graph points at has to be citable, or recall drops it."""
    op_dir, _ = _tree(tmp_path)
    product = _write(op_dir, {"F_beside": "common/op_kernel/arch35/shared.h"})
    conn = sqlite3.connect(str(product))
    try:
        indexed = {row[0] for row in conn.execute("SELECT DISTINCT path FROM source_line")}
        unjoinable = conn.execute(
            "SELECT COUNT(*) FROM entity e WHERE IFNULL(e.file,'') <> '' "
            "AND NOT EXISTS(SELECT 1 FROM source_line l WHERE l.path = e.file)"
        ).fetchone()[0]
    finally:
        conn.close()
    assert "../common/op_kernel/arch35/shared.h" in indexed
    assert unjoinable == 0
