"""Pilot TG engines write the three canonical products, not success markers."""

from __future__ import annotations

from pathlib import Path

from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_PATHS, invoke_engine
from ascendc_pilot.paths import ensure_agent_layout, tg_root, uo_root
from ascendc_pilot.state import start_workflow
from ascendc_pilot.workflows.specs import WORKFLOWS

_ARCH = "arch35"


def _seed_manifest(root: Path) -> None:
    path = uo_root(root, arch=_ARCH) / "manifest.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("op_name: synth_tg\n", encoding="utf-8")


def test_validate_init_fails_without_init_yaml(tmp_path: Path) -> None:
    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root, arch=_ARCH)
    _seed_manifest(root)
    state = start_workflow(root, "tg-init", architecture=_ARCH, op_name="synth_tg")
    run_id = str(state.get("run_id") or "")
    result = invoke_engine(
        root,
        "tg-init",
        "validate_init",
        ctx={"op_name": "synth_tg", "architecture": _ARCH, "run_id": run_id},
    )
    assert result.get("ok") is False
    assert not (tg_root(root, arch=_ARCH) / "init.yaml").is_file()


def test_removed_legacy_actions_gone() -> None:
    ids = {a["id"] for a in WORKFLOWS["tg-init"]["actions"]} | {
        a["id"] for a in WORKFLOWS["tg-plan"]["actions"]
    } | {a["id"] for a in WORKFLOWS["tg-solve"]["actions"]}
    for dead in (
        "semantic_bind",
        "contract_build",
        "init_audit",
        "plan_intent",
        "plan_build",
        "lemma_mine",
        "closure_certify",
    ):
        assert dead not in ids
    assert "plan_scope" in ids


def test_output_contracts_are_three_products() -> None:
    assert OUTPUT_CONTRACT_PATHS["tg-init-v1"] == ["tg/init.yaml"]
    assert OUTPUT_CONTRACT_PATHS["tg-plan-v1"] == ["tg/plan.md"]
    assert OUTPUT_CONTRACT_PATHS["tg-worklog-v1"] == ["tg/worklog.md"]
    assert "tg-cases-v1" not in OUTPUT_CONTRACT_PATHS
    assert OUTPUT_CONTRACT_PATHS["plan-precheck-v1"] == []
    assert OUTPUT_CONTRACT_PATHS["tg-plan-scope-v1"] == []
    assert OUTPUT_CONTRACT_PATHS["tg-plan-fuse-v1"] == []
    assert OUTPUT_CONTRACT_PATHS["tg-plan-narrate-v1"] == []
    assert OUTPUT_CONTRACT_PATHS["tg-construct-v1"] == []
    assert OUTPUT_CONTRACT_PATHS["tg-analyze-v1"] == []
    assert "tg-plan-staging-v1" not in OUTPUT_CONTRACT_PATHS
    assert "tg-construct-staging-v1" not in OUTPUT_CONTRACT_PATHS
    assert "tg-analyze-staging-v1" not in OUTPUT_CONTRACT_PATHS
    assert OUTPUT_CONTRACT_PATHS["solve-precheck-v1"] == []
    assert "tilingkey-contract-v1" not in OUTPUT_CONTRACT_PATHS
    assert "lemma-mine-v1" not in OUTPUT_CONTRACT_PATHS


def test_tg_init_agents() -> None:
    agents = {a["id"] for a in WORKFLOWS["tg-init"]["agents"]}
    assert "tg-csv-contract" not in agents
    assert "tg-semantic-bind" not in agents
    assert "tg-analyst" in agents
    assert "deterministic-tg-engine" in agents


def test_start_persists_pilot_params(tmp_path: Path) -> None:
    root = tmp_path / "op"
    root.mkdir()
    consumer = tmp_path / "scripts"
    consumer.mkdir()
    state = start_workflow(
        root,
        "tg-plan",
        op_name="synth_tg",
        test_script_root=consumer.as_posix(),
        level="L0",
        architecture="arch35",
    )
    assert state.get("op_name") == "synth_tg"
    assert Path(str(state.get("test_script_root") or "")).resolve() == consumer.resolve()


_PLAN_BODY = """# why

## 测什么

默认 TilingKey 维。

## 覆盖什么

每维一个 witness。

## 怎么判定

看 Replay tiling_key。

```yaml
schema: tg-plan/v3
requirement: {id: R-dtype, text: dtype}
approved: true
targets:
- id: T-dispatch
  evidence: {kind: replay_field, field: tiling_key, expected: 1}
guards: []
dimensions:
- id: D-dtype
  target: T-dispatch
  controls: [B]
  partitions:
  - {id: fp16, predicate: {op: eq, field: case.dtype, value: fp16}}
  - {id: bf16, predicate: {op: eq, field: case.dtype, value: bf16}}
coverage:
  L0: {dimensions: [D-dtype]}
  L1: {combinations: []}
  L2: []
  L3: {guards: []}
oracle: []
```
"""


