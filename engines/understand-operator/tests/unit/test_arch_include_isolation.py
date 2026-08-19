# -*- coding: utf-8 -*-
"""arch-920r1 identity: extras -I never point at another arch* folder."""
from __future__ import annotations

from pathlib import Path

from uo_init.build_context import BuildContext
from uo_init.include_heal import (
    HealReport,
    extras_summary_path,
    find_include_dir,
    load_extras_payload,
    reset_index_cache,
    save_extras,
)


def _ctx(tmp_path: Path, *, arch_dir: str = "arch-920r1") -> BuildContext:
    cann = tmp_path / "cann"
    ops = tmp_path / "ops"
    op = ops / "mc2" / "widget"
    op.mkdir(parents=True)
    (op / "op_host").mkdir()
    (op / "op_kernel").mkdir()
    return BuildContext.load(
        cann_root=str(cann),
        ops_root=str(ops),
        op_dir=str(op),
        arch_dir=arch_dir,
        apply_saved_extras=False,
    )


def test_add_include_allows_cousin_rejects_other_arch_root(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    cousin = Path(ctx.op_dir) / "op_kernel" / "arch35"
    cousin.mkdir(parents=True)
    foreign = Path(ctx.op_dir) / "op_kernel" / "arch22"
    foreign.mkdir(parents=True)
    own = Path(ctx.op_dir) / "op_kernel" / "arch-920r1"
    own.mkdir(parents=True)
    extra = tmp_path / "neutral_inc"
    extra.mkdir()
    joined = " ".join(p.replace("\\", "/") for p in ctx.kernel_includes())
    assert "arch35" in joined
    assert ctx.add_include(str(foreign), side="kernel") is False
    assert not any("arch22" in p.replace("\\", "/") for p in ctx.extra_kernel_includes)
    assert ctx.add_include(str(extra), side="kernel") is True


def test_heal_prefers_current_arch_same_basename(tmp_path: Path) -> None:
    reset_index_cache()
    ctx = _ctx(tmp_path)
    own = Path(ctx.op_dir) / "op_kernel" / "arch-920r1" / "foo.h"
    foreign = Path(ctx.op_dir) / "op_kernel" / "arch35" / "foo.h"
    own.parent.mkdir(parents=True)
    foreign.parent.mkdir(parents=True)
    own.write_text("struct Own {};\n", encoding="utf-8")
    foreign.write_text("struct Foreign {};\n", encoding="utf-8")
    hit = find_include_dir(ctx, "foo.h", side="kernel")
    assert hit is not None
    assert "arch-920r1" in hit.found.replace("\\", "/")
    assert "arch35" not in hit.include_dir.replace("\\", "/")


def test_heal_bare_header_only_in_cousin_arch_resolves(tmp_path: Path) -> None:
    reset_index_cache()
    ctx = _ctx(tmp_path)
    cousin = Path(ctx.op_dir) / "op_kernel" / "arch35" / "only_there.h"
    cousin.parent.mkdir(parents=True)
    cousin.write_text("struct Only {};\n", encoding="utf-8")
    hit = find_include_dir(ctx, "only_there.h", side="kernel")
    assert hit is not None
    assert "arch35" in hit.found.replace("\\", "/")


def test_heal_bare_header_only_in_arch22_is_unresolved(tmp_path: Path) -> None:
    reset_index_cache()
    ctx = _ctx(tmp_path)
    foreign = Path(ctx.op_dir) / "op_kernel" / "arch22" / "only_there.h"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("struct Only {};\n", encoding="utf-8")
    assert find_include_dir(ctx, "only_there.h", side="kernel") is None


def test_heal_explicit_other_arch_spelling_uses_neutral_root(tmp_path: Path) -> None:
    reset_index_cache()
    ctx = _ctx(tmp_path)
    foreign = Path(ctx.op_dir) / "op_kernel" / "arch35" / "shared.h"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("struct Shared {};\n", encoding="utf-8")
    hit = find_include_dir(ctx, "arch35/shared.h", side="kernel")
    assert hit is not None
    include_dir = hit.include_dir.replace("\\", "/").rstrip("/")
    assert include_dir.endswith("/op_kernel")
    assert not include_dir.endswith("/arch35")


def test_save_extras_keeps_cousin_strips_other_arch_include_roots(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    cousin = Path(ctx.op_dir) / "op_kernel" / "arch35"
    cousin.mkdir(parents=True)
    foreign = Path(ctx.op_dir) / "op_kernel" / "arch22"
    foreign.mkdir(parents=True)
    extra = tmp_path / "ok_inc"
    extra.mkdir()
    ctx.extra_kernel_includes.append(str(cousin).replace("\\", "/"))
    ctx.extra_kernel_includes.append(str(foreign).replace("\\", "/"))
    ctx.extra_kernel_includes.append(str(extra).replace("\\", "/"))
    path = save_extras(ctx, HealReport(enabled=True))
    assert path is not None
    payload = load_extras_payload(ctx.op_dir, ctx.arch_dir)
    kernel = " ".join(payload.get("kernel") or []).replace("\\", "/")
    assert "arch35" in kernel
    assert "arch22" not in kernel
    assert extras_summary_path(ctx.op_dir, "arch-920r1").is_file()
    assert not extras_summary_path(ctx.op_dir, "arch35").is_file()
