"""Export human-readable KB overview (does not re-extract IR)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from uo._operator.artifacts import existing_operator_root, safe_op_name
from uo.scripts._ir_io import read_yaml, write_yaml


def export_human_views(uo_root: Path | str, *, write: bool = True) -> dict[str, Any]:
    uo_root = Path(uo_root)
    if not (uo_root / "manifest.yaml").exists() and not (uo_root / "ir" / "operator_graph.yaml").exists():
        raise FileNotFoundError(f"KB root looks empty: {uo_root}")

    key_space = read_yaml(uo_root / "tiling" / "key_space.yaml") or {}
    exhaustive = read_yaml(uo_root / "tiling" / "exhaustive_key_space.yaml") or {}
    runtime = read_yaml(uo_root / "kernel" / "runtime_conditions.yaml") or {}
    quality = read_yaml(uo_root / "quality.yaml") or {}
    unresolved = read_yaml(uo_root / "ir" / "unresolved.yaml") or {}
    contract = read_yaml(uo_root / "contracts" / "testcase.yaml") or {}
    key_index = read_yaml(uo_root / "tiling" / "key_cards" / "index.yaml") or {}
    entrypoints = read_yaml(uo_root / "ir" / "entrypoints.yaml") or {}
    ledger = read_yaml(uo_root / "ir" / "resolution_ledger.yaml") or {}
    integrity = read_yaml(uo_root / "checks" / "integrity.yaml") or {}
    kb_review = read_yaml(uo_root / "review" / "kb_product_review.yaml") or {}
    if not kb_review:
        kb_review = read_yaml(uo_root / "checks" / "kb_review.yaml") or {}

    fields = key_space.get("fields") if isinstance(key_space.get("fields"), list) else []
    keys_rows: list[dict[str, Any]] = []
    for field in fields:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name") or "")
        kid = str(field.get("id") or "")
        values = field.get("values") or []
        keys_rows.append(
            {
                "id": kid,
                "name": name,
                "role": field.get("role") or field.get("semantic_role") or "",
                "values": values if isinstance(values, list) else [],
                "value_count": len(values) if isinstance(values, list) else 0,
            }
        )

    if not keys_rows and isinstance(key_index.get("keys"), list):
        for item in key_index["keys"]:
            if not isinstance(item, dict):
                continue
            keys_rows.append(
                {
                    "id": str(item.get("id") or ""),
                    "name": str(item.get("key") or item.get("name") or ""),
                    "role": "",
                    "values": item.get("domain") or [],
                    "value_count": len(item.get("domain") or []) if isinstance(item.get("domain"), list) else 0,
                }
            )

    combo = exhaustive.get("combination_summary") if isinstance(exhaustive.get("combination_summary"), dict) else {}
    summary = exhaustive.get("summary") if isinstance(exhaustive.get("summary"), dict) else {}
    buckets = runtime.get("buckets") if isinstance(runtime.get("buckets"), dict) else {}
    unresolved_items = unresolved.get("items") if isinstance(unresolved.get("items"), list) else []
    ledger_items = ledger.get("items") if isinstance(ledger.get("items"), list) else []
    ledger_counts = ledger.get("counts") if isinstance(ledger.get("counts"), dict) else {}
    op_name = str(
        contract.get("op_name")
        or key_space.get("op_name")
        or quality.get("op_name")
        or uo_root.name
    )
    profile = str(
        (contract.get("source") or {}).get("export_profile")
        or quality.get("export_profile")
        or "unknown"
    )

    keys_table = {
        "version": 1,
        "op_name": op_name,
        "export_profile": profile,
        "key_count": len(keys_rows),
        "keys": keys_rows,
    }

    lines = [
        f"# {op_name} — human overview",
        "",
        f"- export_profile: `{profile}`",
        f"- quality: `{quality.get('status') or quality.get('decision') or 'unknown'}`",
        f"- integrity: `{integrity.get('status') or 'unknown'}`",
        f"- kb_review: `{kb_review.get('verdict') or 'pending'}`",
        f"- tiling keys: **{len(keys_rows)}**",
        f"- template_blocks (summary): **{summary.get('template_block_count', combo.get('template_block_count', '?'))}**",
        f"- args_sel_count: **{exhaustive.get('args_sel_count', combo.get('args_sel_count', '?'))}**",
        f"- runtime conditions: **{runtime.get('condition_count', 0)}** (branches≈{runtime.get('branch_count', 0)})",
        f"- open unresolved: **{len(unresolved_items)}**",
        f"- resolution ledger: **{len(ledger_items)}** ({', '.join(f'{k}={v}' for k, v in sorted(ledger_counts.items())) or 'empty'})",
        "",
        "## How to read this KB",
        "",
        "1. Prefer `indexes/kb_graph.sqlite` via `uo-kb-query` / `uo_query_readonly`.",
        "2. Then Grep hot files (`tiling/key_cards/KEY_*.yaml`, `kernel/runtime_conditions.yaml`).",
        "3. Only then small-window Read. Never dump `ir/operator_graph.yaml`, full `contracts/testcase.yaml`, or `cross_layer/impact_graph.yaml`.",
        "",
        "## Tiling keys",
        "",
        "| id | name | role | values |",
        "|---|---|---|---|",
    ]
    for row in keys_rows:
        vals = row.get("values") or []
        if isinstance(vals, list) and len(vals) > 8:
            val_text = ", ".join(str(v) for v in vals[:8]) + ", …"
        else:
            val_text = ", ".join(str(v) for v in vals) if isinstance(vals, list) else ""
        lines.append(
            f"| `{row.get('id')}` | `{row.get('name')}` | {row.get('role') or '-'} | {val_text or '-'} |"
        )
    if not keys_rows:
        lines.append("| - | - | - | - |")

    lines.extend(
        [
            "",
            "## Runtime condition buckets",
            "",
        ]
    )
    if buckets:
        for name, count in sorted(buckets.items(), key=lambda kv: (-int(kv[1]), str(kv[0]))):
            lines.append(f"- `{name}`: {count}")
    else:
        lines.append("- (none)")

    host_name, kernel_name = _entrypoint_labels(entrypoints)
    lines.extend(
        [
            "",
            "## Entry points",
            "",
            f"- host: `{host_name}`",
            f"- kernel: `{kernel_name}`",
            "",
            "## Resolution dispositions",
            "",
        ]
    )
    if ledger_items:
        # One example rationale per status
        by_status: dict[str, dict[str, Any]] = {}
        for row in ledger_items:
            if not isinstance(row, dict):
                continue
            st = str(row.get("status") or "unknown")
            by_status.setdefault(st, row)
        for st, row in sorted(by_status.items()):
            lines.append(
                f"- `{st}` (×{ledger_counts.get(st, '?')}): {row.get('rationale') or '(no rationale)'} "
                f"— 例 `{row.get('id')}`"
            )
    else:
        lines.append("- (no ledger yet)")

    if unresolved_items:
        lines.extend(["", "## Open unresolved (must be empty for uo-init pass)", ""])
        for item in unresolved_items[:12]:
            if isinstance(item, dict):
                lines.append(f"- `{item.get('id')}`: {item.get('message') or item.get('kind')}")

    if integrity.get("issues"):
        lines.extend(["", "## Integrity issues", ""])
        for issue in integrity.get("issues") or []:
            if isinstance(issue, dict):
                lines.append(
                    f"- [{issue.get('severity')}] `{issue.get('code')}` "
                    f"(rework={issue.get('rework_stage')}): {issue.get('message')}"
                )

    if kb_review.get("verdict"):
        lines.extend(
            [
                "",
                "## KB product review",
                "",
                f"- verdict: **{kb_review.get('verdict')}**",
                f"- summary: {kb_review.get('summary') or ''}",
                "",
            ]
        )
    else:
        lines.append("")

    lines.extend(
        [
            "## Lean notes",
            "",
            "- Hashes: `checks/artifact_hashes.yaml` (not embedded in `contracts/testcase.yaml` when profile=lean).",
            "- Exhaustive template blocks: re-export with `--profile full` if L2 needs full enumeration.",
            "",
        ]
    )
    overview_md = "\n".join(lines)

    payload = {
        "op_name": op_name,
        "export_profile": profile,
        "keys_table": keys_table,
        "overview_path": "summary/human_overview.md",
        "keys_table_path": "summary/keys_table.yaml",
    }
    if write:
        (uo_root / "summary").mkdir(parents=True, exist_ok=True)
        (uo_root / "summary" / "human_overview.md").write_text(overview_md, encoding="utf-8")
        write_yaml(uo_root / "summary" / "keys_table.yaml", keys_table)
    return payload


def _entrypoint_labels(entrypoints: dict[str, Any]) -> tuple[str, str]:
    roles = entrypoints.get("roles") if isinstance(entrypoints.get("roles"), dict) else {}

    def _one(role: str) -> str:
        body = roles.get(role) if isinstance(roles.get(role), dict) else {}
        if not body and isinstance(entrypoints.get(role), dict):
            body = entrypoints[role]
        selected = body.get("selected") if isinstance(body.get("selected"), dict) else {}
        return str(
            selected.get("name")
            or selected.get("qualified_name")
            or body.get("name")
            or body.get("file_path")
            or body.get("symbol")
            or "unknown"
        )

    host = entrypoints.get("host") if isinstance(entrypoints.get("host"), dict) else {}
    kernel = entrypoints.get("kernel") if isinstance(entrypoints.get("kernel"), dict) else {}
    host_name = _one("host_tiling_entry")
    if host_name == "unknown":
        host_name = str(host.get("file_path") or host.get("symbol") or "unknown")
    kernel_name = _one("kernel_entry")
    if kernel_name == "unknown":
        kernel_name = str(kernel.get("file_path") or kernel.get("symbol") or "unknown")
    return host_name, kernel_name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export human-readable KB overview views")
    parser.add_argument("repo", nargs="?", default=".")
    parser.add_argument("--op-name", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    uo_root = existing_operator_root(repo_root, op_name)
    result = export_human_views(uo_root, write=not args.dry_run)
    print(
        f"human views op={result['op_name']} profile={result['export_profile']} "
        f"keys={result['keys_table'].get('key_count')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
