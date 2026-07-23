"""Smoke: TG has no per-op FAG hard tables; second-op consumer works via evidence only."""

from __future__ import annotations

from pathlib import Path

import yaml

from testcase_agent import atom_bind as ab
from testcase_agent import realization_map as rm
from testcase_agent import realization_schema as rs
from testcase_agent.binding_lexicon import normalize_lexicon
from testcase_agent.realization_map import build_realization_map
from testcase_agent.realization_schema import extract_consumer_schema


def test_modules_have_no_fag_token_tables() -> None:
    assert ab.TOKEN_KEY_VALUE == {}
    assert ab.EXTRA_KEY_TOKENS == {}
    assert ab.CSV_FIELD_ALIASES == {}
    assert rm.TOKEN_KEY_VALUE == {}
    assert rm.BOOTSTRAP_DOMAINS == {}
    assert not hasattr(rs, "DEFAULT_SAMPLE_CSV") or getattr(rs, "DEFAULT_SAMPLE_CSV", None) in (None, "")


def test_second_op_consumer_schema_without_fag_names(tmp_path: Path) -> None:
    root = tmp_path / "other_op_tools"
    (root / "data").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "data" / "cases.csv").write_text(
        "Testcase_Name,Enable,M,N,K\ncase0,Enable,16,32,64\n",
        encoding="utf-8",
    )
    (root / "tests" / "runner.py").write_text(
        'def load(t):\n    get_column_index(t, "M")\n    get_column_index(t, "extra_flag")\n',
        encoding="utf-8",
    )
    schema = extract_consumer_schema(root)
    assert "M" in schema["columns"]
    assert "extra_flag" in schema["columns"]
    assert "FASG" not in str(schema)
    assert schema.get("aliases") == {}

    lexicon = normalize_lexicon(
        {
            "source": "other_op",
            "key_tokens": {"IS_SQUARE": {"var": "VAR_KEY_ISSQUARE", "true_value": 1}},
            "key_derivations": [
                {
                    "id": "VAR_KEY_ISSQUARE",
                    "type": "int",
                    "domain": [0, 1],
                    "expr": {
                        "op": "if_then_else",
                        "condition": {"op": "eq", "lhs": {"var": "VAR_CSV_M"}, "rhs": {"var": "VAR_CSV_N"}},
                        "then": 1,
                        "else": 0,
                    },
                    "rationale": "M==N",
                }
            ],
        }
    )
    snapshot = {
        "snapshot_hash": "snap2",
        "files": {
            "tiling/key_space.yaml": {"fields": [{"id": "KEY_ISSQUARE", "values": [0, 1]}]},
            "kernel/branches.yaml": {
                "branches": [
                    {"id": "KBR_SQ", "condition": "IS_SQUARE", "determinant_source": "TemplateArg"},
                ]
            },
        },
    }
    # Promote sample ints via fields for map build
    schema["fields"] = [
        {"name": c, "order": i, "role": "solver_input" if c not in {"Testcase_Name", "Enable"} else ("case_id" if c == "Testcase_Name" else "constant"),
         "value_type": "int" if c in {"M", "N", "K"} else "string",
         "domain": {"values": [16, 32, 64]} if c in {"M", "N", "K"} else (["Enable"] if c == "Enable" else ["*"])}
        for i, c in enumerate(schema["columns"])
    ]
    rmap = build_realization_map(snapshot, schema, lexicon=lexicon, op_name="OtherOp")
    mapped = {item["branch_ref"] for item in rmap["branch_mappings"]}
    assert "KBR_SQ" in mapped
    assert any(item["id"] == "VAR_KEY_ISSQUARE" for item in rmap["derived_variables"])


def test_fag_seed_lexicon_loads() -> None:
    path = Path(__file__).parent / "fixtures" / "fag_binding_lexicon.yaml"
    doc = normalize_lexicon(yaml.safe_load(path.read_text(encoding="utf-8")))
    assert doc["key_tokens"]["IS_TND"]["var"] == "VAR_KEY_ISTND"
    assert any(item["id"] == "VAR_KEY_ISTND" for item in doc["key_derivations"])
