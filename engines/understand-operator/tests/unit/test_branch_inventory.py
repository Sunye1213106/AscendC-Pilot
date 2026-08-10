# -*- coding: utf-8 -*-
from uo_init.branch_inventory import (
    UNIVERSE,
    inventory_paths,
    inventory_text,
    label_universe,
)


def test_baseline_host_denominators(fag_dir):
    files = {
        "tiling.cpp": fag_dir / "op_host" / "flash_attention_score_grad_tiling.cpp",
        "normal": fag_dir
        / "op_host"
        / "arch35"
        / "flash_attention_score_grad_tiling_normal_regbase.cpp",
        "common": fag_dir
        / "op_host"
        / "arch35"
        / "flash_attention_score_grad_tiling_common_regbase.cpp",
    }
    # Text inventory under-counts vs clang (multi-line / macros). Lock file
    # sizes and that inventory is non-trivial; clang totals are integration-only.
    n_tiling = len(inventory_text(files["tiling.cpp"]).nodes)
    n_normal = len(inventory_text(files["normal"]).nodes)
    n_common = len(inventory_text(files["common"]).nodes)
    assert n_tiling >= 30
    assert n_normal >= 80
    assert n_common >= 80
    assert files["tiling.cpp"].stat().st_size > 1000



def test_stable_id_deterministic(fag_dir):
    p = fag_dir / "op_host" / "flash_attention_score_grad_tiling.cpp"
    a = inventory_text(p).ids()
    b = inventory_text(p).ids()
    assert a == b


def test_no_sink_pruning(fag_dir):
    # apt entry + any kernel file with INVOKE
    apt = fag_dir / "op_kernel" / "flash_attention_score_grad_apt.cpp"
    inv = inventory_text(apt)
    # apt has if constexpr — must retain control nodes; never pruned by sink
    assert len(inv.nodes) >= 1
    # scan arch35 for INVOKE if present
    from pathlib import Path

    found = False
    for p in (fag_dir / "op_kernel" / "arch35").rglob("*.h"):
        text = p.read_text(encoding="utf-8", errors="replace")
        if "INVOKE_FAG" in text:
            inv2 = inventory_text(p)
            assert any(n.kind == "macro_dispatch" for n in inv2.nodes)
            found = True
            break
    if not found:
        # still OK: apt nodes retained
        assert any(n.kind.startswith("if") for n in inv.nodes)


def test_universe_labels_closed_set():
    from uo_init.branch_inventory import ControlNode

    n = ControlNode(id="a", kind="if", file="f", line=1, snippet="if (x)")
    label_universe(n)
    assert n.universe in UNIVERSE
