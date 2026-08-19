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


def test_confirm_lexical_from_walks_unique_usr() -> None:
    walks = [
        SimpleNamespace(
            functions={
                "Process": SimpleNamespace(
                    usr="c:@S@Kernel@F@Process",
                    qualified_name="Kernel::Process",
                    file="op_kernel/k.h",
                )
            }
        )
    ]
    sites = [{"caller": "kernel", "callee": "Process"}]
    n = kscan.confirm_lexical_from_walks(sites, walks)
    assert n == 1
    assert sites[0]["callee_usr"] == "c:@S@Kernel@F@Process"
    assert sites[0]["call_kind"] == "resolved_call"


def test_confirm_lexical_from_walks_ambiguous_stays_unresolved() -> None:
    walks = [
        SimpleNamespace(
            functions={
                "Init": SimpleNamespace(usr="c:@S@A@F@Init", qualified_name="A::Init", file="a.h"),
            }
        ),
        SimpleNamespace(
            functions={
                "Init": SimpleNamespace(usr="c:@S@B@F@Init", qualified_name="B::Init", file="b.h"),
            }
        ),
    ]
    sites = [{"caller": "kernel", "callee": "Init"}]
    assert kscan.confirm_lexical_from_walks(sites, walks) == 0
    assert not sites[0].get("callee_usr")


def test_advisory_calls_do_not_close_reachability() -> None:
    from uo_init.ir.codemap import CodeMap
    from uo_init.ir.entity import EntityKind
    from uo_init.ir.evidence import TRUST_ADVISORY, TRUST_AUTHORITATIVE
    from uo_init.ir.relation import RelationKind
    from uo_init.passes.kernel_root_trace import _propagate_reachability

    cm = CodeMap(op_name="op", architecture="arch35")
    lexical_fn = cm.upsert(EntityKind.FUNCTION, "Guessed")
    reached = cm.upsert(
        EntityKind.FUNCTION,
        "Add",
        attrs={"root_status": "REACHED", "root": "AscendC::Add"},
    )
    cm.mint_candidate_relation(
        RelationKind.CALLS, lexical_fn.id, reached.id, provenance="lexical_source_calls"
    )
    _propagate_reachability(cm)
    assert lexical_fn.attrs.get("root_status") != "REACHED"

    resolved_fn = cm.upsert(EntityKind.FUNCTION, "Caller")
    cm.mint_semantic_relation(
        RelationKind.CALLS,
        resolved_fn.id,
        reached.id,
        provenance="clang_ast",
    )
    rel = [r for r in cm.relations.values() if r.src == resolved_fn.id][0]
    assert rel.attrs.get("trust") == TRUST_AUTHORITATIVE
    _propagate_reachability(cm)
    assert resolved_fn.attrs.get("root_status") == "REACHED"
    assert lexical_fn.attrs.get("root_status") != "REACHED"
    assert any(
        r.attrs.get("trust") == TRUST_ADVISORY
        for r in cm.relations.values()
        if r.src == lexical_fn.id
    )


def test_blank_block_comments_keeps_newline_count() -> None:
    from uo_init.source_index.builder import _blank_block_comments

    text = "a\n/*\nb\nc\n*/\nd\n"
    assert text.count("\n") == _blank_block_comments(text).count("\n")


def test_initbuffer_after_file_banner_keeps_physical_lines(tmp_path: Path) -> None:
    """File-banner ``/* */`` must not shift later InitBuffer onto earlier Clang lines."""
    from uo_init.source_index.builder import _scan_file

    banner = "/**\n" + "\n".join(f" * copyright {i}" for i in range(8)) + "\n */\n"
    body = (
        "void Init() {\n"
        "  pipe->InitBuffer(dqInitBuf, 1);\n"
        "  pipe->InitBuffer(dkInitBuf, 1);\n"
        "  pipe->InitBuffer(input2Que[0], 1, n);\n"
        "  pipe->InitBuffer(out1Que, 2, n);\n"
        "}\n"
    )
    text = banner + body
    path = tmp_path / "presfmg.h"
    path.write_text(text, encoding="utf-8")
    facts = _scan_file(path, root=str(tmp_path), registry=None)
    inits = [s for s in facts.call_sites if s.get("callee") == "InitBuffer"]
    lines = text.splitlines()
    by_arg = {(s.get("args") or ["?"])[0]: int(s.get("line") or 0) for s in inits}
    assert "input2Que[0]" in by_arg
    assert "out1Que" in by_arg
    for arg, line in by_arg.items():
        assert 1 <= line <= len(lines)
        assert arg in lines[line - 1], (arg, line, lines[line - 1])


