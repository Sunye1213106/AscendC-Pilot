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

    skill = _text("skills/uo-query/SKILL.md")
    prompt = _text("prompts/tasks/uo/codemap-query.md")
    invariant = _text("pilot/policies/invariants/control-invariants.md")
    access = _text("pilot/policies/invariants/code-access-invariants.md")
    reason = _text("pilot/policies/invariants/intent-reasoning.md")

    assert "禁止 Write `answer.yaml`" in invariant
    assert "partial" in skill or "不存在" in skill
    assert "Dim=V" in access
    assert "禁止 `--mode`" in access
    assert "--query" in _text("pilot/ascendc_pilot/cli.py")
    assert "相关 ≠ 单域" in reason
    assert "fanout" in reason.lower() or "隔离" in reason

    assert "return_value" not in prompt
    assert "answer.yaml" not in prompt
    assert "--finalize" not in prompt


def test_uo_query_router_owned_by_primary() -> None:
    reason = _text("pilot/policies/invariants/intent-reasoning.md")
    skill = _text("skills/uo-query/SKILL.md")
    assert "compile" not in reason
    assert "FIRST_QUERY" not in reason
    assert "分别派" in reason or "分别委派" in reason
    assert "综合只在主控" in reason
    assert "相关 ≠ 单域" in reason
    assert "相关 ≠ 单域" not in skill
    assert "禁止 `--mode`" in _text("pilot/policies/invariants/code-access-invariants.md")
    assert "routing/uo-query.md" not in skill
    ctx = _text("agents/CONTEXT.md")
    assert "主控当前会话 `acp uo-query`" not in ctx


def test_uo_query_host_behavior_not_phrase_sync() -> None:
    policy = _text("pilot/policies/pilot-control/POLICY.md")
    invariant = _text("pilot/policies/invariants/control-invariants.md")
    command_src = _text("scripts/compose_opencode_commands.py")
    driver_facade = _text("opencode-plugin/pilot-driver.ts")
    driver_core = _text("opencode-plugin/pilot-driver-core.ts")
    driver = driver_facade + "\n" + driver_core
    hook = _text("opencode-plugin/ascendc-pilot.ts")
    assert "禁止" in policy and "pilot_run" in policy
    assert "uo-query" in invariant
    assert "host_step.tasks" in invariant
    assert "不要 `pilot_run`" in command_src
    assert "routing/uo-query.md" not in command_src
    assert "禁止在 Task 正文写 `--mode`" not in command_src
    assert "禁止 `--mode`" in _text("pilot/policies/invariants/code-access-invariants.md")
    assert "丢掉" not in command_src
    assert "--mode locate" not in hook
    assert "UO_QUERY_NOT_HOST_DRIVEN" in driver
    assert "primary_router" in driver
    assert 'startedKind === "primary_router"' in driver


def test_splitaxis_example_is_non_normative() -> None:
    product_map = _text("skills/uo-query/references/uo-product-map.md")
    assert "non-normative" in product_map
    assert "examples/uo-query-splitaxis/" in product_map


def test_ce_intent_grill_staging_in_bundle_profile() -> None:
    from ascendc_pilot.context.profiles import get_profile

    profile = get_profile("ce-plan-intent-grill")
    refs = list(profile.references) if profile is not None else []
    assert any("intent-grill-staging.md" in str(r) for r in refs)
    staging = _text("skills/ce-intent-grill/references/intent-grill-staging.md")
    method = _text("skills/ce-intent-grill/SKILL.md")
    for token in ("范围", "不做的事", "测试内容", "未决"):
        assert token in staging
        assert token in method
