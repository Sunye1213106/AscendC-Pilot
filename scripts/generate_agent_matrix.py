"""Generate docs/reference/agent-matrix.generated.md from agents/*.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = ROOT / "agents"
OUT = ROOT / "docs" / "reference" / "agent-matrix.generated.md"


def load_agent(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"agent yaml must be a mapping: {path}")
    data["_path"] = path.relative_to(ROOT).as_posix()
    return data


def summarize_scope(values: list[Any], *, limit: int = 2) -> str:
    items = [str(v) for v in values if str(v).strip()]
    if not items:
        return ""
    head = ", ".join(f"`{x}`" for x in items[:limit])
    if len(items) > limit:
        head += f", +{len(items) - limit}"
    return head


def main() -> int:
    rows = [load_agent(path) for path in sorted(AGENTS_DIR.glob("*.yaml"))]
    lines = [
        "# Agent Matrix",
        "",
        "本文件由 `agents/*.yaml` 生成，请不要手工编辑。",
        "",
        "| Agent | Kind | Role | Mode | Read scopes | Write scopes | 来源 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        agent_id = str(row.get("id") or "")
        kind = str(row.get("kind") or "llm")
        role = str(row.get("role") or "")
        mode = str(row.get("mode") or "")
        reads = summarize_scope(list(row.get("read_scopes") or []))
        writes = summarize_scope(list(row.get("write_scopes") or []))
        source = str(row.get("_path") or "")
        lines.append(
            f"| `{agent_id}` | `{kind}` | `{role}` | `{mode}` | {reads} | {writes} | `{source}` |"
        )
    lines.append("")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
