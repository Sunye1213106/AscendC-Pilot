"""Unique PR facts: clone_receipt is candidate; pin-facts promotes it to change_contract."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return str(proc.stdout or "").strip()


def _op(root: Path) -> Path:
    op = root / "flash_op"
    (op / "op_host" / "arch35").mkdir(parents=True)
    return op


def _prepare_pr_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """Git repo with two commits; returns operator, base_sha, head_sha."""
    repo = tmp_path
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    op = _op(repo)
    src = op / "op_host" / "arch35" / "tiling.cpp"
    src.write_text("int foo = 0;\n", encoding="utf-8")
    _git(repo, "add", "flash_op/op_host/arch35/tiling.cpp")
    _git(
        repo,
        "-c",
        "user.email=pin@example.invalid",
        "-c",
        "user.name=Pin Test",
        "commit",
        "-m",
        "base",
    )
    base = _git(repo, "rev-parse", "HEAD")
    src.write_text("int foo = 1;\n", encoding="utf-8")
    _git(repo, "add", "flash_op/op_host/arch35/tiling.cpp")
    _git(
        repo,
        "-c",
        "user.email=pin@example.invalid",
        "-c",
        "user.name=Pin Test",
        "commit",
        "-m",
        "head",
    )
    head = _git(repo, "rev-parse", "HEAD")
    return op, base, head


def _write_clone_receipt_yaml(
    op: Path,
    *,
    files: list[str],
    url: str = "https://example.test/org/repo/pull/1",
    head_sha: str = "bbb",
    base_sha: str = "aaa",
    worktree: str = "",
) -> Path:
    from ascendc_pilot.user_goal_core import control_root

    path = control_root(op) / "clone_receipt.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema": "tg-clone-receipt/v1",
                "source": {"kind": "pull_request", "url": url},
                "changed_files": files,
                "base_sha": base_sha,
                "head_sha": head_sha,
                "worktree_head": worktree or str(op),
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def test_clone_unique_writes_clone_receipt_not_change_contract(tmp_path: Path, monkeypatch) -> None:
    from ascendc_pilot.actions import goal_engines
    from ascendc_pilot.change_contract import load_change_contract, load_clone_receipt
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
                "head_sha": "headsha",
                "base_sha": "basesha",
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
        yaml.safe_dump(
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
    receipt = load_clone_receipt(op)
    assert receipt is not None
    assert receipt["source"]["kind"] == "pull_request"
    assert "tiling.cpp" in str(receipt.get("changed_files") or [])
    assert not (control_root(op) / "runs").exists() or not any(
        control_root(op).rglob("intent_promoted.yaml")
    )


def test_pin_facts_promotes_clone_receipt(tmp_path: Path) -> None:
    from ascendc_pilot.change_contract import load_change_contract, pin_facts
    from ascendc_pilot.user_goal_core import control_root

    op, base, head = _prepare_pr_repo(tmp_path)
    _write_clone_receipt_yaml(
        op,
        files=["flash_op/op_host/arch35/tiling.cpp"],
        base_sha=base,
        head_sha=head,
        worktree=str(tmp_path),
    )
    out = pin_facts(op)
    assert out.get("ok") is True, out
    doc = yaml.safe_load((control_root(op) / "change_contract.yaml").read_text(encoding="utf-8"))
    assert doc["schema"] == "tg-change-contract/v2"
    assert doc["kind"] == "pr_regression"
    assert doc["changed_files"]
    assert doc["changed_hunks"]
    assert doc["base_sha"] == base
    assert doc["head_sha"] == head
    loaded = load_change_contract(op)
    assert loaded["changed_hunks"]


def test_pin_facts_without_receipt_does_not_write(tmp_path: Path) -> None:
    from ascendc_pilot.change_contract import load_change_contract, pin_facts
    from ascendc_pilot.user_goal_core import control_root

    op = _op(tmp_path)
    out = pin_facts(op)
    assert out.get("ok") is False
    assert out.get("error") == "PIN_FACTS_MISSING"
    assert not (control_root(op) / "change_contract.yaml").is_file()
    assert load_change_contract(op) is None


def test_empty_change_contract_is_not_pinned(tmp_path: Path) -> None:
    from ascendc_pilot.change_contract import load_change_contract
    from ascendc_pilot.user_goal_core import control_root

    op = _op(tmp_path)
    path = control_root(op) / "change_contract.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema": "tg-change-contract/v1",
                "kind": "",
                "changed_files": [],
                "base_sha": "",
                "head_sha": "",
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    assert load_change_contract(op) is None


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
    op2, base, head = _prepare_pr_repo(tmp_path / "pinned")
    # reuse layout helpers on a dedicated repo; this test's `op` has no git.
    from ascendc_pilot.paths import ensure_agent_layout as _layout

    _layout(op2, arch="arch35")
    (op2 / ".ascendc-pilot" / "arch35" / "uo").mkdir(parents=True, exist_ok=True)
    (op2 / ".ascendc-pilot" / "arch35" / "uo" / "manifest.yaml").write_text(
        "op_name: flash_op\n", encoding="utf-8"
    )
    _write_clone_receipt_yaml(
        op2,
        files=["flash_op/op_host/arch35/tiling.cpp"],
        base_sha=base,
        head_sha=head,
        worktree=str(tmp_path / "pinned"),
    )
    pin_facts(op2)
    packet = _compact_plan_scope_packet(op2, {"architecture": "arch35", "run_id": "R1"})
    assert packet.get("has_diff") is True
    assert packet.get("allow_legal_keys") is False
    assert packet.get("changed_hunks")


def test_session_shape_pr_receipt_without_pin_fails_precheck(tmp_path: Path, monkeypatch) -> None:
    from ascendc_pilot.actions.tg_product import run_plan_precheck
    from ascendc_pilot.change_contract import pin_facts
    from ascendc_pilot.paths import ensure_agent_layout
    from ascendc_pilot.state import start_workflow
    from ascendc_pilot.user_goal_core import control_root

    op = _op(tmp_path)
    ensure_agent_layout(op, arch="arch35")
    state = start_workflow(op, "tg-plan", architecture="arch35", op_name="flash_op")
    _write_clone_receipt_yaml(op, files=["op_host/arch35/tiling.cpp"])
    path = control_root(op) / "change_contract.yaml"
    path.write_text(
        "schema: tg-change-contract/v1\nkind: ''\nchanged_files: []\nbase_sha: ''\nhead_sha: ''\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "testcase_agent.init_status.require_init_confirmed",
        lambda *_a, **_k: {"confirmed": True, "uo_digest": "deadbeef"},
    )
    monkeypatch.setattr(
        "ascendc_pilot.actions.tg_product._legal_key_count",
        lambda *_a, **_k: 0,
    )
    # This test is about the change pin, not the methodology handshake; the
    # installed-bundle state of the developer machine must not decide it.
    monkeypatch.setattr("ascendc_pilot.contract_sync.installed_roots", lambda: [])
    out = run_plan_precheck(
        op,
        {
            "architecture": "arch35",
            "op_name": "flash_op",
            "run_id": str(state.get("run_id") or "R1"),
        },
    )
    assert out.get("ok") is False, out
    assert out.get("error") == "PIN_HEAD_MISMATCH"
    assert out.get("ask") in {"human", "primary"}
    assert not list(op.rglob("plan_scope_packet.yaml"))

    live = tmp_path / "live"
    op2, base, head = _prepare_pr_repo(live)
    ensure_agent_layout(op2, arch="arch35")
    state2 = start_workflow(op2, "tg-plan", architecture="arch35", op_name="flash_op")
    _write_clone_receipt_yaml(
        op2,
        files=["flash_op/op_host/arch35/tiling.cpp"],
        base_sha=base,
        head_sha=head,
        worktree=str(live),
    )
    promoted = pin_facts(op2)
    assert promoted.get("ok") is True, promoted
    ok = run_plan_precheck(
        op2,
        {
            "architecture": "arch35",
            "op_name": "flash_op",
            "run_id": str(state2.get("run_id") or "R1"),
        },
    )
    assert ok.get("ok") is True, ok


def test_pr_identity_does_not_use_empty_contract_kind(tmp_path: Path) -> None:
    from ascendc_pilot.change_contract import is_pr_source

    op = _op(tmp_path)
    _write_clone_receipt_yaml(op, files=["op_host/arch35/tiling.cpp"])
    ident = is_pr_source(op)
    assert ident.get("ok") is True
    assert ident.get("is_pr") is True


def test_legal_keys_only_when_local_coverage_pin(tmp_path: Path) -> None:
    from ascendc_pilot.actions.tg_product import _compact_plan_scope_packet
    from ascendc_pilot.change_contract import pin_facts
    from ascendc_pilot.paths import ensure_agent_layout

    op = _op(tmp_path)
    ensure_agent_layout(op, arch="arch35")
    out = pin_facts(op, kind="implementation_coverage", enumerate="legal_keys")
    assert out.get("ok") is True, out
    packet = _compact_plan_scope_packet(op, {"architecture": "arch35"})
    assert packet.get("allow_legal_keys") is True


def test_pr_receipt_rejects_implementation_coverage_pin(tmp_path: Path) -> None:
    from ascendc_pilot.change_contract import pin_facts

    op = _op(tmp_path)
    _write_clone_receipt_yaml(op, files=["op_host/arch35/tiling.cpp"])
    out = pin_facts(op, kind="implementation_coverage", enumerate="legal_keys")
    assert out.get("ok") is False
    assert out.get("error") == "PIN_PR_SOURCE_FORBIDDEN"


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
    monkeypatch.setattr("ascendc_pilot.contract_sync.installed_roots", lambda: [])
    out = run_plan_precheck(
        op,
        {
            "architecture": "arch35",
            "op_name": "flash_op",
            "run_id": str(state.get("run_id") or "R1"),
        },
    )
    assert out.get("ok") is True, out


def test_pin_facts_cli_promotes_project_only(tmp_path: Path, capsys) -> None:
    import json

    from ascendc_pilot.cli import main
    from ascendc_pilot.change_contract import load_change_contract

    op, base, head = _prepare_pr_repo(tmp_path)
    _write_clone_receipt_yaml(
        op,
        files=["flash_op/op_host/arch35/tiling.cpp"],
        base_sha=base,
        head_sha=head,
        worktree=str(tmp_path),
    )
    rc = main(["pin-facts", "--project", str(op)])
    captured = capsys.readouterr()
    assert rc == 0, captured.out
    payload = json.loads(captured.out)
    assert payload.get("ok") is True
    loaded = load_change_contract(op) or {}
    assert loaded.get("kind") == "pr_regression"
    assert loaded.get("changed_hunks")


def test_pin_facts_equal_sha_resolves_parent(tmp_path: Path) -> None:
    from ascendc_pilot.change_contract import load_change_contract, load_clone_receipt, pin_facts

    op, base, head = _prepare_pr_repo(tmp_path)
    _write_clone_receipt_yaml(
        op,
        files=["flash_op/op_host/arch35/tiling.cpp"],
        base_sha=head,
        head_sha=head,
        worktree=str(tmp_path),
    )
    out = pin_facts(op)
    assert out.get("ok") is True, out
    doc = load_change_contract(op)
    assert doc["changed_hunks"]
    assert doc["base_sha"] == base
    assert doc["head_sha"] == head
    receipt = load_clone_receipt(op)
    assert receipt["base_sha"] == base
    assert receipt["head_sha"] == head


def test_pin_facts_cli_rejects_changed_files_flag(tmp_path: Path) -> None:
    from ascendc_pilot.cli import main

    op = _op(tmp_path)
    try:
        main(["pin-facts", "--project", str(op), "--changed-files", "a.cpp"])
    except SystemExit as exc:
        assert int(exc.code or 0) != 0
        return
    raise AssertionError("pin-facts must not accept --changed-files")


def test_v1_pr_contract_without_hunks_is_not_loaded(tmp_path: Path) -> None:
    from ascendc_pilot.change_contract import load_change_contract
    from ascendc_pilot.user_goal_core import control_root

    op = _op(tmp_path)
    path = control_root(op) / "change_contract.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema": "tg-change-contract/v1",
                "kind": "pr_regression",
                "changed_files": ["op_host/a.cpp"],
                "base_sha": "aaa",
                "head_sha": "bbb",
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    assert load_change_contract(op) is None


def test_pin_uses_two_dot_sha_diff(tmp_path: Path, monkeypatch) -> None:
    from ascendc_pilot import change_contract as cc

    seen: list[tuple[str, str]] = []
    orig = cc._git_diff_unified

    def _wrap(cwd, base_sha, head_sha):
        seen.append((str(base_sha), str(head_sha)))
        return orig(cwd, base_sha, head_sha)

    monkeypatch.setattr(cc, "_git_diff_unified", _wrap)
    op, base, head = _prepare_pr_repo(tmp_path)
    _write_clone_receipt_yaml(
        op,
        files=["flash_op/op_host/arch35/tiling.cpp"],
        base_sha=base,
        head_sha=head,
        worktree=str(tmp_path),
    )
    out = cc.pin_facts(op)
    assert out.get("ok") is True, out
    assert seen == [(base, head)]
    assert all("..." not in a and "..." not in b for a, b in seen)


def test_pin_rejects_head_mismatch(tmp_path: Path) -> None:
    from ascendc_pilot.change_contract import pin_facts

    op, base, head = _prepare_pr_repo(tmp_path)
    _write_clone_receipt_yaml(
        op,
        files=["flash_op/op_host/arch35/tiling.cpp"],
        base_sha=base,
        head_sha="deadbeef" + head[8:],
        worktree=str(tmp_path),
    )
    out = pin_facts(op)
    assert out.get("ok") is False
    assert out.get("error") == "PIN_HEAD_MISMATCH"


def _prepare_noisy_pr_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    op = _op(repo)
    src = op / "op_host" / "arch35" / "tiling.cpp"
    src.write_text("void OldFn() {}\nint foo = 0;\n", encoding="utf-8")
    kernel = op / "op_kernel" / "kernel.h"
    kernel.parent.mkdir(parents=True, exist_ok=True)
    kernel.write_text("int k = 0;\n", encoding="utf-8")
    other = repo / "other_op" / "op_host" / "foo.cpp"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text("int x = 0;\n", encoding="utf-8")
    (repo / ".clang-format").write_text("BasedOnStyle: LLVM\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.email=pin@example.invalid",
        "-c",
        "user.name=Pin Test",
        "commit",
        "-m",
        "base",
    )
    base = _git(repo, "rev-parse", "HEAD")
    src.write_text("int foo = 1;\nint selectedRound = 1;\n", encoding="utf-8")
    kernel.write_text("int k = 1;\n", encoding="utf-8")
    other.write_text("int x = 1;\n", encoding="utf-8")
    (repo / ".clang-format").write_text("BasedOnStyle: Google\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.email=pin@example.invalid",
        "-c",
        "user.name=Pin Test",
        "commit",
        "-m",
        "head",
    )
    head = _git(repo, "rev-parse", "HEAD")
    return op, base, head


def test_scope_operator_hunks_drops_other_ops_and_repo_noise() -> None:
    from ascendc_pilot.change_contract import hunk_path, scope_operator_hunks

    hunks = [
        {"new_file": "flash_op/op_host/arch35/tiling.cpp", "hunk_id": "H1"},
        {"new_file": "flash_op/op_kernel/kernel.h", "hunk_id": "H2"},
        {"new_file": "other_op/op_host/foo.cpp", "hunk_id": "H3"},
        {"new_file": ".clang-format", "hunk_id": "H4"},
        {"new_file": "CMakeLists.txt", "hunk_id": "H5"},
    ]
    scoped, relevant = scope_operator_hunks(
        hunks,
        changed_files=["flash_op/op_host/arch35/tiling.cpp"],
        operator_name="flash_op",
    )
    assert [hunk_path(h) for h in scoped] == ["flash_op/op_host/arch35/tiling.cpp"]
    assert [hunk_path(h) for h in relevant] == ["flash_op/op_kernel/kernel.h"]


def test_pin_and_packet_keep_operator_hunks_only(tmp_path: Path) -> None:
    from ascendc_pilot.actions.tg_product import _compact_plan_scope_packet
    from ascendc_pilot.change_contract import hunk_path, load_change_contract, pin_facts
    from ascendc_pilot.paths import ensure_agent_layout

    op, base, head = _prepare_noisy_pr_repo(tmp_path)
    ensure_agent_layout(op, arch="arch35")
    (op / ".ascendc-pilot" / "arch35" / "uo").mkdir(parents=True, exist_ok=True)
    (op / ".ascendc-pilot" / "arch35" / "uo" / "manifest.yaml").write_text(
        "op_name: flash_op\n", encoding="utf-8"
    )
    _write_clone_receipt_yaml(
        op,
        files=["flash_op/op_host/arch35/tiling.cpp"],
        base_sha=base,
        head_sha=head,
        worktree=str(tmp_path),
    )
    out = pin_facts(op)
    assert out.get("ok") is True, out
    contract = load_change_contract(op) or {}
    paths = {hunk_path(h) for h in contract.get("changed_hunks") or []}
    assert any("tiling.cpp" in p for p in paths)
    assert not any(p == ".clang-format" or p.endswith("/.clang-format") for p in paths)
    assert not any("other_op" in p for p in paths)
    assert any("kernel.h" in p for p in paths)

    packet = _compact_plan_scope_packet(op, {"architecture": "arch35", "run_id": "R1"})
    packet_paths = {hunk_path(h) for h in packet.get("changed_hunks") or []}
    assert any("tiling.cpp" in p for p in packet_paths)
    assert not any("kernel.h" in p for p in packet_paths)
    assert not any("other_op" in p for p in packet_paths)
    assert not any("clang-format" in p for p in packet_paths)
    relevant_paths = {hunk_path(h) for h in packet.get("relevant_hunks") or []}
    assert any("kernel.h" in p for p in relevant_paths)
    assert all("deleted_lines" not in (row or {}) for row in packet.get("relevant_hunks") or [])
    meta = packet.get("change_contract") or {}
    assert "changed_hunks" not in meta
    dumped = yaml.safe_dump(packet, allow_unicode=True)
    assert dumped.count("changed_hunks") <= 2
    assert len(dumped) < 80_000
    card = packet.get("plan_route_card") or {}
    kinds = {c.get("kind") for c in card.get("clusters") or [] if isinstance(c, dict)}
    assert "host" in kinds
    assert "kernel" in kinds
    assert card.get("route_hint") == "fragments"
    assert "OldFn" in (packet.get("deleted_symbols") or []) or "OldFn" in (
        card.get("deleted_symbols") or []
    )
