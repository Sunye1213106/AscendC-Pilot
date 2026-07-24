from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from uo.scripts.prepare_operator import _select_run_id


def _write_manifest(base: Path, run_id: str) -> None:
    base.mkdir(parents=True, exist_ok=True)
    (base / "manifest.yaml").write_text(
        yaml.safe_dump({"current_run_id": run_id}, sort_keys=False),
        encoding="utf-8",
    )


def test_write_index_meta_reuses_incomplete_run(tmp_path: Path) -> None:
    base = tmp_path / ".ascendc-pilot" / "uo"
    run_id = "UO_RUN_20260716103317855654"
    _write_manifest(base, run_id)
    phase0 = base / "runs" / run_id / "scope"
    phase0.mkdir(parents=True)
    (phase0 / "scope_scan.yaml").write_text("status: complete\n", encoding="utf-8")

    # Default path used by --write-index-meta (no --resume / no --force-new-run)
    assert _select_run_id(base, resume=False, force_new=False) == run_id
    assert _select_run_id(base, resume=True, force_new=False) == run_id


def test_force_new_run_always_forks(tmp_path: Path) -> None:
    base = tmp_path / ".ascendc-pilot" / "uo"
    run_id = "UO_RUN_20260716103317855654"
    _write_manifest(base, run_id)
    (base / "runs" / run_id / "scope").mkdir(parents=True)

    new_id = _select_run_id(base, resume=False, force_new=True)
    assert new_id != run_id
    assert new_id.startswith("UO_RUN_")


def test_passed_receipt_starts_new_run(tmp_path: Path) -> None:
    base = tmp_path / ".ascendc-pilot" / "uo"
    run_id = "UO_RUN_20260716103317855654"
    _write_manifest(base, run_id)
    phase0 = base / "runs" / run_id / "scope"
    phase0.mkdir(parents=True)
    (phase0 / "receipt.yaml").write_text("status: pass\n", encoding="utf-8")

    new_id = _select_run_id(base, resume=False, force_new=False)
    assert new_id != run_id


def test_bound_pilot_run_id_wins_over_legacy_uo_run(tmp_path: Path) -> None:
    base = tmp_path / ".ascendc-pilot" / "uo"
    legacy = "UO_RUN_legacy"
    _write_manifest(base, legacy)
    (base / "runs" / legacy / "scope").mkdir(parents=True)

    pilot = "RUN_20260724_091453_aa063141"
    assert _select_run_id(base, resume=False, force_new=False, bound_run_id=pilot) == pilot


def test_bound_run_id_rejects_force_new(tmp_path: Path) -> None:
    base = tmp_path / ".ascendc-pilot" / "uo"
    with pytest.raises(SystemExit):
        _select_run_id(
            base,
            resume=False,
            force_new=True,
            bound_run_id="RUN_20260724_091453_aa063141",
        )


def test_reuses_incomplete_pilot_run_id(tmp_path: Path) -> None:
    base = tmp_path / ".ascendc-pilot" / "uo"
    run_id = "RUN_20260724_091453_aa063141"
    _write_manifest(base, run_id)
    phase0 = base / "runs" / run_id / "scope"
    phase0.mkdir(parents=True)
    (phase0 / "scope_scan.yaml").write_text("status: complete\n", encoding="utf-8")
    assert _select_run_id(base, resume=False, force_new=False) == run_id
