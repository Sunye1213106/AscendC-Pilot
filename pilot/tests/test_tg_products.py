"""Canonical TG products: init.yaml / plan.md / worklog.md / cases table."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
TG_ENGINE = ROOT / "engines" / "testcase-generation"
if str(TG_ENGINE) not in sys.path:
    sys.path.insert(0, str(TG_ENGINE))

from testcase_agent import products, test_repo


def test_validate_bind_part_empty_uo_id_is_content_not_structure() -> None:
    """Primary judges whether uo_id is filled/correct; inspect only checks shape."""
    errors = products.validate_bind_part(
        {
            "call": {"kind": "pta"},
            "mapping": {"prefix": {"role": "api_arg", "uo_id": ""}},
        }
    )
    assert not any("uo_id" in e for e in errors)


def test_validate_bind_part_rejects_illegal_call_kind() -> None:
    errors = products.validate_bind_part(
        {
            "call": {"kind": "pta_direct"},
            "mapping": {"B": {"role": "api_arg", "uo_id": "b"}},
        }
    )
    assert any("pta_direct" in e for e in errors)


def test_validate_bind_part_allows_feature_without_uo_id() -> None:
    errors = products.validate_bind_part(
        {
            "call": {"kind": "pta"},
            "mapping": {
                "B": {"role": "api_arg", "uo_id": "b"},
                "inner_drop": {"role": "feature", "uo_id": ""},
            },
        }
    )
    assert not any("inner_drop" in e for e in errors)


def test_validate_init_empty_uo_id_is_content_not_structure() -> None:
    errors = products.validate_init(
        {
            "schema": products.INIT_SCHEMA,
            "kind": "script_repo",
            "table_kind": "csv",
            "entry": "run_fag.py",
            "case_arg": "--case",
            "modes": {"precision": ["only_grad"], "perf": ["profiler"]},
            "columns": [{"name": "B"}, {"name": "prefix"}, {"name": "inner_drop"}],
            "mapping": {
                "B": {"role": "api_arg", "uo_id": "scaleValue"},
                "prefix": {"role": "api_arg", "uo_id": ""},
                "inner_drop": {"role": "feature", "uo_id": ""},
            },
            "domains": {"B": {"compare": "match"}},
            "golden": {},
            "compare": {"how": "script"},
            "generate_inputs": {"fn": "gen"},
            "uo_digest": "abc",
        }
    )
    assert not any("uo_id" in e for e in errors)
    assert not any("scaleValue" in e for e in errors)


def test_script_repo_empty_mapping_fails() -> None:
    errors = products.validate_init(
        {
            "schema": products.INIT_SCHEMA,
            "kind": "script_repo",
            "table_kind": "csv",
            "entry": "run_fag.py",
            "case_arg": "--case",
            "modes": {"precision": ["only_grad"], "perf": ["profiler"]},
            "columns": [{"name": "B"}],
            "mapping": {},
            "domains": {"B": ["1", "2"]},
            "golden": {},
            "compare": {"atol": "1e-4"},
            "generate_inputs": {"fn": "gen"},
            "uo_digest": "abc",
        }
    )
    assert any("mapping" in e for e in errors)


def test_golden_only_precision_fails() -> None:
    errors = products.validate_init(
        {
            "schema": products.INIT_SCHEMA,
            "kind": "script_repo",
            "table_kind": "csv",
            "entry": "run_fag.py",
            "case_arg": "--case",
            "modes": {"precision": ["--golden-only"], "perf": ["profiler"]},
            "columns": [{"name": "B"}],
            "mapping": {"B": "uo:B"},
            "domains": {"B": ["1"]},
            "golden": {},
            "compare": {},
            "generate_inputs": {},
            "uo_digest": "abc",
        }
    )
    assert any("golden-only" in e for e in errors)


def _v3_fence(**overrides: object) -> dict:
    fence = {
        "schema": products.PLAN_SCHEMA,
        "requirement": {"id": "R-dtype", "text": "dtype"},
        "targets": [
            {
                "id": "T-dispatch",
                "evidence": {"kind": "replay_field", "field": "tiling_key", "expected": 1},
            }
        ],
        "guards": [],
        "dimensions": [
            {
                "id": "D-dtype",
                "target": "T-dispatch",
                "controls": ["B"],
                "partitions": [
                    {"id": "fp16", "predicate": {"op": "eq", "field": "case.dtype", "value": "fp16"}},
                    {"id": "bf16", "predicate": {"op": "eq", "field": "case.dtype", "value": "bf16"}},
                ],
            }
        ],
        "coverage": {"L0": {"dimensions": ["D-dtype"]}, "L1": {"combinations": []}, "L2": [], "L3": {"guards": []}},
        "oracle": [],
    }
    fence.update(overrides)
    return fence


def test_plan_rejects_td_mode_and_unknown_column() -> None:
    fence = _v3_fence(
        mode="tilingkey_full_coverage",
        dimensions=[
            {
                "id": "D-dtype",
                "target": "T-dispatch",
                "controls": ["Missing"],
                "partitions": [
                    {"id": "fp16", "predicate": {"op": "eq", "field": "case.dtype", "value": "fp16"}},
                    {"id": "bf16", "predicate": {"op": "eq", "field": "case.dtype", "value": "bf16"}},
                ],
            }
        ],
    )
    errors = products.validate_plan_fence(fence, init_columns=["B"])
    assert any("Missing" in e for e in errors)
    assert any("T=D" in e or "tilingkey_full_coverage" in e for e in errors)


def test_plan_rejects_v1_obligations() -> None:
    errors = products.validate_plan_fence(
        {
            "schema": "tg-plan/v1",
            "obligations": [{"id": "o1", "class": "replay"}],
            "targets": [
                {"id": "T-dispatch", "evidence": {"kind": "replay_field", "field": "tiling_key", "expected": 1}}
            ],
            "coverage": {"L0": {"dimensions": []}, "L1": {"combinations": []}, "L2": [], "L3": {"guards": []}},
        },
        init_columns=["B"],
    )
    assert any("obligations" in e for e in errors)
    assert any("v3" in e or "schema" in e for e in errors)


def test_plan_requires_target_and_coverage() -> None:
    errors = products.validate_plan_fence(
        {
            "schema": products.PLAN_SCHEMA,
            "targets": [{"id": "T-dispatch", "evidence": {"kind": "replay_field"}}],
        },
        init_columns=["B"],
    )
    assert any("evidence.field" in e or "evidence.kind" in e or "coverage" in e for e in errors)


def test_untestable_needs_reason() -> None:
    fence = _v3_fence(untestable=[{"id": "u1"}])
    errors = products.validate_plan_fence(fence, init_columns=["B"])
    assert any("reason" in e for e in errors)


def test_plan_prose_requires_three_headings() -> None:
    errors = products.validate_plan_prose("# plan\n\n```yaml\nschema: tg-plan/v3\n```\n")
    assert any("测什么" in e for e in errors)
    ok = products.validate_plan_prose(
        "## 测什么\n\n## 覆盖什么\n\n## 怎么判定\n"
    )
    assert ok == []


def test_worklog_open_ids() -> None:
    assert products.worklog_open_ids("open: [a, b]\n\n## a\n") == ["a", "b"]
    assert products.worklog_open_ids("open: []\n") == []


def test_scan_includes_xls(tmp_path: Path) -> None:
    (tmp_path / "cases.csv").write_text("B,N\n1,2\n", encoding="utf-8")
    (tmp_path / "cases.xlsx").write_bytes(b"not-a-real-xlsx")
    inv = test_repo.scan(tmp_path)
    kinds = [str(t.get("kind") or "") for t in (inv.get("tables") or [])]
    assert "csv" in kinds
    assert "xlsx" in kinds


def test_collect_intent_reads_plan_markdown_not_yaml(tmp_path: Path) -> None:
    plan = tmp_path / ".ascendc-pilot" / "arch35" / "ce" / "plan" / "sync_plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# sync\n\n## 测试内容\n\n- 覆盖 deterBand\n", encoding="utf-8")
    yaml_bridge = tmp_path / ".ascendc-pilot" / "arch35" / "ce" / "impact" / "tg_plan_intent.yaml"
    yaml_bridge.parent.mkdir(parents=True)
    yaml_bridge.write_text("mode: ce_change_scoped\ntarget_keys: [1]\n", encoding="utf-8")
    doc = products.collect_intent_sources(tmp_path, architecture="arch35")
    kinds = [row.get("kind") for row in doc.get("sources") or []]
    assert "ce_plan" in kinds
    assert "ce_tg_plan_intent" not in kinds
    assert not (tmp_path / ".ascendc-pilot" / "arch35" / "tg" / "plan" / "plan_intent.yaml").exists()


def test_inspect_yaml_applies_bind_fill_before_structure_check(tmp_path: Path, capsys) -> None:
    import json
    from argparse import Namespace

    from ascendc_pilot.cli import _cmd_inspect
    from testcase_agent.bind_parts import emit_bind_parts

    rel = "arch0/runs/R1/actions/bind_init/parts/bind.yaml"
    parts = tmp_path / ".ascendc-pilot" / "arch0" / "runs" / "R1" / "actions" / "bind_init" / "parts"
    emit_bind_parts(
        parts,
        scan={
            "kind": "script_repo",
            "contract": {"entry": "run_x.py", "case_arg": "--case", "columns": ["B"]},
            "inventory": {
                "tables": [
                    {
                        "columns": ["B"],
                        "kind": "csv",
                        "profile": {"columns": {"B": {"inferred_type": "int"}}},
                    }
                ]
            },
        },
        identity={"run_id": "RUN_1"},
    )
    (parts / "bind.fill.yaml").write_text(
        "call: {kind: pta, api: torch_npu.foo, site: a.py:1}\n"
        "call_args: [{name: batch, source_column: B}]\n"
        "mapping:\n  B: {role: api_arg, uo_id: b, encoding: int, evidence: a.py:1}\n"
        "domains:\n  B: {operator: b, compare: match}\n"
        "findings: []\n",
        encoding="utf-8",
    )
    rc = _cmd_inspect(Namespace(inspect_cmd="yaml", project=tmp_path, rel=rel))
    out = capsys.readouterr().out
    assert rc == 0, out
    payload = json.loads(out)
    assert payload.get("ok") is True
    bind = yaml.safe_load((parts / "bind.yaml").read_text(encoding="utf-8"))
    assert bind["call"]["kind"] == "pta"
    assert bind["mapping"]["B"]["uo_id"] == "b"
    assert bind["domains"]["B"]["profile"] == {"inferred_type": "int"}
    assert bind["run_id"] == "RUN_1"


def test_inspect_yaml_checks_structure_not_uo_id_content(tmp_path: Path, capsys) -> None:
    import json
    from argparse import Namespace

    from ascendc_pilot.cli import _cmd_inspect

    rel = "arch0/runs/R1/actions/bind_init/parts/bind.yaml"
    path = tmp_path / ".ascendc-pilot" / rel
    path.parent.mkdir(parents=True)
    path.write_text(
        "schema: tg-bind-part/v1\ncall: {kind: pta}\nmapping:\n  prefix:\n    role: api_arg\n    uo_id: ''\n",
        encoding="utf-8",
    )
    rc = _cmd_inspect(Namespace(inspect_cmd="yaml", project=tmp_path, rel=rel))
    out = capsys.readouterr().out
    assert rc == 0, out
    payload = json.loads(out)
    assert payload.get("ok") is True

    path.write_text(
        "schema: tg-bind-part/v1\ncall: {kind: pta_direct}\nmapping:\n  B:\n    role: api_arg\n    uo_id: b\n",
        encoding="utf-8",
    )
    rc = _cmd_inspect(Namespace(inspect_cmd="yaml", project=tmp_path, rel=rel))
    assert rc == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload.get("ok") is False
    assert payload.get("error") == "BIND_PART_INVALID"
    assert any("pta_direct" in str(e) for e in (payload.get("errors") or []))
