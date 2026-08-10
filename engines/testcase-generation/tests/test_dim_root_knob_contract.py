# -*- coding: utf-8 -*-
"""dim_to_roots / root_to_knobs contract and mutate_in_cone restriction."""

from __future__ import annotations

from dataclasses import dataclass


def test_adapter_pack_emits_dim_to_roots_and_root_to_knobs():
    from uo_init.adapter_pack import build_feature_bindings

    derivation = {
        "fields": [
            {
                "name": "SplitAxis",
                "root_vars": ["INPUT_QUERY_SHAPE", "ATTR_LAYOUT"],
            }
        ]
    }
    # Without live knob schema the builder still separates the two tables.
    doc = build_feature_bindings(derivation)
    assert "dim_to_roots" in doc
    assert doc["dim_to_roots"]["SplitAxis"] == ["INPUT_QUERY_SHAPE", "ATTR_LAYOUT"]
    # root_to_knobs keys are roots, never the dimension name as sole inverted map.
    assert "SplitAxis" not in doc["root_to_knobs"] or not any(
        str(v).startswith("INPUT_") for v in (doc["root_to_knobs"].get("SplitAxis") or [])
    )


def test_knobs_for_field_uses_root_table(monkeypatch):
    from testcase_agent.closure import generate as G

    monkeypatch.setattr(
        G,
        "_feature_bindings_tables",
        lambda: (
            {"SplitAxis": ["INPUT_QUERY_SHAPE", "ATTR_LAYOUT"]},
            {
                "INPUT_QUERY_SHAPE": ["b", "s1", "d"],
                "ATTR_LAYOUT": ["layout"],
            },
        ),
    )

    class _Q:
        def __init__(self, _root):
            pass

        def reads_of(self, field):
            assert field == "SplitAxis"
            return [{"var": "q", "root": "INPUT_QUERY_SHAPE"}]

    monkeypatch.setattr("uo_init.host_codemap.CodemapQuery", _Q)
    knobs = G.knobs_for_field("SplitAxis", uo_root="/tmp/fake-uo")
    assert knobs == ["b", "d", "layout", "s1"] or set(knobs) == {"b", "s1", "d", "layout"}


def test_mutate_in_cone_only_touches_allowed(monkeypatch):
    from testcase_agent.closure import generate as G
    import random

    @dataclass
    class _Case:
        b: int = 1
        s1: int = 128
        layout: int = 0
        noise: int = 9

        def normalised(self):
            return self

    monkeypatch.setattr(
        G, "knobs_for_field", lambda field, uo_root=None: ["b", "s1", "layout"]
    )
    monkeypatch.setattr(
        G,
        "_grid",
        lambda: {
            "b": [1, 2, 4],
            "s1": [64, 128, 256],
            "layout": [0, 1],
            "noise": [0, 1, 2, 3],
        },
    )
    monkeypatch.setattr(
        G,
        "_mutable",
        lambda grid: [(n, list(v)) for n, v in grid.items()],
    )

    base = _Case()
    # noise is outside the cone and must remain unchanged; allowed knobs may change.
    changed = False
    for seed in range(20):
        o = G.mutate_in_cone(base, "SplitAxis", random.Random(seed), k=2, uo_root="/tmp/x")
        assert o.noise == 9
        if (o.b, o.s1, o.layout) != (1, 128, 0):
            changed = True
            break
    assert changed


def test_legacy_root_to_knobs_inversion(monkeypatch):
    from testcase_agent.closure import generate as G

    monkeypatch.setattr(
        "replay.package_data.load_yaml",
        lambda name, refresh=False: {
            # Legacy inverted shape: dim → roots stored under root_to_knobs.
            "root_to_knobs": {
                "SplitAxis": ["INPUT_QUERY_SHAPE", "ATTR_LAYOUT"],
            },
        },
    )

    class _Sem:
        def knob_schema(self):
            return {"b": {}, "s1": {}, "layout": {}}

    class _I:
        SEMANTICS = _Sem()

    monkeypatch.setattr(G.W, "replay_inputs", lambda: _I())
    dim_to_roots, root_to_knobs = G._feature_bindings_tables()
    assert dim_to_roots["SplitAxis"] == ["INPUT_QUERY_SHAPE", "ATTR_LAYOUT"]
    # Recovered root→knob edges from name overlap where possible.
    assert "layout" in root_to_knobs.get("ATTR_LAYOUT", [])
