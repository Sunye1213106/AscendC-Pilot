from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from uo.scripts.prepare_operator import _select_run_id, main as prepare_main


def _write_manifest(base: Path, run_id: str) -> None:
    base.mkdir(parents=True, exist_ok=True)
    (base / "manifest.yaml").write_text(
        yaml.safe_dump({"current_run_id": run_id}, sort_keys=False),
        encoding="utf-8",
    )


def _write_pilot_state(repo: Path, run_id: str = "RUN_20260724_091453_aa063141") -> None:
    state = repo / ".ascendc-pilot" / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "workflow.yaml").write_text(
        yaml.safe_dump(
            {
                "run_id": run_id,
                "workflow_id": "uo-init",
                "status": "running",
            },
            sort_keys=False,
        ),
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


def test_standalone_forbidden_during_active_pilot_even_with_matching_run(tmp_path: Path) -> None:
    repo = tmp_path / "op"
    repo.mkdir()
    run_id = "RUN_20260724_091453_aa063141"
    _write_pilot_state(repo, run_id)

    with pytest.raises(SystemExit, match="STANDALONE_FORBIDDEN_DURING_ACTIVE_PILOT"):
        prepare_main([str(repo), "--op-name", "op", "--standalone", "--run-id", run_id])


def test_standalone_forbidden_when_pilot_active(tmp_path: Path) -> None:
    repo = tmp_path / "op"
    repo.mkdir()
    _write_pilot_state(repo, "RUN_20260724_091453_aa063141")

    with pytest.raises(SystemExit, match="STANDALONE_FORBIDDEN_DURING_ACTIVE_PILOT"):
        prepare_main(
            [
                str(repo),
                "--op-name",
                "op",
                "--standalone",
                "--run-id",
                "RUN_20260724_091453_aa063141",
            ]
        )


def test_active_pilot_requires_bound_run_id(tmp_path: Path) -> None:
    repo = tmp_path / "op"
    repo.mkdir()
    _write_pilot_state(repo)

    with pytest.raises(SystemExit, match="PILOT_RUN_ID_REQUIRED"):
        prepare_main([str(repo), "--op-name", "op"])


def test_active_pilot_rejects_mismatched_bound_run_id(tmp_path: Path) -> None:
    repo = tmp_path / "op"
    repo.mkdir()
    _write_pilot_state(repo, "RUN_20260724_091453_aa063141")

    with pytest.raises(SystemExit, match="PILOT_RUN_ID_MISMATCH"):
        prepare_main([str(repo), "--op-name", "op", "--run-id", "RUN_20260724_999999_bad"])


def test_standalone_without_run_id_cannot_mint_uo_run_during_pilot(tmp_path: Path) -> None:
    repo = tmp_path / "op"
    repo.mkdir()
    _write_pilot_state(repo, "RUN_20260724_091453_aa063141")

    with pytest.raises(SystemExit, match="PILOT_RUN_ID_REQUIRED"):
        prepare_main([str(repo), "--op-name", "op"])


def test_standalone_allowed_without_active_pilot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import uo.scripts.prepare_operator as po

    repo = tmp_path / "op"
    repo.mkdir()
    monkeypatch.setattr(
        po,
        "_resolve_installed_skill_check",
        lambda *_a, **_k: {
            "version": 2,
            "consistent": True,
            "skill_present": True,
            "primary_skill": "uo-init",
            "mismatches": [],
        },
    )

    assert po.main([str(repo), "--op-name", "op", "--standalone"]) == 0
    manifest = yaml.safe_load((repo / ".ascendc-pilot" / "uo" / "manifest.yaml").read_text(encoding="utf-8")) or {}
    assert str(manifest.get("current_run_id") or "").startswith("UO_RUN_")
