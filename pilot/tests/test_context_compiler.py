"""Context Compiler: profiles, slice emission, legacy pack stability."""

from __future__ import annotations

from pathlib import Path

import yaml

from ascendc_pilot.context import build_context_pack, get_profile, maybe_compile_slice
from ascendc_pilot.context.profiles import PROFILES
from ascendc_pilot.paths import context_root, ensure_agent_layout
from ascendc_pilot.state import start_workflow


REPO = Path(__file__).resolve().parents[2]


def test_high_value_profiles_registered() -> None:
    assert "uo-init-resolve" in PROFILES
    assert "tg-solve-lemma-mine" in PROFILES
    assert "ce-review-code-review" in PROFILES
    assert get_profile("missing") is None
    assert get_profile("uo-init-resolve") is not None


def test_maybe_compile_returns_none_without_profile(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init", intent="test", op_name="toy", architecture="arch0")
    assert maybe_compile_slice(tmp_path, context_profile_id=None, action_id="extract") is None
    assert maybe_compile_slice(tmp_path, context_profile_id="no-such", action_id="extract") is None


def test_compile_slice_writes_file_even_without_uo(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init", intent="test", op_name="toy", architecture="arch0")
    slice_doc = maybe_compile_slice(
        tmp_path,
        context_profile_id="uo-init-resolve",
        action_id="resolve",
        workflow_id="uo-init",
        repo_root=REPO,
    )
    assert slice_doc is not None
    assert slice_doc["profile_id"] == "uo-init-resolve"
    assert "token_estimate" in slice_doc
    assert Path(slice_doc["path"]).is_file()
    loaded = yaml.safe_load(Path(slice_doc["path"]).read_text(encoding="utf-8"))
    assert loaded["task"]["action_id"] == "resolve"
    assert "excluded" in loaded
    # References may be missing until P4 gotchas land; status is recorded.
    assert isinstance(loaded["references"], list)


def test_legacy_pack_unchanged_shape(tmp_path: Path) -> None:
    ensure_agent_layout(tmp_path)
    start_workflow(tmp_path, "uo-init", intent="test", op_name="toy", architecture="arch0")
    pack = build_context_pack(tmp_path, intent="run-action:extract", topic="extract")
    assert pack["version"] == 1
    assert "uo_snippet" in pack
    assert "full_kb" in pack["omitted"]
    assert (context_root(tmp_path) / "context_pack.yaml").is_file()
    # Pack must not grow a required slice key (backward compatible).
    assert "context_slice" not in pack
