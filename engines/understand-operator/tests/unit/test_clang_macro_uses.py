# -*- coding: utf-8 -*-
"""Clang MACRO_INSTANTIATION uses bind to already-inventoried operator MACROs."""
from __future__ import annotations

from uo_init.clang_walk import FuncRecord, _Walker
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.ir.relation import RelationKind


class _Kind:
    def __init__(self, name: str):
        self.name = name


class _File:
    def __init__(self, name: str):
        self.name = name


class _Loc:
    def __init__(self, name: str, line: int):
        self.file = _File(name)
        self.line = line


class _Cursor:
    def __init__(
        self,
        kind: str,
        spelling: str = "",
        file: str = "op_kernel/k.cpp",
        line: int = 1,
        parent=None,
        children=(),
        definition: bool = False,
    ):
        self.kind = _Kind(kind)
        self.spelling = spelling
        self.location = _Loc(file, line)
        self.semantic_parent = parent
        self.lexical_parent = parent
        self._children = list(children)
        self._definition = definition

    def get_children(self):
        return list(self._children)

    def is_definition(self) -> bool:
        return self._definition


def test_walker_records_macro_instantiation_parent() -> None:
    file = "op_kernel/k.cpp"
    fn = _Cursor("FUNCTION_DECL", "Process", file, 10, definition=True)
    use = _Cursor(
        "MACRO_INSTANTIATION",
        "COMMON_RUN_PARAM",
        file,
        20,
        parent=fn,
    )
    walker = _Walker(needle="op_kernel", op_root="/workspace/op")
    walker.walk(use, [], "")
    assert len(walker.macro_uses) == 1
    recorded = walker.macro_uses[0]
    assert recorded.name == "COMMON_RUN_PARAM"
    assert recorded.file.replace("\\", "/").endswith("op_kernel/k.cpp")
    assert recorded.line == 20
    assert recorded.parent_name == "Process"
    assert recorded.parent_kind == "FUNCTION_DECL"


def test_bind_expands_existing_macro_to_enclosing_function() -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    macro = cm.upsert(
        EntityKind.MACRO,
        "COMMON_RUN_PARAM",
        eid="SRCMACRO::op_kernel/k.cpp::COMMON_RUN_PARAM",
        attrs={"provenance": "source_define"},
        file="op_kernel/k.cpp",
        line=1,
        status="confirmed",
    )
    fn = cm.upsert(
        EntityKind.FUNCTION,
        "Process",
        eid="SRCKDEFV2::op_kernel/k.cpp::10::::Process",
        attrs={"provenance": "source_kernel_definition_v2"},
        file="op_kernel/k.cpp",
        line=10,
        line_end=40,
        status="confirmed",
    )

    class _IR:
        macro_uses = [
            {
                "name": "COMMON_RUN_PARAM",
                "file": "op_kernel/k.cpp",
                "line": 20,
                "parent_name": "Process",
                "parent_kind": "FUNCTION_DECL",
            }
        ]

    from uo_init.passes.clang_macro_uses import bind_clang_macro_uses

    bind_clang_macro_uses(cm, _IR())
    edges = [
        rel
        for rel in cm.relations.values()
        if rel.kind_name() == RelationKind.EXPANDS_TO.value
        and rel.src == macro.id
        and rel.dst == fn.id
    ]
    assert edges
    assert edges[0].attrs.get("provenance") == "source_clang_macro_instantiation"


def test_bind_does_not_mint_cann_macros_without_operator_entity() -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")

    class _IR:
        macro_uses = [
            {
                "name": "ASCENDC_TPL_KERNEL",
                "file": "op_kernel/k.cpp",
                "line": 8,
                "parent_name": "Process",
                "parent_kind": "FUNCTION_DECL",
            }
        ]

    from uo_init.passes.clang_macro_uses import bind_clang_macro_uses

    bind_clang_macro_uses(cm, _IR())
    assert not cm.by_name("ASCENDC_TPL_KERNEL", kind=EntityKind.MACRO)
    assert not cm.relations


def test_bind_empty_parent_expands_to_file() -> None:
    cm = CodeMap(op_name="toy", architecture="arch35")
    macro = cm.upsert(
        EntityKind.MACRO,
        "COMMON_RUN_PARAM",
        eid="SRCMACRO::op_kernel/k.cpp::COMMON_RUN_PARAM",
        attrs={"provenance": "source_define"},
        file="op_kernel/k.cpp",
        line=1,
        status="confirmed",
    )
    file_ent = cm.upsert(
        EntityKind.FILE,
        "op_kernel/k.cpp",
        eid="FILE::op_kernel/k.cpp",
        attrs={"provenance": "source_inventory"},
        file="op_kernel/k.cpp",
        line=1,
        status="confirmed",
    )

    class _IR:
        macro_uses = [
            {
                "name": "COMMON_RUN_PARAM",
                "file": "D:/src/op_kernel/arch35/../../../op_kernel/k.cpp",
                "line": 20,
                "parent_name": "",
                "parent_kind": "",
            }
        ]

    from uo_init.passes.clang_macro_uses import bind_clang_macro_uses

    bind_clang_macro_uses(cm, _IR())
    edges = [
        rel
        for rel in cm.relations.values()
        if rel.kind_name() == RelationKind.EXPANDS_TO.value
        and rel.src == macro.id
        and rel.dst == file_ent.id
    ]
    assert edges


def test_walker_attaches_tu_instantiation_to_function_extent() -> None:
    file = "op_kernel/k.cpp"
    walker = _Walker(needle="op_kernel", op_root="/workspace/op")
    walker.functions["Process"] = FuncRecord(name="Process", file=file, line=10, line_end=40)
    use = _Cursor("MACRO_INSTANTIATION", "GEN_TYPE_PARAM", file, 22)
    walker.walk(use, [], "")
    walker.attach_macro_parents()
    assert walker.macro_uses[0].parent_name == "Process"
    assert walker.macro_uses[0].parent_kind == "FUNCTION_DECL"
