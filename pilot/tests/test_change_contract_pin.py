"""Wave 1: pin_facts is a Primary Host tool; clone does not auto-pin; plan_scope reads only the pin."""

from __future__ import annotations

from pathlib import Path

import yaml


def _op(root: Path) -> Path:
    op = root / "flash_op"
    (op / "op_host" / "arch35").mkdir(parents=True)
    return op


def test_pin_facts_writes_operator_change_contract(tmp_path: Path) -> None:
    from ascendc_pilot.change_contract import load_change_contract, pin_facts
    from ascendc_pilot.user_goal_core import control_root

    op = _op(tmp_path)
    out = pin_facts(
        op,
        kind="pr_regression",
        changed_files=["op_host/arch35/tiling.cpp"],
        base_sha="aaa",
        head_sha="bbb",
        consumers=["tg-plan"],
    )
    assert out.get("ok") is True
    path = control_root(op) / "change_contract.yaml"
    assert path.is_file()
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["schema"] == "tg-change-contract/v1"
    assert doc["kind"] == "pr_regression"
    assert doc["changed_files"] == ["op_host/arch35/tiling.cpp"]
    assert doc["base_sha"] == "aaa"
    assert doc["head_sha"] == "bbb"
    loaded = load_change_contract(op)
    assert loaded["changed_files"] == ["op_host/arch35/tiling.cpp"]