def test_shifted_initbuffer_does_not_clobber_clang_merge(tmp_path: Path) -> None:
    """Lexical sites at physical lines merge in; shifted lines would drop them."""
    from uo_init.source_index.builder import _scan_file

    banner = "/**\n" + "\n".join(f" * copyright {i}" for i in range(8)) + "\n */\n"
    body = (
        "void Init() {\n"
        "  pipe->InitBuffer(dqInitBuf, 1);\n"
        "  pipe->InitBuffer(dkInitBuf, 1);\n"
        "  pipe->InitBuffer(input2Que[0], 1, n);\n"
        "  pipe->InitBuffer(out1Que, 2, n);\n"
        "}\n"
    )
    path = tmp_path / "presfmg.h"
    path.write_text(banner + body, encoding="utf-8")
    physical = list((banner + body).splitlines())
    clang = []
    for i, src in enumerate(physical, start=1):
        if "InitBuffer(dqInitBuf" in src or "InitBuffer(dkInitBuf" in src:
            clang.append(
                {
                    "file": str(path),
                    "line": i,
                    "callee": "InitBuffer",
                    "args": ["early"],
                }
            )
    facts = _scan_file(path, root=str(tmp_path), registry=None)
    lexical = [s for s in facts.call_sites if s.get("callee") == "InitBuffer"]
    merged, _added = kscan.merge_lexical_sites(clang, lexical, root=str(tmp_path))
    names = []
    for site in merged:
        d = kscan.site_as_dict(site)
        if d.get("callee") == "InitBuffer":
            args = d.get("args") or []
            if args:
                names.append(str(args[0]))
    assert "input2Que[0]" in names
    assert "out1Que" in names


def test_architecture_kernel_files_skips_root_cpp_owned_by_other_arch(tmp_path: Path) -> None:
    root = tmp_path / "op"
    (root / "op_kernel" / "arch35").mkdir(parents=True)
    (root / "op_kernel" / "arch22").mkdir(parents=True)
    (root / "op_kernel" / "arch35" / "k.h").write_text("void Current();\n", encoding="utf-8")
    (root / "op_kernel" / "entry_apt.cpp").write_text(
        '#include "arch35/k.h"\nvoid Apt() {}\n', encoding="utf-8"
    )
    (root / "op_kernel" / "entry.cpp").write_text(
        '#include "arch22/old.h"\nvoid OldEntry() {}\n', encoding="utf-8"
    )
    (root / "op_kernel" / "arch22" / "old.h").write_text(
        "void OldBody() { DataCopy(a, b, n); }\n", encoding="utf-8"
    )
    files = kscan.architecture_kernel_files(root, "arch35")
    names = {p.name for p in files}
    assert "k.h" in names
    assert "entry_apt.cpp" in names
    assert "entry.cpp" not in names
    assert "old.h" not in names


def test_kernel_corpus_does_not_follow_other_arch_includes(tmp_path: Path) -> None:
    root = tmp_path / "op"
    (root / "op_kernel" / "arch35").mkdir(parents=True)
    (root / "op_kernel" / "arch22" / "basic_modules").mkdir(parents=True)
    (root / "op_kernel" / "arch35" / "entry.h").write_text(
        '#include "../arch22/tiling.h"\nvoid Kernel() { DataCopy(a, b, n); }\n',
        encoding="utf-8",
    )
    (root / "op_kernel" / "arch22" / "tiling.h").write_text(
        '#include "basic_modules/cube.h"\nstruct OldTiling {};\n',
        encoding="utf-8",
    )
    (root / "op_kernel" / "arch22" / "basic_modules" / "cube.h").write_text(
        "void Cube() { LoadAlign(v, p); }\n",
        encoding="utf-8",
    )
    files = kscan.kernel_corpus(root, "arch35", include_walks=False)
    posix = [p.as_posix().replace("\\", "/") for p in files]
    assert any(p.endswith("arch35/entry.h") for p in posix)
    assert not any("/arch22/" in p for p in posix)

