# -*- coding: utf-8 -*-
import sys
from pathlib import Path

ROOT = Path(r"d:\PR-review\AscendC-Pilot")
sys.path.insert(0, str(ROOT / "engines" / "understand-operator" / "src"))

from uo_init.derive_key_fields import _container_of
from uo_init.expr_ir import Call, Ref, Select, Const
from uo_init.source_resolver import dotted_path

FB = Ref("fBaseParams", scope="GetShapeAttrsInfo")
Q = Ref("qValue", scope="GetShapeAttrsInfo")
PARSE = Ref("parseInfo", scope="GetParseS1S2OuterInfo")
INV = Ref("invalidS1Array", scope="GetParseS1S2OuterInfo")

cases = [
    ("member actualSeqQlen", Select(Call("field:actualSeqQlen", (FB,)), Ref("batchIdx"))),
    ("call actualSeqQlen(fBaseParams)", Select(Call("actualSeqQlen", (FB,)), Ref("batchIdx"))),
    ("bare actualSeqQlen ref", Select(Ref("actualSeqQlen"), Const(0))),
    ("qValue[0]", Select(Q, Const(0))),
    ("parseInfo[i]", Select(PARSE, Ref("i"))),
    ("parseInfo[i][BEGIN]", Select(Select(PARSE, Ref("i")), Const(0))),
    ("invalidS1Array[j]", Select(INV, Ref("j"))),
    ("field chain begin", Call("begin", (Call("actualSeqQlen", (FB,)),))),
    ("field:begin member", Call("begin", (Call("field:actualSeqQlen", (FB,)),))),
]

for label, expr in cases:
    co = _container_of(expr if not isinstance(expr, Select) else expr.array)
    dp = dotted_path(expr if not isinstance(expr, Select) else expr.array)
    print(f"{label:30} _container_of={co!r:35} dotted_path={dp!r}")
