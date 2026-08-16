# -*- coding: utf-8 -*-
"""tpl_schema pass + TG view backfill."""

from __future__ import annotations

from pathlib import Path

import pytest

from uo_init.canonical_tpl_projection import project_tpl_views_from_codemap
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.passes.tpl_schema import run as run_tpl_schema
from uo_init.tg_projection import backfill_from_source, legal_key_count
from uo_init.tg_views import finalize_tg_views


HEADER = """\
ASCENDC_TPL_ARGS_DECL(
  ToyOp,
  ASCENDC_TPL_BOOL_DECL(IsEmpty, 0, 1),
  ASCENDC_TPL_UINT_DECL(Split, ASCENDC_TPL_3_BW, UI_LIST, 0, 1, 5),
  ASCENDC_TPL_BOOL_DECL(Flag, 0, 1)
);
ASCENDC_TPL_ARGS_SEL(
  ASCENDC_TPL_BOOL_SEL(IsEmpty, 0),
  ASCENDC_TPL_UINT_SEL(Split, UI_LIST, 0, 1),
  ASCENDC_TPL_BOOL_SEL(Flag, 0, 1)
);
ASCENDC_TPL_ARGS_SEL(
  ASCENDC_TPL_BOOL_SEL(IsEmpty, 1),
  ASCENDC_TPL_UINT_SEL(Split, UI_LIST, 5),
  ASCENDC_TPL_BOOL_SEL(Flag, 0)
);
"""


def test_tpl_schema_pass_builds_d(tmp_path: Path):
    header = tmp_path / "toy_template_tiling_key.h"
    header.write_text(HEADER, encoding="utf-8")
    cm = CodeMap(op_name="toy", architecture="arch0")
    ctx: dict = {"tiling_key_header": str(header), "tg_views": {}}
    cm = run_tpl_schema(cm, context=ctx)
    assert cm.meta.get("tpl_schema_pass") == "v1"
    assert int(cm.meta.get("legal_key_count") or 0) == 5  # 2*2 + 1
    assert int(cm.meta.get("args_sel_group_count") or 0) == 2
    keys = cm.by_kind(EntityKind.TILING_KEY)
    assert {k.name for k in keys} >= {"IsEmpty", "Split", "Flag"}
    groups = [
        e for e in cm.by_kind(EntityKind.TEMPLATE) if e.attrs.get("tpl_role") == "args_sel_group"
    ]
    assert len(groups) == 2
    views = finalize_tg_views(cm, existing=ctx["tg_views"])
    assert views["tiling/exhaustive_key_space.yaml"]["legal_key_count"] == 5
    assert "ir/tg_host_view.yaml" in views
    assert views["ir/operator_graph.yaml"]["fingerprint"]
    rebuilt = project_tpl_views_from_codemap(cm)
    assert rebuilt
    assert rebuilt["tiling/exhaustive_key_space.yaml"]["legal_key_count"] == 5
    macros = {e.name for e in cm.by_kind(EntityKind.MACRO)}
    assert "ASCENDC_TPL_ARGS_SEL" in macros
    assert "ASCENDC_TPL_BOOL_SEL" in macros


def test_split_decl_sel_headers_rebuild_canonical_views(tmp_path: Path):
    op = tmp_path / "toy"
    kernel = op / "op_kernel"
    (kernel / "arch35").mkdir(parents=True)
    (op / "op_host").mkdir()
    (kernel / "toy_tiling_key_decl.h").write_text(
        "ASCENDC_TPL_ARGS_DECL(Toy,\n"
        "  ASCENDC_TPL_UINT_DECL(MODE, ASCENDC_TPL_2_BW, ASCENDC_TPL_UI_LIST, 0, 1),\n"
        "  ASCENDC_TPL_BOOL_DECL(FLAG, 0, 1));\n",
        encoding="utf-8",
    )
    (kernel / "arch35" / "toy_apt_tiling_key.h").write_text(
        '#include "../toy_tiling_key_decl.h"\n'
        "ASCENDC_TPL_ARGS_SEL(ASCENDC_TPL_UINT_SEL(MODE, ASCENDC_TPL_UI_LIST, 0),\n"
        "                     ASCENDC_TPL_BOOL_SEL(FLAG, 0, 1));\n",
        encoding="utf-8",
    )
    (kernel / "toy_apt.cpp").write_text(
        '#include "arch35/toy_apt_tiling_key.h"\n'
        "__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *tiling) {}\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch35")
    ctx: dict = {"op_root": str(op), "architecture": "arch35", "tg_views": {}}
    cm = run_tpl_schema(cm, context=ctx)
    groups = [
        e for e in cm.by_kind(EntityKind.TEMPLATE) if e.attrs.get("tpl_role") == "args_sel_group"
    ]
    assert len(groups) == 1
    rebuilt = project_tpl_views_from_codemap(cm)
    assert rebuilt
    assert int(rebuilt["tiling/exhaustive_key_space.yaml"]["legal_key_count"]) == 2


