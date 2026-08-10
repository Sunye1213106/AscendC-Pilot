# -*- coding: utf-8 -*-

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class _Case:
    ident: str

    def normalised(self):
        return self


class _Workspace:
    def __init__(self, root: Path):
        self.root = root
        self.state = root / "state"
        self.artifacts = root / "artifacts"

    def ensure(self):
        self.state.mkdir(parents=True, exist_ok=True)
        self.artifacts.mkdir(parents=True, exist_ok=True)
        return self

    def report(self, name: str) -> Path:
        self.state.mkdir(parents=True, exist_ok=True)
        return self.state / name


class _SurrogateThatLovesEverything:
    def predict(self, frame):
        return [1] * len(frame), [0] * len(frame)


def test_kb_guided_pool_does_not_let_mutation_displace_direct_construct(
    tmp_path, monkeypatch
):
    from testcase_agent.closure import construct
    from testcase_agent.closure import generate as G
    from testcase_agent.closure import workspace as W

    ws = _Workspace(tmp_path).ensure()
    rows = [
        {"key": k, "distance": 1, "differing_dims": "DTemplateNum"}
        for k in range(100, 110)
    ]

    monkeypatch.setattr(G, "_open_target_rows", lambda *a, **k: rows)
    monkeypatch.setattr(W, "decode", lambda key: {"K": str(key)})
    monkeypatch.setattr(construct, "build", lambda inst, seed=0: [_Case(inst["K"])])
    monkeypatch.setattr(G, "_describe_case", lambda case: {"ident": case.ident})

    cases, frame = G.kb_guided_pool(
        4,
        seed=7,
        witnesses=[_Case("accepted-witness")],
        open_keys=[r["key"] for r in rows],
        surrogate=_SurrogateThatLovesEverything(),
        control=False,
        ws=ws,
    )

    assert len(cases) == 4
    assert set(frame["_generation"]) == {"kb_construct"}
    assert all(int(v) != 0 for v in frame["_target_key"])


def test_kb_guided_pool_does_not_fill_with_exploration_by_default(tmp_path, monkeypatch):
    from testcase_agent.closure import construct
    from testcase_agent.closure import generate as G
    from testcase_agent.closure import workspace as W

    ws = _Workspace(tmp_path).ensure()
    rows = [{"key": 101, "distance": 1, "differing_dims": "IsRope"}]

    monkeypatch.setattr(G, "_open_target_rows", lambda *a, **k: rows)
    monkeypatch.setattr(W, "decode", lambda key: {"K": str(key)})
    monkeypatch.setattr(construct, "build", lambda inst, seed=0: [_Case(inst["K"])])
    monkeypatch.setattr(G, "_describe_case", lambda case: {"ident": case.ident})

    cases, frame = G.kb_guided_pool(
        4,
        seed=7,
        witnesses=[_Case("accepted-witness")],
        open_keys=[101],
        control=False,
        ws=ws,
    )

    assert len(cases) == 1
    assert list(frame["_generation"]) == ["kb_construct"]


def test_residual_returns_limited_rows_but_writes_full_csv(tmp_path, monkeypatch):
    from testcase_agent.closure import ledger
    from testcase_agent.closure import residual
    from testcase_agent.closure import workspace as W

    ws = _Workspace(tmp_path).ensure()
    monkeypatch.setattr(ledger, "load_R", lambda _ws=None: {1})
    monkeypatch.setattr(ledger, "load_E", lambda _ws=None: set())
    monkeypatch.setattr(ledger, "declared", lambda: {1, 2, 3, 4})
    monkeypatch.setattr(W, "dim_names", lambda: ["A"])
    monkeypatch.setattr(W, "decode", lambda key: {"A": str(key)})

    out = residual.analyse(ws, max_rows=1)

    assert out["row_count"] == 3
    assert out["rows_truncated"] is True
    assert len(out["rows"]) == 1
    lines = (ws.state / "residual.csv").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4  # header + all three open keys
