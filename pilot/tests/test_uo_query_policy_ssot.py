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


def test_splitaxis_example_is_non_normative() -> None:
    product_map = _text("skills/operator-analysis/references/uo-product-map.md")
    assert "non-normative" in product_map
    assert "examples/uo-query-splitaxis/" in product_map