def _write_capture(root: Path, run_id: str, action_id: str, *, text: str = "", doc: dict | None = None) -> None:
    from ascendc_pilot.paths import agent_root

    sdir = agent_root(root, _ARCH) / "runs" / run_id / "actions" / action_id
    sdir.mkdir(parents=True, exist_ok=True)
    payload = {"text": text, "doc": doc or {}}
    (sdir / "captured.yaml").write_text(
        __import__("yaml").safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


_FUSE_YAML = """schema: tg-plan/v3
requirement: {id: R-dtype, text: dtype}
approved: true
targets:
- id: T-dispatch
  evidence: {kind: replay_field, field: tiling_key, expected: 1}
guards: []
dimensions:
- id: D-dtype
  target: T-dispatch
  controls: [B]
  partitions:
  - {id: fp16, predicate: {op: eq, field: case.dtype, value: fp16}}
  - {id: bf16, predicate: {op: eq, field: case.dtype, value: bf16}}
coverage:
  L0: {dimensions: [D-dtype]}
  L1: {combinations: []}
  L2: []
  L3: {guards: []}
oracle: []
"""

_PLAN_PROSE = """## 测什么

默认 TilingKey 维。

## 覆盖什么

每维一个 witness。

## 怎么判定

看 Replay tiling_key。
"""


def test_plan_promote_writes_from_session_capture(tmp_path: Path) -> None:
    from ascendc_pilot.actions.engines import OUTPUT_CONTRACT_PATHS
    from ascendc_pilot.actions.runtime import _check_output_contract
    from ascendc_pilot.actions.tg_product import run_plan_promote
    from ascendc_pilot.paths import ensure_agent_layout, tg_root
    from ascendc_pilot.state import start_workflow

    assert OUTPUT_CONTRACT_PATHS["tg-plan-scope-v1"] == []
    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root, arch=_ARCH)
    _seed_manifest(root)
    state = start_workflow(root, "tg-plan", architecture=_ARCH, op_name="synth_tg")
    run_id = str(state.get("run_id") or "")
    _write_capture(root, run_id, "plan_fuse", text=_FUSE_YAML)
    _write_capture(root, run_id, "plan_narrate", text=_PLAN_PROSE)
    checked = _check_output_contract(
        root,
        "tg-plan-fuse-v1",
        run_id=run_id,
        workflow_id="tg-plan",
        action_id="plan_fuse",
    )
    assert checked.get("ok") is True, checked
    out = run_plan_promote(root, {"architecture": _ARCH, "run_id": run_id})
    assert out.get("ok") is True, out
    text = (tg_root(root, arch=_ARCH) / "plan.md").read_text(encoding="utf-8")
    assert "## 测什么" in text
    assert "schema: tg-plan/v3" in text


def test_plan_promote_does_not_require_scope_file(tmp_path: Path) -> None:
    from ascendc_pilot.actions.tg_product import run_plan_promote
    from ascendc_pilot.paths import ensure_agent_layout, tg_root
    from ascendc_pilot.state import start_workflow

    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root, arch=_ARCH)
    _seed_manifest(root)
    state = start_workflow(root, "tg-plan", architecture=_ARCH, op_name="synth_tg")
    run_id = str(state.get("run_id") or "")
    _write_capture(root, run_id, "plan_fuse", text=_FUSE_YAML)
    _write_capture(root, run_id, "plan_narrate", text=_PLAN_PROSE)
    out = run_plan_promote(root, {"architecture": _ARCH, "run_id": run_id})
    assert out.get("ok") is True, out
    assert "schema: tg-plan/v3" in (tg_root(root, arch=_ARCH) / "plan.md").read_text(encoding="utf-8")


def test_scope_answer_for_fuse_prefers_natural_language() -> None:
    from ascendc_pilot.actions.runtime import _scope_answer_for_fuse

    nl = "测 arch35 FAG 的 sparse 路径；dropout 关闭。不要铺全量 TilingKey。"
    assert _scope_answer_for_fuse({"text": nl, "doc": {"targets": [{"id": "T-x"}]}}) == nl
    assert _scope_answer_for_fuse({"text": "", "doc": {}}) == ""
    assert _scope_answer_for_fuse({}) == ""


