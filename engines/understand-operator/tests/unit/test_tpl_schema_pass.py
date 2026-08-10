# -*- coding: utf-8 -*-
"""tpl_schema pass + TG view backfill."""

from __future__ import annotations

from pathlib import Path

import pytest

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