def test_clone_unique_does_not_write_change_contract(tmp_path: Path, monkeypatch) -> None:
    import yaml as _yaml

    from ascendc_pilot.actions import goal_engines
    from ascendc_pilot.change_contract import load_change_contract
    from ascendc_pilot.state import start_workflow
    from ascendc_pilot.user_goal_core import control_root

    host = tmp_path / "host"
    host.mkdir()
    op = _op(tmp_path)

    class FakeWorkspace:
        @staticmethod
        def acquire_pull_request(*_a, **_k) -> dict:
            return {
                "ok": True,
                "operator_roots": [str(op)],
                "operator_targets": [
                    {
                        "operator_root": str(op),
                        "operator_name": op.name,
                        "architecture": "arch35",
                    }
                ],
                "changed_files": ["op_host/arch35/tiling.cpp"],
                "worktree_head": str(op),
                "changeset": {"changed_files": ["op_host/arch35/tiling.cpp"]},
            }

        @staticmethod
        def resolve_targets_or_ask(acquire: dict, **kwargs: object) -> dict:
            del kwargs
            return {
                "ok": True,
                "project": str(op),
                "architecture": "arch35",
                "operator_roots": acquire.get("operator_roots") or [],
                "operator_targets": acquire.get("operator_targets") or [],
                "changed_files": acquire.get("changed_files") or [],
                "worktree_head": str(op),
            }

    monkeypatch.setattr(goal_engines, "_git_workspace", lambda: FakeWorkspace)
    state = start_workflow(host, "auto", intent="生成 case", architecture="goal")
    rid = str(state.get("run_id") or "")
    staging = (
        Path(host)
        / ".ascendc-pilot"
        / "goal"
        / "runs"
        / rid
        / "actions"
        / "intent_promote"
        / "staging.yaml"
    )
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.write_text(
        _yaml.safe_dump(
            {
                "intent_text": "为这个 PR 生成针对性测试用例",
                "source": {"kind": "pull_request", "url": "https://example.test/org/repo/pull/1"},
                "needed_capabilities": ["knowledge", "test_generation"],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    out = goal_engines.run_intent_promote(
        host, {"run_id": rid, "architecture": "goal", "intent": "生成 case"}
    )
    assert out.get("ok") is True
    assert "tiling.cpp" in str(out.get("changed_files") or [])
    assert load_change_contract(op) is None
    assert not (control_root(op) / "change_contract.yaml").is_file()


def test_plan_scope_packet_reads_only_pinned_contract(tmp_path: Path, monkeypatch) -> None:
    from ascendc_pilot.actions.tg_product import _compact_plan_scope_packet
    from ascendc_pilot.change_contract import pin_facts
    from ascendc_pilot.paths import ensure_agent_layout

    op = _op(tmp_path)
    ensure_agent_layout(op, arch="arch35")
    (op / ".ascendc-pilot" / "arch35" / "uo").mkdir(parents=True, exist_ok=True)
    (op / ".ascendc-pilot" / "arch35" / "uo" / "manifest.yaml").write_text(
        "op_name: flash_op\n", encoding="utf-8"
    )

    def _boom(*_a, **_k):
        raise AssertionError("plan_scope must not git diff HEAD")

    monkeypatch.setattr(
        "code_engineering.change.capture._run_git",
        _boom,
        raising=False,
    )
    empty = _compact_plan_scope_packet(op, {"architecture": "arch35", "run_id": "R1"})
    assert empty.get("has_diff") is False
    pin_facts(
        op,
        kind="pr_regression",
        changed_files=["op_host/arch35/tiling.cpp"],
        consumers=["tg-plan"],
    )
    packet = _compact_plan_scope_packet(op, {"architecture": "arch35", "run_id": "R1"})
    assert packet.get("has_diff") is True
    assert packet.get("allow_legal_keys") is False
    assert "tiling.cpp" in str(packet.get("changed_files") or packet.get("change_contract") or "")


def test_plan_precheck_pr_regression_requires_pinned_files(tmp_path: Path, monkeypatch) -> None:
    from ascendc_pilot.actions.tg_product import run_plan_precheck
    from ascendc_pilot.change_contract import pin_facts
    from ascendc_pilot.paths import ensure_agent_layout

    op = _op(tmp_path)
    ensure_agent_layout(op, arch="arch35")
    monkeypatch.setattr(
        "testcase_agent.init_status.require_init_confirmed",
        lambda *_a, **_k: {"confirmed": True, "uo_digest": "deadbeef"},
    )
    monkeypatch.setattr(
        "ascendc_pilot.actions.tg_product._legal_key_count",
        lambda *_a, **_k: 0,
    )
    pin_facts(op, kind="pr_regression", changed_files=[], consumers=["tg-plan"])
    out = run_plan_precheck(op, {"architecture": "arch35", "op_name": "flash_op", "run_id": "R1"})
    assert out.get("ok") is False
    assert out.get("error") == "PLAN_PR_CHANGE_REQUIRED"
    assert out.get("retryable") is True

    pin_facts(
        op,
        kind="pr_regression",
        changed_files=["op_host/arch35/tiling.cpp"],
        consumers=["tg-plan"],
    )
    ok = run_plan_precheck(op, {"architecture": "arch35", "op_name": "flash_op", "run_id": "R1"})
    assert ok.get("ok") is True, ok


def test_legal_keys_only_when_pin_asks(tmp_path: Path) -> None:
    from ascendc_pilot.actions.tg_product import _compact_plan_scope_packet
    from ascendc_pilot.change_contract import pin_facts
    from ascendc_pilot.paths import ensure_agent_layout

    op = _op(tmp_path)
    ensure_agent_layout(op, arch="arch35")
    pin_facts(
        op,
        kind="implementation_coverage",
        changed_files=["op_host/arch35/tiling.cpp"],
        enumerate="legal_keys",
        consumers=["tg-plan"],
    )
    packet = _compact_plan_scope_packet(op, {"architecture": "arch35"})
    assert packet.get("allow_legal_keys") is True


def test_pr_change_gate_fails_when_pr_source_and_no_contract(tmp_path: Path, monkeypatch) -> None:
    from ascendc_pilot.actions.tg_product import run_plan_precheck
    from ascendc_pilot.paths import ensure_agent_layout
    from ascendc_pilot.state import start_workflow
    from ascendc_pilot.user_goal import create_user_goal

    op = _op(tmp_path)
    ensure_agent_layout(op, arch="arch35")
    state = start_workflow(op, "tg-plan", architecture="arch35", op_name="flash_op")
    create_user_goal(
        op,
        intent_text="给这个 PR 生成针对性 case",
        llm_intent={
            "needed_workflows": ["tg-plan", "tg-solve"],
            "source": {"kind": "pull_request", "url": "https://gitcode.com/org/repo/pulls/1"},
        },
        architecture="arch35",
        op_name="flash_op",
    )
    monkeypatch.setattr(
        "testcase_agent.init_status.require_init_confirmed",
        lambda *_a, **_k: {"confirmed": True, "uo_digest": "deadbeef"},
    )
    monkeypatch.setattr(
        "ascendc_pilot.actions.tg_product._legal_key_count",
        lambda *_a, **_k: 0,
    )
    out = run_plan_precheck(
        op,
        {
            "architecture": "arch35",
            "op_name": "flash_op",
            "run_id": str(state.get("run_id") or "R1"),
        },
    )
    assert out.get("ok") is False, out
    assert out.get("error") == "PLAN_PR_CHANGE_REQUIRED"


def test_pr_change_gate_allows_local_source_without_contract(tmp_path: Path, monkeypatch) -> None:
    from ascendc_pilot.actions.tg_product import run_plan_precheck
    from ascendc_pilot.paths import ensure_agent_layout
    from ascendc_pilot.state import start_workflow
    from ascendc_pilot.user_goal import create_user_goal

    op = _op(tmp_path)
    ensure_agent_layout(op, arch="arch35")
    state = start_workflow(op, "tg-plan", architecture="arch35", op_name="flash_op")
    create_user_goal(
        op,
        intent_text="把当前实现测明白",
        llm_intent={
            "needed_workflows": ["tg-plan"],
            "source": {"kind": "local"},
        },
        architecture="arch35",
        op_name="flash_op",
    )
    monkeypatch.setattr(
        "testcase_agent.init_status.require_init_confirmed",
        lambda *_a, **_k: {"confirmed": True, "uo_digest": "deadbeef"},
    )
    monkeypatch.setattr(
        "ascendc_pilot.actions.tg_product._legal_key_count",
        lambda *_a, **_k: 0,
    )
    out = run_plan_precheck(
        op,
        {
            "architecture": "arch35",
            "op_name": "flash_op",
            "run_id": str(state.get("run_id") or "R1"),
        },
    )
    assert out.get("ok") is True, out
