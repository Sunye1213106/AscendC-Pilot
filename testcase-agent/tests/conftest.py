from __future__ import annotations

import sys
from pathlib import Path

from testcase_agent.hashing import stable_hash
from testcase_agent.io import write_yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def write_minimal_contract_artifacts(
    out_root: Path,
    *,
    snapshot_hash: str,
    plan_hash: str,
    columns: list[str] | None = None,
) -> dict[str, object]:
    columns = columns or ["Testcase_Name", "Enable"]
    evidence = {
        "version": 1,
        "consumer_root": "",
        "files_read": [],
        "ordered_header_candidates": [{"path": "fixture.csv", "reason": "test_fixture", "columns": columns}],
        "field_accesses": {"Enable": [{"path": "fixture.py", "line": 1, "kind": "required_read"}]},
        "sample_values": {"Enable": ["Enable"]},
        "type_conversion_evidence": {},
        "required_optional_evidence": {"Enable": [{"path": "fixture.py", "line": 1, "kind": "required_read"}]},
        "test_requirement_refs": [],
        "snapshot_hash": snapshot_hash,
        "plan_hash": plan_hash,
        "warnings": [],
    }
    evidence["evidence_hash"] = stable_hash(
        {
            "consumer_root": evidence["consumer_root"],
            "files_read": evidence["files_read"],
            "ordered_header_candidates": evidence["ordered_header_candidates"],
            "field_accesses": evidence["field_accesses"],
            "sample_values": evidence["sample_values"],
            "snapshot_hash": snapshot_hash,
            "plan_hash": plan_hash,
        }
    )
    fields = [
        {
            "name": "Testcase_Name",
            "order": 0,
            "required": True,
            "role": "case_id",
            "value_type": "string",
            "domain": ["*"],
            "default": "",
            "serializer": "string",
            "aliases": [],
            "source_refs": [{"path": "fixture", "kind": "contract"}],
            "confidence": "high",
            "rationale": "case id field",
        },
        {
            "name": "Enable",
            "order": 1,
            "required": True,
            "role": "constant",
            "value_type": "string",
            "domain": ["Enable"],
            "default": "Enable",
            "serializer": "string",
            "aliases": [],
            "source_refs": [{"path": "fixture", "kind": "contract"}],
            "confidence": "high",
            "rationale": "fixed enable marker",
        },
    ]
    consumer_schema = {
        "version": 1,
        "evidence_hash": evidence["evidence_hash"],
        "snapshot_hash": snapshot_hash,
        "plan_hash": plan_hash,
        "fields": fields,
        "warnings": [],
    }
    realization_map = {
        "version": 2,
        "evidence_hash": evidence["evidence_hash"],
        "snapshot_hash": snapshot_hash,
        "plan_hash": plan_hash,
        "consumer": {"columns": columns},
        "csv_variables": [],
        "derived_variables": [],
        "branch_mappings": [],
        "abstract_branches": [],
        "emit": {
            "columns": {
                "Testcase_Name": {"op": "template", "template": "{case_id}"},
            }
        },
        "warnings": [],
    }
    realization_dir = out_root / "realization"
    write_yaml(realization_dir / "consumer_evidence.yaml", evidence)
    write_yaml(realization_dir / "consumer_schema.yaml", consumer_schema)
    write_yaml(realization_dir / "realization_map.yaml", realization_map)
    return {
        "evidence": evidence,
        "consumer_schema": consumer_schema,
        "realization_map": realization_map,
    }
