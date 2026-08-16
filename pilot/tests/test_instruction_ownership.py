"""Instruction ownership: METHOD load, confirm skip, compiler fanout, shared refs."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from ascendc_pilot.actions.method_bundle import materialize_method_bundle
from ascendc_pilot.actions.runtime import _load_method_and_prompt, _resolve_capability_method, prepare_action
from ascendc_pilot.agents_registry import load_agent_meta
from ascendc_pilot.paths import ce_root, ensure_agent_layout
from ascendc_pilot.query_slices import plan_query_slices
from ascendc_pilot.state import start_workflow


REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

Q18 = (
    "950 上一个 FP16 dropout 的 case，D=80，B=1 N=4 S=2048。"
    "host 算出 TilingKey 了，板上却报找不到 kernel。"
    "同一份 shape 打开确定性 TND 之后能编过、tiling 也成功，可是一进核 "
    "coreNum/s1/s2 就是垃圾，连跑下来 dK 对不齐、dQ 齐。"
    "把确定性关掉又能跑完，但核占不满，只有四个 AIC 在动，"
    "msprof 里 AIC 堵着等 AIV 的 L1。"
    "先别改 VF，按 CodeMap 把这条路径说清楚；缺实际 seq 或分核轴就说还缺什么，"
    "不要先认定是同一处 bug。"
)

Q9 = "950 上某 FP16、D=80、带 dropout 的 case 报 kernel 找不到。host 算出的 TilingKey 在 ASCENDC_TPL_SEL 里一定有吗？"

_SKILL_BODIES = (
    "Open = O - V - X",
    "T = (R ∩ T) ∪ E",
    "Materialized skill:",
)


def _method(skill: str, cap: str) -> str:
    return (REPO / "skills" / skill / "capabilities" / cap / "METHOD.md").read_text(encoding="utf-8")


def test_resolver_is_path_join_not_heuristic() -> None:
    assert _resolve_capability_method(REPO, {"id": "kb_lookup", "task_prompt_id": "uo/codemap-query"}) is None
    path = _resolve_capability_method(
        REPO,
        {"action_method_id": "operator-analysis/uo-query"},
    )
    assert path == REPO / "skills" / "operator-analysis" / "capabilities" / "uo-query" / "METHOD.md"


def test_subagent_llm_actions_have_existing_method_files() -> None:
    from ascendc_pilot.workflows import WORKFLOWS

    missing: list[str] = []
    for wid, meta in WORKFLOWS.items():
        if not isinstance(meta, dict) or meta.get("reserved"):
            continue
        for action in meta.get("actions") or []:
            if str(action.get("execution_mode") or "") != "subagent":
                continue
            if not str(action.get("task_prompt_id") or "").strip():
                continue
            mid = str(action.get("action_method_id") or "")
            default = f"{wid}/{str(action.get('id') or '').replace('_', '-')}"
            assert mid and mid != default, f"{wid}/{action.get('id')} used default {default}"
            skill, _, cap = mid.partition("/")
            mp = REPO / "skills" / skill / "capabilities" / cap / "METHOD.md"
            if not mp.is_file() or not mp.read_text(encoding="utf-8").strip():
                missing.append(f"{wid}/{action.get('id')} -> {mid}")
    assert missing == []


def test_standalone_review_session_excludes_certificate_method(tmp_path: Path) -> None:
    method, prompt = _load_method_and_prompt(
        REPO,
        {
            "action_method_id": "code-review/standalone-review",
            "task_prompt_id": "ce/standalone-review",
        },
    )
    assert "H0" in method and "H1" in method
    assert "Open = O - V - X" not in method
    assert "Open = O - V - X" not in prompt
    assert "quick" in method.lower()
    skill_ids = list(load_agent_meta("ce-reviewer", str(REPO)).get("skill_ids") or [])
    assert "code-engineering" in skill_ids
    sdir = tmp_path / "ce-review"
    mat = materialize_method_bundle(
        sdir,
        skill_ids=skill_ids,
        existing_method=method,
        project_root=REPO,
        prompt=prompt,
    )
    assert mat.get("ok") is True, mat
    packed = (sdir / "method.md").read_text(encoding="utf-8")
    assert "Open = O - V - X" not in packed
    assert "Materialized skill:" not in packed
    assert "# 代码审查" not in packed
    assert "Domain map (do not inline): `skills/code-review/SKILL.md`" in packed


def test_verify_review_session_is_obligation_method_not_standalone(tmp_path: Path) -> None:
    method, prompt = _load_method_and_prompt(
        REPO,
        {
            "action_method_id": "code-review/verify-review",
            "task_prompt_id": "ce/code-review",
        },
    )
    assert "VERIFIED" in method
    assert "excepted_obligations" in method or "不签发" in method
    assert "三种入口" not in method
    assert "**quick**" not in method
    assert "Open = O - V - X" not in method
    skill_ids = list(load_agent_meta("ce-reviewer", str(REPO)).get("skill_ids") or [])
    sdir = tmp_path / "ce-verify"
    mat = materialize_method_bundle(
        sdir,
        skill_ids=skill_ids,
        existing_method=method,
        project_root=REPO,
        prompt=prompt,
    )
    assert mat.get("ok") is True, mat
    packed = (sdir / "method.md").read_text(encoding="utf-8")
    assert "三种入口" not in packed
    assert "Open = O - V - X" not in packed
    assert "Materialized skill:" not in packed


def test_confirm_prepare_skips_cognitive_skills(tmp_path: Path) -> None:
    op = tmp_path / "demo_op"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    start_workflow(
        op,
        "tg-init",
        phase="confirm",
        force_phase=True,
        architecture="arch35",
        op_name="DemoOp",
    )
    result = prepare_action(op, "human_confirm")
    assert result.get("ok") is True, result
    session = Path(str(result["session_dir"]))
    method = (session / "method.md").read_text(encoding="utf-8")
    bundle = yaml.safe_load((session / "bundle.yaml").read_text(encoding="utf-8"))
    assert bundle.get("method_materialized", {}).get("host_owned_confirm") is True
    assert "Host-owned confirmation" in method
    for phrase in _SKILL_BODIES:
        assert phrase not in method
    assert "CALLS / READS / WRITES" not in method
    assert "五种入口" not in method
    assert not list((session / "refs").rglob("SKILL.md"))


def test_compiler_fanout_matches_dispatch_tasks(tmp_path: Path) -> None:
    planned = plan_query_slices(Q18)
    assert len(planned) >= 2
    modes = [str(row.get("first_mode") or "") for row in planned]
    assert "" not in modes
    assert len(modes) == len(set(modes))

    op = tmp_path / "demo_op"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    uo_prod = op / ".ascendc-pilot" / "arch35" / "uo"
    uo_prod.mkdir(parents=True, exist_ok=True)
    (uo_prod / "Demo.arch35.uo").write_bytes(b"SQLite format 3\x00")
    start_workflow(op, "uo-query", architecture="arch35", intent=Q18)
    result = prepare_action(op, "kb_lookup")
    assert result.get("ok") is True, result
    tasks = result.get("dispatch_tasks") or []
    assert len(tasks) == len(planned)
    stub_modes = [str(t.get("first_mode") or "") for t in tasks]
    assert stub_modes == modes
    for row in tasks:
        stub = str(row.get("task_prompt_stub") or "")
        assert "FIRST_QUERY:" in stub
        assert "--project" in stub
        assert "SLICE_ID=" in stub


def test_short_question_does_not_fanout(tmp_path: Path) -> None:
    assert plan_query_slices(Q9) == []
    op = tmp_path / "demo_op"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    uo_prod = op / ".ascendc-pilot" / "arch35" / "uo"
    uo_prod.mkdir(parents=True, exist_ok=True)
    (uo_prod / "Demo.arch35.uo").write_bytes(b"SQLite format 3\x00")
    start_workflow(op, "uo-query", architecture="arch35", intent=Q9)
    result = prepare_action(op, "kb_lookup")
    assert result.get("ok") is True, result
    assert not result.get("dispatch_tasks")


def test_shared_reference_projections_match_ssot() -> None:
    from sync_shared_references import SKILLS, check

    errors = check(REPO)
    assert errors == [], errors
    src = (REPO / "knowledge" / "shared-references" / "finding-format.md").read_bytes()
    for skill in SKILLS:
        dest = REPO / "skills" / skill / "references" / "finding-format.md"
        assert dest.read_bytes() == src
    ce = REPO / "skills" / "code-engineering" / "references" / "finding-format.md"
    assert not ce.is_file()


def test_instruction_ownership_lint_clean() -> None:
    from check_instruction_ownership import errors

    assert errors(REPO) == []


def test_scenario_targeted_plan_intent_does_not_widen_to_declared(tmp_path: Path) -> None:
    from ascendc_pilot.actions.tg_plan_targets import plan_intent

    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "tg-plan", architecture="arch35", op_name="DemoOp")
    scenarios = ce_root(tmp_path, arch="arch35") / "scenarios" / "scenario_set.yaml"
    scenarios.parent.mkdir(parents=True, exist_ok=True)
    scenarios.write_text(
        "schema: ce-scenario-set/v1\nitems:\n  - id: P-cast\n  - id: F-pipe\n",
        encoding="utf-8",
    )
    result = plan_intent(tmp_path, {"mode": "scenario_targeted"})
    assert result.get("ok") is True, result
    assert result.get("target_mode") == "scenario_set"
    assert result.get("forbid_cartesian_over_declared") is True
    assert result.get("do_not_widen_to_declared_set") is True
    assert result.get("scenarios") == ["P-cast", "F-pipe"]


def test_scenario_targeted_empty_set_fail_closed(tmp_path: Path) -> None:
    from ascendc_pilot.actions.tg_plan_targets import plan_intent

    ensure_agent_layout(tmp_path, arch="arch35")
    start_workflow(tmp_path, "tg-plan", architecture="arch35", op_name="DemoOp")
    result = plan_intent(tmp_path, {"mode": "scenario_targeted"})
    assert result.get("ok") is False
    assert result.get("reason_code") == "SCENARIO_SET_EMPTY"
