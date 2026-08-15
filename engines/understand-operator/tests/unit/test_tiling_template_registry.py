# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.passes.tiling_template_registry import enrich_tiling_template_registry
from uo_init.store.writer import write_codemap
from uo_init.uo_query import open_query


def test_tiling_template_registry_projects_priority_and_locate(tmp_path: Path) -> None:
    root = tmp_path / "fag"
    host = root / "op_host" / "arch35"
    host.mkdir(parents=True)
    (root / "op_kernel" / "arch35").mkdir(parents=True)
    (host / "tiling.cpp").write_text(
        """
REGISTER_TILING_TEMPLATE_WITH_ARCH(FlashAttentionScoreGrad, FlashAttentionScoreGradTiling, ASCEND_V220, 900)
REGISTER_TILING_TEMPLATE_WITH_ARCH(FlashAttentionScoreGrad, RegbaseFAG, ASCEND_V350, 950)
REGISTER_TILING_DEFAULT(RegbaseFAG)

class RegbaseFAG {
 public:
  bool IsCapable() { return true; }
};
""",
        encoding="utf-8",
    )
    cm = CodeMap(op_name="FlashAttentionScoreGrad", architecture="arch35")
    enrich_tiling_template_registry(cm, root, architecture="arch35")
    preds = [
        e
        for e in cm.by_kind(EntityKind.PREDICATE)
        if e.attrs.get("predicate_role") == "tiling_template_registry"
    ]
    by_class = {str(e.attrs.get("class")): e for e in preds}
    assert by_class["RegbaseFAG"].attrs.get("priority") == 950
    assert by_class["FlashAttentionScoreGradTiling"].attrs.get("priority") == 900
    assert by_class["RegbaseFAG"].attrs.get("is_capable_line")

    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "fag.arch35.uo"
    product.parent.mkdir(parents=True, exist_ok=True)
    write_codemap(cm, product)
    q = open_query(tmp_path)
    loc = q.aggregate_locate("REGISTER_TILING_TEMPLATE RegbaseFAG")
    names = {str(row.get("name") or "") for row in loc["locations"]}
    assert any("RegbaseFAG" in name for name in names)
    facts = next(
        (row.get("facts") or {})
        for row in loc["locations"]
        if "RegbaseFAG" in str(row.get("name") or "")
    )
    assert int(facts.get("priority") or 0) == 950
    default = q.aggregate_locate("REGISTER_TILING_DEFAULT")
    assert default["count"] >= 1
    assert any(
        str(row.get("name") or "") == "REGISTER_TILING_DEFAULT"
        for row in default["locations"]
    )
