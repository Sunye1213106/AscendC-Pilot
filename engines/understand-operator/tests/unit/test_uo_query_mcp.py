# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

import pytest

from uo_init.query_mcp import handle, run_query
from uo_init.store.reader import find_uo_product

FAG = Path(
    r"D:\PR-review\pr_workspace\.ascendc-pr"
    r"\gitcode.com--cann--ops-transformer--pr-9851"
    r"\attention\flash_attention_score_grad"
)
PRODUCT = find_uo_product(FAG, architecture="arch35")

pytestmark = pytest.mark.skipif(
    PRODUCT is None or not Path(PRODUCT).is_file(),
    reason="FAG arch35 .uo product is not present",
)


def test_run_query_name_card() -> None:
    payload = run_query(project=str(FAG), architecture="arch35", pattern="IsPse")
    assert payload.get("ok") is True
    assert payload.get("shape") == "name"
    assert payload.get("count", 0) >= 1


def test_mcp_tools_list_and_call() -> None:
    listed = handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    tools = listed["result"]["tools"]
    assert tools[0]["name"] == "uo_query"
    called = handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "uo_query",
                "arguments": {
                    "project": str(FAG),
                    "architecture": "arch35",
                    "pattern": "IsPse=1",
                },
            },
        }
    )
    assert called["result"]["isError"] is False
    body = json.loads(called["result"]["content"][0]["text"])
    assert body.get("ok") is True
    assert body.get("shape") == "cover"
    assert int(body.get("matching_block_count") or 0) > 0
