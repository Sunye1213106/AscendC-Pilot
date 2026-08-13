# -*- coding: utf-8 -*-
"""TG host view is a projection; production load is ``.uo`` only."""

from __future__ import annotations

from pathlib import Path

import yaml

from uo_init.ir.codemap import CodeMap
from uo_init.ir.entity import EntityKind
from uo_init.store.writer import write_codemap


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
        export_tg_host_view,
        migrate_load_host_view_from_yaml,
    )

    uo = tmp_path / "uo"
    (uo / "ir").mkdir(parents=True)

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
    assert not (uo / CODEMAP_YAML).is_file()
    assert out.get("alias_yaml") in ("", None)

    migrated = migrate_load_host_view_from_yaml(uo)
    preds = [
        p for p in (migrated.get("predicates") or [])
        if p.get("feature_hint") == "dtype_is_fp32"
    ]
    assert any("DT_FLOAT" in (p.get("condition") or "") for p in preds)
    deter = next(f for f in migrated.get("fields") or [] if f.get("name") == "DeterType")
    assert any(r.get("root") == "SESSION_OPTION" for r in (deter.get("reads") or []))


def test_load_tg_host_view_from_uo_product(tmp_path: Path):
    from uo_init.host_codemap import load_tg_host_view

    cm = CodeMap(op_name="toy", architecture="arch35")
    cm.upsert(
        EntityKind.TILING_KEY,
        "SplitAxis",
        attrs={"source_declared": True, "decl_order": 0},
    )
    product = tmp_path / ".ascendc-pilot" / "arch35" / "uo" / "toy.arch35.uo"
    write_codemap(cm, product)
    loaded = load_tg_host_view(tmp_path)
    names = {f.get("name") for f in (loaded.get("fields") or [])}
    declared = loaded.get("declared_keys") or {}
    assert "SplitAxis" in names or "SplitAxis" in declared


def test_yaml_only_host_view_is_not_production_authority(tmp_path: Path):
    from uo_init.host_codemap import load_tg_host_view, migrate_load_host_view_from_yaml

    uo = tmp_path / ".ascendc-pilot" / "arch35" / "uo"
    (uo / "ir").mkdir(parents=True)
    doc = {
        "schema": "tg-host-view/v1",
        "source": {"graph_fingerprint": "fp-x"},
        "fields": [{"name": "SplitAxis", "kind": "key_dim", "writers": [], "reads": []}],
    }
    (uo / "ir" / "tg_host_view.yaml").write_text(
        yaml.safe_dump(doc, sort_keys=False), encoding="utf-8",
    )
    assert load_tg_host_view(tmp_path) == {}
    migrated = migrate_load_host_view_from_yaml(uo)
    assert migrated.get("source", {}).get("graph_fingerprint") == "fp-x"


def test_pilot_export_tg_host_view_reuses_matching_view(tmp_path: Path, monkeypatch):
    """A matching durable TG host view must not force another host extract."""
    monkeypatch.setenv("UO_ARCH", "arch35")

    from uo_init import pilot_engines as P
    from uo_init.host_codemap import TG_HOST_VIEW_YAML

    project = tmp_path / "op"
    uo = P._uo_root(project, arch="arch35")
    (uo / "ir").mkdir(parents=True)
    (uo / "checks").mkdir(parents=True)

    (uo / "ir" / "operator_graph.yaml").write_text(
        yaml.safe_dump({
            "version": 1,
            "fingerprint": "fp-cache",
            "nodes": [],
            "edges": [],
            "evidence": [],
            "domains": [],
        }),
        encoding="utf-8",
    )
    (uo / "manifest.yaml").write_text(
        yaml.safe_dump({
            "content_hash": "mh-cache",
            "source_revision": "rev-cache",
        }),
        encoding="utf-8",
    )
    view = {
        "schema": "tg-host-view/v1",
        "source": {
            "graph_fingerprint": "fp-cache",
            "manifest_hash": "mh-cache",
            "source_revision": "rev-cache",
            "authority": "uo/ir/operator_graph.yaml",
            "role": "tg_host_projection",
            "generated_by": "export_tg_host_view",
        },
        "fields": [{
            "name": "SplitAxis",
            "kind": "key_dim",
            "exactness": "exact",
            "grade": "green",
            "writers": [],
            "reads": [],
        }],
        "predicates": [],
        "declared_keys": {},
        "platform_gates": [],
    }
    (uo / TG_HOST_VIEW_YAML).parent.mkdir(parents=True, exist_ok=True)
    (uo / TG_HOST_VIEW_YAML).write_text(
        yaml.safe_dump(view, sort_keys=False), encoding="utf-8",
    )

    def _explode(*args, **kwargs):
        raise AssertionError("_ensure_bundle should not run on cache hit")

    monkeypatch.setattr(P, "_ensure_bundle", _explode)
    out = P.export_tg_host_view(project, {"arch_dir": "arch35"})

    assert out["ok"] is True
    assert out["cached"] is True
    assert out["fields"] == 1
    assert out["graph_fingerprint"] == "fp-cache"
