# -*- coding: utf-8 -*-
"""Local Extension registry + OperatorWorkspace smoke tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "pilot"))


def test_operator_workspace_local_root(tmp_path: Path) -> None:
    from ascendc_pilot.workspace import OperatorWorkspace

    (tmp_path / "op_host").mkdir()
    ws = OperatorWorkspace.resolve(tmp_path, arch="arch35", allow_pilot_checkout=True)
    assert ws.local_root == tmp_path / ".ascendc-pilot" / "arch35" / "local"
    assert ws.local_extension_dir("case_builder").name == "case-builder"


def test_local_extension_load_and_required_exports(tmp_path: Path) -> None:
    from ascendc_pilot.local_extension import (
        LocalCapabilityRequired,
        LocalExtensionContractError,
        LocalExtensionRegistry,
    )

    root = tmp_path / ".ascendc-pilot" / "arch0" / "local" / "tilingdata-decoder"
    root.mkdir(parents=True)
    (root / "manifest.yaml").write_text(
        "\n".join(
            [
                "schema: ascendc-pilot-local-extension/v1",
                "interface: tilingdata_decoder",
                "version: 1",
                "reason:",
                "  code: UO_LAYOUT_INCOMPLETE",
                "  detail: test fixture",
            ]
        ),
        encoding="utf-8",
    )
    (root / "implementation.py").write_text(
        "def decode(raw, layout=None):\n    return {'ok': True, 'n': len(raw)}\n",
        encoding="utf-8",
    )

    reg = LocalExtensionRegistry(tmp_path / ".ascendc-pilot" / "arch0" / "local")
    ext = reg.get_extension("tilingdata_decoder")
    assert ext is not None
    assert ext.reason_code == "UO_LAYOUT_INCOMPLETE"
    mod = reg.load_module("tilingdata_decoder")
    assert mod.decode(b"abc")["n"] == 3

    with pytest.raises(LocalCapabilityRequired) as ei:
        reg.get_extension("case_builder", required=True)
    assert ei.value.as_dict()["interface"] == "case_builder"

    # Missing required export → contract error
    bad = tmp_path / ".ascendc-pilot" / "arch0" / "local" / "case-builder"
    bad.mkdir(parents=True)
    (bad / "manifest.yaml").write_text(
        "\n".join(
            [
                "schema: ascendc-pilot-local-extension/v1",
                "interface: case_builder",
                "version: 1",
            ]
        ),
        encoding="utf-8",
    )
    (bad / "implementation.py").write_text("foo = 1\n", encoding="utf-8")
    with pytest.raises(LocalExtensionContractError):
        reg.load_module("case_builder")


def test_from_operator_root_rejects_pilot_checkout() -> None:
    from ascendc_pilot.local_extension import LocalExtensionRegistry
    from ascendc_pilot.paths import pilot_checkout_root

    with pytest.raises(ValueError, match="refusing|operator root"):
        LocalExtensionRegistry.from_operator_root(pilot_checkout_root())


def test_package_data_fixture_synthetic(monkeypatch: pytest.MonkeyPatch) -> None:
    sys.path.insert(0, str(REPO / "scripts"))
    monkeypatch.setenv("UO_OPERATOR", "_synthetic_toy")
    monkeypatch.setenv("UO_ARCH", "arch0")
    monkeypatch.delenv("ASCENDC_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("UO_OP_DIR", raising=False)
    monkeypatch.delenv("UO_PACKAGE_DIR", raising=False)

    from replay import package_data

    package_data.clear_caches()
    pkg = package_data.active_package_dir(REPO)
    assert pkg.parent.name == "_synthetic_toy"
    assert (pkg / "operator.yaml").is_file()
    assert package_data.package_file("input_semantics.py", root=REPO).is_file()
