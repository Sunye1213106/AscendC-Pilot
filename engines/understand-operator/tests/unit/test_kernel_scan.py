# -*- coding: utf-8 -*-
from types import SimpleNamespace
from pathlib import Path

from uo_init.passes import kernel_scan as kscan


def test_collect_call_sites_allows_walk_methods(monkeypatch, tmp_path: Path):
    """Packed-key kernels put EnQue in class methods, not the KERNEL entry."""
    site = SimpleNamespace(caller="InitAllZeroOutput", callee="EnQue", file="x.h")
    wr = SimpleNamespace(
        path=str(tmp_path / "op_kernel" / "entry.cpp"),
        call_sites=[site],
        functions={"InitAllZeroOutput": object(), "incre_flash_attention": object()},
        local_decls=[],
        controls=[],
    )
    monkeypatch.setattr(
        "uo_init.tu_cache.iter_cached_walks", lambda *a, **k: [wr]
    )
    import time

    calls, *_ = kscan.collect_call_sites_from_walks(
        tmp_path,
        architecture="arch22",
        reachable={"incre_flash_attention"},
        filter_strict=True,
        deadline=time.time() + 30,
    )
    assert [kscan.site_as_dict(s).get("callee") for s in calls] == ["EnQue"]


def test_kernel_api_scan_files_follows_quoted_include(tmp_path: Path) -> None:
    root = tmp_path / "op"
    (root / "op_kernel" / "arch35").mkdir(parents=True)
    (root / "inc").mkdir()
    (root / "inc" / "copy.h").write_text("void Impl() { DataCopy(a, b, n); }\n", encoding="utf-8")
    (root / "op_kernel" / "arch35" / "entry.h").write_text(
        '#include "../../inc/copy.h"\nvoid Kernel() {}\n',
        encoding="utf-8",
    )
    files = kscan.kernel_api_scan_files(root, "arch35")
    names = {p.name for p in files}
    assert "copy.h" in names
    assert "entry.h" in names


def test_kernel_api_scan_files_follows_family_common_cgmct(tmp_path: Path) -> None:
    """Quoted ``cgmct/`` includes resolve via sibling family ``common/``, not CANN."""
    family = tmp_path / "family"
    op = family / "op"
    common = family / "common" / "cgmct" / "block"
    common.mkdir(parents=True)
    (op / "op_kernel" / "arch35").mkdir(parents=True)
    (common / "copy.h").write_text(
        "void Impl() { DataCopy(dst, src, n); LoadData(a, b, p); }\n",
        encoding="utf-8",
    )
    (op / "op_kernel" / "arch35" / "entry.h").write_text(
        '#include "cgmct/block/copy.h"\nvoid Kernel() {}\n',
        encoding="utf-8",
    )
    files = kscan.kernel_api_scan_files(op, "arch35")
    names = {p.name for p in files}
    assert "copy.h" in names
    from uo_init.diagnostics.source_api import ALL_SOURCE_OWNERS, count_source_kernel_apis

    gated = count_source_kernel_apis(op, "arch35")
    assert gated["DataCopy"] == 0
    assert gated["LoadData"] == 0
    all_counts = count_source_kernel_apis(op, "arch35", owners=ALL_SOURCE_OWNERS)
    assert all_counts["DataCopy"] == 1
    assert all_counts["LoadData"] == 1


def test_architecture_kernel_files_include_neutral_skip_other_arch(tmp_path: Path) -> None:
    """apt-style ops keep TQue in op_kernel/*.h, not only op_kernel/<arch>/."""
    root = tmp_path / "gmm_like"
    (root / "op_kernel" / "arch35").mkdir(parents=True)
    (root / "op_kernel" / "arch22").mkdir(parents=True)
    (root / "op_kernel" / "arch35" / "tiling.h").write_text("int tiling;\n", encoding="utf-8")
    (root / "op_kernel" / "quant.h").write_text("void EnQueBody();\n", encoding="utf-8")
    (root / "op_kernel" / "entry.cpp").write_text("void KernelEntry() {}\n", encoding="utf-8")
    (root / "op_kernel" / "arch22" / "old.h").write_text("void OldEnQue();\n", encoding="utf-8")
    files = kscan.architecture_kernel_files(root, "arch35")
    names = {p.name for p in files}
    assert names == {"tiling.h", "quant.h", "entry.cpp"}
    assert all("arch22" not in p.as_posix() for p in files)


def test_kernel_corpus_follows_sibling_cpp_and_tags_owner(tmp_path: Path) -> None:
    """Fusion wrapper #include of a sibling .cpp stays in the corpus with sibling_op owner."""
    family = tmp_path / "family"
    wrap = family / "wrap"
    sib = family / "sib"
    (wrap / "op_kernel" / "arch35").mkdir(parents=True)
    (sib / "op_kernel").mkdir(parents=True)
    (sib / "op_kernel" / "k.cpp").write_text(
        "void Impl() { q.EnQue(x); LoadAlign(v, p); }\n",
        encoding="utf-8",
    )
    (wrap / "op_kernel" / "entry.cpp").write_text(
        '#include "../../sib/op_kernel/k.cpp"\nvoid Kernel() {}\n',
        encoding="utf-8",
    )
    files = kscan.kernel_corpus(wrap, "arch35", include_walks=False)
    names = {p.name for p in files}
    assert "k.cpp" in names
    assert "entry.cpp" in names
    sib_file = next(p for p in files if p.name == "k.cpp")
    assert kscan.kernel_file_owner(sib_file, wrap) == "sibling_op"
    assert kscan.kernel_file_owner(wrap / "op_kernel" / "entry.cpp", wrap) == "this_op"
    from uo_init.diagnostics.source_api import count_source_kernel_apis

    counts = count_source_kernel_apis(wrap, "arch35")
    assert counts["EnQue"] == 1
    assert counts["LoadAlign"] == 1


