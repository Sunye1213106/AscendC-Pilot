"""Thin inventory + consumer fingerprint for LLM binding (no per-op hard tables)."""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

TORCH_IMPORT_RE = re.compile(r"\b(torch|torch_npu)\b")
ACLNN_RE = re.compile(r"\baclnn[A-Za-z0-9_]*\b|\bacl(rt|nn)[A-Za-z0-9_]*\b")


def fingerprint_consumer(consumer_root: Path) -> dict[str, Any]:
    """Classify test scripts as torch / aclnn / unknown; collect call sites."""
    root = Path(consumer_root)
    kind = "unknown"
    sites: list[dict[str, Any]] = []
    torch_hits = 0
    acl_hits = 0
    if not root.is_dir():
        return {"consumer_kind": kind, "api_call_sites": sites}
    for path in sorted(root.rglob("*.py")):
        if any(part.startswith(".") or part in {"__pycache__", "venv", ".venv"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = path.relative_to(root).as_posix()
        if TORCH_IMPORT_RE.search(text):
            torch_hits += 1
            sites.append({"path": rel, "kind": "torch", "symbol": "torch"})
        for match in ACLNN_RE.finditer(text):
            acl_hits += 1
            sites.append({"path": rel, "kind": "aclnn", "symbol": match.group(0), "line": text[: match.start()].count("\n") + 1})
        # Literal string clues on comparisons (no semantic interpretation).
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for comp in node.comparators:
                    if isinstance(comp, ast.Constant) and isinstance(comp.value, str) and comp.value.strip():
                        sites.append(
                            {
                                "path": rel,
                                "kind": "string_literal",
                                "value": comp.value,
                                "line": getattr(node, "lineno", None),
                            }
                        )
    if acl_hits and not torch_hits:
        kind = "aclnn"
    elif torch_hits and not acl_hits:
        kind = "torch"
    elif torch_hits and acl_hits:
        kind = "mixed"
    # Cap sites for prompt size
    return {"consumer_kind": kind, "api_call_sites": sites[:200], "torch_hits": torch_hits, "aclnn_hits": acl_hits}


def build_binding_inventory(
    *,
    schema: dict[str, Any],
    lexicon: dict[str, Any],
    snapshot_files: dict[str, Any] | None,
    consumer_root: Path | None,
    binding_gaps: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    columns = list(schema.get("columns") or [])
    fields = [f for f in (schema.get("fields") or []) if isinstance(f, dict)]
    thin_domains: list[dict[str, Any]] = []
    for field in fields:
        name = str(field.get("name") or "")
        domain = field.get("domain")
        role = str(field.get("role") or "")
        thin = False
        if isinstance(domain, list) and set(str(v) for v in domain) <= {"_", "NONE", ""}:
            thin = True
        if role in {"tensor_placeholder"} or (isinstance(domain, list) and not domain):
            thin = True
        if thin and name:
            thin_domains.append({"column": name, "role": role, "domain": domain, "code": "THIN_DOMAIN"})

    from .kb_semantics import assemble_key_determinants

    # Prefer TG-assembled determinants from KB layers; ignore retired UO contracts.
    key_determinants = assemble_key_determinants(snapshot_files if isinstance(snapshot_files, dict) else {})
    legacy = (snapshot_files or {}).get("contracts/testcase.yaml") if isinstance(snapshot_files, dict) else {}
    if not key_determinants and isinstance(legacy, dict):
        key_determinants = legacy.get("key_determinants") or {}
    key_ids: list[str] = []
    needs_binding: list[str] = []
    not_input_derivable: list[str] = []
    unsolved_input: list[str] = []
    host_hints: dict[str, Any] = {}
    for key_id, spec in (key_determinants or {}).items():
        key_ids.append(str(key_id))
        if not isinstance(spec, dict):
            continue
        idv = spec.get("input_derivable")
        # Kernel-local / no host input ancestor → never Task bind.
        if spec.get("not_input_derivable") is True or idv is False:
            not_input_derivable.append(str(key_id))
            continue
        if idv == "unsolved":
            unsolved_input.append(str(key_id))
        # input_derivable true / unsolved / needs_binding / empty csv → Task uo-query.
        if spec.get("needs_binding") or idv is True or idv == "unsolved" or not (spec.get("csv_determinants") or []):
            needs_binding.append(str(key_id))
            if spec.get("host_parent") or spec.get("derivation_roots"):
                host_hints[str(key_id)] = {
                    "host_parent": spec.get("host_parent"),
                    "host_parent_evidence": spec.get("host_parent_evidence") or "",
                    "derivation_roots": list(spec.get("derivation_roots") or [])[:16],
                    "gap_ref": spec.get("gap_ref"),
                    "input_derivable": idv,
                }

    fingerprint = fingerprint_consumer(consumer_root) if consumer_root else {"consumer_kind": "unknown", "api_call_sites": []}
    doc_candidates = _find_doc_candidates(consumer_root) if consumer_root else []

    gaps = list(binding_gaps or [])
    for item in thin_domains:
        gaps.append(
            {
                "code": "THIN_DOMAIN",
                "column": item["column"],
                "message": f"column {item['column']} has thin/unreviewed domain — LLM domain review required",
            }
        )

    locked = [
        str(item.get("id"))
        for item in (lexicon.get("key_derivations") or [])
        if isinstance(item, dict) and item.get("locked")
    ]
    proposed = [
        str(item.get("id"))
        for item in (lexicon.get("key_derivations") or [])
        if isinstance(item, dict) and not item.get("locked") and item.get("id")
    ]

    return {
        "version": 1,
        "csv_columns": columns,
        "key_ids": key_ids,
        "needs_binding_keys": needs_binding,
        "not_input_derivable_keys": not_input_derivable,
        "unsolved_input_derivable_keys": unsolved_input,
        "host_parent_hints": host_hints,
        "lexicon_locked_ids": locked,
        "lexicon_proposed_ids": proposed,
        "thin_domains": thin_domains,
        "consumer_kind": fingerprint.get("consumer_kind"),
        "api_call_sites": fingerprint.get("api_call_sites") or [],
        "interface_doc_candidates": doc_candidates,
        "binding_gaps": gaps,
        "status": "ready_for_llm" if gaps or needs_binding or proposed else "ready",
    }


def build_domain_review(
    *,
    schema: dict[str, Any],
    inventory: dict[str, Any],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stub domain_review: all free CSV fields start unreviewed unless already confirmed."""
    existing_cols = {}
    if isinstance(existing, dict):
        for item in existing.get("columns") or []:
            if isinstance(item, dict) and item.get("name"):
                existing_cols[str(item["name"])] = item

    columns_out: list[dict[str, Any]] = []
    for field in schema.get("fields") or []:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name") or "")
        if not name:
            continue
        role = str(field.get("role") or "")
        if role in {"case_id", "constant", "metadata", "expected_result"}:
            continue
        prev = existing_cols.get(name) or {}
        status = str(prev.get("status") or "unreviewed")
        if status not in {"confirmed", "human", "llm_confirmed"}:
            # Thin secondary layout / presence → force review
            if name in {t.get("column") for t in (inventory.get("thin_domains") or [])}:
                status = "unreviewed"
            elif role == "solver_input":
                status = str(prev.get("status") or "unreviewed")
        columns_out.append(
            {
                "name": name,
                "role": role,
                "proposed_domain": prev.get("proposed_domain", field.get("domain")),
                "status": status,
                "evidence_refs": prev.get("evidence_refs") or field.get("source_refs") or [],
            }
        )

    pending = [c["name"] for c in columns_out if c.get("status") in {"unreviewed", "pending"}]
    return {
        "version": 1,
        "status": "confirmed" if not pending else "pending",
        "columns": columns_out,
        "pending_columns": pending,
        "hint": "Continue /tg-init: uo-query → merge → verify → audit; AskQuestion only for domain lock before --confirm / tg-solve",
    }


def build_llm_bind_prompt_bundle(inventory: dict[str, Any], unresolved: dict[str, Any]) -> dict[str, Any]:
    key_ids = list(inventory.get("needs_binding_keys") or [])[:20]
    hints = inventory.get("host_parent_hints") or {}
    compact_hints = {kid: hints[kid] for kid in key_ids if kid in hints}
    return {
        "version": 1,
        "purpose": "LLM KEY↔CSV binding + domain review (do not add AST rules)",
        "consumer_kind": inventory.get("consumer_kind"),
        "csv_columns": inventory.get("csv_columns"),
        "needs_binding_keys": inventory.get("needs_binding_keys"),
        "not_input_derivable_keys": inventory.get("not_input_derivable_keys") or [],
        "unsolved_input_derivable_keys": inventory.get("unsolved_input_derivable_keys") or [],
        # Compact Host context: one-hop parent + roots (no full chain dump).
        "host_parent_hints": compact_hints,
        "binding_gaps": inventory.get("binding_gaps"),
        "api_call_sites_sample": (inventory.get("api_call_sites") or [])[:40],
        "interface_doc_candidates": inventory.get("interface_doc_candidates"),
        "cbm_query_hints": [
            {"kind": "symbol", "query": kid.replace("KEY_", "").replace("VAR_", "")}
            for kid in key_ids
        ],
        "unresolved": unresolved,
        "instructions": [
            "Bind unbound KEY/KVAR to real CSV columns using script/KB evidence only",
            "Use host_parent_hints (one-hop parent + derivation_roots); walk KB determined_by/reaches_input — do not expect full host_derivation_chain dumps",
            "Skip not_input_derivable_keys (legitimate kernel-local); for unsolved_input_derivable_keys read UO ir/input_derivable_gaps.yaml as evidence then Task uo-query → OUT_ROOT uo_query_resolve (never Edit $UO_ROOT)",
            "Propose domain_hints for thin/unreviewed columns; never confirm '_' as a legal cell value",
            "For operator host/kernel semantics: use CBM search_graph / get_code_snippet (scope index), not full-file dumps",
            "Prefer summary/human_overview.md + uo_kb_query before opening large YAML",
            "Output binding_lexicon key_derivations with locked:true only after human confirm",
            "Do not invent per-op AST heuristics in plugin Python",
        ],
    }


def _find_doc_candidates(consumer_root: Path) -> list[str]:
    root = Path(consumer_root)
    out: list[str] = []
    for pattern in ("**/*.md", "**/docs/**/*.md", "**/接口*.md"):
        for path in root.glob(pattern):
            if path.is_file():
                try:
                    out.append(path.relative_to(root).as_posix())
                except ValueError:
                    out.append(str(path))
            if len(out) >= 30:
                return out
    # Also peek parent for docs
    parent = root.parent
    for path in list(parent.glob("docs/**/*.md"))[:20]:
        out.append(str(path))
    return out[:40]
