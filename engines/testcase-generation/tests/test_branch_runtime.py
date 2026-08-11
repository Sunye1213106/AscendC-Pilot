# -*- coding: utf-8 -*-
"""Generic L3 branch runtime: only real same-key observations settle debt."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from testcase_agent.closure import branch_runtime as BR
from testcase_agent.closure import obligations as OBL
from testcase_agent.closure import search_round
from testcase_agent.closure.workspace import Workspace


@dataclass
class _Case:
    value: int = 0

    def normalised(self) -> "_Case":
        return self


class _Runner:
    def __init__(self, cache: Path) -> None:
        self.cache = cache
        self.actual_key = 2
        self.written: list[Path] = []

    def run(self, cases, *, tag: str, with_log: bool, check: bool):
        del with_log, check
        self.cache.mkdir(parents=True, exist_ok=True)
        (self.cache / f"{tag}_log.txt").write_text("", encoding="utf-8")
        return {
            cid: SimpleNamespace(
                ok=True,
                key=self.actual_key,
                diag={"foo": 1},
                reject="",
            )
            for cid in cases
        }

    def write_wide(self, path: Path, cases, results) -> None:
        del cases, results
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("case_id\n", encoding="utf-8")
        self.written.append(path)


def _inventory() -> dict:
    return {
        "schema": "tg-obligation-inventory/v1",
        "summary": {},
        "obligations": [
            {
                "id": "TD::1::foo::one",
                "type": "TILINGDATA_VALUE_CLASS",
                "tiling_key": 1,
                "field": "foo",
                "predicate": "foo == 1",
                "status": OBL.UNRESOLVED,
            },
            {
                "id": "KB::1::b1::true",
                "type": "KERNEL_BRANCH_OUTCOME",
                "tiling_key": 1,
                "branch_id": "b1",
                "outcome": True,
                "status": OBL.UNRESOLVED,
            },
        ],
    }


def _patch_runtime(monkeypatch, tmp_path: Path):
    ws = Workspace(root=tmp_path, artifacts=tmp_path / "artifacts", state=tmp_path / "closure").ensure()
    inv = _inventory()
    runner = _Runner(tmp_path / "replay")

    monkeypatch.setattr(BR, "precheck", lambda _ws: {"ok": True, "reason": "READY"})
    monkeypatch.setattr(BR, "ensure_inventory", lambda _ws=None: inv)
    monkeypatch.setattr(BR, "build_candidates", lambda *a, **k: [_Case(1)])
    monkeypatch.setattr(BR.W, "decode", lambda key: {"K": str(key)})
    monkeypatch.setattr(BR.W, "replay_runner", lambda: runner)
    monkeypatch.setattr(BR, "_load_decoder", lambda: (None, "decoder_missing"))
    monkeypatch.setattr(
        BR.KD,
        "load_kernel_branches",
        lambda ws=None: [
            {
                "id": "b1",
                "condition": "foo == 1",
                "fields": ["foo"],
            }
        ],
    )
    return ws, inv, runner


def test_off_key_replay_never_settles_runtime_obligations(monkeypatch, tmp_path: Path) -> None:
    ws, inv, runner = _patch_runtime(monkeypatch, tmp_path)
    runner.actual_key = 2  # target is key=1

    result = BR.run_round(ws, budget=4, seed=0)

    assert result["progress"]["on_key"] == 0
    assert result["progress"]["new_obligations"] == 0
    assert result["progress"]["open_obligations"] == 2
    assert all(row["status"] == OBL.UNRESOLVED for row in inv["obligations"])
    assert not runner.written


def test_same_key_runtime_state_covers_td_and_branch(monkeypatch, tmp_path: Path) -> None:
    ws, inv, runner = _patch_runtime(monkeypatch, tmp_path)
    runner.actual_key = 1

    result = BR.run_round(ws, budget=4, seed=0)

    assert result["progress"]["on_key"] == 1
    assert result["progress"]["new_obligations"] == 2
    assert result["progress"]["open_obligations"] == 0
    assert result["route_hint"] == "GAP_ZERO"
    assert {row["status"] for row in inv["obligations"]} == {OBL.COVERED}
    assert runner.written and runner.written[0].name.startswith("branch_round_")


def test_search_round_dispatches_l3_without_running_key_search(monkeypatch, tmp_path: Path) -> None:
    ws = Workspace(root=tmp_path, artifacts=tmp_path / "artifacts", state=tmp_path / "closure").ensure()
    sentinel = {
        "ok": True,
        "round_dir": str(tmp_path / "branch"),
        "progress": {"new_R": 0, "new_obligations": 1},
        "route_hint": "SEARCH_PROGRESS",
    }
    monkeypatch.setattr(BR, "is_branch_mode", lambda _ws=None: True)
    monkeypatch.setattr(BR, "run_round", lambda *a, **k: sentinel)

    assert search_round.run_round(ws, budget=3, seed=7) is sentinel
