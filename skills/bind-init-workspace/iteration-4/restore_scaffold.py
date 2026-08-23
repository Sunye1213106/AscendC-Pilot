"""Restore empty bind.yaml scaffold from .engine/bind.owned.yaml."""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

OWNED = Path(
    r"D:/TEST/pr_workspace/.ascendc-pr/gitcode.com--cann--ops-transformer--pr-9851/"
    r"attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/"
    r"RUN_20260822_160048_c23c9341/actions/bind_init/parts/.engine/bind.owned.yaml"
)
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else OWNED.parent.parent / "bind.yaml"


def main() -> None:
    owned = yaml.safe_load(OWNED.read_text(encoding="utf-8")) or {}
    columns = []
    for item in owned.get("columns") or []:
        if isinstance(item, dict):
            columns.append(str(item.get("name") or ""))
        else:
            columns.append(str(item))
    columns = [c for c in columns if c]
    profiles = owned.get("domains_profile") or {}
    doc = {
        "schema": owned.get("schema") or "tg-bind-part/v1",
        "run_id": owned.get("run_id"),
        "workflow_id": owned.get("workflow_id"),
        "action_id": owned.get("action_id"),
        "actor_id": owned.get("actor_id"),
        "artifact_identity": dict(owned.get("artifact_identity") or {}),
        "kind": owned.get("kind") or "script_repo",
        "table_kind": owned.get("table_kind") or "xls",
        "entry": owned.get("entry") or "",
        "case_arg": owned.get("case_arg") or "",
        "call": {"kind": "", "api": "", "site": ""},
        "call_args": [],
        "columns": [{"name": name} for name in columns],
        "mapping": {
            name: {"role": "", "uo_id": "", "encoding": "", "evidence": ""}
            for name in columns
        },
        "domains": {
            name: {
                "profile": dict(profiles.get(name) or {}),
                "operator": "",
                "compare": "",
            }
            for name in columns
        },
        "findings": [],
        "llm_edit": False,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"wrote {OUT} columns={len(columns)}")


if __name__ == "__main__":
    main()
