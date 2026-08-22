"""Context Compiler: profiles, slice emission, legacy pack stability."""

from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.context import build_context_pack, get_profile, maybe_compile_slice
from ascendc_pilot.context.profiles import PROFILES
from ascendc_pilot.paths import context_root, ensure_agent_layout
from ascendc_pilot.state import start_workflow
from ascendc_pilot.workflows.specs import WORKFLOWS as SPEC_WORKFLOWS


REPO = Path(__file__).resolve().parents[2]

_REQUIRED_PROFILES = (
    "uo-init-propose-include-heal",
    "uo-investigate-investigate",
    "uo-query-kb-lookup",
    "tg-init-bind-init",
    "tg-init-bind-review",
    "tg-plan-plan-scope",
    "tg-plan-plan-fuse",
    "tg-solve-construct-cases",
    "tg-solve-analyze-round",
    "ce-review-code-review",
    "ce-plan-draft",
    "ce-apply-patch",
    "handoff-session",
)

_LLM_ROLES = {
    "producer",
    "referee",
    "readonly_analyst",
    "readonly_reviewer",
    "controller",
}
_LLM_MODES = {"subagent", "primary_interactive", "primary_review"}


def test_high_value_profiles_registered() -> None:
    assert "uo-init-resolve" not in PROFILES
    assert get_profile("uo-init-resolve") is None
    assert get_profile("missing") is None
    for pid in _REQUIRED_PROFILES:
        assert pid in PROFILES, pid
        assert get_profile(pid) is not None
        assert get_profile(pid).id == pid


def test_profile_does_not_select_domain_references() -> None:
    for pid, prof in PROFILES.items():
        assert not getattr(prof, "references", ()), pid
        for rel in prof.conditional_refs:
            assert (REPO / rel).is_file(), f"{pid}: missing conditional {rel}"


def test_tg_skill_pointers_are_action_local() -> None:
    from ascendc_pilot.actions.method_bundle import declared_reference_paths

    bind_init = declared_reference_paths("bind-init", REPO)
    plan = declared_reference_paths("plan", REPO)
    solve = declared_reference_paths("solve", REPO)
    assert "skills/bind-init/references/harness.md" in bind_init
    assert "skills/bind-init/references/columns.md" in bind_init
    assert "skills/bind-init/references/review.md" in bind_init
    assert "skills/bind-init/references/test-script-repo.md" in bind_init
    assert "skills/bind-init/references/harness-edge-cases.md" in bind_init
    assert "skills/bind-init/references/column-binding-edge-cases.md" in bind_init
    assert "skills/plan/references/scope.md" in plan
    assert "skills/plan/references/fuse.md" in plan
    assert "skills/plan/references/planning-gotchas.md" in plan
    assert "skills/plan/references/planning-context.md" in plan
    assert "skills/solve/references/targeted-construct.md" in solve
    assert "skills/solve/references/oracle.md" not in solve
    assert "skills/solve/references/failure-patterns.md" in solve
    for path in (*bind_init, *plan, *solve):
        assert "skills/testcase-generation/references/gotchas.md" not in path


def test_llm_actions_declare_registered_profiles() -> None:
    for wid, meta in SPEC_WORKFLOWS.items():
        for action in meta.get("actions") or []:
            aid = action["id"]
            pid = action.get("context_profile_id")
            role = str(action.get("role_id") or "")
            mode = str(action.get("execution_mode") or "")
            llm = role in _LLM_ROLES or mode in _LLM_MODES
            if llm:
                assert pid, f"{wid}/{aid}: LLM Action missing context_profile_id"
                assert pid in PROFILES, f"{wid}/{aid}: unregistered profile {pid}"
            else:
                assert not pid, f"{wid}/{aid}: deterministic Action must omit context_profile_id, got {pid!r}"


