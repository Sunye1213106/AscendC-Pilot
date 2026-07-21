"""tg-contract: script evidence + bootstrap/LLM realization map before planning."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .hashing import semantic_snapshot_hash
from .init import TgInitError, tg_init
from .io import ensure_output_dirs, output_root, read_json, read_yaml, write_yaml
from .realization_contract import ContractError, realization_paths
from .realization_dsl import normalize_realization_map, realization_report
from .realization_map import build_realization_map
from .realization_schema import build_consumer_schema_from_evidence, require_consumer_root
from .realization_validation import validate_contract_artifacts
from .reachability import annotate_reachable_values
from .consumer_evidence import prepare_consumer_evidence


class TgContractError(RuntimeError):
    pass


def tg_contract(
    project_root: Path,
    op_name: str,
    *,
    csv_consumer_root: Path,
    reuse_snapshot: bool = False,
    plan_hash: str = "",
    lexicon_seed: Path | None = None,
) -> dict[str, Any]:
    project_root = project_root.resolve()
    consumer_root = require_consumer_root(csv_consumer_root)
    out_root = output_root(project_root, op_name)
    ensure_output_dirs(out_root)
    snapshot_path = out_root / "snapshot" / "understand_contract.json"

    if reuse_snapshot and snapshot_path.exists():
        snapshot = read_json(snapshot_path)
        if snapshot.get("snapshot_hash") != semantic_snapshot_hash(snapshot):
            raise TgContractError("SNAPSHOT_HASH_MISMATCH: snapshot_hash does not match snapshot contents")
    else:
        try:
            init_result = tg_init(project_root, op_name)
        except TgInitError as exc:
            raise TgContractError(str(exc)) from exc
        snapshot = init_result["snapshot"]

    snapshot_hash = str(snapshot.get("snapshot_hash") or "")
    paths = realization_paths(out_root)
    # Contract may run before plan; use empty plan_hash until tg-plan refreshes hashes.
    obligations_path = out_root / "plan" / "coverage_obligations.yaml"
    if not obligations_path.exists():
        # prepare_consumer_evidence requires obligations path — write a stub for evidence gathering.
        write_yaml(
            obligations_path,
            {
                "version": 1,
                "plan_hash": plan_hash or "",
                "obligations": [],
                "snapshot_hash": snapshot_hash,
            },
        )
    evidence = prepare_consumer_evidence(
        out_root,
        consumer_root=consumer_root,
        snapshot_path=snapshot_path,
        obligations_path=obligations_path,
    )
    evidence["snapshot_hash"] = snapshot_hash
    evidence["plan_hash"] = plan_hash or ""
    # Re-seal evidence_hash after stamping hashes used by contract validation.
    from .hashing import stable_hash

    evidence["evidence_hash"] = stable_hash(
        {
            "consumer_root": evidence.get("consumer_root"),
            "files_read": evidence.get("files_read"),
            "ordered_header_candidates": evidence.get("ordered_header_candidates"),
            "field_accesses": evidence.get("field_accesses"),
            "sample_values": evidence.get("sample_values"),
            "sample_int_ranges": evidence.get("sample_int_ranges"),
            "domain_hints": evidence.get("domain_hints"),
            "type_conversion_evidence": evidence.get("type_conversion_evidence"),
            "required_optional_evidence": evidence.get("required_optional_evidence"),
            "test_requirement_refs": evidence.get("test_requirement_refs"),
            "snapshot_hash": snapshot_hash,
            "plan_hash": evidence["plan_hash"],
        }
    )
    write_yaml(paths["evidence"], evidence)

    files = snapshot.get("files") if isinstance(snapshot.get("files"), dict) else {}
    key_space = files.get("tiling/key_space.yaml") if isinstance(files.get("tiling/key_space.yaml"), dict) else {}
    # Prefer ir/tilingkey_space dimensions when key_space fields empty.
    if not (key_space.get("fields") or key_space.get("dimensions")):
        alt = files.get("ir/tilingkey_space.yaml")
        if isinstance(alt, dict):
            key_space = alt

    schema = build_consumer_schema_from_evidence(
        evidence,
        consumer_root,
        key_space=key_space,
        snapshot_files=files,
    )
    schema["snapshot_hash"] = snapshot_hash
    schema["plan_hash"] = evidence["plan_hash"]
    schema["evidence_hash"] = evidence.get("evidence_hash", "")
    schema["op_name"] = op_name
    write_yaml(paths["schema"], schema)

    # Stub domain_hints for LLM/human when missing (do not scrape sample csv/xls).
    from .consumer_evidence import propose_domain_hints_stub
    from .csv_domain_cover import extract_uo_domain_entries_by_column

    hints_path = paths["dir"] / "domain_hints.yaml"
    if not hints_path.exists():
        stub = propose_domain_hints_stub(
            list(schema.get("columns") or []),
            uo_entries=extract_uo_domain_entries_by_column(files, list(schema.get("columns") or [])),
        )
        write_yaml(hints_path, stub)

    from .binding_lexicon import lexicon_from_key_space, merge_lexicons, normalize_lexicon
    from .lexicon_propose import load_lexicon_seed, propose_key_derivations_from_evidence
    from .binding_inventory import (
        build_binding_inventory,
        build_domain_review,
        build_llm_bind_prompt_bundle,
    )

    lexicon_path = paths["dir"] / "binding_lexicon.yaml"
    existing_lexicon = read_yaml(lexicon_path) if lexicon_path.exists() else {}
    boot = lexicon_from_key_space(key_space)
    seed_doc = load_lexicon_seed(lexicon_seed) if lexicon_seed else {}
    seed_usable = bool(
        seed_doc.get("key_derivations")
        or seed_doc.get("key_tokens")
        or seed_doc.get("csv_field_aliases")
        or seed_doc.get("arith_constants")
    )
    merged_lexicon = normalize_lexicon(
        merge_lexicons(
            boot,
            existing_lexicon if isinstance(existing_lexicon, dict) else {},
            seed_doc if seed_usable else None,
        )
    )
    merged_lexicon, binding_gaps = propose_key_derivations_from_evidence(
        lexicon=merged_lexicon,
        csv_columns=list(schema.get("columns") or []),
        sample_values=dict(evidence.get("sample_values") or {}),
        snapshot_files=files,
    )
    write_yaml(lexicon_path, merged_lexicon)

    realization_map = build_realization_map(snapshot, schema, lexicon=merged_lexicon, op_name=op_name)
    realization_map = annotate_reachable_values(realization_map)
    realization_map = normalize_realization_map(realization_map)
    realization_map["version"] = 2
    realization_map["snapshot_hash"] = snapshot_hash
    realization_map["plan_hash"] = evidence["plan_hash"]
    realization_map["evidence_hash"] = evidence.get("evidence_hash", "")
    realization_map["status"] = "bootstrap"
    realization_map.setdefault("warnings", [])
    if not (merged_lexicon.get("key_derivations") or []):
        if "binding_lexicon_required" not in realization_map["warnings"]:
            realization_map["warnings"].append(
                "binding_lexicon_required: run /tg-csv-contract to fill realization/binding_lexicon.yaml "
                "(key_tokens, csv_field_aliases, key_derivations) from script/KB evidence — TG no longer ships per-op hard tables"
            )
    write_yaml(paths["map"], realization_map)

    alignment_report = realization_map.get("alignment_report") or {}
    alignment_path = paths["dir"] / "alignment_report.yaml"
    write_yaml(alignment_path, alignment_report)

    validation = validate_contract_artifacts(
        evidence,
        schema,
        realization_map,
        snapshot_hash=snapshot_hash,
        plan_hash=str(evidence.get("plan_hash") or ""),
        allow_bootstrap=True,
    )
    report = realization_report(realization_map)
    report.update(validation)
    write_yaml(paths["report"], report)

    inventory = build_binding_inventory(
        schema=schema,
        lexicon=merged_lexicon,
        snapshot_files=files,
        consumer_root=consumer_root,
        binding_gaps=binding_gaps,
    )
    write_yaml(paths["dir"] / "binding_inventory.yaml", inventory)
    evidence["consumer_kind"] = inventory.get("consumer_kind")
    write_yaml(paths["evidence"], evidence)

    domain_review_path = paths["dir"] / "domain_review.yaml"
    existing_review = read_yaml(domain_review_path) if domain_review_path.exists() else {}
    domain_review = build_domain_review(
        schema=schema,
        inventory=inventory,
        existing=existing_review if isinstance(existing_review, dict) else None,
    )
    write_yaml(domain_review_path, domain_review)

    needs_llm = bool(binding_gaps or inventory.get("needs_binding_keys") or domain_review.get("status") == "pending")
    unresolved = {
        "version": 1,
        "status": "ready_for_llm" if needs_llm or validation["status"] == "pass" else "blocked",
        "validation_status": validation["status"],
        "errors": validation.get("errors") or [],
        "warnings": realization_map.get("warnings") or [],
        "binding_gaps": binding_gaps,
        "needs_binding_keys": inventory.get("needs_binding_keys") or [],
        "domain_review_status": domain_review.get("status"),
        "hint": "Run /tg-csv-contract or tg-domain-review (LLM) to bind KEY↔CSV and confirm domains; AskQuestion confirm before tg-solve.",
        "next": "tg-csv-contract|tg-domain-review",
    }
    write_yaml(paths["unresolved"], unresolved)
    write_yaml(paths["dir"] / "llm_bind_prompt_bundle.yaml", build_llm_bind_prompt_bundle(inventory, unresolved))

    run_path = out_root / "run.yaml"
    run = read_yaml(run_path) if run_path.exists() else {}
    run.update(
        {
            "command": "tg-contract",
            "phase": "csv_contract",
            "status": validation["status"],
            "next_command": "tg-csv-contract|tg-domain-review then tg-plan",
            "consumer_root": consumer_root.as_posix(),
            "snapshot_hash": snapshot_hash,
            "consumer_kind": inventory.get("consumer_kind"),
            "domain_review_status": domain_review.get("status"),
        }
    )
    write_yaml(run_path, run)

    if validation["status"] != "pass":
        first = (validation.get("errors") or [{"code": "CSV_CONTRACT_REQUIRED", "message": "contract validation failed"}])[0]
        raise TgContractError(f"{first.get('code')}: {first.get('message')}")

    return {
        "status": "ok",
        "snapshot_hash": snapshot_hash,
        "evidence_hash": evidence.get("evidence_hash", ""),
        "contract_hash": validation.get("contract_hash", ""),
        "consumer_root": consumer_root.as_posix(),
        "consumer_kind": inventory.get("consumer_kind"),
        "domain_review_status": domain_review.get("status"),
        "binding_gaps": len(binding_gaps),
        "schema": schema,
        "realization_map": realization_map,
        "validation": validation,
        "report": report,
        "unresolved": unresolved,
        "paths": {key: str(path) for key, path in paths.items()},
    }


def load_realization_for_plan(out_root: Path) -> dict[str, Any]:
    paths = realization_paths(out_root)
    if not paths["map"].exists():
        raise TgContractError(
            "CSV_CONTRACT_REQUIRED: missing realization/realization_map.yaml. "
            "Run tg-contract --csv-consumer-root <test_script_root> first."
        )
    return normalize_realization_map(read_yaml(paths["map"]))


def refresh_contract_plan_hash(out_root: Path, plan_hash: str, snapshot_hash: str) -> None:
    """After tg-plan, stamp plan_hash onto contract artifacts so tg-solve validation matches."""
    paths = realization_paths(out_root)
    for key in ("evidence", "schema", "map"):
        path = paths[key]
        if not path.exists():
            continue
        doc = read_yaml(path)
        doc["plan_hash"] = plan_hash
        doc["snapshot_hash"] = snapshot_hash
        write_yaml(path, doc)
