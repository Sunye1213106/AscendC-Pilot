# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from uo_init.clang_walk import BaseDecl, CallSite
from uo_init.host_ir import FuncSummary, HostIR
from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.op_spec import discover
from uo_init.passes.symbol_roles import (
    ROLE_HOST_TILING_ENTRY,
    ROLE_HOST_TILING_HELPER,
    ROLE_KERNEL_ENTRY,
    ROLE_KERNEL_SEMANTIC_ROOT,
    ROLE_OP_DEFINITION,
    project_symbol_roles,
)
from uo_init import scope_scan as ss


def _write(root: Path, rel: str, text: str = "") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_file_role_is_layout_not_set_tiling_key_identity(tmp_path: Path) -> None:
    root = tmp_path / "attention"
    _write(root, "widget/op_host/regbase_common.cpp", "void Pack() { SetTilingKey(k); }\n")
    _write(root, "widget/op_host/widget_def.cpp", "class Widget : public OpDef {};\n")
    _write(root, "widget/op_kernel/widget.cpp", "__global__ void widget() {}\n")
    scope = ss.scan(root / "widget", arch_dir="arch35")
    common = next(f for f in scope.files if f.path.name == "regbase_common.cpp")
    assert common.role == ss.ROLE_HOST_OTHER
    assert ss.HINT_TILING not in common.role_hints
    spec = discover(root / "widget", arch_dir="arch35")
    assert any(p.name == "regbase_common.cpp" for p in spec.host_targets)
    assert spec.op_name == "Widget"
    assert not spec.display_name_hint


def test_op_name_from_filename_is_display_hint_only(tmp_path: Path) -> None:
    root = tmp_path / "attention"
    _write(root, "widget/op_host/widget_def.cpp", "// no OpDef class here\n")
    _write(root, "widget/op_kernel/widget.cpp", "__global__ void widget() {}\n")
    spec = discover(root / "widget", arch_dir="arch35")
    assert spec.display_name_hint == "Widget"
    assert any(str(a).startswith("display_name_hint:") for a in spec.ambiguities)


def test_symbol_roles_hang_on_functions_not_the_file() -> None:
    cm = CodeMap(op_name="Widget", architecture="arch35")
    file_ent = cm.upsert(
        EntityKind.FILE,
        "op_host/regbase_common.cpp",
        attrs={"role": "host", "provenance": "source_inventory"},
        file="op_host/regbase_common.cpp",
        line=1,
        status="confirmed",
    )
    host = HostIR(
        call_sites=[
            CallSite(
                caller="DoOpTiling",
                callee="SetTilingKey",
                file="op_host/regbase_common.cpp",
                line=40,
            ),
            CallSite(
                caller="DoOpTiling",
                callee="FillBase",
                file="op_host/regbase_common.cpp",
                line=20,
            ),
        ],
        summaries={
            "DoOpTiling": FuncSummary(
                name="DoOpTiling",
                file="op_host/regbase_common.cpp",
                line=10,
                calls=[("FillBase", ()), ("SetTilingKey", ("k",))],
            ),
            "FillBase": FuncSummary(
                name="FillBase",
                file="op_host/regbase_common.cpp",
                line=4,
            ),
        },
        base_decls=[
            BaseDecl(
                derived_name="Widget",
                base_name="OpDef",
                file="op_host/widget_def.cpp",
                line=1,
            )
        ],
        backend="clang",
    )
    kernel_ir = SimpleNamespace(
        functions={
            "widget": {
                "file": "op_kernel/widget.cpp",
                "line": 3,
                "calls": ["Process"],
            },
            "Process": {"file": "op_kernel/widget.cpp", "line": 10, "calls": []},
        }
    )
    cm.upsert(
        EntityKind.KERNEL,
        "widget",
        attrs={"provenance": "source_kernel_signature"},
        file="op_kernel/widget.cpp",
        line=3,
        status="confirmed",
    )
    project_symbol_roles(cm, host_ir=host, kernel_ir=kernel_ir)

    tiling = cm.by_name("DoOpTiling", kind=EntityKind.FUNCTION)[0]
    helper = cm.by_name("FillBase", kind=EntityKind.FUNCTION)[0]
    opdef = cm.by_name("Widget", kind=EntityKind.TYPE)[0]
    kernel = cm.by_name("widget", kind=EntityKind.KERNEL)[0]
    process = cm.by_name("Process", kind=EntityKind.FUNCTION)[0]
    assert ROLE_HOST_TILING_ENTRY in tiling.attrs["symbol_roles"]
    assert ROLE_HOST_TILING_HELPER in helper.attrs["symbol_roles"]
    assert ROLE_OP_DEFINITION in opdef.attrs["symbol_roles"]
    assert ROLE_KERNEL_ENTRY in kernel.attrs["symbol_roles"]
    assert ROLE_KERNEL_SEMANTIC_ROOT in process.attrs["symbol_roles"]
    assert file_ent.attrs.get("role") == "host"
    assert file_ent.attrs["file_role_summary"]["contains"] == sorted(
        {ROLE_HOST_TILING_ENTRY, ROLE_HOST_TILING_HELPER}
    )
    assert file_ent.attrs.get("symbol_roles") in (None, [])
