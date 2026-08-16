# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_uo_query_assets_agree_on_readonly_return_value() -> None:
    agent = yaml.safe_load(_text("agents/uo-query.yaml"))
    assert agent["id"] == "uo-query"
    assert agent["write_scopes"] == []

    method = _text("skills/operator-analysis/capabilities/uo-query/METHOD.md")
    prompt = _text("prompts/tasks/uo/codemap-query.md")
    policy = _text("pilot/policies/pilot-control/POLICY.md")
    invariant = _text("pilot/policies/invariants/control-invariants.md")

    control_text = "\n".join((method, policy, invariant))
    all_text = "\n".join((control_text, prompt))
    assert "return_value" in control_text
    assert "MUST NOT Write `answer.yaml`" in invariant
    assert "源码作答" in method
    assert "禁止 Glob/dir/tree 找 `.uo`" in method
    assert "template_match" in method
    assert "dim_coverage" in method
    assert "kernel_launch" in method
    assert "findstr" in method
    assert "--query" in _text("pilot/ascendc_pilot/cli.py")
    assert "session `method.md`" in method
    assert "源码作答" in policy

    # Task prompt stays cognitive/task-only; transport plumbing belongs to
    # METHOD/Policy/Runtime so skill architecture lint can enforce separation.
    assert "return_value" not in prompt
    assert "answer.yaml" not in prompt
    assert "--finalize" not in prompt

    stale_phrases = (
        "subagent MUST Write lease `answer.yaml`",
        "subagent 必须把答案写入 lease 的 `answer.yaml`",
        "返工让 subagent 补写该文件",
    )
    for phrase in stale_phrases:
        assert phrase not in all_text


def test_uo_query_visible_router_ssot() -> None:
    skill = _text("skills/operator-analysis/SKILL.md")
    method = _text("skills/operator-analysis/capabilities/uo-query/METHOD.md")
    policy = _text("pilot/policies/pilot-control/POLICY.md")
    invariant = _text("pilot/policies/invariants/control-invariants.md")
    command_src = _text("scripts/compose_opencode_commands.py")
    driver = _text("opencode-plugin/pilot-driver.ts")
    hook = _text("opencode-plugin/ascendc-pilot.ts")
    docs = _text("docs/architecture/agent-runtime.md")
    assert "可见 LLM 路由" in skill
    assert "禁止 `pilot_run`" in skill
    assert "先对人说出路由" in skill
    assert "同一轮" in skill
    assert "综合" in skill
    assert "相关 ≠ 单域" in skill
    assert "更连贯" in skill
    assert "FIRST_QUERY" in skill
    assert "整题" in skill
    assert "Q6" not in skill
    assert "Q7" not in skill
    assert "Q18" not in skill
    assert "整题" in policy
    assert "整题" in command_src
    assert "kernel_launch" in method
    assert "search" in method and "ProcessVec" in method
    assert "FIRST_QUERY" in method
    assert "相关 ≠ 单域" in policy
    assert "FIRST_QUERY" in policy
    assert "related ≠ 单域" in invariant
    assert "FIRST_QUERY" in invariant
    assert "相关 ≠ 单域" in command_src
    assert "FIRST_QUERY" in command_src
    assert "相关 ≠ 单域" in docs
    assert "SLICE_ID" in method
    assert "可见 LLM 路由" in policy
    assert "禁止" in policy and "pilot_run" in policy
    assert "except `uo-query`" in invariant
    assert "Never" in invariant and "uo-query" in invariant
    assert "不要 `pilot_run`" in command_src
    assert "UO_QUERY_NOT_HOST_DRIVEN" in driver
    assert "primary_router" in driver
    assert 'startedKind === "primary_router"' in driver
    assert "perm.task = \"allow\"" in hook
    assert "可见 LLM 路由" in docs or "可见分类" in docs
    assert "host_step.tasks" in invariant  # still for TG/CE Host dispatch
    assert '"tasks"' in driver
    assert "native_tasks" in driver
    assert "SLICE_ID=" in hook
    assert "fanout_slice" in hook
    assert "primary_synthesize" in hook


def test_splitaxis_example_is_non_normative() -> None:
    product_map = _text("skills/operator-analysis/references/uo-product-map.md")
    assert "non-normative" in product_map
    assert "examples/uo-query-splitaxis/" in product_map