def test_kernel_corpus_does_not_recurse_sibling_tree(tmp_path: Path) -> None:
    """One-hop sibling .cpp stays; nested sibling headers do not, unless walk-cited."""
    family = tmp_path / "family"
    wrap = family / "wrap"
    sib = family / "sib"
    (wrap / "op_kernel" / "arch35").mkdir(parents=True)
    (sib / "op_kernel").mkdir(parents=True)
    (sib / "op_kernel" / "nested.h").write_text(
        "void Deep() { q.EnQue(y); }\n",
        encoding="utf-8",
    )
    (sib / "op_kernel" / "k.cpp").write_text(
        '#include "nested.h"\nvoid Impl() { q.EnQue(x); }\n',
        encoding="utf-8",
    )
    (wrap / "op_kernel" / "entry.cpp").write_text(
        '#include "../../sib/op_kernel/k.cpp"\nvoid Kernel() {}\n',
        encoding="utf-8",
    )
    files = kscan.kernel_corpus(wrap, "arch35", include_walks=False)
    names = {p.name for p in files}
    assert "k.cpp" in names
    assert "nested.h" not in names
    from uo_init.diagnostics.source_api import count_source_kernel_apis

    counts = count_source_kernel_apis(wrap, "arch35")
    assert counts["EnQue"] == 1


def test_kernel_corpus_skips_cann_walk_cited(monkeypatch, tmp_path: Path) -> None:
    """Clang-cited CANN headers stay out of the lexical corpus (graph already has them)."""
    op = tmp_path / "family" / "op"
    (op / "op_kernel" / "arch35").mkdir(parents=True)
    (op / "op_kernel" / "arch35" / "entry.cpp").write_text(
        "void Kernel() {}\n",
        encoding="utf-8",
    )
    cann = tmp_path / "cann-asc" / "include" / "ascendc" / "kernel.h"
    cann.parent.mkdir(parents=True)
    cann.write_text("void Impl() { Cast(o, i, r, n); q.EnQue(x); }\n", encoding="utf-8")
    monkeypatch.setattr(
        kscan,
        "walk_cited_kernel_files",
        lambda *a, **k: [cann],
    )
    files = kscan.kernel_corpus(op, "arch35")
    assert cann not in files
    assert kscan.kernel_file_owner(cann, op) == "cann"
    from uo_init.diagnostics.source_api import count_source_kernel_apis

    counts = count_source_kernel_apis(op, "arch35")
    assert counts["Cast"] == 0
    assert counts["EnQue"] == 0


def test_collect_call_sites_dedupes_same_file_line_callee(monkeypatch, tmp_path: Path) -> None:
    from types import SimpleNamespace
    import time

    site_a = SimpleNamespace(
        caller="Kernel",
        callee="DataCopy",
        file=str(tmp_path / "op_kernel" / "a.h"),
        line=10,
        column=0,
        args=["dst", "src"],
        template_args=["float"],
    )
    site_b = SimpleNamespace(
        caller="Kernel",
        callee="DataCopy",
        file=str(tmp_path / "op_kernel" / "a.h"),
        line=10,
        column=0,
        args=["dst", "src"],
        template_args=["half"],
    )
    wr = SimpleNamespace(
        path=str(tmp_path / "op_kernel" / "entry.cpp"),
        call_sites=[site_a, site_b],
        functions={"Kernel": object()},
        local_decls=[],
        controls=[],
    )
    monkeypatch.setattr("uo_init.tu_cache.iter_cached_walks", lambda *a, **k: [wr, wr])
    calls, *_ = kscan.collect_call_sites_from_walks(
        tmp_path,
        architecture="arch35",
        reachable={"Kernel"},
        filter_strict=True,
        deadline=time.time() + 30,
    )
    assert len(calls) == 1
    row = kscan.site_as_dict(calls[0])
    assert row["callee"] == "DataCopy"
    assert int(row.get("instantiation_n") or 0) >= 2


def test_operation_site_id_ignores_ordinal_keeps_column() -> None:
    from uo_init.ids import operation_site_id

    a = operation_site_id(file="a.h", line=10, column=0, callee="Cast", ordinal=0)
    b = operation_site_id(file="a.h", line=10, column=0, callee="Cast", ordinal=32)
    assert a == b
    c = operation_site_id(file="a.h", line=10, column=3, callee="Cast")
    d = operation_site_id(file="a.h", line=10, column=8, callee="Cast")
    assert c != d
    assert c != a
