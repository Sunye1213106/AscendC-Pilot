# -*- coding: utf-8 -*-
"""Regression for CE review root fixes: glob, git, index, spec METHOD, intake."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PILOT = REPO / "pilot"
CE_ENGINE = REPO / "engines" / "code-engineering"
for extra in (str(PILOT), str(CE_ENGINE)):
    if extra not in sys.path:
        sys.path.insert(0, extra)

from ascendc_pilot.authorize import authorize, _glob_scope_candidates
from ascendc_pilot.authorize.lease import issue_action_lease
from ascendc_pilot.paths import agent_root, ensure_agent_layout, uo_root
from ascendc_pilot.state import load_state, start_workflow


def _ce_review_op(tmp_path: Path, *, with_uo: bool = True) -> Path:
    op = tmp_path / "DemoOp"
    op.mkdir()
    (op / "op_host" / "arch35").mkdir(parents=True)
    (op / "op_kernel" / "arch35").mkdir(parents=True)
    (op / "op_kernel" / "arch35" / "k.cpp").write_text("int x;\n", encoding="utf-8")
    ensure_agent_layout(op, arch="arch35")
    start_workflow(op, "ce-review", phase="review", force_phase=True, architecture="arch35")
    if with_uo:
        uo = uo_root(op, arch="arch35")
        uo.mkdir(parents=True, exist_ok=True)
        (uo / "DemoOp.arch35.uo").write_bytes(b"uo")
    state = load_state(op) or {}
    issue_action_lease(
        op,
        state=state,
        action_id="code_review",
        actor_id="ce-reviewer",
        allowed_read_paths=["ce/plan/**", "runs/**", "context/**", "uo/*.uo"],
        allowed_write_paths=["runs/**/actions/code_review/**"],
    )
    return op


def test_glob_scope_candidates_strip_dot_rel() -> None:
    cands = _glob_scope_candidates(".", "ce/plan/**")
    assert "ce/plan/**" in cands
    assert "ce/plan" in cands
    assert all(not c.startswith("./") for c in cands)


def test_glob_ce_plan_from_agent_root_allowed(tmp_path: Path) -> None:
    op = _ce_review_op(tmp_path)
    root = agent_root(op, "arch35")
    (root / "ce" / "plan").mkdir(parents=True, exist_ok=True)
    verdict = authorize(
        op,
        tool="glob",
        path=str(root),
        command="ce/plan/**",
        agent="ce-reviewer",
        action="code_review",
    )
    assert verdict.get("decision") == "allow", verdict
    runs = authorize(
        op,
        tool="glob",
        path=str(root),
        command="runs/**",
        agent="ce-reviewer",
        action="code_review",
    )
    assert runs.get("decision") == "allow", runs


def test_glob_ce_plan_from_operator_root_not_source_fence(tmp_path: Path) -> None:
    op = _ce_review_op(tmp_path)
    verdict = authorize(
        op,
        tool="glob",
        path=str(op),
        command="ce/plan/**",
        agent="ce-reviewer",
        action="code_review",
    )
    assert verdict.get("decision") == "allow", verdict
    assert verdict.get("reason_code") != "SOURCE_READ_USE_UO_QUERY"


def test_glob_op_kernel_still_uses_uo_query(tmp_path: Path) -> None:
    op = _ce_review_op(tmp_path)
    verdict = authorize(
        op,
        tool="glob",
        path=str(op),
        command="op_kernel/**",
        agent="ce-reviewer",
        action="code_review",
    )
    assert verdict.get("decision") == "allow", verdict
    assert verdict.get("reason_code") != "SOURCE_READ_USE_UO_QUERY"


def test_glob_tests_not_uo_query_fence(tmp_path: Path) -> None:
    op = _ce_review_op(tmp_path)
    (op / "tests").mkdir()
    (op / "tests" / "t.cpp").write_text("int t;\n", encoding="utf-8")
    verdict = authorize(
        op,
        tool="glob",
        path=str(op),
        command="tests/**",
        agent="ce-reviewer",
        action="code_review",
    )
    assert verdict.get("decision") == "allow", verdict
    assert verdict.get("reason_code") != "SOURCE_READ_USE_UO_QUERY"


def test_ce_reviewer_readonly_git_log_allowed(tmp_path: Path) -> None:
    op = _ce_review_op(tmp_path, with_uo=False)
    log_v = authorize(
        op,
        tool="bash",
        command="git log --oneline -8",
        agent="ce-reviewer",
        action="code_review",
    )
    assert log_v.get("decision") == "allow", log_v
    assert log_v.get("reason_code") == "GIT_READONLY"
    show_v = authorize(
        op,
        tool="bash",
        command="git show --stat HEAD",
        agent="ce-reviewer",
        action="code_review",
    )
    assert show_v.get("decision") == "allow", show_v
    diff_v = authorize(
        op,
        tool="bash",
        command="git diff --stat HEAD~1",
        agent="ce-reviewer",
        action="code_review",
    )
    assert diff_v.get("decision") == "allow", diff_v


def test_ce_reviewer_git_checkout_and_blob_denied(tmp_path: Path) -> None:
    op = _ce_review_op(tmp_path, with_uo=False)
    checkout = authorize(
        op,
        tool="bash",
        command="git checkout HEAD -- op_kernel/arch35/k.cpp",
        agent="ce-reviewer",
        action="code_review",
    )
    assert checkout.get("decision") == "ask", checkout
    blob = authorize(
        op,
        tool="bash",
        command="git show HEAD:op_kernel/arch35/k.cpp",
        agent="ce-reviewer",
        action="code_review",
    )
    assert blob.get("decision") == "ask", blob


def test_readonly_powershell_if_probe_allowed(tmp_path: Path) -> None:
    op = _ce_review_op(tmp_path, with_uo=False)
    verdict = authorize(
        op,
        tool="bash",
        command="if (Test-Path .ascendc-pilot) { Get-ChildItem .ascendc-pilot }",
        agent="ce-reviewer",
        action="code_review",
    )
    assert verdict.get("decision") == "allow", verdict
    assert verdict.get("reason_code") == "BASH_READONLY_INSPECT"


def test_spec_method_infers_intent_not_narrate_only() -> None:
    method = (REPO / "skills" / "standalone-review" / "references" / "spec.md").read_text(encoding="utf-8")
    assert "粗意图" in method
    assert "完成度" in method
    assert "只陈述理解就算完成" in method or "禁止「只陈述理解就算完成」" in method
    assert "只陈述变更理解，不假装有计划" not in method
    standalone = (REPO / "skills" / "standalone-review" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "index.md" in standalone
    assert "禁止只陈述变更理解" in standalone
    prompt = (REPO / "prompts" / "tasks" / "ce" / "standalone-review.md").read_text(
        encoding="utf-8"
    )
    assert "index.md" in prompt
    assert "diff.md" not in prompt.split("请阅读")[0] if "请阅读" in prompt else True
    assert "Change index" in prompt


def test_change_capture_writes_index_not_as_novel(tmp_path: Path) -> None:
    from ascendc_pilot.actions.engines import _write_change_capture_artifacts

    diff = """diff --git a/op_kernel/arch35/k.cpp b/op_kernel/arch35/k.cpp
