# -*- coding: utf-8 -*-
"""Phase-5: second (synthetic) operator adapter smoke — no real second op needed."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_SCRIPTS = REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


@pytest.fixture()
def toy_env(monkeypatch):
    monkeypatch.setenv("UO_OPERATOR", "_synthetic_toy")
    monkeypatch.setenv("UO_ARCH", "arch0")
    monkeypatch.setenv("UO_REPLAY_DISTRO", "Ubuntu-2204")
    from replay import inputs as I
    from replay import package_data
    from replay import runner as R

    package_data.clear_caches()
    R._default = None
    I.reload()
    yield
    monkeypatch.delenv("UO_OPERATOR", raising=False)
    monkeypatch.delenv("UO_ARCH", raising=False)
    package_data.clear_caches()
    R._default = None
    I.reload()


def test_inputs_loader_not_hardcoded_to_fag():
    import ast

    path = REPO / "scripts" / "replay" / "inputs.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    text = ast.unparse(tree)
    assert "flash_attention_score_grad" not in text
    assert "package_data" in text or "UO_OPERATOR" in path.read_text(encoding="utf-8")


def test_second_operator_adapter_smoke(toy_env):
    from replay import inputs as I
    from replay import package_data
    from replay.manifest import OperatorManifest
    from replay.semantics import InputSemantics

    pkg = package_data.active_package_dir(REPO)
    assert pkg.name == "arch0"
    assert pkg.parent.name == "_synthetic_toy"

    assert isinstance(I.SEMANTICS, InputSemantics)
    case = I.Case(n=4).normalised()
    ins, outs = I.shapes(case)
    assert ins["x"] == [4]
    assert outs["y"] == [4]
    assert I.describe(case)["dtype"] == "FLOAT"

    man = OperatorManifest.load(pkg / "operator.yaml")
    assert man.name == "_synthetic_toy"
    assert man.arch == "arch0"

    hints = package_data.load_yaml("search_hints.yaml", refresh=True)
    assert "sampling_grid" in hints
    assert hints["sampling_grid"]["layout"] == ["FLAT"]

    construct = package_data.load_yaml("construction_hints.yaml", refresh=True)
    features = package_data.load_yaml("feature_bindings.yaml", refresh=True)
    assert isinstance(construct, dict)
    assert isinstance(features, dict)


def test_closure_tables_loaded_from_operator_package():
    """FAG cold-start: adapter pack YAML is absent → empty dicts, not hard fail."""
    os.environ.pop("UO_OPERATOR", None)
    os.environ.pop("UO_ARCH", None)
    from replay import inputs as I
    from replay import package_data
    from replay import runner as R

    package_data.clear_caches()
    R._default = None
    I.reload()

    construct = package_data.load_yaml("construction_hints.yaml", refresh=True)
    search = package_data.load_yaml("search_hints.yaml", refresh=True)
    features = package_data.load_yaml("feature_bindings.yaml", refresh=True)
    assert isinstance(construct, dict)
    assert isinstance(search, dict)
    assert isinstance(features, dict)
    # Priors purged: empty until export_adapter_pack. If a local pack exists,
    # keep a weak shape check rather than golden FAG tables.
    if construct:
        assert "d_for" in construct or "defaults" in construct or "loops" in construct
    if search:
        assert "sampling_grid" in search or "nearest_knobs" in search
    if features.get("static_parents"):
        from testcase_agent.closure import features as F

        status = F.static_parent_status("DeterType")
        parents = F.static_parents(
            "DeterType", ["deterministic", "layout", "dtype"]
        )
        if status == "present":
            assert "deterministic" in parents
        else:
            # missing / explicit_empty must not pretend static == all features
            assert parents == []
