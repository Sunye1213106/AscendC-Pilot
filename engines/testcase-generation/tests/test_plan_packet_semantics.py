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
            "is_deter": {
                "control": {"status": "active"},
                "confidence": "confirmed",
                "relation": "derived",
                "runtime": {"target": "ctx.deterministic"},
                "uo": {"id": "", "candidate": "DeterType"},
                "evidence": "harness reads the column",
            },
            "inner_drop": {"control": {"status": "active"}, "confidence": "unresolved"},
            "layout": {"control": {"status": "shadowed"}, "confidence": "confirmed"},
        }
    }
    out = plan_packet.controls_catalog(init)
    assert out["case_allowed"] == ["B", "is_deter", "sparse_mode"]
    assert out["unresolved_active"] == ["inner_drop"]
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


def test_changed_file_resolves_through_known_repo_prefix(tmp_path: Path) -> None:
    repo = tmp_path
    op = repo / "attention" / "flash_attention_score_grad"
    (op / "op_host").mkdir(parents=True)
    (op / "op_host" / "deter.h").write_text("int x = 1;\n", encoding="utf-8")
    found = plan_packet.resolve_changed_file(
        op,
        "attention/flash_attention_score_grad/op_host/deter.h",
        repo_root=repo,
    )
    assert found is not None and found.name == "deter.h"
    assert plan_packet.resolve_changed_file(op, "nowhere/absent.h") is None


def test_parent_path_is_not_eaten_by_lstrip(tmp_path: Path) -> None:
    repo = tmp_path
    op = repo / "attention" / "flash_attention_score_grad"
    (op / "op_host").mkdir(parents=True)
    (op / "common").mkdir()
    (op / "common" / "foo.h").write_text("int nested = 1;\n", encoding="utf-8")
    sibling = repo / "attention" / "common"
    sibling.mkdir(parents=True)
    (sibling / "foo.h").write_text("int shared = 1;\n", encoding="utf-8")
    found = plan_packet.resolve_changed_file(op, "../common/foo.h", repo_root=repo)
    assert found is not None
    assert found.resolve() == (sibling / "foo.h").resolve()


def test_dot_slash_operator_relative_resolves(tmp_path: Path) -> None:
    op = tmp_path / "op"
    (op / "op_host").mkdir(parents=True)
    (op / "op_host" / "foo.cpp").write_text("int x = 1;\n", encoding="utf-8")
    found = plan_packet.resolve_changed_file(op, "./op_host/foo.cpp")
    assert found is not None and found.name == "foo.cpp"


def test_duplicate_basename_is_ambiguous(tmp_path: Path) -> None:
    op = tmp_path / "op"
    (op / "op_host").mkdir(parents=True)
    (op / "op_kernel").mkdir(parents=True)
    (op / "op_host" / "foo.h").write_text("int a = 1;\n", encoding="utf-8")
    (op / "op_kernel" / "foo.h").write_text("int b = 1;\n", encoding="utf-8")
    assert plan_packet.resolve_changed_file(op, "foo.h") is None
    assert plan_packet.resolve_changed_file(op, "op_host/foo.h") is not None


def test_unknown_repo_prefix_is_not_suffix_guessed(tmp_path: Path) -> None:
    op = tmp_path / "flash_attention_score_grad"
    (op / "op_host").mkdir(parents=True)
    (op / "op_host" / "deter.h").write_text("int x = 1;\n", encoding="utf-8")
    assert (
        plan_packet.resolve_changed_file(
            op, "elsewhere/flash_attention_score_grad/op_host/deter.h"
        )
        is None
    )


def test_method_contract_digest_tracks_methodology_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "prompts" / "tasks" / "tg").mkdir(parents=True)
    (repo / "skills" / "test-plan" / "references").mkdir(parents=True)
    owner = repo / "prompts" / "tasks" / "tg" / "plan-owner.md"
    cov = repo / "skills" / "test-plan" / "references" / "coverage-ir.md"
    owner.write_text("v1\n", encoding="utf-8")
    cov.write_text("guard activation\n", encoding="utf-8")

    first = plan_packet.method_contract(repo)
    assert first["guard_semantics"] == "activation/v1"
    assert first["target_policy"] == "pr-owned-observable/v1"

    cov.write_text("guard activation, l2 full_cross\n", encoding="utf-8")
    assert plan_packet.method_contract(repo)["contract_digest"] != first["contract_digest"]


def _owned(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "kind": "TILING_FIELD",
        "change": {
            "kinds": ["writer_changed"],
            "ownership": {"pr_eligible": True},
            "evidence": [
                {
                    "hunk_id": "H1",
                    "relation": "WRITES",
                    "direction": "seed_to_writer",
                    "line": 10,
                }
            ],
        },
    }


