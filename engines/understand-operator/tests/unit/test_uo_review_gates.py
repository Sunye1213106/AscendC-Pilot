# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))


def test_reap_isolate_child_kills_then_waits() -> None:
    from uo_init.extract_bundle import _reap_isolate_child
    events: list[str] = []

    class _Proc:
        def kill(self) -> None:
            events.append("kill")

        def wait(self, timeout=None) -> int:
            events.append(f"wait:{timeout}")
            return 0

    _reap_isolate_child(_Proc(), timeout=2.5)
    assert events == ["kill", "wait:2.5"]


def test_hold_open_argv_are_diverse() -> None:
    from uo_query_battery import hold_open_argv

    argv = hold_open_argv(
        [
            "Dim=IsTnd",
            "IsTnd=1",
            "LocalTensor",
            "s1Inner",
            "op_host/h.cpp:10",
        ],
        n=12,
    )
    assert len(argv) == 12
    assert len(set(argv)) > 1
    assert "LocalTensor" in argv
    assert any(item != "LocalTensor" for item in argv)


def test_process_tree_rss_fields() -> None:
    from uo_init_perf_gate import ProcessTreeRssMonitor

    mon = ProcessTreeRssMonitor(interval_s=0.05)
    mon.mark_stage()
    snap = mon.snapshot()
    assert "stage_boundary_rss_mb" in snap
    assert "sampled_peak_rss_mb" in snap
    assert snap["sampled_peak_rss_mb"] >= 0
    assert snap["stage_boundary_rss_mb"] >= 0


def test_probe_oracle_empty_cover_with_nearby_is_usable() -> None:
    from _probe_fag_query_quality import judge

    out = judge(
        {"expect": "cover_combo"},
        {
            "ok": True,
            "shape": "cover",
            "matching_block_count": 0,
            "coverage": {
                "completeness": "coverage_checked",
                "nearby": [{"dropped": "S2TemplateNum", "values": ["0", "128"]}],
            },
            "nearby": [{"dropped": "S2TemplateNum", "values": ["0", "128"]}],
        },
        400,
    )
    assert out["grade"] == "usable"


def test_probe_oracle_s1inner_honest_empty_readers() -> None:
    from _probe_fag_query_quality import judge

    out = judge(
        {
            "expect": "name_located",
            "need_writers": True,
            "honest_empty_readers": True,
        },
        {
            "ok": True,
            "shape": "name",
            "cards": [
                {
                    "kind": "FIELD",
                    "name": "s1Inner",
                    "file": "op_kernel/t.h",
                    "line": 197,
                    "snippet": "uint32_t s1Inner;",
                    "extras": {
                        "writers": [{"name": "GetTiling", "file": "host.cpp", "line": 491}],
                        "readers": [],
                    },
                }
            ],
        },
        800,
    )
    assert out["grade"] == "usable"
    assert any("honest" in n.lower() or "empty" in n.lower() for n in out.get("notes") or [])
