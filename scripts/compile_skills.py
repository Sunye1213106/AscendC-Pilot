"""Minimal Skill compiler: skills-src → generated/<host>/skills/."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

HARNESS_LOOP = """## Harness control plane（唯一权威）

本 Skill **不**拥有阶段/门禁/完成态。每一轮只做：

1. `harness start <workflow_id> --project $PROJECT_ROOT`（若无活动 run）或读 `harness status`
2. `harness next --project $PROJECT_ROOT` → 取 `phase_label_zh`、`allowed_actions`、`open_items`
3. 按返回的 **一个** `action_id` 执行对应领域方法（见 references / prompts）
4. 需要时 `harness advance <next_phase>` / `harness rework --reason <code>`
5. 终态仅 `harness complete`；禁止自行宣布 done / `passed`

Gate 失败 → 保持 phase，status=`rework_required` 或 `human_required`；勿当作立即 blocked。
"""


def _load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None or not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta = {}
    if yaml is not None:
        loaded = yaml.safe_load(parts[1]) or {}
        if isinstance(loaded, dict):
            meta = loaded
    return meta, parts[2].lstrip("\n")


def _dump_frontmatter(meta: dict[str, Any]) -> str:
    if yaml is None:
        lines = ["---"]
        for k, v in meta.items():
            lines.append(f"{k}: {v}")
        lines.append("---\n")
        return "\n".join(lines)
    body = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    return f"---\n{body}\n---\n"


def compile_skill(
    src_dir: Path,
    dest_dir: Path,
    *,
    host_meta: dict[str, Any],
    inject_loop: bool = True,
) -> None:
    skill_md = src_dir / "SKILL.md"
    if not skill_md.is_file():
        return
    meta, body = _split_frontmatter(skill_md.read_text(encoding="utf-8"))
    # Host may override disable-model-invocation etc.
    overrides = dict(host_meta.get("skill_defaults") or {})
    per_skill = (host_meta.get("skills") or {}).get(src_dir.name) or {}
    if isinstance(per_skill, dict):
        overrides.update(per_skill)
    meta = {**meta, **overrides}
    if inject_loop and "## Harness control plane" not in body:
        # Insert after first H1
        lines = body.splitlines()
        out: list[str] = []
        inserted = False
        for i, line in enumerate(lines):
            out.append(line)
            if not inserted and line.startswith("# "):
                out.append("")
                out.append(HARNESS_LOOP.rstrip())
                out.append("")
                inserted = True
        body = "\n".join(out)
        if not inserted:
            body = HARNESS_LOOP + "\n" + body

    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "SKILL.md").write_text(_dump_frontmatter(meta) + "\n" + body.lstrip("\n"), encoding="utf-8")

    # Copy sidecar trees
    for name in ("references", "scripts", "assets"):
        src = src_dir / name
        if src.is_dir():
            dst = dest_dir / name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
    for extra in src_dir.glob("PATHS.md"):
        shutil.copy2(extra, dest_dir / extra.name)


def compile_all(repo_root: Path, *, hosts: list[str] | None = None) -> dict[str, Any]:
    src_root = repo_root / "skills-src"
    hosts_dir = src_root / "hosts"
    out_root = repo_root / "generated"
    if not src_root.is_dir():
        raise FileNotFoundError(f"missing skills-src at {src_root}")

    host_names = hosts or [p.stem for p in hosts_dir.glob("*.yaml")]
    compiled: list[str] = []
    for host in host_names:
        host_meta = _load_yaml(hosts_dir / f"{host}.yaml")
        dest_skills = out_root / host / "skills"
        if dest_skills.exists():
            shutil.rmtree(dest_skills)
        dest_skills.mkdir(parents=True, exist_ok=True)
        for skill_dir in sorted(src_root.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name in {"hosts", "_common"}:
                continue
            if not (skill_dir / "SKILL.md").is_file():
                continue
            compile_skill(skill_dir, dest_skills / skill_dir.name, host_meta=host_meta)
            compiled.append(f"{host}/{skill_dir.name}")
    return {"ok": True, "compiled": compiled, "out_root": out_root.as_posix()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compile skills-src → generated/<host>/skills")
    parser.add_argument("--repo", type=Path, default=None)
    parser.add_argument("--host", action="append", default=[])
    args = parser.parse_args(argv)
    repo = args.repo or Path(__file__).resolve().parents[1]
    result = compile_all(repo, hosts=args.host or None)
    print(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