def test_decl_only_schema_does_not_stamp_tpl_views(tmp_path: Path):
    header = tmp_path / "decl_only.h"
    header.write_text(
        "ASCENDC_TPL_ARGS_DECL(Toy, ASCENDC_TPL_BOOL_DECL(Flag, 0, 1));\n",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="toy", architecture="arch0")
    ctx: dict = {
        "tiling_key_header": str(header),
        "tg_views": {"tiling/tpl_schema.yaml": {"stale": True}},
    }
    cm = run_tpl_schema(cm, context=ctx)
    assert cm.meta.get("tpl_schema_pass") == "v1-decl-only"
    assert "tiling/tpl_schema.yaml" not in ctx["tg_views"]
    assert project_tpl_views_from_codemap(cm) == {}


def test_args_sel_helper_macros_rebuild_canonical_views(tmp_path: Path):
    header = tmp_path / "helper_tiling_key.h"
    parts = [
        "#define SET_HELPER(tag) ASCENDC_TPL_BOOL_SEL(FLAG, 0), "
        "ASCENDC_TPL_UINT_SEL(MODE, ASCENDC_TPL_UI_LIST, MODE_##tag)\n",
        "ASCENDC_TPL_ARGS_DECL(Toy,\n",
        "  ASCENDC_TPL_BOOL_DECL(FLAG, 0, 1),\n",
        "  ASCENDC_TPL_UINT_DECL(MODE, ASCENDC_TPL_4_BW, ASCENDC_TPL_UI_LIST, MODE_A, MODE_B));\n",
    ]
    for i in range(30):
        tag = "A" if i % 2 == 0 else "B"
        parts.append(f"ASCENDC_TPL_ARGS_SEL(SET_HELPER({tag}));\n")
    header.write_text("".join(parts), encoding="utf-8")
    cm = CodeMap(op_name="toy", architecture="arch0")
    ctx: dict = {"tiling_key_header": str(header), "tg_views": {}}
    cm = run_tpl_schema(cm, context=ctx)
    groups = [
        e for e in cm.by_kind(EntityKind.TEMPLATE) if e.attrs.get("tpl_role") == "args_sel_group"
    ]
    assert len(groups) == 30
    rebuilt = project_tpl_views_from_codemap(cm)
    assert rebuilt
    assert int(rebuilt["tiling/template_blocks.yaml"]["count"]) == 30


@pytest.mark.skipif(
    not Path(
        r"d:\PR-review\TEST\ops-transformer\attention\flash_attention_score_grad"
        r"\op_kernel\arch35\flash_attention_score_grad_template_tiling_key.h"
    ).is_file(),
    reason="FAG source header not present",
)
def test_fag_backfill_legal_key_count(tmp_path: Path):
    import shutil

    src_uo = Path(
        r"d:\PR-review\AscendC-Pilot\artifacts\fa-pr13\flash_attention_score_grad.arch35.uo"
    )
    if not src_uo.is_file():
        pytest.skip("FAG artifact .uo missing")
    dst = tmp_path / "fag.uo"
    shutil.copy2(src_uo, dst)
    op = Path(r"d:\PR-review\TEST\ops-transformer\attention\flash_attention_score_grad")
    header = (
        op / "op_kernel" / "arch35" / "flash_attention_score_grad_template_tiling_key.h"
    )
    out = backfill_from_source(op, uo_path=dst, tiling_key_header=header)
    assert out.get("ok") is True
    assert int(out.get("legal_key_count") or 0) == 8705
    assert legal_key_count(dst) == 8705