def test_plan_promote_assembles_primary_prose_and_fuse_yaml(tmp_path: Path) -> None:
    from ascendc_pilot.actions.tg_product import run_plan_promote
    from ascendc_pilot.paths import ensure_agent_layout, tg_root
    from ascendc_pilot.state import start_workflow

    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root, arch=_ARCH)
    _seed_manifest(root)
    state = start_workflow(root, "tg-plan", architecture=_ARCH, op_name="synth_tg")
    run_id = str(state.get("run_id") or "")
    _write_capture(root, run_id, "plan_fuse", text=_FUSE_YAML)
    _write_capture(root, run_id, "plan_narrate", text=_PLAN_PROSE)
    out = run_plan_promote(root, {"architecture": _ARCH, "run_id": run_id})
    assert out.get("ok") is True, out
    text = (tg_root(root, arch=_ARCH) / "plan.md").read_text(encoding="utf-8")
    assert "## 测什么" in text
    assert "```yaml" in text
    assert "schema: tg-plan/v3" in text


def test_plan_promote_requires_fuse_yaml(tmp_path: Path) -> None:
    from ascendc_pilot.actions.tg_product import run_plan_promote
    from ascendc_pilot.paths import ensure_agent_layout
    from ascendc_pilot.state import start_workflow

    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root, arch=_ARCH)
    _seed_manifest(root)
    state = start_workflow(root, "tg-plan", architecture=_ARCH, op_name="synth_tg")
    run_id = str(state.get("run_id") or "")
    out = run_plan_promote(
        root,
        {"architecture": _ARCH, "run_id": run_id},
    )
    assert out.get("ok") is False
    assert out.get("error") == "PLAN_FUSE_REQUIRED"
    assert out.get("retryable") is True
    assert out.get("failure_class") == "format_transport"


def test_plan_promote_requires_primary_prose(tmp_path: Path) -> None:
    from ascendc_pilot.actions.tg_product import run_plan_promote
    from ascendc_pilot.paths import ensure_agent_layout
    from ascendc_pilot.state import start_workflow

    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root, arch=_ARCH)
    _seed_manifest(root)
    state = start_workflow(root, "tg-plan", architecture=_ARCH, op_name="synth_tg")
    run_id = str(state.get("run_id") or "")
    _write_capture(root, run_id, "plan_fuse", text=_FUSE_YAML)
    out = run_plan_promote(root, {"architecture": _ARCH, "run_id": run_id})
    assert out.get("ok") is False
    assert out.get("error") == "PLAN_PROSE_REQUIRED"
    assert out.get("retryable") is True
    assert out.get("failure_class") == "format_transport"
    assert "plan_narrate" in (out.get("rework_action_ids") or [])


def test_plan_promote_does_not_take_prose_from_fuse(tmp_path: Path) -> None:
    from ascendc_pilot.actions.tg_product import run_plan_promote
    from ascendc_pilot.paths import ensure_agent_layout
    from ascendc_pilot.state import start_workflow

    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root, arch=_ARCH)
    _seed_manifest(root)
    state = start_workflow(root, "tg-plan", architecture=_ARCH, op_name="synth_tg")
    run_id = str(state.get("run_id") or "")
    _write_capture(root, run_id, "plan_fuse", text=_PLAN_BODY)
    out = run_plan_promote(root, {"architecture": _ARCH, "run_id": run_id})
    assert out.get("ok") is False
    assert out.get("error") == "PLAN_PROSE_REQUIRED"


def test_compact_plan_scope_packet_skips_around(tmp_path: Path) -> None:
    from ascendc_pilot.actions.tg_product import _compact_plan_scope_packet
    from ascendc_pilot.paths import ensure_agent_layout

    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root, arch=_ARCH)
    _seed_manifest(root)
    packet = _compact_plan_scope_packet(root, {"architecture": _ARCH, "run_id": "R1"})
    assert packet.get("schema") == "tg-plan-scope-packet/v1"
    assert packet.get("skip_around") is True
    assert "ident_cards" in packet
    assert "intent_sources" in packet


def test_construct_promote_does_not_write_cases(tmp_path: Path) -> None:
    from ascendc_pilot.actions.tg_product import run_construct_promote
    from ascendc_pilot.paths import ensure_agent_layout, tg_root
    from ascendc_pilot.state import start_workflow
    from testcase_agent.products import INIT_SCHEMA, dump_init

    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root, arch=_ARCH)
    _seed_manifest(root)
    state = start_workflow(root, "tg-solve", architecture=_ARCH, op_name="synth_tg")
    run_id = str(state.get("run_id") or "")
    tg = tg_root(root, arch=_ARCH)
    dump_init(
        tg,
        {
            "schema": INIT_SCHEMA,
            "kind": "default_input",
            "table_kind": "csv",
            "uo_digest": "deadbeef",
            "columns": [{"name": "B"}, {"name": "dtype"}],
        },
    )
    _write_capture(
        root,
        run_id,
        "construct_cases",
        doc={"columns": ["B", "dtype"], "rows": [{"B": "1", "dtype": "fp16"}]},
    )
    out = run_construct_promote(root, {"architecture": _ARCH, "run_id": run_id})
    assert out.get("ok") is True, out
    assert out.get("wrote_cases") is False
    assert not (tg / "cases.csv").is_file()
    assert (tg / "replay" / "pending.yaml").is_file()
    assert not (tg / "coverage_ledger.yaml").is_file()
    assert not (tg / "case_bindings.yaml").is_file()
    assert not any(p.name == "targets.yaml" for p in root.rglob("targets.yaml"))
    assert not any(p.parent.name == "parts" and p.parents[1].name == "construct_cases" for p in root.rglob("*"))