def test_maybe_compile_returns_none_without_profile(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch0")
    start_workflow(tmp_path, "uo-init", intent="test", op_name="toy", architecture="arch0")
    assert maybe_compile_slice(tmp_path, context_profile_id=None, action_id="extract") is None
    assert maybe_compile_slice(tmp_path, context_profile_id="no-such", action_id="extract") is None


def test_compile_slice_writes_file_even_without_uo(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch0")
    start_workflow(tmp_path, "uo-init", intent="test", op_name="toy", architecture="arch0")
    slice_doc = maybe_compile_slice(
        tmp_path,
        context_profile_id="uo-investigate-investigate",
        action_id="investigate",
        workflow_id="uo-investigate",
        repo_root=REPO,
    )
    assert slice_doc is not None
    assert slice_doc["profile_id"] == "uo-investigate-investigate"
    assert "token_estimate" in slice_doc
    assert slice_doc["budget_ok"] is True
    assert slice_doc["token_estimate"] <= slice_doc["token_budget"]
    assert isinstance(slice_doc["budget_receipts"], list)
    assert Path(slice_doc["path"]).is_file()
    loaded = yaml.safe_load(Path(slice_doc["path"]).read_text(encoding="utf-8"))
    assert loaded["task"]["action_id"] == "investigate"
    assert "excluded" in loaded
    assert loaded["budget_ok"] is True
    assert loaded.get("ok") is True
    assert not loaded.get("missing_references")
    assert isinstance(loaded["references"], list)
    assert loaded["references"], "expected path-list references"
    for row in loaded["references"]:
        assert row.get("status") == "ok"
        assert row.get("path")
        assert "text" not in row, "slice must not embed reference bodies"


def test_compile_slice_fails_closed_on_missing_refs(tmp_path: Path, monkeypatch) -> None:
    ensure_agent_layout(tmp_path, arch="arch0")
    start_workflow(tmp_path, "uo-init", intent="test", op_name="toy", architecture="arch0")
    from ascendc_pilot.context import compiler as comp

    def _fake_load(repo: Path, refs: tuple[str, ...]):
        return [{"path": "skills/nope/missing.md", "status": "missing"}]

    monkeypatch.setattr(comp, "_load_references", _fake_load)
    slice_doc = maybe_compile_slice(
        tmp_path,
        context_profile_id="uo-investigate-investigate",
        action_id="investigate",
        workflow_id="uo-investigate",
        repo_root=REPO,
    )
    assert slice_doc is not None
    assert slice_doc.get("ok") is False
    assert slice_doc.get("reason_code") == "CONTEXT_REFERENCES_MISSING"
    assert "skills/nope/missing.md" in (slice_doc.get("missing_references") or [])


def test_legacy_pack_unchanged_shape(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path, arch="arch0")
    start_workflow(tmp_path, "uo-init", intent="test", op_name="toy", architecture="arch0")
    pack = build_context_pack(tmp_path, intent="run-action:extract", topic="extract")
    assert pack["version"] == 1
    assert "uo_snippet" in pack
    assert "full_kb" in pack["omitted"]
    assert (context_root(tmp_path) / "context_pack.yaml").is_file()
    # Pack must not grow a required slice key (backward compatible).
    assert "context_slice" not in pack


def test_open_keys_seeds_from_worklog(tmp_path: Path) -> None:
    from ascendc_pilot.context.compiler import _seed_ids
    from ascendc_pilot.paths import tg_root

    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "tg-solve", architecture="arch35")
    worklog = tg_root(tmp_path, "arch35") / "worklog.md"
    worklog.parent.mkdir(parents=True, exist_ok=True)
    worklog.write_text("open: [KEY_A, KEY_B]\n\n## KEY_A\n", encoding="utf-8")
    seeds = _seed_ids(tmp_path, "open_keys", limit=20)
    assert "KEY_A" in seeds
    assert "KEY_B" in seeds


def test_profiles_and_compiler_drop_search_and_impact_of_slices() -> None:
    compiler = (REPO / "pilot" / "ascendc_pilot" / "context" / "compiler.py").read_text(
        encoding="utf-8"
    )
    assert 'method == "search"' not in compiler
    assert 'method == "impact_of"' not in compiler
    for pid, prof in PROFILES.items():
        methods = [qs.method for qs in prof.query_slices]
        assert "search" not in methods, (pid, methods)
        assert "impact_of" not in methods, (pid, methods)
