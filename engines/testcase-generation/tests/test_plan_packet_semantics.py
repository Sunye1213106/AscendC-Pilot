"""The scope packet must hand Plan Owner facts, not a file list to re-derive."""

from __future__ import annotations

from pathlib import Path

from testcase_agent import plan_packet
from testcase_agent.coverage.contract import (
    REPLAY_NAMESPACE_MISUSE,
    TARGET_NOT_CHANGED,
    validate_against_packet,
)


def test_controls_split_by_confidence_and_status() -> None:
    init = {
        "mapping": {
            "B": {"control": {"status": "active"}, "confidence": "confirmed"},
            "sparse_mode": {"control": {"status": "active"}, "confidence": "confirmed"},
            "is_deter": {"control": {"status": "active"}, "confidence": "unresolved"},
            "layout": {"control": {"status": "shadowed"}, "confidence": "confirmed"},
        }
    }
    out = plan_packet.controls_catalog(init)
    assert out["case_allowed"] == ["B", "sparse_mode"]
    assert out["unresolved_active"] == ["is_deter"]
    assert out["inactive"] == ["layout"]


def test_branch_locals_flag_probeable_and_ambiguous(tmp_path: Path) -> None:
    src = tmp_path / "op_host" / "tiling_deter.cpp"
    src.parent.mkdir(parents=True)
    src.write_text(
        "\n".join(
            [
                "void Sel() {",
                "  bool hybridBandCond = (n1 == n2);",
                "  if (hybridBandCond) { mode = 1; }",
                "  int64_t maxRound = CeilDiv(s1, base);",
                "  loops = Min(maxRound, cap);",
                "  int64_t reused = 1;",
                "  reused = 2;",
                "  if (reused > 0) { keep = true; }",
                "  int64_t quiet = 7;",
                "}",
            ]
        ),
        encoding="utf-8",
    )
    rows = {
        row["name"]: row
        for row in plan_packet.branch_locals(tmp_path, ["op_host/tiling_deter.cpp"])
    }
    assert rows["hybridBandCond"]["consumed_by_branch"] is True
    assert rows["hybridBandCond"]["probeable"] is True
    assert rows["maxRound"]["consumed_by_compare"] is True
    # Two assignments inside the change means the injector cannot pick one.
    assert rows["reused"]["probeable"] is False
    assert "PROBE_AMBIGUOUS" in rows["reused"]["probe_blocked"]
    # No branch or comparison consumes it, so it is not a coverage axis.
    assert "quiet" not in rows


def test_changed_file_resolves_through_repo_prefix(tmp_path: Path) -> None:
    op = tmp_path / "flash_attention_score_grad"
    (op / "op_host").mkdir(parents=True)
    (op / "op_host" / "deter.h").write_text("int x = 1;\n", encoding="utf-8")
    found = plan_packet.resolve_changed_file(
        op, "attention/flash_attention_score_grad/op_host/deter.h"
    )
    assert found is not None and found.name == "deter.h"
    assert plan_packet.resolve_changed_file(op, "nowhere/absent.h") is None


def test_method_contract_digest_tracks_methodology_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "prompts" / "tasks" / "tg").mkdir(parents=True)
    (repo / "skills" / "test-plan" / "references").mkdir(parents=True)
    owner = repo / "prompts" / "tasks" / "tg" / "plan-owner.md"
    cov = repo / "skills" / "test-plan" / "references" / "coverage-planning.md"
    owner.write_text("v1\n", encoding="utf-8")
    cov.write_text("guard activation\n", encoding="utf-8")

    first = plan_packet.method_contract(repo)
    assert first["guard_semantics"] == "activation/v1"
    assert first["target_policy"] == "changed_assignment/v1"

    cov.write_text("guard activation, l2 full_cross\n", encoding="utf-8")
    assert plan_packet.method_contract(repo)["contract_digest"] != first["contract_digest"]


def _packet(**over) -> dict:
    base = {
        "change_contract": {"kind": "pr_regression"},
        "observation_catalog": {
            "replay_allowed": ["deterBandScheduleMode", "enablePreSfmg"],
            "replay_forbidden": [
                {"name": "DeterType", "kind": "TILING_KEY", "reason": "dispatch"}
            ],
        },
        "behavior_candidates": [
            {"symbol": "deterBandScheduleMode", "kind": "TILING_FIELD"}
        ],
    }
    base.update(over)
    return base


def test_dispatch_entity_under_replay_is_rejected() -> None:
    fence = {
        "targets": [
            {
                "id": "T-deter-band-dispatch",
                "evidence": {"kind": "replay_field", "field": "replay.DeterType"},
            }
        ]
    }
    errors = validate_against_packet(fence, _packet())
    assert any(REPLAY_NAMESPACE_MISUSE in e for e in errors)
    assert any("dispatch_map" in e for e in errors)


def test_pr_regression_target_must_be_a_changed_assignment() -> None:
    fence = {
        "targets": [
            {
                "id": "T-presfmg",
                "evidence": {"kind": "replay_field", "field": "replay.enablePreSfmg"},
            }
        ]
    }
    errors = validate_against_packet(fence, _packet())
    assert any(TARGET_NOT_CHANGED in e for e in errors)

    ok = {
        "targets": [
            {
                "id": "T-band-schedule",
                "evidence": {
                    "kind": "replay_field",
                    "field": "replay.deterBandScheduleMode",
                },
            }
        ]
    }
    assert validate_against_packet(ok, _packet()) == []


def test_implementation_coverage_target_is_not_delta_checked() -> None:
    fence = {
        "targets": [
            {"id": "T-x", "evidence": {"field": "replay.enablePreSfmg"}}
        ]
    }
    packet = _packet(change_contract={"kind": "implementation_coverage"})
    assert validate_against_packet(fence, packet) == []


def test_no_packet_means_no_extra_claims() -> None:
    fence = {"targets": [{"id": "T-x", "evidence": {"field": "replay.DeterType"}}]}
    assert validate_against_packet(fence, None) == []
    assert validate_against_packet(fence, {}) == []
