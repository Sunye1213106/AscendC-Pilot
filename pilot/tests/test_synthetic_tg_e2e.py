# -*- coding: utf-8 -*-
"""Synthetic TG: init.yaml + plan.md products, no T=D overlay."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from synthetic_uo import write_synthetic_uo as _write_synthetic_uo


@pytest.fixture()
def synthetic_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("UO_OPERATOR", "_synthetic_toy")
    monkeypatch.setenv("UO_ARCH", "arch0")
    monkeypatch.setenv("TG_CLOSURE_CI", "1")
    monkeypatch.setenv("ASCENDC_PROJECT_ROOT", str(tmp_path))

    from ascendc_pilot.paths import ensure_agent_layout, tg_root

    ensure_agent_layout(tmp_path, arch="arch0")
    _write_synthetic_uo(tmp_path)
    tg = tg_root(tmp_path, arch="arch0")
    tg.mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_repo_scan_and_validate_init(synthetic_root: Path):
    from ascendc_pilot.actions.tg_product import run_repo_scan, run_validate_init
    from ascendc_pilot.human_interaction import adopt_test_script_root
    from testcase_agent.products import dump_init, INIT_SCHEMA
    from ascendc_pilot.paths import tg_root
    from ascendc_pilot.state import start_workflow

    state = start_workflow(
        synthetic_root,
        "tg-init",
        architecture="arch0",
        op_name="_synthetic_toy",
    )
    adopt_test_script_root(synthetic_root, "no_repo_uo_query")
    run_id = str(state.get("run_id") or "")
    scan = run_repo_scan(synthetic_root, {"architecture": "arch0", "run_id": run_id})
    assert scan.get("ok") is True
    from ascendc_pilot.actions.tg_product import _action_dir

    parts = _action_dir(synthetic_root, {"architecture": "arch0", "run_id": run_id}, "bind_init") / "parts"
    assert (parts / "bind.yaml").is_file()
    assert (parts / "harness.yaml").is_file()
    assert (parts / ".engine" / "bind.owned.yaml").is_file()
    bind_doc = yaml.safe_load((parts / "bind.yaml").read_text(encoding="utf-8"))
    assert bind_doc.get("schema") == "tg-bind-part/v1"
    assert bind_doc.get("run_id") == run_id
    dump_init(
        tg_root(synthetic_root, arch="arch0"),
        {
            "schema": INIT_SCHEMA,
            "kind": "default_input",
            "table_kind": "csv",
            "uo_digest": "deadbeef",
            "confirmed": False,
        },
    )
    out = run_validate_init(synthetic_root, {"architecture": "arch0", "run_id": run_id})
    assert out.get("ok") is True, out


def test_plan_validate_rejects_td_mode(synthetic_root: Path):
    from ascendc_pilot.actions.tg_product import run_plan_validate
    from testcase_agent.products import dump_init, INIT_SCHEMA
    from ascendc_pilot.paths import tg_root

    tg = tg_root(synthetic_root, arch="arch0")
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
    (tg / "plan.md").write_text(
        "# plan\n\n```yaml\nschema: tg-plan/v3\nmode: tilingkey_full_coverage\ntargets: []\n```\n",
        encoding="utf-8",
    )
    out = run_plan_validate(synthetic_root, {"architecture": "arch0", "run_id": "RUN1"})
    assert out.get("ok") is False
    assert any("T=D" in e or "tilingkey_full_coverage" in e or "empty" in e for e in (out.get("errors") or []))


def test_no_td_overlay():
    from ascendc_pilot.workflows import WORKFLOWS

    assert not (WORKFLOWS["tg-solve"].get("mode_overlays") or {})
    ids = [a["id"] for a in WORKFLOWS["tg-solve"]["actions"]]
    assert "lemma_mine" not in ids
    assert "construct_cases" in ids


def test_repo_scan_asks_when_goal_wants_tests_and_root_empty(synthetic_root: Path) -> None:
    from ascendc_pilot.actions.tg_product import run_repo_scan
    from ascendc_pilot.user_goal import create_user_goal

    create_user_goal(
        synthetic_root,
        intent_text="生成针对性测例",
        llm_intent={
            "objective_zh": "生成针对性测例",
            "needed_capabilities": ["knowledge", "test_generation"],
            "source": {"kind": "local"},
        },
        architecture="arch0",
    )
    scan = run_repo_scan(synthetic_root, {"architecture": "arch0", "run_id": "R1"})
    assert scan.get("needs_human_decision") is True
    ask = scan.get("ask_question") or {}
    opts = ask.get("options") or []
    assert len(opts) >= 2
    values = {str(o.get("value") or "") for o in opts if isinstance(o, dict)}
    assert "custom" in values
    assert "no_repo_uo_query" in values
    assert "have_repo" not in values
    assert "stop" not in values
    assert str(opts[0].get("value") or "") == "no_repo_uo_query"
    assert str(opts[-1].get("value") or "") == "custom"
    assert ask.get("allow_free_text") is True
    assert scan.get("ok") is False


def test_repo_scan_asks_without_user_goal(synthetic_root: Path) -> None:
    from ascendc_pilot.actions.tg_product import run_repo_scan

    scan = run_repo_scan(synthetic_root, {"architecture": "arch0", "run_id": "R1"})
    assert scan.get("needs_human_decision") is True
    values = {
        str(o.get("value") or "")
        for o in ((scan.get("ask_question") or {}).get("options") or [])
        if isinstance(o, dict)
    }
    assert "custom" in values
    assert "no_repo_uo_query" in values
    assert "have_repo" not in values
    assert "stop" not in values


def test_repo_scan_default_input_sentinel_skips_ask(synthetic_root: Path) -> None:
    from ascendc_pilot.actions.tg_product import run_repo_scan

    scan = run_repo_scan(
        synthetic_root,
        {"architecture": "arch0", "run_id": "R1", "test_script_root": "no_repo_uo_query"},
    )
    assert scan.get("needs_human_decision") is not True
    assert scan.get("ok") is True
    assert str((scan.get("inventory") or {}).get("kind") or "") == "default_input"


def test_prepare_repo_scan_does_not_finalize_when_asking(synthetic_root: Path) -> None:
    from ascendc_pilot.actions import prepare_action
    from ascendc_pilot.state import load_state, save_state, start_workflow
    from ascendc_pilot.user_goal import create_user_goal

    start_workflow(
        synthetic_root,
        "tg-init",
        architecture="arch0",
        op_name="_synthetic_toy",
        phase="scan",
        force_phase=True,
    )
    create_user_goal(
        synthetic_root,
        intent_text="生成针对性测例",
        llm_intent={
            "objective_zh": "生成针对性测例",
            "needed_capabilities": ["knowledge", "test_generation"],
            "source": {"kind": "local"},
        },
        architecture="arch0",
    )
    state = load_state(synthetic_root) or {}
    state["phase"] = "scan"
    save_state(synthetic_root, state)
    prep = prepare_action(synthetic_root, "repo_scan")
    assert prep.get("needs_human_decision") is True
    assert prep.get("auto_finalize") is not True
    assert isinstance(prep.get("ask_question"), dict)
    assert len((prep.get("ask_question") or {}).get("options") or []) >= 2
    assert not (prep.get("finalize") or {}).get("ok")


def test_custom_does_not_count_as_script_root(synthetic_root: Path) -> None:
    from ascendc_pilot.actions.tg_product import run_repo_scan

    scan = run_repo_scan(
        synthetic_root,
        {"architecture": "arch0", "run_id": "R1", "test_script_root": "custom"},
    )
    assert scan.get("needs_human_decision") is True
    assert str(scan.get("test_script_root") or "") == ""


def test_repo_scan_adopts_existing_directory(synthetic_root: Path) -> None:
    from ascendc_pilot.actions.tg_product import run_repo_scan

    repo = synthetic_root / "fag_debug_tools"
    repo.mkdir()
    scan = run_repo_scan(
        synthetic_root,
        {"architecture": "arch0", "run_id": "R1", "test_script_root": str(repo)},
    )
    assert scan.get("needs_human_decision") is not True
    assert scan.get("ok") is True
    assert scan.get("kind") == "script_repo"
    assert Path(str(scan.get("test_script_root"))).resolve() == repo.resolve()


def test_bind_promote_rejects_without_referee(synthetic_root: Path) -> None:
    from ascendc_pilot.actions.tg_product import run_bind_promote
    from ascendc_pilot.state import start_workflow

    state = start_workflow(
        synthetic_root, "tg-init", architecture="arch0", op_name="_synthetic_toy"
    )
    out = run_bind_promote(
        synthetic_root,
        {"architecture": "arch0", "run_id": str(state.get("run_id") or ""), "op_name": "_synthetic_toy"},
    )
    assert out.get("ok") is False
    assert out.get("error") == "REFEREE_REJECTED"


def test_bind_promote_merges_parts_after_referee(synthetic_root: Path) -> None:
    from ascendc_pilot.actions.tg_product import _action_dir, run_bind_promote, run_repo_scan
    from ascendc_pilot.human_interaction import adopt_test_script_root
    from ascendc_pilot.paths import tg_root
    from ascendc_pilot.state import start_workflow
    from testcase_agent.products import load_init

    state = start_workflow(
        synthetic_root, "tg-init", architecture="arch0", op_name="_synthetic_toy"
    )
    adopt_test_script_root(synthetic_root, "no_repo_uo_query")
    ctx = {"architecture": "arch0", "run_id": str(state.get("run_id") or ""), "op_name": "_synthetic_toy"}
    scan = run_repo_scan(synthetic_root, {**ctx, "test_script_root": "no_repo_uo_query"})
    assert scan.get("ok") is True
    bind_root = _action_dir(synthetic_root, ctx, "bind_init")
    (bind_root / "parts").mkdir(parents=True, exist_ok=True)
    (bind_root / "parts" / "harness.yaml").write_text(
        "golden: {status: match}\ncompare: {atol: 1e-4}\nmodes: {precision: [run], perf: []}\n"
        "generate_inputs: {kind: default}\nfindings: [h1]\n",
        encoding="utf-8",
    )
    (bind_root / "parts" / "bind.yaml").write_text(
        "table_kind: csv\nentry: ''\ncase_arg: ''\ncolumns: [{name: B}]\n"
        "mapping: {}\ndomains: {B: '>=0'}\nfindings: [b1]\n",
        encoding="utf-8",
    )
    review_root = _action_dir(synthetic_root, ctx, "bind_review")
    review_root.mkdir(parents=True)
    (review_root / "verdict.yaml").write_text("ok: true\n", encoding="utf-8")
    out = run_bind_promote(synthetic_root, ctx)
    assert out.get("ok") is True, out
    doc = load_init(tg_root(synthetic_root, arch="arch0"))
    assert doc.get("kind") == "default_input"
    assert doc.get("confirmed") is not True
    from ascendc_pilot.actions.tg_product import run_validate_init

    val = run_validate_init(synthetic_root, ctx)
    assert val.get("ok") is True, val
    doc = load_init(tg_root(synthetic_root, arch="arch0"))
    assert doc.get("confirmed") is True
    assert doc.get("golden", {}).get("status") == "match"
    assert doc.get("columns")[0]["name"] == "B"
    assert "h1" in doc.get("findings")
    assert "b1" in doc.get("findings")


def test_bind_promote_prose_evidence_does_not_crash(synthetic_root: Path) -> None:
    """Free-form evidence with later ``other.cpp:2068`` must not abort promote.

    Naive ``rpartition(':')`` left ``file.h:105 TILING...`` as the path; Windows
    then FileNotFoundError'd and acp exited with ACP_NO_JSON.
    """
    from ascendc_pilot.actions.tg_product import _action_dir, run_bind_promote, run_repo_scan
    from ascendc_pilot.human_interaction import adopt_test_script_root
    from ascendc_pilot.state import start_workflow

    src = (
        synthetic_root
        / "op_kernel"
        / "arch35"
        / "flash_attention_score_grad_tiling_data_regbase.h"
    )
    src.parent.mkdir(parents=True)
    src.write_text("\n".join(f"line{i}" for i in range(1, 12)) + "\n", encoding="utf-8")

    state = start_workflow(
        synthetic_root, "tg-init", architecture="arch0", op_name="_synthetic_toy"
    )
    adopt_test_script_root(synthetic_root, "no_repo_uo_query")
    ctx = {
        "architecture": "arch0",
        "run_id": str(state.get("run_id") or ""),
        "op_name": "_synthetic_toy",
    }
    assert run_repo_scan(synthetic_root, {**ctx, "test_script_root": "no_repo_uo_query"}).get("ok")
    bind_root = _action_dir(synthetic_root, ctx, "bind_init")
    (bind_root / "parts").mkdir(parents=True, exist_ok=True)
    (bind_root / "parts" / "harness.yaml").write_text(
        "golden: {status: match}\ncompare: {atol: 1e-4}\nmodes: {precision: [run], perf: []}\n"
        "generate_inputs: {kind: default}\n",
        encoding="utf-8",
    )
    (bind_root / "parts" / "bind.yaml").write_text(
        "table_kind: csv\nentry: ''\ncase_arg: ''\ncolumns: [{name: B}]\n"
        "mapping:\n"
        "  B:\n"
        "    control: {status: active}\n"
        "    relation: tensor_shape\n"
        "    confidence: confirmed\n"
        "    uo: {id: b, candidate: ''}\n"
        "    evidence: op_kernel/arch35/flash_attention_score_grad_tiling_data_regbase.h:3 "
        "TILING_FIELD b; set_n2 at tiling_normal_regbase.cpp:2068\n"
        "domains: {B: '>=0'}\n",
        encoding="utf-8",
    )
    # Drop scan-owned keys so restore cannot replace the prose evidence row.
    engine_dir = bind_root / "parts" / ".engine"
    if engine_dir.is_dir():
        for child in engine_dir.iterdir():
            child.unlink()
    review_root = _action_dir(synthetic_root, ctx, "bind_review")
    review_root.mkdir(parents=True, exist_ok=True)
    (review_root / "verdict.yaml").write_text("ok: true\n", encoding="utf-8")
    out = run_bind_promote(synthetic_root, ctx)
    assert out.get("ok") is True, out
    proofs = out.get("evidence_proofs") or []
    assert proofs, out
    hit = next((p for p in proofs if p.get("column") == "B"), proofs[0])
    assert hit.get("ok") is True, hit
    assert hit.get("path") == "op_kernel/arch35/flash_attention_score_grad_tiling_data_regbase.h"
    assert ":" not in str(hit.get("path") or "")



def test_bind_promote_normalizes_list_mapping_domains_and_mixed_table(synthetic_root: Path) -> None:
    from ascendc_pilot.actions.tg_product import _action_dir, run_bind_promote, run_repo_scan
    from ascendc_pilot.human_interaction import adopt_test_script_root
    from ascendc_pilot.paths import tg_root
    from ascendc_pilot.state import start_workflow
    from testcase_agent.products import load_init

    state = start_workflow(
        synthetic_root, "tg-init", architecture="arch0", op_name="_synthetic_toy"
    )
    adopt_test_script_root(synthetic_root, "no_repo_uo_query")
    ctx = {"architecture": "arch0", "run_id": str(state.get("run_id") or ""), "op_name": "_synthetic_toy"}
    scan = run_repo_scan(synthetic_root, {**ctx, "test_script_root": "no_repo_uo_query"})
    assert scan.get("ok") is True
    bind_root = _action_dir(synthetic_root, ctx, "bind_init")
    (bind_root / "parts").mkdir(parents=True, exist_ok=True)
    (bind_root / "parts" / "harness.yaml").write_text(
        "golden: {status: match}\ncompare: {how: script}\n"
        "modes:\n  precision: {flag: only_grad}\n  perf: {flag: profiler}\n"
        "generate_inputs: {kind: default}\nfindings: [h1]\n",
        encoding="utf-8",
    )
    (bind_root / "parts" / "bind.yaml").write_text(
        "table_kind: mixed\nentry: run.py\ncase_arg: --case\ncolumns: [D, CaseName]\n"
        "call: {kind: pta, api: npu_fusion, site: runner.py:10}\n"
        "mapping:\n"
        "  - column: D\n    control: {status: active}\n    relation: direct\n"
        "    confidence: confirmed\n    uo: {id: DTemplateNum, candidate: ''}\n"
        "    encoding: 字面量\n"
        "  - column: CaseName\n    control: {status: metadata}\n    relation: ''\n"
        "    confidence: unresolved\n    uo: {id: '', candidate: ''}\n"
        "domains:\n  D:\n    profile: {max: 1}\n    operator: {declared: [0, 1], product: [0, 1]}\n"
        "    compare: match\n"
        "findings: [b1]\n",
        encoding="utf-8",
    )
    review_root = _action_dir(synthetic_root, ctx, "bind_review")
    review_root.mkdir(parents=True)
    (review_root / "verdict.yaml").write_text("ok: true\n", encoding="utf-8")
    out = run_bind_promote(synthetic_root, ctx)
    assert out.get("ok") is True, out
    doc = load_init(tg_root(synthetic_root, arch="arch0"))
    assert doc.get("table_kind") in {"csv", "xls", "xlsx"}
    assert isinstance(doc.get("mapping"), dict)
    assert doc["mapping"]["D"]["uo"]["id"] == "DTemplateNum"
    assert doc["mapping"]["D"]["control"]["status"] == "active"
    assert doc["mapping"]["CaseName"]["control"]["status"] == "metadata"
    assert not str((doc["mapping"]["CaseName"].get("uo") or {}).get("id") or "").strip()
    assert isinstance(doc.get("domains"), dict)
    assert doc["domains"]["D"]["compare"] == "match"
    assert doc.get("call", {}).get("kind") == "pta"
    assert doc.get("columns")[0]["name"] == "D"


_INVALID_HARNESS = (
    "golden: {status: match}\n"
    "compare: {atol: 1e-4}\n"
    "modes:\n"
    "  perf:\n"
    "    - value: profiler\n"
    "      config:\n"
    "        loop: 10\n"
    "    # comment at sequence indent\n"
    "    prof_csv_reader: {entry: show_prof.py}\n"
    "generate_inputs: {kind: default}\n"
    "findings: [h1]\n"
)


def test_bind_promote_merges_empty_uo_id_and_validate_init_confirms(
    synthetic_root: Path,
) -> None:
    """Structure-clean parts merge; empty uo_id is Primary content, not a merge gate."""
    from testcase_agent import products as tg_products
    from ascendc_pilot.actions.tg_product import (
        _action_dir,
        run_bind_promote,
        run_repo_scan,
        run_validate_init,
    )
    from ascendc_pilot.human_interaction import adopt_test_script_root
    from ascendc_pilot.paths import tg_root
    from ascendc_pilot.state import start_workflow
    from testcase_agent.products import load_init

    bind_text = (
        "schema: tg-bind-part/v1\nkind: script_repo\ntable_kind: csv\n"
        "entry: run.py\ncase_arg: --case\n"
        "call: {kind: pta, api: npu_fusion}\n"
        "columns: [{name: B}, {name: prefix}]\n"
        "mapping:\n"
        "  B:\n    control: {status: active}\n    relation: direct\n"
        "    confidence: confirmed\n    uo: {id: b, candidate: ''}\n"
        "    encoding: batch\n"
        "  prefix:\n    control: {status: unwired}\n    relation: direct\n"
        "    confidence: unresolved\n    uo: {id: '', candidate: ''}\n"
        "    encoding: prefix list\n"
        "domains:\n  B: {profile: {max: 8}, operator: b, compare: match}\n"
        "  prefix: {profile: {empty_rate: 1.0}, operator: '', compare: mismatch}\n"
    )
    harness_text = (
        "schema: tg-harness-part/v1\ngolden: {status: match}\ncompare: {how: script}\n"
        "modes:\n  precision: [only_grad]\n  perf: [profiler]\n"
        "generate_inputs: {kind: default}\ncall: {kind: pta}\n"
    )
    import yaml as _yaml

    bind_doc = _yaml.safe_load(bind_text)
    harness_doc = _yaml.safe_load(harness_text)
    assert tg_products.check_tg_part(bind_doc) == []
    assert tg_products.check_tg_part(harness_doc) == []

    state = start_workflow(
        synthetic_root, "tg-init", architecture="arch0", op_name="_synthetic_toy"
    )
    repo = synthetic_root / "fag_debug_tools"
    repo.mkdir()
    (repo / "run.py").write_text("print(1)\n", encoding="utf-8")
    adopt_test_script_root(synthetic_root, str(repo))
    ctx = {
        "architecture": "arch0",
        "run_id": str(state.get("run_id") or ""),
        "op_name": "_synthetic_toy",
    }
    scan = run_repo_scan(synthetic_root, {**ctx, "test_script_root": str(repo)})
    assert scan.get("ok") is True, scan
    bind_root = _action_dir(synthetic_root, ctx, "bind_init")
    (bind_root / "parts").mkdir(parents=True, exist_ok=True)
    (bind_root / "parts" / "harness.yaml").write_text(harness_text, encoding="utf-8")
    (bind_root / "parts" / "bind.yaml").write_text(bind_text, encoding="utf-8")
    review_root = _action_dir(synthetic_root, ctx, "bind_review")
    review_root.mkdir(parents=True)
    (review_root / "verdict.yaml").write_text("ok: true\n", encoding="utf-8")

    out = run_bind_promote(synthetic_root, ctx)
    assert out.get("ok") is True, out
    tg = tg_root(synthetic_root, arch="arch0")
    assert (tg / "init.yaml").is_file()
    doc = load_init(tg)
    assert doc["mapping"]["prefix"]["control"]["status"] == "unwired"
    assert str((doc["mapping"]["prefix"].get("uo") or {}).get("id") or "") == ""

    val = run_validate_init(synthetic_root, ctx)
    assert val.get("ok") is True, val
    assert load_init(tg).get("confirmed") is True


def test_checker_clean_bind_part_promotes_and_validates(synthetic_root: Path) -> None:
    """Structural inspect yaml pass ⇒ merge writes and validate_init confirms."""
    from testcase_agent import products as tg_products
    from ascendc_pilot.actions.tg_product import (
        _action_dir,
        run_bind_promote,
        run_repo_scan,
        run_validate_init,
    )
    from ascendc_pilot.human_interaction import adopt_test_script_root
    from ascendc_pilot.paths import tg_root
    from ascendc_pilot.state import start_workflow
    from testcase_agent.products import load_init

    bind_doc = {
        "schema": "tg-bind-part/v1",
        "kind": "script_repo",
        "table_kind": "csv",
        "entry": "run.py",
        "case_arg": "--case",
        "call": {"kind": "pta", "api": "npu_fusion"},
        "columns": [{"name": "B"}],
        "mapping": {
            "B": {
                "control": {"status": "active"},
                "relation": "direct",
                "confidence": "confirmed",
                "uo": {"id": "b", "candidate": ""},
                "encoding": "batch",
            }
        },
        "domains": {"B": {"profile": {"max": 8}, "operator": "b", "compare": "match"}},
    }
    harness_doc = {
        "schema": "tg-harness-part/v1",
        "golden": {"status": "match"},
        "compare": {"how": "script"},
        "modes": {"precision": ["only_grad"], "perf": ["profiler"]},
        "generate_inputs": {"kind": "default"},
        "call": {"kind": "pta"},
    }
    assert tg_products.validate_bind_part(bind_doc) == []
    assert tg_products.validate_harness_part(harness_doc) == []
    assert tg_products.check_tg_part(bind_doc) == []
    assert tg_products.check_tg_part(harness_doc) == []

    state = start_workflow(
        synthetic_root, "tg-init", architecture="arch0", op_name="_synthetic_toy"
    )
    repo = synthetic_root / "fag_debug_tools"
    repo.mkdir()
    (repo / "run.py").write_text("print(1)\n", encoding="utf-8")
    adopt_test_script_root(synthetic_root, str(repo))
    ctx = {
        "architecture": "arch0",
        "run_id": str(state.get("run_id") or ""),
        "op_name": "_synthetic_toy",
    }
    scan = run_repo_scan(synthetic_root, {**ctx, "test_script_root": str(repo)})
    assert scan.get("ok") is True, scan
    bind_root = _action_dir(synthetic_root, ctx, "bind_init")
    (bind_root / "parts").mkdir(parents=True, exist_ok=True)
    import yaml as _yaml

    (bind_root / "parts" / "harness.yaml").write_text(
        _yaml.safe_dump(harness_doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (bind_root / "parts" / "bind.yaml").write_text(
        _yaml.safe_dump(bind_doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    review_root = _action_dir(synthetic_root, ctx, "bind_review")
    review_root.mkdir(parents=True)
    (review_root / "verdict.yaml").write_text("ok: true\n", encoding="utf-8")
    out = run_bind_promote(synthetic_root, ctx)
    assert out.get("ok") is True, out
    val = run_validate_init(synthetic_root, ctx)
    assert val.get("ok") is True, val
    assert load_init(tg_root(synthetic_root, arch="arch0")).get("confirmed") is True


def test_bind_promote_writes_illegal_call_kind_for_validate_init(
    synthetic_root: Path,
) -> None:
    """ses_fd6e: pta_direct must merge into init.yaml, then fail validate_init."""
    from ascendc_pilot.actions.tg_product import (
        _action_dir,
        run_bind_promote,
        run_repo_scan,
        run_validate_init,
    )
    from ascendc_pilot.human_interaction import adopt_test_script_root
    from ascendc_pilot.paths import tg_root
    from ascendc_pilot.state import start_workflow
    from testcase_agent.products import load_init

    state = start_workflow(
        synthetic_root, "tg-init", architecture="arch0", op_name="_synthetic_toy"
    )
    adopt_test_script_root(synthetic_root, "no_repo_uo_query")
    ctx = {
        "architecture": "arch0",
        "run_id": str(state.get("run_id") or ""),
        "op_name": "_synthetic_toy",
    }
    scan = run_repo_scan(synthetic_root, {**ctx, "test_script_root": "no_repo_uo_query"})
    assert scan.get("ok") is True
    bind_root = _action_dir(synthetic_root, ctx, "bind_init")
    (bind_root / "parts").mkdir(parents=True, exist_ok=True)
    (bind_root / "parts" / "harness.yaml").write_text(
        "golden: {status: match}\ncompare: {how: script}\n"
        "modes: {precision: [run], perf: []}\n"
        "generate_inputs: {kind: default}\ncall: {kind: pta}\n",
        encoding="utf-8",
    )
    (bind_root / "parts" / "bind.yaml").write_text(
        "table_kind: csv\nentry: ''\ncase_arg: ''\ncolumns: [{name: B}]\n"
        "call: {kind: pta_direct, api: npu_fusion}\n"
        "mapping: {}\ndomains: {B: '>=0'}\n",
        encoding="utf-8",
    )
    review_root = _action_dir(synthetic_root, ctx, "bind_review")
    review_root.mkdir(parents=True)
    (review_root / "verdict.yaml").write_text("ok: true\n", encoding="utf-8")
    out = run_bind_promote(synthetic_root, ctx)
    assert out.get("ok") is True, out
    doc = load_init(tg_root(synthetic_root, arch="arch0"))
    assert doc.get("call", {}).get("kind") == "pta_direct"
    val = run_validate_init(synthetic_root, ctx)
    assert val.get("ok") is False, val
    joined = " ".join(str(item) for item in (val.get("errors") or []))
    assert "pta_direct" in joined


def test_bind_promote_invalid_yaml_is_structured(synthetic_root: Path) -> None:
    from ascendc_pilot.actions.tg_product import _action_dir, run_bind_promote
    from ascendc_pilot.state import start_workflow

    state = start_workflow(
        synthetic_root, "tg-init", architecture="arch0", op_name="_synthetic_toy"
    )
    ctx = {"architecture": "arch0", "run_id": str(state.get("run_id") or ""), "op_name": "_synthetic_toy"}
    bind_root = _action_dir(synthetic_root, ctx, "bind_init")
    (bind_root / "parts").mkdir(parents=True, exist_ok=True)
    (bind_root / "parts" / "harness.yaml").write_text(_INVALID_HARNESS, encoding="utf-8")
    (bind_root / "parts" / "bind.yaml").write_text(
        "table_kind: csv\nentry: ''\ncase_arg: ''\ncolumns: [{name: B}]\n"
        "mapping: {}\ndomains: {B: '>=0'}\nfindings: [b1]\n",
        encoding="utf-8",
    )
    review_root = _action_dir(synthetic_root, ctx, "bind_review")
    review_root.mkdir(parents=True)
    (review_root / "verdict.yaml").write_text("ok: true\n", encoding="utf-8")
    out = run_bind_promote(synthetic_root, ctx)
    assert out.get("ok") is False, out
    assert out.get("error") == "BIND_PART_YAML_INVALID"
    assert "无法解析" in str(out.get("message_zh") or "")
    assert out.get("line")


def test_bind_review_pass_blocked_on_invalid_yaml(synthetic_root: Path) -> None:
    from ascendc_pilot.actions.runtime import _complete_bind_review_prepare, _session_dir
    from ascendc_pilot.state import start_workflow

    state = start_workflow(
        synthetic_root, "tg-init", architecture="arch0", op_name="_synthetic_toy"
    )
    run_id = str(state.get("run_id") or "")
    bind_parts = _session_dir(synthetic_root, run_id, "bind_init") / "parts"
    bind_parts.mkdir(parents=True)
    (bind_parts / "harness.yaml").write_text(_INVALID_HARNESS, encoding="utf-8")
    (bind_parts / "bind.yaml").write_text("columns: [{name: B}]\n", encoding="utf-8")
    sdir = _session_dir(synthetic_root, run_id, "bind_review")
    sdir.mkdir(parents=True)
    out = _complete_bind_review_prepare(
        synthetic_root,
        run_id=run_id,
        sdir=sdir,
        result={"ok": True},
        intent="PASS",
    )
    assert out.get("ok") is False, out
    assert out.get("error") == "BIND_PART_YAML_INVALID"
    assert out.get("host_step_kind") == "primary_review"
    assert not (sdir / "verdict.yaml").is_file()
    assert (bind_parts / "harness.yaml").is_file()


def test_bind_review_pass_rejects_confirmed_empty_uo_id(synthetic_root: Path) -> None:
    from ascendc_pilot.actions.runtime import _complete_bind_review_prepare, _session_dir
    from ascendc_pilot.state import start_workflow

    state = start_workflow(
        synthetic_root, "tg-init", architecture="arch0", op_name="_synthetic_toy"
    )
    run_id = str(state.get("run_id") or "")
    bind_parts = _session_dir(synthetic_root, run_id, "bind_init") / "parts"
    bind_parts.mkdir(parents=True)
    (bind_parts / "harness.yaml").write_text("golden: {status: match}\n", encoding="utf-8")
    (bind_parts / "bind.yaml").write_text(
        "call: {kind: pta}\n"
        "mapping:\n"
        "  Dtype:\n"
        "    control: {status: active}\n"
        "    relation: direct\n"
        "    confidence: confirmed\n"
        "    uo: {id: '', candidate: inputDataType}\n",
        encoding="utf-8",
    )
    sdir = _session_dir(synthetic_root, run_id, "bind_review")
    sdir.mkdir(parents=True)
    out = _complete_bind_review_prepare(
        synthetic_root,
        run_id=run_id,
        sdir=sdir,
        result={"ok": True},
        intent="PASS",
    )
    assert out.get("ok") is False, out
    assert out.get("error") == "BIND_PART_INVALID"
    assert not (sdir / "verdict.yaml").is_file()


def test_bind_review_rework_keeps_named_slice_for_patch(synthetic_root: Path) -> None:
    from ascendc_pilot.actions.runtime import _complete_bind_review_prepare, _session_dir
    from ascendc_pilot.state import start_workflow

    state = start_workflow(
        synthetic_root, "tg-init", architecture="arch0", op_name="_synthetic_toy"
    )
    run_id = str(state.get("run_id") or "")
    bind_parts = _session_dir(synthetic_root, run_id, "bind_init") / "parts"
    bind_parts.mkdir(parents=True)
    (bind_parts / "harness.yaml").write_text("golden: {status: match}\n", encoding="utf-8")
    (bind_parts / "bind.yaml").write_text("columns: [{name: B}]\n", encoding="utf-8")
    sdir = _session_dir(synthetic_root, run_id, "bind_review")
    sdir.mkdir(parents=True)
    out = _complete_bind_review_prepare(
        synthetic_root,
        run_id=run_id,
        sdir=sdir,
        result={"ok": True},
        intent="REWORK harness: golden 不清",
    )
    assert out.get("continue_drive") is True, out
    assert out.get("rework") == ["harness"]
    assert (bind_parts / "harness.yaml").is_file()
    assert (bind_parts / "harness.yaml.prev").is_file()
    assert (bind_parts / "harness.yaml").read_text(encoding="utf-8") == "golden: {status: match}\n"
    assert (bind_parts / "bind.yaml").is_file()
    assert not (sdir / "verdict.yaml").is_file()
    assert not (sdir / "referee.yaml").is_file()
    rework_doc = yaml.safe_load(
        (_session_dir(synthetic_root, run_id, "bind_init") / "rework.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert rework_doc.get("slices") == ["harness"]


def test_bind_review_pass_from_intent_writes_engine_verdict(synthetic_root: Path) -> None:
    from ascendc_pilot.actions.runtime import _complete_bind_review_prepare, _session_dir
    from ascendc_pilot.state import start_workflow

    state = start_workflow(
        synthetic_root, "tg-init", architecture="arch0", op_name="_synthetic_toy"
    )
    run_id = str(state.get("run_id") or "")
    bind_parts = _session_dir(synthetic_root, run_id, "bind_init") / "parts"
    bind_parts.mkdir(parents=True)
    (bind_parts / "harness.yaml").write_text("golden: {status: match}\n", encoding="utf-8")
    (bind_parts / "bind.yaml").write_text("columns: [{name: B}]\n", encoding="utf-8")
    sdir = _session_dir(synthetic_root, run_id, "bind_review")
    sdir.mkdir(parents=True)
    pending = _complete_bind_review_prepare(
        synthetic_root,
        run_id=run_id,
        sdir=sdir,
        result={"ok": True},
        intent="绑定测试仓 flash_attention_score_grad",
    )
    assert pending.get("host_step_kind") == "primary_review"
    assert "PASS" in str(pending.get("message_zh") or "")
    assert not (sdir / "verdict.yaml").is_file()
    out = _complete_bind_review_prepare(
        synthetic_root,
        run_id=run_id,
        sdir=sdir,
        result={"ok": True},
        intent="PASS",
    )
    assert out.get("auto_finalize") is not False
    assert "bind_promote" in str(out.get("message_zh") or "")
    assert "tg-plan" in str(out.get("message_zh") or "")
    assert (sdir / "verdict.yaml").is_file()
    assert "ok: true" in (sdir / "verdict.yaml").read_text(encoding="utf-8")
    assert not (sdir / "referee.yaml").is_file()


def test_bind_review_empty_after_prompt_needs_intent(synthetic_root: Path) -> None:
    from ascendc_pilot.actions.runtime import _complete_bind_review_prepare, _session_dir
    from ascendc_pilot.state import start_workflow

    state = start_workflow(
        synthetic_root, "tg-init", architecture="arch0", op_name="_synthetic_toy"
    )
    run_id = str(state.get("run_id") or "")
    bind_parts = _session_dir(synthetic_root, run_id, "bind_init") / "parts"
    bind_parts.mkdir(parents=True)
    (bind_parts / "harness.yaml").write_text("golden: {status: match}\n", encoding="utf-8")
    (bind_parts / "bind.yaml").write_text("columns: [{name: B}]\n", encoding="utf-8")
    sdir = _session_dir(synthetic_root, run_id, "bind_review")
    sdir.mkdir(parents=True)
    first = _complete_bind_review_prepare(
        synthetic_root,
        run_id=run_id,
        sdir=sdir,
        result={"ok": True},
        intent="绑定测试仓 flash_attention_score_grad",
    )
    assert first.get("host_step_kind") == "primary_review"
    second = _complete_bind_review_prepare(
        synthetic_root,
        run_id=run_id,
        sdir=sdir,
        result={"ok": True},
        intent="",
    )
    assert second.get("ok") is True
    assert second.get("host_step_kind") == "primary_review"
    assert not second.get("error")
    assert not (sdir / "verdict.yaml").is_file()


def test_bind_review_pass_uses_turn_intent_not_product_nl(synthetic_root: Path) -> None:
    from ascendc_pilot.actions.runtime import (
        _complete_bind_review_prepare,
        _session_dir,
        bind_turn_intent,
        current_turn_intent,
    )
    from ascendc_pilot.state import start_workflow

    state = start_workflow(
        synthetic_root,
        "tg-init",
        architecture="arch0",
        op_name="_synthetic_toy",
        intent="绑定测试仓 flash_attention_score_grad 并生成针对性测例",
    )
    run_id = str(state.get("run_id") or "")
    bind_parts = _session_dir(synthetic_root, run_id, "bind_init") / "parts"
    bind_parts.mkdir(parents=True)
    (bind_parts / "harness.yaml").write_text("golden: {status: match}\n", encoding="utf-8")
    (bind_parts / "bind.yaml").write_text("columns: [{name: B}]\n", encoding="utf-8")
    sdir = _session_dir(synthetic_root, run_id, "bind_review")
    sdir.mkdir(parents=True)
    (sdir / "review_prompted.yaml").write_text("schema: tg-bind-review-prompted/v1\n", encoding="utf-8")
    token = bind_turn_intent("PASS")
    try:
        assert current_turn_intent() == "PASS"
        out = _complete_bind_review_prepare(
            synthetic_root,
            run_id=run_id,
            sdir=sdir,
            result={"ok": True},
            intent="",
        )
    finally:
        from ascendc_pilot.actions import runtime as _rt

        _rt._TURN_INTENT.reset(token)
    assert out.get("auto_finalize") is not False, out
    assert (sdir / "verdict.yaml").is_file()


def test_repo_scan_adopts_git_url_via_clone_mock(
    synthetic_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    from ascendc_pilot.actions.tg_product import run_repo_scan

    repo = Path(__file__).resolve().parents[2]
    ws = repo / "engines" / "workspace"
    if str(ws) not in sys.path:
        sys.path.insert(0, str(ws))
    import git_workspace as gw

    dest = synthetic_root / "cloned_harness"
    dest.mkdir()

    def fake_clone(url: str, *, project_root):
        assert "gitcode.com/foo/bar" in url
        return {"ok": True, "path": str(dest.resolve()), "cloned": True}

    monkeypatch.setattr(gw, "clone_harness_repo", fake_clone)
    scan = run_repo_scan(
        synthetic_root,
        {
            "architecture": "arch0",
            "run_id": "R1",
            "test_script_root": "https://gitcode.com/foo/bar",
        },
    )
    assert scan.get("needs_human_decision") is not True, scan
    assert scan.get("ok") is True
    assert scan.get("kind") == "script_repo"
    assert Path(str(scan.get("test_script_root"))).resolve() == dest.resolve()


def test_start_tg_init_git_url_is_confirmed_and_skips_ask(
    synthetic_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ses_fdc7: user-given git URL must not reopen the three-way harness AskQuestion."""
    import sys

    from ascendc_pilot.actions.tg_product import run_repo_scan
    from ascendc_pilot.human_interaction import (
        coerce_test_script_root_arg,
        normalize_start_test_script_root,
    )
    from ascendc_pilot.state import start_workflow

    url = "https://gitcode.com/foo/bar"
    stored, confirmed = normalize_start_test_script_root(synthetic_root, url)
    assert confirmed is True
    assert stored == url
    assert coerce_test_script_root_arg(url) == url

    repo = Path(__file__).resolve().parents[2]
    ws = repo / "engines" / "workspace"
    if str(ws) not in sys.path:
        sys.path.insert(0, str(ws))
    import git_workspace as gw

    dest = synthetic_root / "cloned_from_start"
    dest.mkdir()
    monkeypatch.setattr(
        gw,
        "clone_harness_repo",
        lambda u, *, project_root: {"ok": True, "path": str(dest.resolve()), "cloned": True},
    )
    state = start_workflow(
        synthetic_root,
        "tg-init",
        architecture="arch0",
        op_name="_synthetic_toy",
        test_script_root=url,
    )
    assert state.get("test_script_confirmed") is True
    assert str(state.get("test_script_root") or "") == url
    scan = run_repo_scan(
        synthetic_root,
        {
            "architecture": "arch0",
            "run_id": str(state.get("run_id") or ""),
            "op_name": "_synthetic_toy",
        },
    )
    assert scan.get("needs_human_decision") is not True, scan
    assert scan.get("ok") is True
    assert scan.get("kind") == "script_repo"
    assert Path(str(scan.get("test_script_root"))).resolve() == dest.resolve()


def test_cli_coerce_keeps_git_url_and_rejects_in_tree_tests(synthetic_root: Path) -> None:
    from argparse import Namespace

    from ascendc_pilot.cli import _coerce_start_test_script_root
    from ascendc_pilot.human_interaction import normalize_start_test_script_root

    url = "https://gitcode.com/coder_linx/fag_debug_tools"
    ns = Namespace(test_script_root=url, project=synthetic_root)
    assert _coerce_start_test_script_root(ns) == url

    tests = synthetic_root / "tests"
    tests.mkdir()
    stored, confirmed = normalize_start_test_script_root(synthetic_root, str(tests))
    assert confirmed is False
    assert stored == ""
