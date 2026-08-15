# -*- coding: utf-8 -*-
from pathlib import Path

from uo_init.diagnostics.source_api import (
    classify_blocker,
    count_source_kernel_apis,
    precision_gaps,
    rank_blockers,
)


def test_source_api_counts_arch_neutral_and_skips_other_arch(tmp_path: Path) -> None:
    root = tmp_path / "op"
    (root / "op_kernel" / "arch35").mkdir(parents=True)
    (root / "op_kernel" / "arch22").mkdir(parents=True)
    (root / "op_kernel" / "quant.h").write_text(
        "void Work() { q.EnQue(x); DeQue(); DataCopy(dst, src, n); DataCopyPad(a, b, p); Cast(o, i, r, n); }\n",
        encoding="utf-8",
    )
    (root / "op_kernel" / "arch22" / "old.h").write_text(
        "void Old() { q.EnQue(x); DataCopy(dst, src, n); }\n",
        encoding="utf-8",
    )
    counts = count_source_kernel_apis(root, "arch35")
    assert counts["EnQue"] == 1
    assert counts["DeQue"] == 1
    assert counts["DataCopy"] == 1
    assert counts["DataCopyPad"] == 1
    assert counts["Cast"] == 1


def test_source_api_skips_method_definitions(tmp_path: Path) -> None:
    root = tmp_path / "op"
    (root / "op_kernel" / "arch35").mkdir(parents=True)
    (root / "op_kernel" / "arch35" / "q.h").write_text(
        "inline void EnQue(LocalTensor<T> &t) { (void)t; }\n"
        "void DeQue(LocalTensor<T> &t);\n"
        "void Work() { q.EnQue(x); q.DeQue(); }\n",
        encoding="utf-8",
    )
    counts = count_source_kernel_apis(root, "arch35")
    assert counts["EnQue"] == 1
    assert counts["DeQue"] == 1


def test_source_api_follows_quoted_include_outside_op_kernel(tmp_path: Path) -> None:
    root = tmp_path / "op"
    (root / "op_kernel" / "arch35").mkdir(parents=True)
    (root / "inc").mkdir(parents=True)
    (root / "inc" / "copy.h").write_text(
        "void Impl() { DataCopy(dst, src, n); Copy(a, b); }\n",
        encoding="utf-8",
    )
    (root / "op_kernel" / "arch35" / "entry.h").write_text(
        '#include "../../inc/copy.h"\nvoid Kernel() {}\n',
        encoding="utf-8",
    )
    counts = count_source_kernel_apis(root, "arch35")
    assert counts["DataCopy"] == 1
    assert counts["Copy"] == 1


def test_source_api_unique_counts_file_line_name(tmp_path: Path) -> None:
    root = tmp_path / "op"
    (root / "op_kernel" / "arch35").mkdir(parents=True)
    (root / "op_kernel" / "arch35" / "entry.h").write_text(
        "void Work() { q.EnQue(a); q.EnQue(b); }\n"
        "void Other() { q.EnQue(c); }\n",
        encoding="utf-8",
    )
    counts = count_source_kernel_apis(root, "arch35")
    assert counts["EnQue"] == 2


def test_source_api_gated_skips_family_common(tmp_path: Path) -> None:
    family = tmp_path / "family"
    op = family / "op"
    common = family / "common" / "cgmct" / "block"
    common.mkdir(parents=True)
    (op / "op_kernel" / "arch35").mkdir(parents=True)
    (common / "cast.h").write_text("void T() { Cast(o, i, r, n); }\n", encoding="utf-8")
    (op / "op_kernel" / "arch35" / "entry.h").write_text(
        '#include "cgmct/block/cast.h"\nvoid Kernel() { q.EnQue(x); }\n',
        encoding="utf-8",
    )
    gated = count_source_kernel_apis(op, "arch35")
    assert gated["EnQue"] == 1
    assert gated["Cast"] == 0
    from uo_init.diagnostics.source_api import ALL_SOURCE_OWNERS

    assert count_source_kernel_apis(op, "arch35", owners=ALL_SOURCE_OWNERS)["Cast"] == 1


def test_source_api_from_codemap_prefers_snapshot() -> None:
    from types import SimpleNamespace
    from uo_init.diagnostics.source_api import source_api_from_codemap

    cm = SimpleNamespace(
        architecture="arch35",
        meta={"kernel_root_trace": {"source_api_gated": {"EnQue": 3, "Cast": 1}}},
    )
    out = source_api_from_codemap(cm, source_root="unused", architecture="arch35")
    assert out is not None
    assert out["EnQue"] == 3
    assert out["Cast"] == 1


def test_precision_gaps_only_when_source_present() -> None:
    source = {"EnQue": 0, "DeQue": 0, "DataCopyPad": 4, "DataCopy": 2, "Cast": 1}
    graph = {
        "EnQue": {"n": 0, "with_span": 0},
        "DeQue": {"n": 0, "with_span": 0},
        "DataCopyPad": {"n": 0, "with_span": 0},
        "DataCopy": {"n": 2, "with_span": 2},
        "Cast": {"n": 1, "with_span": 0},
    }
    gaps = {g["api"] for g in precision_gaps(source, graph)}
    assert gaps == {"DataCopyPad", "Cast"}


def test_precision_gaps_when_graph_drops_below_source() -> None:
    source = {"DataCopy": 20, "EnQue": 0, "DeQue": 0, "DataCopyPad": 0, "Cast": 0}
    graph = {"DataCopy": {"n": 17, "with_span": 17}}
    gaps = precision_gaps(source, graph)
    assert len(gaps) == 1
    assert gaps[0]["api"] == "DataCopy"
    assert gaps[0]["source"] == 20
    assert gaps[0]["graph_n"] == 17


def test_rank_blockers_picks_largest_class() -> None:
    cases = [
        {"rel": "a/one", "architecture": "arch35", "failed_step": "prepare"},
        {"rel": "a/two", "architecture": "arch35", "failed_step": "prepare"},
        {"rel": "a/three", "architecture": "arch35", "failed_step": "extract"},
        {
            "rel": "a/four",
            "architecture": "arch35",
            "failed_step": "verify",
            "verdict": "fail",
            "noise": {"precision_gaps": [], "quality": {}},
        },
    ]
    ranked = rank_blockers(cases)
    assert ranked["worst"] == "prepare_blocked"
    assert ranked["counts"]["prepare_blocked"] == 2
    assert classify_blocker(cases[1]) == "prepare_blocked"


def test_rank_blockers_quality_not_ready() -> None:
    case = {
        "rel": "a/five",
        "architecture": "arch35",
        "failed_step": "quality",
        "verdict": "pass",
        "ok": False,
        "noise": {
            "precision_gaps": [],
            "other_count": 0,
            "quality": {"grade": "usable", "not_ready_reasons": [], "surfaces": {}},
        },
    }
    assert classify_blocker(case) == "quality_not_ready"
