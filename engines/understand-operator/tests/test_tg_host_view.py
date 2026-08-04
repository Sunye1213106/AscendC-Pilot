# -*- coding: utf-8 -*-
"""TG host view is a KB projection, not a second authority."""

from __future__ import annotations

from pathlib import Path

import yaml


class _Write:
    def __init__(self, path, function, file, line, rhs, guards=None, via=""):
        self.path = path
        self.function = function
        self.file = file
        self.line = line
        self.rhs = rhs
        self._guards = guards or []
        self.via = via

    def guards(self):
        return list(self._guards)


class _HostIR:
    def __init__(self, writes):
        self.writes = writes

    def expand_callee_writers(self):
        return list(self.writes)


def test_export_tg_host_view_stamps_fingerprint(tmp_path: Path):
    from uo_init.host_codemap import (
        CODEMAP_YAML,
        TG_HOST_VIEW_YAML,
        CodemapQuery,
        export_tg_host_view,
    )
    from uo_init.kb_index import HOST_VIEW_TABLES, upsert_host_view_tables
    import sqlite3

    uo = tmp_path / "uo"
    (uo / "ir").mkdir(parents=True)
    (uo / "indexes").mkdir(parents=True)

    # Minimal kb_graph so upsert has a target.
    db = uo / "indexes" / "kb_graph.sqlite"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(
        "INSERT INTO meta(key,value) VALUES(?,?)",
        ("graph_fingerprint", "fp-abc"),
    )
    conn.executescript(HOST_VIEW_TABLES)
    conn.commit()
    conn.close()

    host_ir = _HostIR([
        _Write(
            "fBaseParams.splitAxis", "SetSplitAxis", "x.cpp", 10,
            "0", guards=["queryType == ge::DT_FLOAT && d > 256"],
        ),
        _Write(
            "fBaseParams.deterSparseType", "GetDeter", "y.cpp", 20,
            "1", guards=["sparseMode == PREFIX"],
        ),
    ])
    derive = [{
        "name": "DeterType",
        "exactness": "overapproximated",
        "status": "partial",
        "var_roots": {"VAR_SESSION_DETERMINISTIC": "SESSION_OPTION"},
        "domain": [0, 1, 2],
    }]

    out = export_tg_host_view(
        host_ir,
        uo,
        derive_fields=derive,
        graph_fingerprint="fp-abc",
        source_revision="rev1",
    )
    assert out["ok"] is True
    assert out["graph_fingerprint"] == "fp-abc"

    view = yaml.safe_load((uo / TG_HOST_VIEW_YAML).read_text(encoding="utf-8"))
    assert view["schema"] == "tg-host-view/v1"
    assert view["source"]["authority"] == "uo/ir/operator_graph.yaml"
    assert view["source"]["graph_fingerprint"] == "fp-abc"
    assert view["source"]["role"] == "tg_host_projection"
    # Alias must NOT be written (single authority = tg_host_view + kb_graph).
    assert not (uo / CODEMAP_YAML).is_file()
    assert out.get("alias_yaml") in ("", None)

    upsert = upsert_host_view_tables(uo, view)
    assert upsert["ok"] is True
    assert upsert["host_view_fingerprint"] == "fp-abc"

    q = CodemapQuery(uo)
    assert q._mode == "kb"
    preds = q.predicates(feature_hint="dtype_is_fp32")
    assert any("DT_FLOAT" in (p.get("condition") or "") for p in preds)
    reads = q.reads_of("DeterType")
    assert any(r.get("root") == "SESSION_OPTION" for r in reads)


def test_load_tg_host_view_without_probe_cache(tmp_path: Path):
    """export/load path must reuse durable tg_host_view without fag_bundle.pkl."""
    from uo_init.host_codemap import load_tg_host_view

    uo = tmp_path / ".ascendc-pilot" / "uo"
    (uo / "ir").mkdir(parents=True)
    doc = {
        "schema": "tg-host-view/v1",
        "source": {
            "graph_fingerprint": "fp-x",
            "authority": "uo/ir/operator_graph.yaml",
            "role": "tg_host_projection",
            "generated_by": "export_tg_host_view",
        },
        "fields": [{"name": "SplitAxis", "kind": "key_dim", "writers": [], "reads": []}],
        "predicates": [],
        "declared_keys": {},
        "platform_gates": [],
    }
    (uo / "ir" / "tg_host_view.yaml").write_text(
        yaml.safe_dump(doc, sort_keys=False), encoding="utf-8",
    )
    loaded = load_tg_host_view(uo)
    assert loaded.get("source", {}).get("graph_fingerprint") == "fp-x"
    assert any(f.get("name") == "SplitAxis" for f in (loaded.get("fields") or []))
