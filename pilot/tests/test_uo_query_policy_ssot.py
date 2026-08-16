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
    invariant = _text("pilot/policies/invariants/control-invariants.md")

    assert "MUST NOT Write `answer.yaml`" in invariant
    assert "源码作答" in method
    assert "禁止 Glob/dir/tree 找 `.uo`" in method
    assert "template_match" in method
    assert "dim_coverage" in method
    assert "kernel_launch" in method
    assert "findstr" in method
    assert "--query" in _text("pilot/ascendc_pilot/cli.py")
    assert "session `method.md`" in method

    assert "return_value" not in prompt
    assert "answer.yaml" not in prompt
    assert "--finalize" not in prompt

    stale_phrases = (
        "subagent MUST Write lease `answer.yaml`",
        "subagent 必须把答案写入 lease 的 `answer.yaml`",
        "返工让 subagent 补写该文件",
    )
    all_text = "\n".join((method, prompt, invariant))
    for phrase in stale_phrases:
        assert phrase not in all_text


def test_uo_query_router_owned_by_method() -> None:
    router = _text("skills/operator-analysis/routing/uo-query.md")
    method = _text("skills/operator-analysis/capabilities/uo-query/METHOD.md")
    skill = _text("skills/operator-analysis/SKILL.md")
    assert "相关 ≠ 单域" in router
    assert "FIRST_QUERY" in router
    assert "host_step.tasks" in router
    assert "FIRST_QUERY" in method
    assert "SLICE_ID" in method
    assert "kernel_launch" in method
    assert "search" in method and "ProcessVec" in method
    assert "routing/uo-query.md" in skill
    assert "uo-query-router/METHOD.md" not in skill
    assert "相关 ≠ 单域" not in skill
    assert "Q6" not in skill
    assert "Q7" not in skill
    assert "Q18" not in skill


def test_uo_query_host_behavior_not_phrase_sync() -> None:
    policy = _text("pilot/policies/pilot-control/POLICY.md")
    invariant = _text("pilot/policies/invariants/control-invariants.md")
    command_src = _text("scripts/compose_opencode_commands.py")
    driver = _text("opencode-plugin/pilot-driver.ts")
    hook = _text("opencode-plugin/ascendc-pilot.ts")
    assert "禁止" in policy and "pilot_run" in policy
    assert "except `uo-query`" in invariant
    assert "Never" in invariant and "uo-query" in invariant
    assert "host_step.tasks" in invariant
    assert "不要 `pilot_run`" in command_src
    assert "routing/uo-query.md" in command_src
    assert "UO_QUERY_NOT_HOST_DRIVEN" in driver
    assert "primary_router" in driver
    assert 'startedKind === "primary_router"' in driver
    assert 'perm.task = "allow"' in hook
    assert '"tasks"' in driver
    assert "native_tasks" in driver
    assert "SLICE_ID=" in hook
    assert "fanout_slice" in hook
    assert "primary_synthesize" in hook


def test_splitaxis_example_is_non_normative() -> None:
    product_map = _text("skills/operator-analysis/references/uo-product-map.md")
    assert "non-normative" in product_map
    assert "examples/uo-query-splitaxis/" in product_map
