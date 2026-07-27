"""TilingData Schema / SchemaVariant 提取。

支持：BEGIN_TILING_DATA_DEF 宏族、C++ struct/class、REGISTER_*、模板 variant。
Field identity = SchemaVariant + nested path + leaf。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from uo.scripts.ascendc_macro_facts import load_macro_facts
from uo.scripts.host_contract_schema import make_entity, make_evidence, stable_id
from uo.scripts.receiver_binding import normalize_type_name

SCHEMA_VERSION = "1.0.0"

STRUCT_RE = re.compile(
    r"\b(?:struct|class)\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*[^{]+)?\{",
    re.MULTILINE,
)
FIELD_RE = re.compile(
    r"\b((?:uint\d+_t|int\d+_t|float|double|bool|size_t|[A-Za-z_][A-Za-z0-9_:]*)"
    r"(?:\s*<[^;]+>)?)\s+([A-Za-z_][A-Za-z0-9_]*)\s*(?:\[[^\]]*\])?\s*;"
)
TEMPLATE_STRUCT_RE = re.compile(
    r"template\s*<([^>]+)>\s*struct\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.MULTILINE,
)


def variant_identity(
    *,
    base_schema: str,
    template_arguments: list[str] | None = None,
    compile_context_id: str = "",
    architecture: str = "",
    registration: str = "",
) -> str:
    return stable_id(
        base_schema,
        ",".join(template_arguments or []),
        compile_context_id,
        architecture,
        registration,
        prefix="TSV:",
    )


def extract_schemas_from_macro_facts(
    facts: dict[str, Any],
    *,
    compile_context_id: str,
    architecture: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    entities: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    current_schema: str | None = None
    current_fields: list[dict[str, Any]] = []
    schemas: dict[str, dict[str, Any]] = {}

    for inv in facts.get("invocations") or []:
        macro = str(inv.get("macro") or "")
        args = list((inv.get("normalized_args") or {}).get("positional") or inv.get("raw_args") or [])
        ev = make_evidence(
            file_path=str(inv.get("file_path") or ""),
            start_line=int(inv.get("start_line") or 0),
            end_line=int(inv.get("end_line") or 0),
            extractor="tiling_data_schema",
            extractor_version=SCHEMA_VERSION,
            evidence_level="macro_contract_fact",
        )
        evidence.append(ev)

        if macro == "BEGIN_TILING_DATA_DEF" and args:
            current_schema = normalize_type_name(args[0])
            current_fields = []
        elif macro == "TILING_DATA_FIELD_DEF" and current_schema and len(args) >= 2:
            current_fields.append(
                {"field_type": args[0].strip(), "field_name": args[1].strip(), "kind": "scalar"}
            )
        elif macro == "TILING_DATA_FIELD_DEF_ARR" and current_schema and len(args) >= 2:
            current_fields.append(
                {
                    "field_type": args[0].strip(),
                    "field_name": args[1].strip(),
                    "array_size": args[2].strip() if len(args) > 2 else "",
                    "kind": "array",
                }
            )
        elif macro == "TILING_DATA_FIELD_DEF_STRUCT" and current_schema and len(args) >= 2:
            current_fields.append(
                {
                    "field_type": args[0].strip(),
                    "field_name": args[1].strip(),
                    "kind": "struct",
                    "nested": True,
                }
            )
        elif macro == "END_TILING_DATA_DEF" and current_schema:
            schemas[current_schema] = {
                "base_schema": current_schema,
                "fields": list(current_fields),
                "source": "macro_def",
                "evidence_ref": ev["id"],
            }
            current_schema = None
            current_fields = []
        elif macro in {"REGISTER_TILING_DATA_CLASS", "REGISTER_TILING_DEFAULT"} and len(args) >= 2:
            schema = normalize_type_name(args[1])
            schemas.setdefault(
                schema,
                {"base_schema": schema, "fields": [], "source": "registration"},
            )
            schemas[schema]["registration"] = macro
            schemas[schema]["operator_type"] = args[0].strip()

    for base, info in schemas.items():
        vid = variant_identity(
            base_schema=base,
            template_arguments=[],
            compile_context_id=compile_context_id,
            architecture=architecture,
            registration=str(info.get("registration") or ""),
        )
        schema_ent = make_entity(
            kind="TilingSchema",
            identity_key=f"TilingSchema:{base}",
            qualified_name=base,
            binding_time="build_time",
            architecture=architecture,
            compile_context_id=compile_context_id,
            evidence_refs=[info.get("evidence_ref")] if info.get("evidence_ref") else [],
        )
        variant_ent = make_entity(
            kind="TilingSchemaVariant",
            identity_key=vid,
            qualified_name=base,
            binding_time="build_time",
            architecture=architecture,
            compile_context_id=compile_context_id,
            extra={
                "tiling_schema_variant_id": vid,
                "base_schema": base,
                "template_arguments": [],
                "registration": info.get("registration"),
            },
        )
        entities.extend([schema_ent, variant_ent])
        for field in info.get("fields") or []:
            leaf = str(field.get("field_name") or "")
            path = leaf
            field_ent = make_entity(
                kind="NestedTilingField" if field.get("nested") else "TilingField",
                identity_key=f"{vid}::{path}",
                qualified_name=f"{base}.{path}",
                binding_time="build_time",
                architecture=architecture,
                compile_context_id=compile_context_id,
                extra={
                    "schema_variant_id": variant_ent["id"],
                    "tiling_schema_variant_id": vid,
                    "field_path": path,
                    "field_type": field.get("field_type"),
                    "field_kind": field.get("kind"),
                },
            )
            entities.append(field_ent)

    return entities, evidence, unresolved


def extract_cpp_struct_schemas(
    text: str,
    file_path: str,
    *,
    compile_context_id: str,
    architecture: str,
) -> list[dict[str, Any]]:
    """启发式提取名称含 TilingData 的 struct/class。"""
    entities: list[dict[str, Any]] = []
    for m in STRUCT_RE.finditer(text or ""):
        name = m.group(1)
        if "tiling" not in name.casefold() and "Tiling" not in name:
            continue
        # slice body
        start = m.end() - 1
        depth = 0
        end = start
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        body = text[start + 1 : end]
        vid = variant_identity(
            base_schema=name,
            compile_context_id=compile_context_id,
            architecture=architecture,
        )
        schema_ent = make_entity(
            kind="TilingSchema",
            identity_key=f"TilingSchema:{name}",
            qualified_name=name,
            binding_time="build_time",
            architecture=architecture,
            compile_context_id=compile_context_id,
            extra={"source": "cpp_struct", "file_path": file_path},
        )
        variant_ent = make_entity(
            kind="TilingSchemaVariant",
            identity_key=vid,
            qualified_name=name,
            binding_time="build_time",
            architecture=architecture,
            compile_context_id=compile_context_id,
            extra={
                "tiling_schema_variant_id": vid,
                "base_schema": name,
                "template_arguments": [],
                "source": "cpp_struct",
            },
        )
        entities.extend([schema_ent, variant_ent])
        for fm in FIELD_RE.finditer(body):
            ftype, fname = fm.group(1).strip(), fm.group(2).strip()
            if fname in {"public", "private", "protected"}:
                continue
            entities.append(
                make_entity(
                    kind="TilingField",
                    identity_key=f"{vid}::{fname}",
                    qualified_name=f"{name}.{fname}",
                    binding_time="build_time",
                    architecture=architecture,
                    compile_context_id=compile_context_id,
                    extra={
                        "schema_variant_id": variant_ent["id"],
                        "tiling_schema_variant_id": vid,
                        "field_path": fname,
                        "field_type": ftype,
                    },
                )
            )
    # template variants
    for m in TEMPLATE_STRUCT_RE.finditer(text or ""):
        params = [p.strip() for p in m.group(1).split(",") if p.strip()]
        name = m.group(2)
        if "tiling" not in name.casefold() and "Tiling" not in name:
            continue
        # Keep as distinct variant identity keyed by param names (not values)
        vid = variant_identity(
            base_schema=name,
            template_arguments=params,
            compile_context_id=compile_context_id,
            architecture=architecture,
        )
        entities.append(
            make_entity(
                kind="TilingSchemaVariant",
                identity_key=vid,
                qualified_name=f"{name}<{','.join(params)}>",
                binding_time="build_time",
                architecture=architecture,
                compile_context_id=compile_context_id,
                extra={
                    "tiling_schema_variant_id": vid,
                    "base_schema": name,
                    "template_arguments": params,
                    "source": "template_struct",
                },
            )
        )
    return entities


def build_tiling_data_schemas(
    repo_root: Path,
    op_name: str,
    *,
    architecture: str = "arch35",
    uo_root: Path | None = None,
    source_texts: dict[str, str] | None = None,
) -> dict[str, Any]:
    from uo._operator.artifacts import existing_operator_root
    from uo.scripts.ascendc_macro_facts import _confirmed_source_files, _relative_path
    from uo.scripts.host_compile_context import load_host_compile_context

    root = uo_root or existing_operator_root(repo_root, op_name)
    ctx = load_host_compile_context(root)
    ccid = str(ctx.get("compile_context_id") or "")
    facts = load_macro_facts(root)
    entities, evidence, unresolved = extract_schemas_from_macro_facts(
        facts, compile_context_id=ccid, architecture=architecture
    )
    if source_texts is None:
        source_texts = {}
        for path in _confirmed_source_files(root, repo_root):
            try:
                source_texts[_relative_path(path, repo_root)] = path.read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError:
                continue
    for fp, text in source_texts.items():
        entities.extend(
            extract_cpp_struct_schemas(
                text, fp, compile_context_id=ccid, architecture=architecture
            )
        )
    return {
        "version": SCHEMA_VERSION,
        "compile_context_id": ccid,
        "architecture": architecture,
        "entities": entities,
        "evidence": evidence,
        "unresolved": unresolved,
    }
