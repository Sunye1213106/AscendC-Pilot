# -*- coding: utf-8 -*-
"""value_defining_sites backtrace: final ABI copy vs earlier value choice."""
from __future__ import annotations

from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import Entity, EntityKind
from uo_init.passes.value_defining_sites import enrich_value_defining_sites
from uo_init.tg_views import project_tilingdata_view


def _synthetic_op(tmp: Path) -> Path:
    """Minimal host that copies a param into TD after deciding the value."""
    root = tmp / "demo_op"
    (root / "op_host" / "arch35").mkdir(parents=True)
    (root / "op_kernel" / "arch35").mkdir(parents=True)
    (root / "op_graph").mkdir(parents=True)
    (root / "op_host" / "arch35" / "tiling.cpp").write_text(
        """
struct PreParams { uint32_t flag; uint32_t optionalOn; uint8_t modeTag; };
struct DemoTilingData {
  void set_flag(uint32_t v) { flag = v; }
  void set_optionalOn(uint32_t v) { optionalOn = v; }
  void set_modeTag(uint8_t v) { modeTag = v; }
  uint32_t flag; uint32_t optionalOn; uint8_t modeTag;
};

void Decide(PreParams& params, int x, bool hasOpt) {
  params.flag = 1;
  if (x % 8 != 0) {
    params.flag = 0;
  }
  params.optionalOn = hasOpt ? 1 : 0;
  params.modeTag = 0;
}

void Pack(DemoTilingData* td, PreParams& params) {
  td->set_flag(params.flag);
  td->set_optionalOn(params.optionalOn);
  td->set_modeTag(params.modeTag);
}
""",
        encoding="utf-8",
    )
    return root


def test_value_defining_sites_trace_param_assigns(tmp_path: Path) -> None:
    root = _synthetic_op(tmp_path)
    cm = CodeMap(op_name="demo", architecture="arch35")
    cm.add_entity(Entity(id="TD_Pre", kind=EntityKind.TILING_DATA, name="PreParams", attrs={}))
    cm.add_entity(Entity(id="TD_Demo", kind=EntityKind.TILING_DATA, name="DemoTilingData", attrs={}))
    for name, owner in (
        ("flag", "DemoTilingData"),
        ("optionalOn", "DemoTilingData"),
        ("modeTag", "DemoTilingData"),
    ):
        cm.add_entity(
            Entity(
                id=f"TF_{name}",
                kind=EntityKind.TILING_FIELD,
                name=name,
                attrs={
                    "owner": owner,
                    "host_writer_sites": [{
                        "file": "op_host/arch35/tiling.cpp",
                        "line": 1,
                        "receiver": "td",
                        "expression": f"params.{name}",
                        "mode": "setter",
                    }],
                },
            )
        )

    enrich_value_defining_sites(cm, root, architecture="arch35")

    flag = cm.entities["TF_flag"]
    sites = flag.attrs.get("value_defining_sites") or []
    rhs_set = {str(s.get("rhs") or "").replace(" ", "") for s in sites}
    assert "1" in rhs_set and "0" in rhs_set, sites
    assert all(s.get("kind") == "assignment" for s in sites)

    opt = cm.entities["TF_optionalOn"]
    opt_sites = opt.attrs.get("value_defining_sites") or []
    assert any("hasOpt" in str(s.get("rhs")) for s in opt_sites), opt_sites

    view = project_tilingdata_view(cm)
    rows = {f["name"]: f for s in view["structs"] for f in s["fields"]}
    assert rows["flag"].get("value_defining_sites")
    assert rows["optionalOn"].get("value_defining_sites")