def _packet(**over) -> dict:
    base = {
        "change_contract": {"kind": "pr_regression"},
        "observation_catalog": {
            "replay_allowed": ["deterBandScheduleMode", "enablePreSfmg"],
            "replay_forbidden": [
                {"name": "DeterType", "kind": "TILING_KEY", "reason": "dispatch"}
            ],
        },
        "behavior_candidates": [_owned("deterBandScheduleMode")],
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


def test_declaration_only_is_not_pr_owned() -> None:
    from testcase_agent.pr_ownership import annotate_candidate, is_pr_owned

    row = {
        "symbol": "deterMode",
        "declared_at": {"file": "op_host/tiling.cpp", "line": 4},
        "writers": [{"file": "op_host/tiling.cpp", "line": 20}],
    }
    hunks = [
        {
            "hunk_id": "H1",
            "old_file": "op_host/tiling.cpp",
            "new_file": "op_host/tiling.cpp",
            "old_start": 4,
            "old_end": 4,
            "new_start": 4,
            "new_end": 4,
            "status": "modified",
            "deleted_lines": ["int deterMode = 0;"],
            "added_lines": ["int32_t deterMode = 0;"],
        }
    ]
    annotate_candidate(row, hunks=hunks, file_key=lambda p: p)
    assert "declaration_in_changed_hunk" in row["change"]["kinds"]
    assert is_pr_owned(row) is False
    fence = {
        "targets": [{"id": "T-d", "evidence": {"field": "replay.deterMode"}}]
    }
    packet = _packet(behavior_candidates=[row])
    assert any(TARGET_NOT_CHANGED in e for e in validate_against_packet(fence, packet))


def test_writer_in_hunk_is_pr_owned_other_field_is_not() -> None:
    from testcase_agent.pr_ownership import annotate_candidate, is_pr_owned

    hunks = [
        {
            "hunk_id": "H1",
            "old_file": "xxx_tiling.cpp",
            "new_file": "xxx_tiling.cpp",
            "old_start": 12,
            "old_end": 12,
            "new_start": 12,
            "new_end": 12,
            "status": "modified",
            "deleted_lines": ["  foo = old_value;"],
            "added_lines": ["  foo = new_value;"],
        }
    ]
    foo = {
        "symbol": "foo",
        "declared_at": {"file": "xxx_tiling.cpp", "line": 1},
        "writers": [{"file": "xxx_tiling.cpp", "line": 12}],
    }
    deter = {
        "symbol": "deterMode",
        "declared_at": {"file": "xxx_tiling.cpp", "line": 2},
        "writers": [{"file": "xxx_tiling.cpp", "line": 8}],
    }
    annotate_candidate(foo, hunks=hunks, file_key=lambda p: p)
    annotate_candidate(deter, hunks=hunks, file_key=lambda p: p)
    assert is_pr_owned(foo) is True
    assert is_pr_owned(deter) is False
    packet = _packet(behavior_candidates=[foo, deter])
    bad = {"targets": [{"id": "T-d", "evidence": {"field": "replay.deterMode"}}]}
    good = {"targets": [{"id": "T-f", "evidence": {"field": "replay.foo"}}]}
    assert any(TARGET_NOT_CHANGED in e for e in validate_against_packet(bad, packet))
    assert validate_against_packet(good, packet) == []


def test_bare_pr_eligible_without_evidence_is_rejected() -> None:
    row = {
        "symbol": "foo",
        "change": {
            "kinds": ["writer_changed"],
            "ownership": {"pr_eligible": True},
            "evidence": [],
        },
    }
    packet = _packet(behavior_candidates=[row])
    fence = {"targets": [{"id": "T-f", "evidence": {"field": "replay.foo"}}]}
    assert any(TARGET_NOT_CHANGED in e for e in validate_against_packet(fence, packet))


def test_undirected_neighbor_is_context() -> None:
    from testcase_agent.pr_ownership import annotate_candidate, is_pr_owned

    row = {
        "symbol": "fieldX",
        "declared_at": {"file": "op_host/a.cpp", "line": 80},
        "writers": [{"file": "op_host/a.cpp", "line": 80, "id": "W1"}],
    }
    hunks = [
        {
            "hunk_id": "H1",
            "new_file": "op_host/a.cpp",
            "old_file": "op_host/a.cpp",
            "old_start": 10,
            "old_end": 10,
            "new_start": 10,
            "new_end": 10,
            "deleted_lines": ["  helperA();"],
            "added_lines": ["  helperA(flag);"],
        }
    ]
    annotate_candidate(row, hunks=hunks, file_key=lambda p: p)
    assert is_pr_owned(row) is False


def test_directed_control_proof_owns_observable() -> None:
    from testcase_agent.pr_ownership import annotate_candidate, is_pr_owned

    row = {
        "symbol": "deterMode",
        "writers": [{"file": "op_host/a.cpp", "line": 40, "id": "W1"}],
    }
    hunks = [
        {
            "hunk_id": "H3",
            "new_file": "op_host/a.cpp",
            "old_file": "op_host/a.cpp",
            "old_start": 12,
            "old_end": 12,
            "new_start": 12,
            "new_end": 12,
            "deleted_lines": ["  if (s1 > limit) {"],
            "added_lines": [],
        }
    ]
    annotate_candidate(
        row,
        hunks=hunks,
        file_key=lambda p: p,
        directed_proofs=[
            {"kind": "observable_control_dependency_changed", "hunk_id": "H3", "relation": "CONTROLS", "line": 12}
        ],
    )
    assert is_pr_owned(row) is True
    assert "CONTROLS" in {e["relation"] for e in row["change"]["evidence"]}


def test_deleted_assignment_on_old_side_owns_symbol() -> None:
    from testcase_agent.pr_ownership import annotate_candidate, is_pr_owned

    row = {"symbol": "foo", "writers": []}
    hunks = [
        {
            "hunk_id": "H1",
            "old_file": "op_host/a.cpp",
            "new_file": "op_host/a.cpp",
            "old_start": 20,
            "old_end": 20,
            "new_start": 20,
            "new_end": 20,
            "status": "deleted",
            "deleted_lines": ["  tilingData->foo = 1;"],
            "added_lines": [],
        }
    ]
    annotate_candidate(row, hunks=hunks, file_key=lambda p: p)
    assert is_pr_owned(row) is True


def test_kvmerge_use_in_hunk_is_probeable(tmp_path: Path) -> None:
    src = tmp_path / "op_host" / "tiling.cpp"
    src.parent.mkdir(parents=True)
    src.write_text(
        "\n".join(
            [
                "void Sel() {",
                "  bool kvMerge = value == nullptr;",
                "  int keep = 0;",
                "  if (kvMerge && enableDeter) {",
                "    keep = 1;",
                "  }",
                "}",
            ]
        ),
        encoding="utf-8",
    )
    hunks = [
        {
            "hunk_id": "H1",
            "old_file": "op_host/tiling.cpp",
            "new_file": "op_host/tiling.cpp",
            "old_start": 4,
            "old_end": 4,
            "new_start": 4,
            "new_end": 4,
            "deleted_lines": ["  if (enableDeter) {"],
            "added_lines": ["  if (kvMerge && enableDeter) {"],
        }
    ]
    rows = {
        row["name"]: row
        for row in plan_packet.branch_locals(
            tmp_path, ["op_host/tiling.cpp"], changed_hunks=hunks
        )
    }
    assert rows["kvMerge"]["probeable"] is True
    assert "keep" not in rows


def test_multiple_reaching_defs_are_ambiguous(tmp_path: Path) -> None:
    src = tmp_path / "op_host" / "tiling.cpp"
    src.parent.mkdir(parents=True)
    src.write_text(
        "\n".join(
            [
                "void Sel() {",
                "  int mode = 0;",
                "  mode = 1;",
                "  if (mode == 2) {",
                "    run = true;",
                "  }",
                "}",
            ]
        ),
        encoding="utf-8",
    )
    hunks = [
        {
            "hunk_id": "H1",
            "old_file": "op_host/tiling.cpp",
            "new_file": "op_host/tiling.cpp",
            "old_start": 4,
            "old_end": 4,
            "new_start": 4,
            "new_end": 4,
            "deleted_lines": ["  if (mode == 1) {"],
            "added_lines": ["  if (mode == 2) {"],
        }
    ]
    rows = {
        row["name"]: row
        for row in plan_packet.branch_locals(
            tmp_path, ["op_host/tiling.cpp"], changed_hunks=hunks
        )
    }
    assert rows["mode"]["probeable"] is False
    assert "PROBE_AMBIGUOUS" in rows["mode"]["probe_blocked"]


def test_hunk_digest_and_route_card_split_host_kernel() -> None:
    hunks = [
        {
            "hunk_id": "H1",
            "new_file": "op_host/tiling.cpp",
            "status": "modified",
            "deleted_lines": ["void OldFn() {"],
            "added_lines": ["int selectedRound = 1;"],
        }
    ]
    relevant = [
        {
            "hunk_id": "H2",
            "new_file": "op_kernel/kernel.h",
            "status": "modified",
            "deleted_lines": [],
            "added_lines": ["int bar = 2;"],
        }
    ]
    digest = plan_packet.hunk_change_digest(hunks)
    assert "OldFn" in digest["deleted_symbols"]
    assert "selectedRound" in digest["modified_writes"]
    card = plan_packet.build_plan_route_card(
        ["op_host/tiling.cpp"], hunks, relevant_hunks=relevant
    )
    assert card["route_hint"] == "fragments"
    kinds = {c["kind"] for c in card["clusters"]}
    assert kinds == {"host", "kernel"}
    text = plan_packet.format_plan_route_card(card)
    assert "改动摘要" in text
    assert "FOCUS fragment" in text


def test_single_host_cluster_is_one_owner() -> None:
    hunks = [
        {
            "new_file": "op_host/tiling.cpp",
            "status": "modified",
            "deleted_lines": [],
            "added_lines": ["int foo = 1;"],
        }
    ]
    card = plan_packet.build_plan_route_card(["op_host/tiling.cpp"], hunks)
    assert card["route_hint"] == "one_owner"
    assert "1 个 Plan Owner" in plan_packet.format_plan_route_card(card)