--- a/op_kernel/arch35/k.cpp
+++ b/op_kernel/arch35/k.cpp
@@ -1,1 +1,3 @@
 int x;
+void CalBandDeterIndex() {}
+int DeterBandScheduleMode = 1;
"""
    out = tmp_path / "change_capture"
    artifacts = _write_change_capture_artifacts(
        out,
        diff_text=diff,
        project_root=tmp_path,
        architecture="arch35",
        base_sha="aaa",
        head_sha="bbb",
    )
    index = Path(artifacts["index"])
    assert index.is_file()
    text = index.read_text(encoding="utf-8")
    assert "Suggested uo-query" in text
    assert "CalBandDeterIndex" in text
    suggested = [ln for ln in text.splitlines() if ln.startswith("- `uo-query")]
    assert suggested, text
    assert suggested[0] == "- `uo-query CalBandDeterIndex`"
    assert any("uo-query --file" in ln for ln in suggested)
    assert "Do not linearly read" in text
    assert (out / "uo_hints.md").is_file()
    assert (out / "diff.md").is_file()
    assert "forensic" in (out / "diff.md").read_text(encoding="utf-8").lower()
    hunks = list((out / "hunks").glob("*.diff"))
    assert hunks
    assert artifacts["index"].endswith("index.md")


def test_change_capture_index_subject_from_head_commit(tmp_path: Path) -> None:
    from ascendc_pilot.actions.engines import _write_change_capture_artifacts

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "t"], cwd=tmp_path, check=True, capture_output=True
    )
    src = tmp_path / "op_kernel" / "arch35"
    src.mkdir(parents=True)
    (src / "k.cpp").write_text("int x;\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "formal deter band"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    diff = """diff --git a/op_kernel/arch35/k.cpp b/op_kernel/arch35/k.cpp
--- a/op_kernel/arch35/k.cpp
+++ b/op_kernel/arch35/k.cpp
@@ -1,1 +1,2 @@
 int x;
+void CalBandDeterIndex() {}
"""
    artifacts = _write_change_capture_artifacts(
        tmp_path / "change_capture",
        diff_text=diff,
        project_root=tmp_path,
        architecture="arch35",
        base_sha=head,
        head_sha=head,
    )
    text = Path(artifacts["index"]).read_text(encoding="utf-8")
    assert "formal deter band" in text
    suggested = [ln for ln in text.splitlines() if ln.startswith("- `uo-query")]
    assert suggested and suggested[0] == "- `uo-query CalBandDeterIndex`"
