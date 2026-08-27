#!/usr/bin/env python3
"""Fail when schemas/ files and Skill write surfaces drift apart."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
SCHEMAS = REPO / "schemas"
CATALOG = SCHEMAS / "catalog.yaml"
SKILLS = REPO / "skills"
ENGINE = REPO / "engines" / "testcase-generation"

WRITE_ROLES = frozenset({"llm_write", "llm_edit"})


def _load_catalog() -> list[dict]:
    doc = yaml.safe_load(CATALOG.read_text(encoding="utf-8")) or {}
    entries = doc.get("entries") if isinstance(doc, dict) else None
    if not isinstance(entries, list):
        raise ValueError("schemas/catalog.yaml missing entries list")
    return [row for row in entries if isinstance(row, dict)]


def _schema_files() -> set[str]:
    out: set[str] = set()
    for path in SCHEMAS.rglob("*.yaml"):
        rel = path.relative_to(SCHEMAS).as_posix()
        if rel == "catalog.yaml":
            continue
        out.add(rel)
    return out


def _engine_schema_ids() -> dict[str, str]:
    if str(ENGINE) not in sys.path:
        sys.path.insert(0, str(ENGINE))
    from testcase_agent.plan_fill import FILL_SCHEMA
    from testcase_agent.products import INIT_SCHEMA, PLAN_SCHEMA
    from testcase_agent.solve_fill import SOLVE_FILL_SCHEMA

    return {
        "tg-init/v1": INIT_SCHEMA,
        "tg-plan/v3": PLAN_SCHEMA,
        "tg-plan-fill/v1": FILL_SCHEMA,
        "tg-solve-fill/v1": SOLVE_FILL_SCHEMA,
    }


def check() -> list[str]:
    errors: list[str] = []
    if not CATALOG.is_file():
        return ["missing schemas/catalog.yaml"]
    try:
        entries = _load_catalog()
    except Exception as exc:  # noqa: BLE001
        return [f"schemas/catalog.yaml: {exc}"]

    listed_files: list[str] = []
    ids_by_file: dict[str, str] = {}
    known_ids: set[str] = set()
    for idx, row in enumerate(entries):
        loc = f"catalog.entries[{idx}]"
        file_rel = str(row.get("file") or "").strip()
        schema_id = str(row.get("id") or "").strip()
        role = str(row.get("role") or "").strip()
        if not file_rel:
            errors.append(f"{loc}: file required")
            continue
        if not schema_id:
            errors.append(f"{loc}: id required")
        if file_rel in listed_files:
            errors.append(f"{loc}: duplicate file {file_rel}")
        listed_files.append(file_rel)
        ids_by_file[file_rel] = schema_id
        known_ids.add(schema_id)
        path = SCHEMAS / file_rel
        if not path.is_file():
            errors.append(f"{loc}: missing {file_rel}")
            continue
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(doc, dict):
            errors.append(f"{file_rel}: not a mapping")
            continue
        got = str(doc.get("schema") or "").strip()
        if got != schema_id:
            errors.append(f"{file_rel}: schema {got!r} != catalog id {schema_id!r}")
        iface = str(row.get("interface") or "").strip()
        if iface:
            got_iface = str(doc.get("interface") or "").strip()
            if got_iface != iface:
                errors.append(
                    f"{file_rel}: interface {got_iface!r} != catalog {iface!r}"
                )
        owned = [str(x) for x in (doc.get("engine_owned") or [])]
        llm = [str(x) for x in (doc.get("llm_owned") or [])]
        overlap = sorted(set(owned) & set(llm))
        if overlap:
            errors.append(f"{file_rel}: engine_owned ∩ llm_owned {overlap}")

        skill = row.get("skill")
        skill_id = str(skill or "").strip()
        if role in WRITE_ROLES:
            if not skill_id:
                errors.append(f"{loc}: {role} requires skill")
            playbook = str(row.get("playbook") or "").strip()
            if not playbook:
                errors.append(f"{loc}: {role} requires playbook")
            elif skill_id:
                book = SKILLS / skill_id / playbook
                if not book.is_file():
                    errors.append(f"{loc}: missing skills/{skill_id}/{playbook}")
                else:
                    text = book.read_text(encoding="utf-8")
                    if schema_id not in text:
                        errors.append(
                            f"skills/{skill_id}/{playbook} missing schema id {schema_id}"
                        )
                    pointer = f"schemas/{file_rel}"
                    if pointer not in text:
                        errors.append(
                            f"skills/{skill_id}/{playbook} missing pointer `{pointer}`"
                        )
        if skill_id and not (SKILLS / skill_id / "SKILL.md").is_file():
            errors.append(f"{loc}: missing skills/{skill_id}/SKILL.md")
        expands = str(row.get("expands_to") or "").strip()
        if role == "fill_expand" and not expands:
            errors.append(f"{loc}: fill_expand requires expands_to")
        if expands and expands not in known_ids and expands not in {
            str(x.get("id") or "") for x in entries
        }:
            errors.append(f"{loc}: expands_to {expands!r} not in catalog")

    actual = _schema_files()
    listed = set(listed_files)
    for missing in sorted(actual - listed):
        errors.append(f"schemas/{missing} not in catalog.yaml")
    for extra in sorted(listed - actual):
        errors.append(f"catalog lists {extra} but file is missing")

    try:
        engine_ids = _engine_schema_ids()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"engine schema constants: {exc}")
        engine_ids = {}
    for want, got in engine_ids.items():
        if got != want:
            errors.append(f"engine constant {got!r} != catalog {want!r}")
        if want not in known_ids:
            errors.append(f"engine id {want} missing from catalog")

    if str(ENGINE) not in sys.path:
        sys.path.insert(0, str(ENGINE))
    try:
        from testcase_agent.bind_parts import _SCHEMA_FILES

        for kind, name in _SCHEMA_FILES.items():
            rel = f"tg/{name}"
            if rel not in listed:
                errors.append(f"bind_parts._SCHEMA_FILES[{kind!r}]={name!r} not in catalog")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"bind_parts schemas: {exc}")

    return errors


def main() -> int:
    errors = check()
    if errors:
        for item in errors:
            print(f"schema-catalog: {item}")
        print(f"schema-catalog: {len(errors)} error(s)")
        return 1
    print("schema-catalog: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
