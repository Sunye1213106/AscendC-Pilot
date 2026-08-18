"""Instruction ownership: METHOD load, confirm skip, query prepare, shared refs."""

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
    from ascendc_pilot.actions.method_bundle import method_skill_ids_for_action
    from ascendc_pilot.context.profiles import get_profile

    profile = get_profile("ce-review-code-review")
    extra = list(profile.references) if profile is not None else []
    scoped = method_skill_ids_for_action(
        {"action_method_id": "code-review/standalone-review"},
        agent_skill_ids=skill_ids,
        extra_ref_paths=extra,
    )
    assert scoped == ["code-review"]
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
    assert "Domain map (do not inline): `skills/code-review/SKILL.md`" in packed
    assert "skills/code-engineering/SKILL.md" not in packed


def test_method_skill_ids_intersect_profile_and_ceiling() -> None:
    from ascendc_pilot.actions.method_bundle import method_skill_ids_for_action
    from ascendc_pilot.context.profiles import get_profile

    ceiling = ["code-review", "operator-analysis", "code-engineering", "testcase-generation"]
    fd = get_profile("ce-intent-feature-decompose")
    assert method_skill_ids_for_action(
        {"action_method_id": "code-engineering/ce-feature-decompose"},
        agent_skill_ids=ceiling,
        extra_ref_paths=list(fd.references) if fd else [],
    ) == ["code-engineering"]
    knobs = get_profile("ce-impact-scenario-knobs")
    assert method_skill_ids_for_action(
        {"action_method_id": "code-engineering/ce-scenario-knobs"},
        agent_skill_ids=ceiling,
        extra_ref_paths=list(knobs.references) if knobs else [],
    ) == ["code-engineering", "testcase-generation"]


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
    from ascendc_pilot.workflows import WORKFLOWS

    confirm = next(a for a in WORKFLOWS["tg-init"]["actions"] if a["id"] == "human_confirm")
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
    oracle_ssot = (REPO / "knowledge" / "shared-references" / "harness-oracle.md").read_bytes()
    for skill in ("testcase-generation", "code-engineering"):
        dest = REPO / "skills" / skill / "references" / "harness-oracle.md"
        assert dest.is_file()
        assert dest.read_bytes() == oracle_ssot
    for skill in ("operator-analysis", "source-proof", "code-review"):
        leaked = REPO / "skills" / skill / "references" / "harness-oracle.md"
        assert not leaked.is_file()


def test_instruction_ownership_lint_clean() -> None:
    from check_instruction_ownership import errors

    assert errors(REPO) == []


def test_all_subagent_llm_actions_materialize_method_bundle(tmp_path: Path) -> None:
    from ascendc_pilot.context.profiles import get_profile
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
            profile = get_profile(action.get("context_profile_id"))
            extra = list(profile.references) if profile is not None else []
            from ascendc_pilot.actions.method_bundle import method_skill_ids_for_action

            skill_ids = method_skill_ids_for_action(
                action,
                agent_skill_ids=ceiling,
                extra_ref_paths=extra,
            )
            sdir = tmp_path / wid / str(action.get("id"))
            mat = materialize_method_bundle(
                sdir,
                skill_ids=skill_ids,
                existing_method=method,
                project_root=REPO,
                prompt=prompt,
                extra_ref_paths=extra,
            )
            if not mat.get("ok") or mat.get("unauthorized") or mat.get("missing"):
                failures.append(
                    f"{wid}/{action.get('id')}: ok={mat.get('ok')} "
                    f"missing={mat.get('missing')} unauthorized={mat.get('unauthorized')}"
                )
    assert failures == []


def test_cross_tree_harness_oracle_is_unauthorized(tmp_path: Path) -> None:
    mat = materialize_method_bundle(
        tmp_path / "x",
        skill_ids=["code-engineering"],
        existing_method="see `skills/testcase-generation/references/harness-oracle.md`",
        project_root=REPO,
    )
    assert mat.get("ok") is False
    unauthorized = [str(x) for x in (mat.get("unauthorized") or [])]
    assert any("testcase-generation" in x and "harness-oracle" in x for x in unauthorized)


def test_confirm_and_deterministic_omit_action_method_id() -> None:
    from ascendc_pilot.workflows import WORKFLOWS

    bad: list[str] = []
    for wid, meta in WORKFLOWS.items():
        if not isinstance(meta, dict) or meta.get("reserved"):
            continue
        for action in meta.get("actions") or []:
            mode = str(action.get("execution_mode") or "")
            mid = str(action.get("action_method_id") or "").strip()
            if mode in {"deterministic", "primary_interactive"} and mid:
                bad.append(f"{wid}/{action.get('id')}: {mode} has {mid}")
            if mode == "subagent" and str(action.get("task_prompt_id") or "").strip() and not mid:
                bad.append(f"{wid}/{action.get('id')}: LLM Action missing method_id")
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
        "pilot/policies/invariants/control-invariants.md",
        "pilot/policies/invariants/host-runtime-contract.md",
    )
    hits: list[str] = []
    for rel in rels:
        text = (REPO / rel).read_text(encoding="utf-8")
        for phrase in stale:
            if phrase in text:
                hits.append(f"{rel}: {phrase}")
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
