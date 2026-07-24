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
    entrypoint_graph = read_yaml(uo_root / "ir" / "entrypoint_graph.yaml") or {}
    ledger = read_yaml(uo_root / "ir" / "resolution_ledger.yaml") or {}
    integrity = read_yaml(uo_root / "checks" / "integrity.yaml") or {}
    tilingkey = read_yaml(uo_root / "ir" / "tilingkey_space.yaml") or {}
    kb_review = read_yaml(uo_root / "review" / "kb_product_review.yaml") or {}

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

    aliases = tilingkey.get("template_aliases") if isinstance(tilingkey.get("template_aliases"), list) else []
    blocks = tilingkey.get("template_blocks") if isinstance(tilingkey.get("template_blocks"), list) else []
    ktpl_count = len(aliases) if aliases else len(blocks)
    summary = exhaustive.get("summary") if isinstance(exhaustive.get("summary"), dict) else {}
    if not ktpl_count:
        ktpl_count = int(
            summary.get("ktpl_instance_count")
            or exhaustive.get("ktpl_instance_count")
            or summary.get("template_block_count")
            or 0
        )

    buckets = runtime.get("buckets") if isinstance(runtime.get("buckets"), dict) else {}
    unresolved_items = unresolved.get("items") if isinstance(unresolved.get("items"), list) else []
    ledger_items = ledger.get("items") if isinstance(ledger.get("items"), list) else []
    ledger_counts = ledger.get("counts") if isinstance(ledger.get("counts"), dict) else {}
    # uo_root is always .../.ascendc-pilot/uo — never use uo_root.name as op_name.
    package_name = uo_root.parent.parent.name if uo_root.name == "uo" else uo_root.name
    op_name = str(
        key_space.get("op_name")
        or quality.get("op_name")
        or tilingkey.get("op_name")
        or package_name
    )

    keys_table = {
        "version": 1,
        "op_name": op_name,
        "key_count": len(keys_rows),
        "ktpl_count": ktpl_count,
        "keys": keys_rows,
    }

    lines = [
        f"# {op_name} — human overview",
        "",
        f"- quality: `{quality.get('status') or quality.get('decision') or 'unknown'}`",
        f"- integrity: `{integrity.get('status') or 'unknown'}`",
        f"- kb_review: `{kb_review.get('verdict') or 'pending'}`",
        f"- tiling keys: **{len(keys_rows)}**",
        f"- KTPL instances (legal templates): **{ktpl_count}**",
        f"- args_sel_count: **{tilingkey.get('args_sel_count', exhaustive.get('args_sel_count', '?'))}**",
        f"- runtime conditions: **{runtime.get('condition_count', 0)}** (branches≈{runtime.get('branch_count', 0)})",
        f"- open unresolved: **{len(unresolved_items)}**",
        f"- resolution ledger: **{len(ledger_items)}** ({', '.join(f'{k}={v}' for k, v in sorted(ledger_counts.items())) or 'empty'})",
        "",
        "## How to read this KB",
        "",
        "1. `uo_kb_query.py --status-only` — confirm `indexes/kb_graph.sqlite` is fresh/ready.",
        "2. `uo_kb_query.py --pattern <entity_of|neighbors_of|list_templates|templates_for_key|…> --target …` — **at least one** graph query.",
        "3. Open only paths returned as `detail_ref` (small-window Read). Follow `writes`/`derives`/`determined_by`/`fixes_flag` edges for KEY↔Host / KTPL.",
        "4. If `sqlite_ready=false` only: yaml_fallback via routes + `tiling/key_space.yaml` / `ir/tilingkey_space.yaml`.",
        "5. Never dump `ir/operator_graph.yaml`, historical `contracts/**`, `tiling/key_cards/**`, or `cross_layer/impact_graph.yaml`.",
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

    host_name, kernel_name = _entrypoint_labels(entrypoint_graph)
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
            "## Notes",
            "",
            "- Hashes: `checks/artifact_hashes.yaml`. Testcase contracts live under TG, not UO `contracts/`.",
            "- Legal compile-time templates: query `list_templates` / `templates_for_key` on `indexes/kb_graph.sqlite` (KTPL_* + `fixes_flag`).",
            "- UO does not materialize cartesian `template_blocks` or per-KEY `key_cards`.",
            "",
        ]
    )
    overview_md = "\n".join(lines)

    payload = {
        "op_name": op_name,
        "ktpl_count": ktpl_count,
        "keys_table": keys_table,
        "overview_path": "summary/human_overview.md",
        "keys_table_path": "summary/keys_table.yaml",
    }
    if write:
        (uo_root / "summary").mkdir(parents=True, exist_ok=True)
        (uo_root / "summary" / "human_overview.md").write_text(overview_md, encoding="utf-8")
        write_yaml(uo_root / "summary" / "keys_table.yaml", keys_table)
    return payload


def _entrypoint_labels(graph: dict[str, Any]) -> tuple[str, str]:
    """Labels from entrypoint_graph nodes (public_host_entry / public_kernel_entry)."""

    def _label_for(roles: tuple[str, ...]) -> str:
        for node in graph.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            role = str(node.get("role") or "")
            # Legacy aliases already normalized in graph, but accept both.
            if role not in roles and role not in {
                "host_tiling_entry" if "public_host_entry" in roles else "",
                "kernel_entry" if "public_kernel_entry" in roles else "",
            }:
                continue
            sym = node.get("symbol_ref") if isinstance(node.get("symbol_ref"), dict) else {}
            name = node.get("name") or sym.get("qualified_name")
            if name:
                return str(name)
            loc = node.get("locator") if isinstance(node.get("locator"), dict) else {}
            if loc.get("file_path"):
                return str(loc.get("file_path"))
        return "unknown"

    host_name = _label_for(("public_host_entry", "normal_impl", "varlen_impl", "empty_impl", "host_tiling_entry"))
    kernel_name = _label_for(("public_kernel_entry", "concrete_kernel_impl", "kernel_entry"))
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
        f"human views op={result['op_name']} ktpl={result['ktpl_count']} "
        f"keys={result['keys_table'].get('key_count')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
