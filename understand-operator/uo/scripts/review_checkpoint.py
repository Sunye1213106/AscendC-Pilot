from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, operator_root, safe_op_name, write_text
from uo._operator.run_context import active_run_id, phase0_snapshot
from uo._operator.spec import spec_bundle_hash


GATE_OPTIONS: dict[str, list[tuple[str, str]]] = {
    "macro_scope": [
        ("continue", "approve Phase 0 scope and allow finalize_phase0.py"),
        ("revise", "revise include/exclude/uncertain scope and review again"),
        ("stop", "stop workflow"),
        ("manual_supplement", "record manual scope notes for the orchestrator"),
    ],
    "query_missing_kb": [
        ("init", "run /uo-init before answering from KB"),
        ("source", "answer this question directly from source/CBM without building KB"),
        ("stop", "cancel this query"),
        ("manual_supplement", "record the KB path or op-name supplied in chat"),
    ],
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Human-review decision helper for understand-operator.")
    parser.add_argument("repo", nargs="?", default=".", help="AscendC repository root")
    parser.add_argument("--op-name", help="Operator name")
    parser.add_argument("--gate", required=True, choices=sorted(GATE_OPTIONS))
    parser.add_argument("--title", default="")
    parser.add_argument("--default", default=None)
    parser.add_argument("--decision", default=None)
    parser.add_argument("--notes", default="")
    parser.add_argument("--include", action="append", default=[], help="Append a path to approved initial/operator scope.")
    parser.add_argument(
        "--replace-initial",
        action="append",
        default=[],
        help="Replace initial_operator_files with these paths (repeatable). Narrowing must use this, not --include.",
    )
    parser.add_argument("--exclude", action="append", default=[], help="Add a path to excluded scope.")
    parser.add_argument("--approve-dependency", action="append", default=[], help="Approve dependency path(s).")
    parser.add_argument("--reject-dependency", action="append", default=[], help="Reject dependency path(s).")
    parser.add_argument("--approve-architecture", action="append", default=[], help="Approve architecture variant(s).")
    parser.add_argument("--exclude-architecture", action="append", default=[], help="Exclude architecture variant(s).")
    parser.add_argument("--resolve-uncertain", action="append", default=[], help="Resolve uncertain path as <path>:include or <path>:exclude.")
    parser.add_argument("--approved-task-ids", default="", help="Retained for CLI compatibility; ignored.")
    parser.add_argument("--print-menu", action="store_true")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--arrows", action="store_true", help="Retained for CLI compatibility; uses numbered mode.")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    base = operator_root(repo_root, op_name) if args.gate == "query_missing_kb" else existing_operator_root(repo_root, op_name)
    if args.gate != "query_missing_kb" and not base.exists():
        print(f"KB not found: {base}", file=sys.stderr)
        return 2
    if args.gate == "query_missing_kb":
        (base / "summary").mkdir(parents=True, exist_ok=True)

    options = GATE_OPTIONS[args.gate]
    values = [value for value, _ in options]
    default_idx = values.index(args.default) if args.default in values else 0
    title = args.title or _default_title(args.gate)

    if args.decision:
        choice = _normalize_choice(args.decision, values)
        if choice is None:
            print(f"Invalid --decision {args.decision!r}. Allowed: {', '.join(values)}", file=sys.stderr)
            _print_menu(title, args.gate, op_name, options, default_idx)
            return 2
        return _commit(
            base,
            gate=args.gate,
            op_name=op_name,
            choice=choice,
            notes=str(args.notes or "").strip(),
            changes=_scope_changes(args),
            ui="chat_decision",
        )

    if args.print_menu or not args.interactive:
        _print_menu(title, args.gate, op_name, options, default_idx)
        print("UO_REVIEW_DECISION=pending")
        print("UO_REVIEW_MODE=chat")
        return 0

    choice = _numbered_menu(options, default_idx)
    notes = _prompt_multiline("manual supplement:") if choice == "manual_supplement" else ""
    return _commit(base, gate=args.gate, op_name=op_name, choice=choice, notes=notes, changes={}, ui="numbered_menu")


def _commit(base: Path, *, gate: str, op_name: str, choice: str, notes: str, changes: dict[str, Any] | None = None, ui: str) -> int:
    decision = {
        "gate": gate,
        "op_name": op_name,
        "decision": choice,
        "notes": notes,
        "decided_at": datetime.now(tz=timezone.utc).isoformat(),
        "reviewer": os.environ.get("USERNAME") or os.environ.get("USER") or "user",
        "ui": ui,
    }
    if gate == "query_missing_kb":
        out_path = base / "summary" / "query_missing_kb_decision.json"
        write_text(out_path, json.dumps(decision, ensure_ascii=False, indent=2) + "\n")
        print(f"Wrote {out_path}")
    else:
        out_path = _write_scope_review(base, decision, changes or {})
        print(f"Wrote {out_path}")
    print(f"UO_REVIEW_DECISION={choice}")
    return 0


def _write_scope_review(base: Path, decision: dict[str, Any], changes: dict[str, Any]) -> Path:
    run_id = active_run_id(base)
    phase0 = base / "runs" / run_id / "phase0"
    scan = _load_yaml(phase0 / "scope_scan.yaml")
    semantic = _load_yaml(phase0 / "semantic_enrichment.yaml")
    files = scan.get("files") if isinstance(scan.get("files"), dict) else {}
    resolved_include = [item["path"] for item in changes.get("resolved_uncertain") or [] if item.get("action") == "include" and item.get("path")]
    resolved_exclude = [item["path"] for item in changes.get("resolved_uncertain") or [] if item.get("action") == "exclude" and item.get("path")]
    confirmed_scope = _confirmed_scope_additions(semantic)
    excluded_paths = _unique_paths(
        [*(_paths(files.get("excluded_files") or [])), *(changes.get("added_exclude") or []), *(changes.get("rejected_dependencies") or []), *resolved_exclude]
    )
    dependency_files = _merge_path_items(files.get("dependency_files") or [], changes.get("approved_dependencies") or [], "manual_dependency")
    dependency_files = _merge_path_items(dependency_files, confirmed_scope, "semantic_enrichment")
    dependency_files = _merge_path_items(dependency_files, resolved_include, "scope_review_resolution", include_reason="scope_review_resolution")
    replaced = [str(p).replace("\\", "/") for p in (changes.get("replaced_initial") or []) if str(p).strip()]
    if replaced:
        if changes.get("added_include"):
            print(
                "WARN: --replace-initial takes precedence over --include; appended includes ignored.",
                file=sys.stderr,
            )
        initial_files = _merge_path_items([], replaced, "manual_replace_initial", include_reason="manual_replace_initial")
    else:
        initial_files = _merge_path_items(files.get("initial_operator_files") or [], changes.get("added_include") or [], "manual_include")
    generated_files = files.get("generated_files") or []
    uncertain_files = _resolve_uncertain(files.get("uncertain_files") or [], changes.get("resolved_uncertain") or [])
    excluded_architectures = [str(x).strip() for x in (changes.get("excluded_architectures") or []) if str(x).strip()]
    # Architecture exclusions must remove matching files from the approved list
    # (not just record a label). Paths like common/op_host/arch22/... and
    # flash_attention_score_grad/op_kernel/arch22/... are filtered here.
    arch_excluded_paths = _paths_matching_architectures(
        [
            *(_paths(initial_files)),
            *(_paths(dependency_files)),
            *(_paths(generated_files)),
            *(_paths(uncertain_files)),
        ],
        excluded_architectures,
    )
    excluded_paths = _unique_paths([*excluded_paths, *arch_excluded_paths])
    initial_files = _remove_paths(initial_files, excluded_paths)
    dependency_files = _remove_paths(dependency_files, excluded_paths)
    generated_files = _remove_paths(generated_files, excluded_paths)
    uncertain_files = _remove_paths(uncertain_files, excluded_paths + resolved_include)
    excluded_files = _merge_path_items([], excluded_paths, "manual_exclude")
    architecture_variants = _merge_names(scan.get("architecture_variants") or [], changes.get("approved_architectures") or [], changes.get("excluded_architectures") or [])
    conflicts = _scope_conflicts(
        {
            "initial_operator_files": initial_files,
            "dependency_files": dependency_files,
            "generated_files": generated_files,
            "excluded_files": excluded_files,
            "uncertain_files": uncertain_files,
        }
    )
    payload = {
        "version": 1,
        "artifact": {"type": "runs.scope_review", "schema_version": 1, "owner": "uo-orchestrator"},
        "snapshot": phase0_snapshot(base, run_id),
        "status": "decided",
        "decision": decision["decision"],
        "reviewed_at": decision["decided_at"],
        "reviewer": decision.get("reviewer") or "user",
        "notes": decision.get("notes") or "",
        "approved_scope": {
            "initial_operator_files": initial_files,
            "dependency_files": dependency_files,
            "external_system_files": files.get("external_system_files") or [],
            "third_party_files": files.get("third_party_files") or [],
            "generated_files": generated_files,
            "excluded_files": excluded_files,
            "uncertain_files": uncertain_files,
            "architecture_variants": architecture_variants,
            "operator_roots": scan.get("operator_roots") or [],
            "include_search_paths": scan.get("include_search_paths") or [],
        },
        "changes": changes,
        "scope_conflicts": conflicts,
        "items": [
            {
                "id": "OP_PHASE0_SCOPE_REVIEW",
                "kind": "scope_review",
                "status": "recorded",
                "identity": {"run_id": run_id, "gate": decision["gate"]},
                "sources": [{"kind": "runtime", "path": f"runs/{run_id}/phase0/scope_review.yaml"}],
                "decision": decision["decision"],
            }
        ],
        "relations": [],
        "unresolved": [{"id": "UNRESOLVED_SCOPE_CONFLICT", "kind": "scope_conflict", "details": conflicts}] if conflicts else [],
    }
    out_path = phase0 / "scope_review.yaml"
    write_text(out_path, _to_yaml(payload))
    if decision["decision"] == "continue":
        _write_scope_confirmed(base, run_id, decision, payload["approved_scope"])
    return out_path


def _scan_discovered_common(scan: dict[str, Any]) -> bool:
    """True when Phase0 scan reported an AscendC common library to index."""
    if not isinstance(scan, dict):
        return False
    if scan.get("common_rel") or scan.get("common_library"):
        return True
    notes = scan.get("warnings") or scan.get("notes") or []
    if isinstance(notes, list) and any("common library" in str(n) or "ascendc_common" in str(n) for n in notes):
        return True
    # Fallback: any initial/dependency path under common/
    files = scan.get("files") if isinstance(scan.get("files"), dict) else {}
    for group in ("initial_operator_files", "dependency_files"):
        for item in files.get(group) or []:
            path = _path_of(item).replace("\\", "/")
            if path.startswith("common/") or "/common/" in path:
                return True
    return False


def _confirmed_has_common(files: list[dict[str, str]]) -> bool:
    return any(str(item.get("path") or "").replace("\\", "/").startswith("common/") for item in files)


def _require_common_in_confirmed(scan: dict[str, Any], files: list[dict[str, str]]) -> None:
    if not _scan_discovered_common(scan):
        return
    if _confirmed_has_common(files):
        return
    raise SystemExit(
        "COMMON_SCOPE_REQUIRED: Phase0 scan discovered common/, but confirmed_file_list has no common/ paths. "
        "Re-run review with continue only after include-pruned common files remain in approved scope."
    )


def _write_scope_confirmed(base: Path, run_id: str, decision: dict[str, Any], approved_scope: dict[str, Any]) -> None:
    phase0 = base / "runs" / run_id / "phase0"
    scan = _load_yaml(phase0 / "scope_scan.yaml")
    files = _confirmed_file_items(approved_scope)
    _require_common_in_confirmed(scan, files)
    payload = {
        "version": 1,
        "artifact": {"type": "runs.scope_confirmed", "schema_version": 1, "owner": "uo-orchestrator"},
        "snapshot": phase0_snapshot(base, run_id),
        "status": "confirmed",
        "operator": decision["op_name"],
        "confirmed_file_list": files,
        "excluded_files": approved_scope.get("excluded_files") or [],
        "analysis_scope": {
            "input_output": _paths_by_role(files, {"input_output", "api", "proto"}),
            "host": _paths_by_role(files, {"host"}),
            "tiling": _paths_by_role(files, {"tiling", "host"}),
            "kernel": _paths_by_role(files, {"kernel"}),
            "headers": _paths_by_role(files, {"headers", "header"}),
            "other": _paths_by_role(files, {"unknown", "other", "manual_include", "manual_dependency"}),
        },
        "confirmation": {
            "reviewed_at": decision["decided_at"],
            "reviewer": decision.get("reviewer") or "user",
            "notes": decision.get("notes") or "",
        },
        "cbm": {"indexing_allowed": True, "input": "confirmed_file_list"},
    }
    write_text(base / "runs" / run_id / "phase0" / "scope_confirmed.yaml", _to_yaml(payload))


def _confirmed_file_items(approved_scope: dict[str, Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for group in ("initial_operator_files", "dependency_files", "generated_files"):
        for item in approved_scope.get(group) or []:
            path = _path_of(item).replace("\\", "/")
            if not path or path in seen:
                continue
            role = str(item.get("role") if isinstance(item, dict) else "") or _role_from_path(path)
            result.append({"path": path, "role": role, "source": group})
            seen.add(path)
    return result


def _paths_by_role(items: list[dict[str, str]], roles: set[str]) -> list[str]:
    return [item["path"] for item in items if item.get("role") in roles]


def _role_from_path(path: str) -> str:
    lower = path.lower()
    suffix = Path(lower).suffix
    if suffix in {".h", ".hh", ".hpp", ".hxx"}:
        return "headers"
    if "op_kernel" in lower or "kernel" in lower:
        return "kernel"
    if "tiling" in lower:
        return "tiling"
    if "op_host" in lower or "host" in lower:
        return "host"
    if "op_api" in lower or "proto" in lower or "infer" in lower:
        return "input_output"
    return "other"


def _scope_changes(args: argparse.Namespace) -> dict[str, Any]:
    resolved: list[dict[str, str]] = []
    for raw in args.resolve_uncertain or []:
        path, sep, action = str(raw).rpartition(":")
        if sep and action in {"include", "exclude"}:
            resolved.append({"path": path, "action": action})
    return {
        "added_include": list(args.include or []),
        "replaced_initial": list(getattr(args, "replace_initial", None) or []),
        "added_exclude": list(args.exclude or []),
        "approved_dependencies": list(args.approve_dependency or []),
        "rejected_dependencies": list(args.reject_dependency or []),
        "approved_architectures": list(args.approve_architecture or []),
        "excluded_architectures": list(args.exclude_architecture or []),
        "resolved_uncertain": resolved,
    }


def _path_of(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("path") or "")
    return str(item)


def _merge_path_items(items: list[Any], paths: list[str], role: str, *, include_reason: str = "scope review override") -> list[Any]:
    result = list(items)
    seen = {_path_of(item) for item in result}
    for path in paths:
        if path and path not in seen:
            result.append({"path": path, "role": role, "include_reason": include_reason})
            seen.add(path)
    return result


def _remove_paths(items: list[Any], paths: list[str]) -> list[Any]:
    rejected = {str(p).replace("\\", "/") for p in paths}
    return [item for item in items if _path_of(item).replace("\\", "/") not in rejected]


def _paths_matching_architectures(paths: list[str], architectures: list[str]) -> list[str]:
    """Return paths that contain a path segment equal to an excluded architecture name."""
    if not architectures:
        return []
    arch_set = {a.strip().casefold() for a in architectures if a and str(a).strip()}
    if not arch_set:
        return []
    matched: list[str] = []
    for raw in paths:
        path = str(raw or "").replace("\\", "/")
        if not path:
            continue
        parts = {part.casefold() for part in path.split("/") if part}
        if parts & arch_set:
            matched.append(path)
    return matched


def _resolve_uncertain(items: list[Any], resolutions: list[dict[str, str]]) -> list[Any]:
    resolved = {item["path"]: item["action"] for item in resolutions if item.get("path")}
    return [item for item in items if _path_of(item) not in resolved]


def _paths(items: list[Any]) -> list[str]:
    return [path for path in (_path_of(item) for item in items) if path]


def _unique_paths(paths: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for path in paths:
        normalized = str(path).replace("\\", "/")
        if normalized and normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return result


def _confirmed_scope_additions(doc: dict[str, Any]) -> list[str]:
    candidates = doc.get("confirmed_scope_additions")
    if not isinstance(candidates, list):
        data = {}
        for item in doc.get("items") or []:
            if isinstance(item, dict) and isinstance(item.get("data"), dict):
                data = item["data"]
                break
        candidates = data.get("confirmed_scope_additions") if isinstance(data.get("confirmed_scope_additions"), list) else []
    return _unique_paths([_path_of(item) for item in candidates])


def _scope_conflicts(groups: dict[str, list[Any]]) -> list[dict[str, str]]:
    owner_by_path: dict[str, str] = {}
    conflicts: list[dict[str, str]] = []
    for group, items in groups.items():
        for path in _paths(items):
            previous = owner_by_path.get(path)
            if previous and previous != group:
                conflicts.append({"path": path, "first": previous, "second": group})
            owner_by_path[path] = group
    return conflicts


def _merge_names(items: list[Any], approved: list[str], excluded: list[str]) -> list[Any]:
    excluded_set = set(excluded)
    result = [item for item in items if str(item.get("name") if isinstance(item, dict) else item) not in excluded_set]
    seen = {str(item.get("name") if isinstance(item, dict) else item) for item in result}
    for name in approved:
        if name and name not in seen:
            result.append({"name": name, "semantic_status": "approved_by_review"})
            seen.add(name)
    return result


def _normalize_choice(raw: str, values: list[str]) -> str | None:
    text = raw.strip().replace("-", "_")
    if text in values:
        return text
    if text.isdigit() and 1 <= int(text) <= len(values):
        return values[int(text) - 1]
    aliases = {"yes": "continue", "ok": "continue", "y": "continue", "n": "stop", "cancel": "stop"}
    mapped = aliases.get(text.lower())
    return mapped if mapped in values else None


def _print_menu(title: str, gate: str, op_name: str, options: list[tuple[str, str]], default_idx: int) -> None:
    print()
    print("=" * 60)
    print(title)
    print(f"gate: {gate}    op: {op_name}")
    print("=" * 60)
    for index, (value, desc) in enumerate(options, start=1):
        mark = "*" if index - 1 == default_idx else " "
        print(f"  {mark} [{index}] {value} - {desc}")
    print()
    print(
        f'python review_checkpoint.py <repo> --op-name {op_name} --gate {gate} '
        f'--decision <choice> [--notes "..."]'
    )


def _numbered_menu(options: list[tuple[str, str]], default_idx: int) -> str:
    _print_menu("Review", "interactive", "", options, default_idx)
    default_value = options[default_idx][0]
    while True:
        raw = input(f"choice 1-{len(options)} (default {default_idx + 1}={default_value}): ").strip()
        if not raw:
            return default_value
        choice = _normalize_choice(raw, [value for value, _ in options])
        if choice:
            return choice
        print("Invalid input, try again.")


def _prompt_multiline(header: str) -> str:
    print(header)
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line == "":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _default_title(gate: str) -> str:
    return {"macro_scope": "Phase 0 Scope Review", "query_missing_kb": "uo-query Missing KB"}[gate]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _to_yaml(data: dict[str, Any]) -> str:
    try:
        import yaml

        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    except Exception:  # noqa: BLE001
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
