# -*- coding: utf-8 -*-
"""Observation → lemma lead wiring (no pair-absence invention)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml


@pytest.fixture
def closure_ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from testcase_agent.closure import workspace as W

    root = tmp_path / "op"
    state = root / ".ascendc-pilot" / "arch0" / "tg" / "closure"
    artifacts = state / "artifacts"
    state.mkdir(parents=True)
    artifacts.mkdir(parents=True)

    class _WS:
        def __init__(self):
            self.root = root
            self.state = state
            self.artifacts = artifacts
            self.r_path = state / "R.txt"
            self.e_path = state / "excluded.txt"
            self.open_path = state / "open.txt"
            self.e_why_path = state / "excluded_why.csv"

        def ensure(self):
            self.state.mkdir(parents=True, exist_ok=True)
            self.artifacts.mkdir(parents=True, exist_ok=True)
            return self

        def report(self, name: str) -> Path:
            return self.state / name

    ws = _WS().ensure()
    monkeypatch.setattr(W, "default_workspace", lambda *a, **k: ws)
    monkeypatch.setenv("UO_ARCH", "arch0")
    monkeypatch.setenv("UO_OPERATOR", "_synthetic_toy")
    monkeypatch.setattr(W, "dim_names", lambda: ["SplitAxis", "IsTndSwizzle"])
    monkeypatch.setattr(
        W,
        "decode",
        lambda key: {
            "SplitAxis": str((int(key) >> 1) & 0xF),
            "IsTndSwizzle": str(int(key) & 1),
        },
    )
    monkeypatch.setattr(
        W,
        "decode_many",
        lambda keys: [W.decode(k) for k in keys],
    )
    return ws


def test_classify_rewrite_refuse_hit():
    from testcase_agent.closure import observations as OBS

    assert OBS.classify_row({
        "_target_key": 11, "tiling_key": 11, "ok": 1, "reject": "",
    }) == OBS.KIND_HIT
    assert OBS.classify_row({
        "_target_key": 11, "tiling_key": 0, "ok": 1,
        "_mismatch_dims": "SplitAxis|IsTndSwizzle", "reject": "",
    }) == OBS.KIND_REWRITE
    assert OBS.classify_row({
        "_target_key": 11, "tiling_key": -1, "ok": 0, "reject": "BAD_PARAM",
    }) == OBS.KIND_REFUSE
    assert OBS.classify_row({
        "_target_key": 11, "tiling_key": -1, "ok": 0, "reject": "HOST_CRASHED",
    }) is None


def test_build_leads_requires_observations(closure_ws, monkeypatch):
    from testcase_agent.closure import observations as OBS
    from testcase_agent.closure import ledger

    monkeypatch.setattr(ledger, "declared", lambda: {11, 12, 13})
    monkeypatch.setattr(ledger, "load_R", lambda _ws=None: set())
    monkeypatch.setattr(ledger, "load_E", lambda _ws=None: set())

    empty = OBS.build_leads(closure_ws, top=10, df=pd.DataFrame())
    assert empty["lead_count"] == 0
    assert empty["leads"] == []

    df = pd.DataFrame([
        {
            "_target_key": 11,
            "tiling_key": 0,
            "ok": 1,
            "reject": "",
            "_mismatch_dims": "SplitAxis|IsTndSwizzle",
            "_src": "round_0001_model_key_cases.csv",
        },
        {
            "_target_key": 11,
            "tiling_key": 0,
            "ok": 1,
            "reject": "",
            "_mismatch_dims": "SplitAxis|IsTndSwizzle",
            "_src": "round_0002_model_key_cases.csv",
        },
        {
            "_target_key": 12,
            "tiling_key": -1,
            "ok": 0,
            "reject": "PARAM_INVALID",
            "_mismatch_dims": "",
            "_src": "round_0002_model_key_cases.csv",
        },
        # Must not invent from HIT / crash.
        {
            "_target_key": 13,
            "tiling_key": 13,
            "ok": 1,
            "reject": "",
            "_mismatch_dims": "",
            "_src": "round_0003_model_key_cases.csv",
        },
        {
            "_target_key": 13,
            "tiling_key": -1,
            "ok": 0,
            "reject": "HOST_CRASHED:sigsegv",
            "_mismatch_dims": "",
            "_src": "round_0003_model_key_cases.csv",
        },
    ])
    doc = OBS.build_leads(closure_ws, top=10, df=df)
    assert doc["observation_count"] == 3
    assert doc["lead_count"] == 2
    kinds = {x["kind"] for x in doc["leads"]}
    assert kinds == {"rewrite", "refuse"}
    for lead in doc["leads"]:
        assert lead["source"] == "oracle_observation"
        assert lead["id"].startswith("OBS_LEAD_")
        assert lead["evidence_path"].endswith(f"{lead['id']}.yaml")
        assert lead["observations"]


def test_lemma_evidence_uses_lead_id(closure_ws, tmp_path: Path):
    from testcase_agent.closure import lemma_evidence as LE

    src = tmp_path / "op_host"
    src.mkdir()
    (src / "tiling.cpp").write_text(
        "void SetSplit() {\n  if (SplitAxis == 5) return;\n  splitAxis = 0;\n}\n",
        encoding="utf-8",
    )
    # Point workspace root source walk at tmp_path contents via collect's regex walker.
    closure_ws.root = tmp_path
    out = LE.collect("SplitAxis=5", ws=closure_ws, lead_id="OBS_LEAD_TEST01")
    assert out["ok"] is True
    assert Path(out["yaml"]).name == "OBS_LEAD_TEST01.yaml"
    assert out["evidence_path"].endswith("OBS_LEAD_TEST01.yaml")
    pack = yaml.safe_load(Path(out["yaml"]).read_text(encoding="utf-8"))
    assert pack["lead_id"] == "OBS_LEAD_TEST01"
