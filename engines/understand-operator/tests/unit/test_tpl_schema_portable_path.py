from pathlib import Path

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.passes import tpl_schema


def test_tpl_schema_source_refs_are_operator_relative(tmp_path: Path) -> None:
    operator = tmp_path / "demo_op"
    header = operator / "op_kernel" / "arch35" / "demo_template_tiling_key.h"
    header.parent.mkdir(parents=True)
    header.write_text(
        "ASCENDC_TPL_ARGS_DECL(DemoOp, ASCENDC_TPL_BOOL_DECL(IsFoo, 0, 1))\n",
        encoding="utf-8",
    )

    cm = CodeMap(op_name="demo_op", architecture="arch35")
    ctx = {
        "op_root": str(operator),
        "architecture": "arch35",
        "tiling_key_header": str(header),
    }

    tpl_schema.run(cm, context=ctx)

    expected = "demo_op/op_kernel/arch35/demo_template_tiling_key.h"
    assert cm.meta["tpl_schema"]["header"] == expected
    keys = cm.by_kind(EntityKind.TILING_KEY)
    assert keys and all(key.file == expected for key in keys)
    assert ctx["tg_views"]["tiling/tpl_schema.yaml"]["header"] == expected
    assert ctx["tg_views"]["tiling/exhaustive_key_space.yaml"]["header"] == expected
    assert not Path(expected).is_absolute()
    assert str(tmp_path) not in repr(cm.to_dict())
    assert str(tmp_path) not in repr(ctx["tg_views"])
