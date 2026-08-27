"""Instruction ownership: METHOD load, confirm skip, query prepare."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from ascendc_pilot.actions.method_bundle import materialize_method_bundle
from ascendc_pilot.actions.runtime import _load_method_and_prompt, _resolve_capability_method, prepare_action
from ascendc_pilot.agents_registry import load_agent_meta
from ascendc_pilot.paths import ce_root, ensure_agent_layout
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


def _method(skill_id: str) -> str:
    return (REPO / "skills" / skill_id / "SKILL.md").read_text(encoding="utf-8")


def test_resolver_is_path_join_not_heuristic() -> None:
    assert _resolve_capability_method(REPO, {"id": "kb_lookup", "task_prompt_id": "uo/codemap-query"}) is None
    path = _resolve_capability_method(
        REPO,
        {"skill_id": "uo-query"},
    )
    assert path == REPO / "skills" / "uo-query" / "SKILL.md"


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
            mid = str(action.get("skill_id") or action.get("action_method_id") or "")
            if "/" in mid:
                mid = mid.rsplit("/", 1)[-1]
            mp = REPO / "skills" / mid / "SKILL.md"
            if not mp.is_file() or not mp.read_text(encoding="utf-8").strip():
                missing.append(f"{wid}/{action.get('id')} -> {mid}")
    assert missing == []


def test_standalone_review_session_excludes_certificate_method(tmp_path: Path) -> None:
    method, prompt = _load_method_and_prompt(
        REPO,
        {
            "skill_id": "standalone-review",
            "task_prompt_id": "ce/standalone-review",
        },
    )
    assert "两轴" in method or "Spec" in method
    assert "Open = O - V - X" not in method
    assert "Open = O - V - X" not in prompt
    skill_ids = list(load_agent_meta("ce-reviewer", str(REPO)).get("skill_ids") or [])
    assert "standalone-review" in skill_ids
    from ascendc_pilot.actions.method_bundle import method_skill_ids_for_action

    scoped = method_skill_ids_for_action(
        {"skill_id": "standalone-review"},
        agent_skill_ids=skill_ids,
    )
    assert "standalone-review" in scoped
    sdir = tmp_path / "ce-review"
    mat = materialize_method_bundle(
        sdir,
        skill_ids=scoped,
        existing_method=method,
        project_root=REPO,
        prompt=prompt,
    )
    assert mat.get("ok") is True, mat
    packed = (sdir / "method.md").read_text(encoding="utf-8")
    assert "Open = O - V - X" not in packed
    assert "Materialized skill:" not in packed
    assert "# 代码审查" not in packed
    assert "Domain map" not in packed
    assert "skills/code-engineering/SKILL.md" not in packed


def test_method_skill_ids_intersect_action_and_ceiling() -> None:
    from ascendc_pilot.actions.method_bundle import method_skill_ids_for_action

    ceiling = ["ce-plan-draft", "ce-apply", "standalone-review", "uo-query"]
    assert method_skill_ids_for_action(
        {"skill_id": "ce-plan-draft"},
        agent_skill_ids=ceiling,
    ) == ["ce-plan-draft"]
    assert method_skill_ids_for_action(
        {"skill_id": "ce-apply"},
        agent_skill_ids=ceiling,
    ) == ["ce-apply"]


def test_overlay_skill_id_is_not_stripped_by_ceiling() -> None:
    from ascendc_pilot.actions.method_bundle import method_skill_ids_for_action

    ceiling = ["bind-init", "test-plan", "solve", "uo-query"]
    assert method_skill_ids_for_action(
        {"skill_id": "source-proof"},
        agent_skill_ids=ceiling,
    ) == ["source-proof"]
    assert method_skill_ids_for_action(
        {"skill_id": "proof-review"},
        agent_skill_ids=ceiling,
    ) == ["proof-review"]
    assert method_skill_ids_for_action(
        {"skill_id": "source-proof"},
        agent_skill_ids=ceiling,
        extra_ref_paths=["skills/uo-query/references/does-not-need-to-exist.md"],
    ) == ["source-proof", "uo-query"]


def test_deleted_verify_review_method_is_gone() -> None:
    method, prompt = _load_method_and_prompt(
        REPO,
        {
            "action_method_id": "code-review/verify-review",
            "task_prompt_id": "ce/code-review",
        },
    )
    assert method == ""
    assert prompt == ""
    standalone, standalone_prompt = _load_method_and_prompt(
        REPO,
        {
            "skill_id": "standalone-review",
            "task_prompt_id": "ce/standalone-review",
        },
    )
    assert "两轴" in standalone or "Spec" in standalone
    assert standalone_prompt.strip()


def test_confirm_prepare_skips_cognitive_skills(tmp_path: Path) -> None:
    op = tmp_path / "demo_op"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    start_workflow(
        op,
        "tg-plan",
        phase="approve",
        force_phase=True,
        architecture="arch35",
        op_name="DemoOp",
    )
    result = prepare_action(op, "plan_approve")
    assert result.get("ok") is True, result
    session = Path(str(result["session_dir"]))
    method = (session / "method.md").read_text(encoding="utf-8")
    bundle = yaml.safe_load((session / "bundle.yaml").read_text(encoding="utf-8"))
    assert bundle.get("method_materialized", {}).get("host_owned_confirm") is True
    assert "Host-owned confirmation" in method
    from ascendc_pilot.workflows import WORKFLOWS

    confirm = next(a for a in WORKFLOWS["tg-plan"]["actions"] if a["id"] == "plan_approve")
    assert not confirm.get("action_method_id")
    for phrase in _SKILL_BODIES:
        assert phrase not in method
    assert "CALLS / READS / WRITES" not in method
    assert "五种入口" not in method
    assert not list((session / "refs").rglob("SKILL.md"))


def test_prepare_kb_lookup_does_not_fanout_tasks(tmp_path: Path) -> None:
    op = tmp_path / "demo_op"
    op.mkdir()
    ensure_agent_layout(op, arch="arch35")
    uo_prod = op / ".ascendc-pilot" / "arch35" / "uo"
    uo_prod.mkdir(parents=True, exist_ok=True)
    (uo_prod / "Demo.arch35.uo").write_bytes(b"SQLite format 3\x00")
    start_workflow(op, "uo-query", architecture="arch35", intent=Q18)
    result = prepare_action(op, "kb_lookup")
    assert result.get("ok") is True, result
    assert not result.get("dispatch_tasks")
    stub = str(result.get("task_prompt_stub") or "")
    assert "FIRST_QUERY:" not in stub
    assert "SLICE_ID=" not in stub


def test_short_question_does_not_fanout(tmp_path: Path) -> None:
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


def test_instruction_ownership_lint_clean() -> None:
    from check_instruction_ownership import errors

    assert errors(REPO) == []


def test_all_subagent_llm_actions_materialize_method_bundle(tmp_path: Path) -> None:
    from ascendc_pilot.workflows import WORKFLOWS

    failures: list[str] = []
    for wid, meta in WORKFLOWS.items():
        if not isinstance(meta, dict) or meta.get("reserved"):
            continue
        for action in meta.get("actions") or []:
            if str(action.get("execution_mode") or "") != "subagent":
                continue
            if not str(action.get("task_prompt_id") or "").strip():
                continue
            method, prompt = _load_method_and_prompt(REPO, action)
            actor = str(action.get("agent_id") or "")
            ceiling = list(
                load_agent_meta(actor, str(REPO)).get("max_skill_ids")
                or load_agent_meta(actor, str(REPO)).get("skill_ids")
                or []
            )
            from ascendc_pilot.actions.method_bundle import method_skill_ids_for_action

            skill_ids = method_skill_ids_for_action(
                action,
                agent_skill_ids=ceiling,
            )
            sdir = tmp_path / wid / str(action.get("id"))
            axes = list(action.get("fanout_axes") or [])
            copy_declared = not (
                bool(axes) and all(str(a.get("method_ref") or "").strip() for a in axes)
            )
            mat = materialize_method_bundle(
                sdir,
                skill_ids=skill_ids,
                existing_method=method,
                project_root=REPO,
                prompt=prompt,
                current_skill_id=str(action.get("skill_id") or "").rsplit("/", 1)[-1],
                copy_declared_refs=copy_declared,
                explicit_refs=list(action.get("refs") or []),
            )
            if not mat.get("ok") or mat.get("unauthorized") or mat.get("missing"):
                failures.append(
                    f"{wid}/{action.get('id')}: ok={mat.get('ok')} "
                    f"missing={mat.get('missing')} unauthorized={mat.get('unauthorized')}"
                )
    assert failures == []


def test_cross_tree_foreign_reference_is_unauthorized(tmp_path: Path) -> None:
    mat = materialize_method_bundle(
        tmp_path / "x",
        skill_ids=["ce-apply"],
        existing_method="see `skills/solve/references/construct.md`",
        project_root=REPO,
        current_skill_id="ce-apply",
    )
    assert mat.get("ok") is False
    unauthorized = [str(x) for x in (mat.get("unauthorized") or [])]
    assert any("solve" in x and "construct.md" in x for x in unauthorized)


def test_bare_basename_extra_ref_is_ambiguous(tmp_path: Path) -> None:
    mat = materialize_method_bundle(
        tmp_path / "y",
        skill_ids=["ce-apply"],
        existing_method="# ce apply\n",
        project_root=REPO,
        extra_ref_paths=["gotchas.md"],
        current_skill_id="ce-apply",
    )
    assert mat.get("ok") is False
    assert mat.get("reason_code") == "REFERENCE_AMBIGUOUS"


def test_confirm_and_deterministic_omit_action_method_id() -> None:
    from ascendc_pilot.workflows import WORKFLOWS

    bad: list[str] = []
    for wid, meta in WORKFLOWS.items():
        if not isinstance(meta, dict) or meta.get("reserved"):
            continue
        for action in meta.get("actions") or []:
            mode = str(action.get("execution_mode") or "")
            mid = str(action.get("skill_id") or action.get("action_method_id") or "").strip()
            if mode in {"deterministic", "primary_interactive"} and mid:
                bad.append(f"{wid}/{action.get('id')}: {mode} has {mid}")
            if mode == "subagent" and str(action.get("task_prompt_id") or "").strip() and not mid:
                bad.append(f"{wid}/{action.get('id')}: LLM Action missing skill_id")
    assert bad == []


def test_docs_do_not_claim_query_has_no_method_bundle() -> None:
    stale = (
        "query is not Host-prepared",
        "子代没有 session `prompt.md`",
        "uo-query 子代**没有** Host 物化的 session `prompt.md`",
        "不要 `kb_lookup --finalize`",
        "不 `finalize` kb_lookup",
    )
    rels = (
        "agents/uo-query.yaml",
        "docs/architecture/agent-runtime.md",
        "docs/architecture/workflows.md",
        "docs/modules/uo.md",
        "pilot/policies/pilot-control/POLICY.md",
        "pilot/policies/invariants/host-runtime-contract.md",
    )
    hits: list[str] = []
    for rel in rels:
        text = (REPO / rel).read_text(encoding="utf-8")
        for phrase in stale:
            if phrase in text:
                hits.append(f"{rel}: {phrase}")
    assert hits == []


def test_agent_playbooks_do_not_teach_acp_inspect_or_scan_steps() -> None:
    rels = (
        "docs/getting-started/quickstart.md",
        "tools/codemap/structured-ir-query/METHOD.md",
    )
    hits: list[str] = []
    for rel in rels:
        text = (REPO / rel).read_text(encoding="utf-8")
        for phrase in ("acp scan-architectures", "acp inspect ", "acp inspect-failure"):
            if phrase in text:
                hits.append(f"{rel}: {phrase}")
    tools = (REPO / "docs/getting-started/acp-tools.md").read_text(encoding="utf-8")
    agent_half = tools.split("## 人类在终端里", 1)[0]
    for phrase in ("acp scan-architectures", "acp inspect ", "acp inspect-failure"):
        if phrase in agent_half:
            hits.append(f"docs/getting-started/acp-tools.md (agent steps): {phrase}")
    assert hits == []


def test_producer_referee_write_scopes_do_not_overlap() -> None:
    from ascendc_pilot.workflows import WORKFLOWS

    agents = REPO / "agents"
    overlap: list[str] = []
    for wid, meta in WORKFLOWS.items():
        if not isinstance(meta, dict) or meta.get("reserved"):
            continue
        producer: set[str] = set()
        referee: set[str] = set()
        seen: set[str] = set()
        for action in meta.get("actions") or []:
            actor = str(action.get("agent_id") or "")
            role = str(action.get("role_id") or "")
            if not actor or actor in seen or role not in {"producer", "referee"}:
                continue
            seen.add(actor)
            path = agents / f"{actor}.yaml"
            if not path.is_file():
                continue
            meta_a = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            scopes = {str(s) for s in (meta_a.get("write_scopes") or [])}
            if role == "producer":
                producer |= scopes
            else:
                referee |= scopes
        both = producer & referee
        if both:
            overlap.append(f"{wid}: {sorted(both)}")
    assert overlap == []


def test_bind_columns_ssot_deletes_append_and_override() -> None:
    columns = (REPO / "skills" / "bind-init" / "references" / "columns.md").read_text(
        encoding="utf-8"
    )
    assert "禁止追加" in columns
    assert "先追加再接线" not in columns
    assert "只 Edit 一次" not in columns
    assert not (
        REPO / "skills" / "bind-init" / "references" / "column-binding-edge-cases.md"
    ).exists()