def test_certify_rejects_empty_open_prose(tmp_path: Path) -> None:
    from ascendc_pilot.actions.tg_product import run_solve_certify
    from ascendc_pilot.gates.tg_adapters import gate_worklog_closed
    from ascendc_pilot.paths import ensure_agent_layout, tg_root
    from ascendc_pilot.state import start_workflow
    from testcase_agent.products import INIT_SCHEMA, dump_init

    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root, arch=_ARCH)
    _seed_manifest(root)
    start_workflow(root, "tg-solve", architecture=_ARCH, op_name="synth_tg")
    tg = tg_root(root, arch=_ARCH)
    dump_init(
        tg,
        {
            "schema": INIT_SCHEMA,
            "kind": "default_input",
            "table_kind": "csv",
            "uo_digest": "deadbeef",
            "columns": [{"name": "B"}],
        },
    )
    (tg / "worklog.md").write_text("open: []\n\nno ledger fence\n", encoding="utf-8")
    gated = gate_worklog_closed(root, architecture=_ARCH)
    assert gated.get("ok") is False
    out = run_solve_certify(root, {"architecture": _ARCH, "run_id": "R1"})
    assert out.get("ok") is False
    assert not (tg / "cases.csv").is_file()


def test_analyze_promote_merges_capture_into_ledger(tmp_path: Path) -> None:
    from ascendc_pilot.actions.tg_product import run_analyze_promote
    from ascendc_pilot.paths import ensure_agent_layout, tg_root
    from ascendc_pilot.state import start_workflow
    from testcase_agent.coverage.ledger import dump_worklog, seed_ledger

    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root, arch=_ARCH)
    _seed_manifest(root)
    state = start_workflow(root, "tg-solve", architecture=_ARCH, op_name="synth_tg")
    run_id = str(state.get("run_id") or "")
    tg = tg_root(root, arch=_ARCH)
    (tg / "worklog.md").write_text(
        dump_worklog(seed_ledger([{"id": "O1", "status": "MISS"}])),
        encoding="utf-8",
    )
    _write_capture(root, run_id, "analyze_round", text="refinement:\n  miss:\n    - obligation: O1\n")
    out = run_analyze_promote(root, {"architecture": _ARCH, "run_id": run_id})
    assert out.get("ok") is True, out
    text = (tg / "worklog.md").read_text(encoding="utf-8")
    assert "O1" in text
    assert "schema: tg-worklog/v2" in text or "tg-worklog/v2" in text


def test_compile_obligations_writes_worklog_not_sidecar(tmp_path: Path) -> None:
    from ascendc_pilot.actions.tg_product import run_compile_obligations, run_plan_promote
    from ascendc_pilot.paths import ensure_agent_layout, tg_root
    from ascendc_pilot.state import start_workflow

    root = tmp_path / "op"
    root.mkdir()
    ensure_agent_layout(root, arch=_ARCH)
    _seed_manifest(root)
    state = start_workflow(root, "tg-plan", architecture=_ARCH, op_name="synth_tg")
    run_id = str(state.get("run_id") or "")
    _write_capture(root, run_id, "plan_fuse", text=_FUSE_YAML)
    _write_capture(root, run_id, "plan_narrate", text=_PLAN_PROSE)
    promoted = run_plan_promote(root, {"architecture": _ARCH, "run_id": run_id})
    assert promoted.get("ok") is True, promoted
    tg = tg_root(root, arch=_ARCH)
    out = run_compile_obligations(root, {"architecture": _ARCH, "run_id": run_id})
    assert out.get("ok") is True, out
    assert (tg / "worklog.md").is_file()
    assert "tg-worklog/v2" in (tg / "worklog.md").read_text(encoding="utf-8")
    assert not (tg / "coverage_ledger.yaml").is_file()
    assert not any(p.name == "targets.yaml" for p in root.rglob("targets.yaml"))
    assert not any(
        p.name == "parts" and p.parent.name in {"plan_scope", "plan_fuse"}
        for p in root.rglob("*")
        if p.is_dir()
    )
